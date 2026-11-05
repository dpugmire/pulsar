"""Control the actual workspace controller through the Python/HTTP boundary."""

import asyncio
import json
import shutil
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
from trame.app import get_server

from db import CampaignDb
from pulsar.client import PulsarClientError, connect
from pulsar.control import API_PATH, ControlError, ViewerControl, register_control_api
from pulsar.controllers.composer import PulsarController
from pulsar.controllers.context import ControllerContext
from pulsar.models.grid import empty_grid_cell
from pulsar.models.source_selection import source_fields_from_row
from pulsar.models.workspace_state import parse_workspace_document, workspace_json
from pulsar.results import ResultStore, register_result_media_route
from pulsar.state import init_state
from sqlite_store import SQLiteCampaignCollection


class ControlFixture:
    def make_controller(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.collection = SQLiteCampaignCollection(
            self.root / "cache.sqlite", "/campaign/example.aca"
        )
        self.addCleanup(self.collection._con.close)
        self.db = CampaignDb(self.collection)
        self.server = get_server(f"control-{uuid4()}", client_type="vue3")
        init_state(self.server.state, self.db)

        def ingest(_path, collection, **_):
            collection.insert_one(
                {
                    "campaign_path": "/campaign/example.aca",
                    "variable_id": "density",
                    "variable_name": "density",
                    "variable_type": "variable",
                    "source_dataset": "run-a/output.bp",
                    "variable_path": "run-a/output.bp/density",
                    "metadata": {"Shape": "2,2", "AvailableStepsCount": "3"},
                }
            )

        from pulsar.backends import LocalCampaignBackend

        self.controller = PulsarController(
            ControllerContext(
                server=self.server,
                backend=LocalCampaignBackend(self.db),
                db=self.db,
                collection=self.collection,
                parse_campaign=ingest,
                campaign_path="/campaign/example.aca",
                result_store=ResultStore(
                    self.root / "results", "/campaign/example.aca"
                ),
            )
        ).register()
        self.controller.ingest_campaign_every_time()
        # Only the payload-rendering boundary is replaced; selection, layout,
        # source discovery, transactions, and undo are real Pulsar operations.
        tile = empty_grid_cell()
        tile.update(
            variable_id="density",
            variable_name="density",
            media_type="image",
            status="ok",
            src="data:image/png;base64,payload",
            selected_visualization="heatmap",
        )
        self.controller.build_grid_cell_for_variable = Mock(
            side_effect=lambda *_args, **_kwargs: deepcopy(tile)
        )
        self.controller.maybe_handle_generated_scalar_plot = Mock(return_value=False)
        self.state = self.server.state

    def add_rusanov_sources(self):
        for index, source in enumerate(("rusanov_128/output.bp", "rusanov_64/output.bp")):
            self.collection.insert_one(
                {
                    "variable_id": "density",
                    "variable_name": "density",
                    "variable_type": "variable",
                    "source_dataset": source,
                    "metadata": {"Shape": "2,2"},
                }
            )
            self.collection.insert_one(
                {
                    "variable_id": "pressure",
                    "variable_type": "variable",
                    "source_dataset": source,
                    "max": 3 - index,
                }
            )
        render = self.controller.build_grid_cell_for_variable.side_effect

        def render_source(*args, **kwargs):
            tile = render(*args, **kwargs)
            tile.update(source_fields_from_row(kwargs.get("source_row") or {}))
            return tile

        self.controller.build_grid_cell_for_variable.side_effect = render_source


class ViewerControlTests(ControlFixture, unittest.TestCase):
    def setUp(self):
        self.make_controller()
        self.control = ViewerControl(self.controller, "test-instance")

    def register_image(self):
        path = self.root / "comparison.png"
        Image.new("RGB", (16, 12), "blue").save(path)
        return self.control.register_result(
            title="Resolution comparison",
            image_path=path,
            provenance={"intent": "Inspect resolution sensitivity"},
        )

    def test_query_table_is_undoable_and_restores_without_cache_rows(self):
        result = asyncio.run(self.control.query(
            "select variable_id,maximum from q_variables", request="Variable maxima"
        ))
        self.assertEqual(result["rows"], [["density", None]])
        # Querying is independent of the active catalog and makes no workspace edit.
        self.assertEqual(len(self.controller.history.undo_entries), 0)
        self.assertEqual(self.control.results(), [])
        tab = self.control.create_tab("Metadata")
        tile = self.control.show_query(result["query_id"], tab["tab_id"])
        self.assertEqual(tile["media_type"], "query_table")
        self.controller.set_active_grid_cell(tile["cell_index"])
        self.assertEqual(self.state.selectedVar, "")
        self.controller.show_metadata_query_details(tile["cell_index"])
        self.assertIn("select variable_id", self.state.helpModalText)
        self.assertTrue(self.controller.undo_workspace())
        self.assertEqual(self.control.tabs()[-1]["tiles"], [])
        self.assertTrue(self.controller.redo_workspace())
        document = self.control.workspace()
        encoded = json.dumps(document)
        self.assertNotIn("query_rows", encoded)
        self.assertNotIn("query_csv_uri", encoded)
        self.collection.drop()
        self.control.restore_workspace(document)
        self.assertEqual(self.state.gridCells[0]["query_rows"], [{"c0": "density", "c1": None}])
        self.assertEqual(self.state.gridCells[0]["status"], "ok")

    def test_query_freeform_placement_full_grid_and_missing_snapshot(self):
        result = asyncio.run(self.control.query("select 1 as value"))
        tab = self.control.tabs()[0]
        self.controller.set_grid_layout_mode("freeform")
        one = self.control.show_query(result["query_id"], tab["tab_id"])
        two = self.control.show_query(result["query_id"], tab["tab_id"])
        self.assertNotEqual(one["tile_id"], two["tile_id"])
        self.controller.set_grid_layout_mode("uniform")
        self.controller.set_grid_layout_size(1, 1)
        before = self.controller.capture_workspace_history()
        with self.assertRaises(ControlError) as error:
            self.control.show_query(result["query_id"], tab["tab_id"])
        self.assertEqual(error.exception.code, "workspace_full")
        self.assertEqual(self.controller.capture_workspace_history(), before)
        (self.controller.query_result_store().directory / result["query_id"] / "query.json").unlink()
        self.controller.refresh_grid_cells()
        self.assertEqual(self.state.gridCells[0]["status"], "error")
        self.assertEqual(self.state.gridCells[0]["query_result_id"], result["query_id"])

    def test_working_result_coexists_with_campaign_tile_and_is_undoable(self):
        tab = self.control.tabs()[0]
        self.control.add_visualization("density", tab["tab_id"])
        result = self.register_image()
        tile = self.control.add_result(result["result_id"], tab["tab_id"])
        self.assertEqual(tile["publication_status"], "unpublished")
        self.assertEqual(len(self.control.tabs()[0]["tiles"]), 2)
        self.controller.set_active_grid_cell(tile["cell_index"])
        self.assertEqual(self.state.selectedVar, "")
        self.controller.show_working_result_details(tile["cell_index"])
        self.assertIn("Inspect resolution sensitivity", self.state.helpModalText)
        self.assertTrue(self.controller.undo_workspace())
        self.assertEqual(len(self.control.tabs()[0]["tiles"]), 1)
        self.assertTrue(self.controller.redo_workspace())
        self.assertEqual(
            self.control.tabs()[0]["tiles"][1]["working_result_id"], result["result_id"]
        )

    def test_working_result_restores_after_cache_rebuild_and_store_reconnect(self):
        result = self.register_image()
        tab = self.control.create_tab("Working results")
        self.control.add_result(result["result_id"], tab["tab_id"])
        document = parse_workspace_document(
            workspace_json(self.state, self.controller.campaign_path)
        )
        self.assertNotIn("/pulsar-results/", json.dumps(document))
        self.controller.ingest_campaign_every_time()
        self.controller.result_store = ResultStore(
            self.root / "results", self.controller.campaign_path
        )
        self.controller.restore_workspace_state(document)
        cell = self.state.gridCells[0]
        self.assertEqual(cell["working_result_id"], result["result_id"])
        self.assertEqual(cell["status"], "ok")
        self.assertEqual(
            self.control.result(result["result_id"])["provenance"]["intent"],
            "Inspect resolution sensitivity",
        )

    def test_working_result_freeform_placement_and_missing_artifact(self):
        result = self.register_image()
        self.controller.set_grid_layout_mode("freeform")
        tab = self.control.tabs()[0]
        one = self.control.add_result(result["result_id"], tab["tab_id"])
        two = self.control.add_result(result["result_id"], tab["tab_id"])
        self.assertNotEqual(one["tile_id"], two["tile_id"])
        (
            self.controller.result_store.directory / result["result_id"] / "image.png"
        ).unlink()
        self.controller.refresh_grid_cells()
        self.assertEqual(self.state.gridCells[0]["status"], "error")
        self.assertEqual(
            self.state.gridCells[0]["working_result_id"], result["result_id"]
        )

    def test_context_tracks_browser_selection_and_excludes_payloads(self):
        self.controller.assign_var_to_grid_cell(0, "density")
        context = self.control.context()
        self.assertEqual(context["selected_variable_id"], "density")
        self.assertEqual(context["selected_tiles"][0]["variable_id"], "density")
        self.assertNotIn("payload", json.dumps(context))
        self.assertNotIn("src", context["selected_tiles"][0])
        self.assertEqual(
            self.control.catalog(), [{"variable_id": "density", "label": "density"}]
        )

    def test_create_tab_and_add_plot_are_separate_undoable_edits(self):
        tab = self.control.create_tab("Comparison")
        self.assertEqual(tab["title"], "Comparison")
        self.assertTrue(tab["active"])
        self.assertEqual(len(self.controller.history.undo_entries), 1)
        plot = self.control.add_visualization("density", tab["tab_id"])
        self.assertEqual(plot["tab_id"], tab["tab_id"])
        self.assertEqual(plot["status"], "ok")
        self.assertEqual(len(self.controller.history.undo_entries), 2)
        self.assertTrue(self.controller.undo_workspace())
        self.assertEqual(self.control.tabs()[-1]["tiles"], [])
        self.assertTrue(self.controller.undo_workspace())
        self.assertEqual(len(self.control.tabs()), 1)

    def test_targeted_add_activates_tab_and_preserves_other_tab(self):
        first = self.control.tabs()[0]
        self.control.add_visualization("density", first["tab_id"])
        second = self.control.create_tab("Other")
        result = self.control.add_visualization("density", first["tab_id"])
        self.assertEqual(result["cell_index"], 1)
        self.assertEqual(self.state.workspaceActiveTabId, first["tab_id"])
        tabs = {tab["tab_id"]: tab for tab in self.control.tabs()}
        self.assertEqual(len(tabs[first["tab_id"]]["tiles"]), 2)
        self.assertEqual(tabs[second["tab_id"]]["tiles"], [])

    def test_freeform_uses_existing_canvas_placement(self):
        self.controller.set_grid_layout_mode("freeform")
        tab = self.control.tabs()[0]
        one = self.control.add_visualization("density", tab["tab_id"])
        two = self.control.add_visualization("density", tab["tab_id"])
        self.assertTrue(one["tile_id"])
        self.assertNotEqual(one["tile_id"], two["tile_id"])
        self.assertEqual(len(self.control.tabs()[0]["tiles"]), 2)

    def test_query_source_refs_select_distinct_sources_in_both_layouts(self):
        self.add_rusanov_sources()
        result = asyncio.run(self.control.query(
            "select source_ref,source_dataset from q_variables join q_sources using(source_ref) "
            "where variable_id='pressure' order by maximum desc"
        ))
        for mode in ("uniform", "freeform"):
            with self.subTest(mode=mode):
                tab = self.control.create_tab(mode)
                self.controller.set_grid_layout_mode(mode)
                for ref, source in result["rows"] + result["rows"][:1]:
                    tile = self.control.add_visualization(
                        "density", tab["tab_id"], source_ref=ref
                    )
                    self.assertEqual(tile["source_dataset"], source)
                    self.assertTrue(
                        tile["source_id"].startswith("local-source:v1:")
                    )
                    self.assertEqual(tile["source_id"], tile["_source_key"])
                    scalar_call = (
                        self.controller.maybe_handle_generated_scalar_plot.call_args
                    )
                    self.assertEqual(
                        scalar_call.kwargs["source_row"]["source_dataset"], source
                    )
                tiles = self.control.tabs()[-1]["tiles"]
                self.assertNotEqual(tiles[0]["source_id"], tiles[1]["source_id"])
                self.assertEqual(tiles[0]["source_id"], tiles[2]["source_id"])
                self.assertTrue(self.controller.undo_workspace())
                self.assertEqual(len(self.control.tabs()[-1]["tiles"]), 2)
                self.assertTrue(self.controller.redo_workspace())
                self.assertEqual(len(self.control.tabs()[-1]["tiles"]), 3)

    def test_invalid_or_ambiguous_source_ref_preserves_workspace(self):
        self.add_rusanov_sources()
        self.collection.insert_one({
            "variable_id": "pressure", "variable_type": "variable",
            "source_dataset": "pressure-only.bp",
        })
        tab = self.control.tabs()[0]
        before = self.controller.capture_workspace_history()
        for ref, code in (
            ("", "invalid_request"),
            ([], "invalid_request"),
            ("not a reference", "source_not_found"),
            ('["dataset","missing/output.bp"]', "source_not_found"),
            ('["dataset","pressure-only.bp"]', "source_not_found"),
        ):
            with self.subTest(ref=ref), self.assertRaises(ControlError) as error:
                self.control.add_visualization("density", tab["tab_id"], source_ref=ref)
            self.assertEqual(error.exception.code, code)
            self.assertEqual(self.controller.capture_workspace_history(), before)
        summary = self.controller.application.get_source_summary(
            {"variable_id": "density"}
        )
        source = summary["sources"][0]
        with patch.object(
            self.controller.application, "get_source_summary",
            return_value={"sources": [source, source]},
        ):
            with self.assertRaises(ControlError) as error:
                self.control.add_visualization(
                    "density", tab["tab_id"],
                    source_ref=json.dumps(
                        ["dataset", source["source_dataset"]], separators=(",", ":")
                    ),
                )
        self.assertEqual(error.exception.code, "ambiguous_source")
        self.assertEqual(self.controller.capture_workspace_history(), before)

    def test_explicit_source_still_obeys_current_catalog_query(self):
        self.add_rusanov_sources()
        tab = self.control.tabs()[0]
        self.state.queryFilter = {"source_dataset": "rusanov_64/output.bp"}
        before = self.controller.capture_workspace_history()
        with self.assertRaises(ControlError) as error:
            self.control.add_visualization(
                "density", tab["tab_id"],
                source_ref='["dataset","rusanov_128/output.bp"]',
            )
        self.assertEqual(error.exception.code, "source_not_found")
        self.assertEqual(self.controller.capture_workspace_history(), before)

    def test_invalid_requests_do_not_change_workspace(self):
        before = self.controller.capture_workspace_history()
        cases = (
            lambda: self.control.create_tab(""),
            lambda: self.control.create_tab("Bad", "missing"),
            lambda: self.control.add_visualization("missing", "tab-1"),
            lambda: self.control.add_visualization("density", "missing"),
        )
        for call in cases:
            with self.assertRaises(ControlError):
                call()
            self.assertEqual(self.controller.capture_workspace_history(), before)
        self.assertEqual(len(self.controller.history.undo_entries), 0)

    def test_full_grid_does_not_replace_existing_plot(self):
        self.controller.set_grid_layout_size(1, 1)
        tab = self.control.tabs()[0]
        self.control.add_visualization("density", tab["tab_id"])
        before = self.controller.capture_workspace_history()
        with self.assertRaises(ControlError) as error:
            self.control.add_visualization("density", tab["tab_id"])
        self.assertEqual(error.exception.code, "workspace_full")
        self.assertEqual(self.controller.capture_workspace_history(), before)

    def test_render_failure_rolls_back_and_restores_active_tab(self):
        first = self.control.tabs()[0]
        second = self.control.create_tab("Other")
        self.controller.build_grid_cell_for_variable.side_effect = RuntimeError(
            "cannot read input"
        )
        before_count = len(self.controller.history.undo_entries)
        with self.assertRaises(ControlError) as error:
            self.control.add_visualization("density", first["tab_id"])
        self.assertEqual(error.exception.code, "visualization_unavailable")
        self.assertEqual(self.state.workspaceActiveTabId, second["tab_id"])
        self.assertEqual(len(self.controller.history.undo_entries), before_count)
        self.assertTrue(all(not tab["tiles"] for tab in self.control.tabs()))

    def test_render_failure_preserves_selection_in_same_tab(self):
        tab = self.control.tabs()[0]
        self.control.add_visualization("density", tab["tab_id"])
        before = self.control.context()
        self.controller.build_grid_cell_for_variable.side_effect = RuntimeError(
            "cannot read input"
        )
        with self.assertRaises(ControlError):
            self.control.add_visualization("density", tab["tab_id"])
        self.assertEqual(self.control.context(), before)

    def test_scalar_confirmation_is_cleared_on_failed_request(self):
        def require_confirmation(*_args, **_kwargs):
            self.state.showScalarPlotDialog = True
            return True

        self.controller.maybe_handle_generated_scalar_plot.side_effect = (
            require_confirmation
        )
        tab = self.control.tabs()[0]
        with self.assertRaises(ControlError) as error:
            self.control.add_visualization("density", tab["tab_id"])
        self.assertEqual(error.exception.code, "confirmation_required")
        self.assertFalse(self.state.showScalarPlotDialog)
        self.assertEqual(self.control.tabs()[0]["tiles"], [])


class ControlHttpTests(ControlFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.make_controller()
        self.session_path = self.root / "session.json"
        self.control = register_control_api(
            self.server, self.controller, self.session_path
        )
        self.addCleanup(self.server.controller.on_server_exited)
        app = web.Application()
        register_result_media_route(self.server, self.controller.result_store)
        self.server.controller.on_server_bind(SimpleNamespace(app=app))
        self.http = TestClient(TestServer(app))
        self.addAsyncCleanup(self.http.close)
        await self.http.start_server()
        self.server._running_port = self.http.server.port
        self.server.controller.on_server_ready()
        self.session = json.loads(self.session_path.read_text())
        self.headers = {
            "Authorization": f"Bearer {self.session['token']}",
            "X-Pulsar-Instance": self.session["instance_id"],
        }

    async def test_real_python_client_round_trip_and_reconnect(self):
        def workflow():
            client = connect(session_file=self.session_path)
            self.assertEqual(
                client.context()["instance_id"], self.session["instance_id"]
            )
            self.assertEqual(client.catalog()[0]["variable_id"], "density")
            tab = client.create_tab("Python comparison")
            result = client.add_visualization("density", tab_id=tab["tab_id"])
            self.assertEqual(result["media_type"], "image")
            reconnected = connect(session_file=self.session_path)
            self.assertEqual(
                reconnected.tabs()[-1]["tiles"][0]["variable_id"], "density"
            )
            with self.assertRaises(PulsarClientError) as error:
                reconnected.add_visualization("unknown", tab_id=tab["tab_id"])
            self.assertEqual(error.exception.status, 404)
            self.assertEqual(error.exception.code, "not_found")

        await asyncio.to_thread(workflow)

    async def test_python_client_adds_sources_returned_by_query(self):
        self.add_rusanov_sources()

        def workflow():
            client = connect(session_file=self.session_path)
            result = client.query(
                "select source_ref,source_dataset from q_variables join q_sources using(source_ref) "
                "where variable_id='pressure' order by maximum desc"
            )
            tab = client.create_tab("Query sources")
            for ref, source in result["rows"]:
                tile = client.add_visualization(
                    "density", tab_id=tab["tab_id"], source_ref=ref
                )
                self.assertEqual(tile["source_dataset"], source)
            tiles = client.tabs()[-1]["tiles"]
            self.assertNotEqual(tiles[0]["source_id"], tiles[1]["source_id"])
            with self.assertRaises(PulsarClientError) as error:
                client.add_visualization(
                    "density", tab_id=tab["tab_id"], source_ref="unknown"
                )
            self.assertEqual(error.exception.code, "source_not_found")
            self.assertEqual(len(client.tabs()[-1]["tiles"]), 2)

        await asyncio.to_thread(workflow)

    async def wait_for_time_request(self):
        for _ in range(100):
            request = self.state.timelineSeekRequest
            if request:
                return dict(request)
            await asyncio.sleep(0.001)
        self.fail("Time request was not sent to the browser")

    async def test_time_client_waits_for_browser_and_returns_actual_samples(self):
        tab = self.control.create_tab("Time")
        self.control.add_visualization("density", tab["tab_id"])
        client = await asyncio.to_thread(connect, session_file=self.session_path)
        task = asyncio.create_task(asyncio.to_thread(
            client.set_time, 0.6, tab_id=tab["tab_id"]
        ))
        request = await self.wait_for_time_request()
        self.assertFalse(task.done())
        # The HTTP server remains responsive while the browser is seeking.
        context = await asyncio.to_thread(client.context)
        self.assertEqual(context["active_tab_id"], tab["tab_id"])
        with self.assertRaises(ControlError) as error:
            await self.control.set_time(0.7, tab["tab_id"])
        self.assertEqual(error.exception.code, "seek_busy")
        self.control.complete_time_seek({**request, "request_id": "old-request"})
        self.assertFalse(task.done())
        self.control.complete_time_seek({
            **request, "physical_time": 0.5, "slider_index": 2,
            "plots": [{
                "cell_index": 0, "source_id": "", "physical_time": 0.4,
                "sample_index": 1, "frame_index": 7, "status": "sample",
            }],
        })
        receipt = await task
        self.assertEqual(receipt["requested_time"], 0.6)
        self.assertEqual(receipt["physical_time"], 0.5)
        self.assertEqual(receipt["plots"][0]["physical_time"], 0.4)
        self.assertEqual(receipt["plots"][0]["frame_index"], 7)
        self.assertEqual(receipt["plots"][0]["variable_id"], "density")
        self.assertEqual(self.state.timelineSeekRequest, {})

    async def test_time_validation_browser_errors_timeout_and_cancel(self):
        tab = self.control.tabs()[0]
        before = self.controller.capture_workspace_history()
        for value in (None, "0.5", True, float("inf"), float("nan"), 1 << 2048):
            with self.subTest(value=value), self.assertRaises(ControlError):
                await self.control.set_time(value, tab["tab_id"])
        with self.assertRaises(ControlError):
            await self.control.set_time(0.5, "missing")
        self.assertEqual(self.controller.capture_workspace_history(), before)
        response = await self.http.post(
            API_PATH + "/time", headers=self.headers, json={"tab_id": tab["tab_id"]}
        )
        self.assertEqual(response.status, 400)
        for message in ("No physical-time timeline", None):
            task = asyncio.create_task(self.control.set_time(0.5, tab["tab_id"]))
            request = await self.wait_for_time_request()
            if message:
                self.control.complete_time_seek({**request, "error": message})
            else:
                # A receipt from a tab that was switched away cannot claim success.
                self.control.complete_time_seek({**request, "tab_id": "another-tab"})
            with self.assertRaises(ControlError):
                await task
            self.assertEqual(self.state.timelineSeekRequest, {})
        with patch("pulsar.control.TIMELINE_SEEK_TIMEOUT", 0.01):
            with self.assertRaises(ControlError) as error:
                await self.control.set_time(0.5, tab["tab_id"])
            self.assertEqual(error.exception.code, "seek_timeout")
        self.assertEqual(self.state.timelineSeekRequest, {})
        task = asyncio.create_task(self.control.set_time(0.5, tab["tab_id"]))
        request = await self.wait_for_time_request()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.control.complete_time_seek({**request, "physical_time": 0.5})
        self.assertEqual(self.state.timelineSeekRequest, {})
        self.assertIsNone(self.control._pending_seek)

    async def test_time_receipt_rejects_replaced_plot(self):
        tab = self.control.tabs()[0]
        self.control.add_visualization("density", tab["tab_id"])
        task = asyncio.create_task(self.control.set_time(0.5, tab["tab_id"]))
        request = await self.wait_for_time_request()
        cells = deepcopy(self.state.gridCells)
        cells[0]["selected_visualization"] = "another-visualization"
        self.state.gridCells = cells
        self.control.complete_time_seek({
            **request, "physical_time": 0.5, "slider_index": 1,
            "plots": [{"cell_index": 0, "source_id": "", "status": "sample"}],
        })
        with self.assertRaises(ControlError) as error:
            await task
        self.assertEqual(error.exception.code, "workspace_changed")
        self.assertEqual(self.state.timelineSeekRequest, {})

    async def test_metadata_query_client_workflow_and_errors(self):
        def workflow():
            client = connect(session_file=self.session_path)
            self.assertEqual(client.query_schema()["scope"], "campaign")
            result = client.query("select variable_id from q_variables where variable_id=:id",
                                  {"id": "density"}, "Find density")
            self.assertEqual(result["rows"], [["density"]])
            tab = client.create_tab("Query")
            client.show_query(result["query_id"], tab_id=tab["tab_id"])
            self.assertEqual(client.tabs()[-1]["tiles"][0]["query_result_id"], result["query_id"])
            fresh = connect(session_file=self.session_path)
            self.assertEqual(fresh.queries()[0]["query_id"], result["query_id"])
            self.assertEqual(fresh.query_result(result["query_id"])["sql"], result["sql"])
            with self.assertRaises(PulsarClientError) as error:
                fresh.query("delete from campaign_entries")
            self.assertEqual(error.exception.code, "query_failed")
            self.assertEqual(len(fresh.queries()), 1)
            return result

        await asyncio.to_thread(workflow)
        response = await self.http.post(API_PATH + "/queries", headers=self.headers,
                                        json={"sql": "select 1", "unexpected": True})
        self.assertEqual(response.status, 400)
        response = await self.http.get(API_PATH + "/query-schema")
        self.assertEqual(response.status, 401)

    async def test_missing_or_invalid_sql_returns_bad_request_without_changes(self):
        before = self.controller.capture_workspace_history()
        queries = self.control.queries()
        for payload in (
            {},
            {"parameters": {}, "request": "Missing SQL"},
            {"sql": None},
            {"sql": ""},
            {"sql": "   "},
            {"sql": 17},
        ):
            with self.subTest(payload=payload):
                response = await self.http.post(
                    API_PATH + "/queries", headers=self.headers, json=payload
                )
                self.assertEqual(response.status, 400)
                error = (await response.json())["error"]
                self.assertEqual(error["code"], "query_failed")
                self.assertIn("SQL must be nonempty text", error["message"])
                self.assertEqual(self.control.queries(), queries)
                self.assertEqual(self.controller.capture_workspace_history(), before)

        response = await self.http.post(
            API_PATH + "/queries", headers=self.headers, json={"sql": "select 1"}
        )
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["result"]["rows"], [[1]])

    async def test_running_metadata_query_does_not_block_context_and_can_cancel(self):
        from threading import Event

        from pulsar.metadata_query import MetadataQueryError

        started = Event()

        def execute(_sql, _parameters, _request, *, cancel):
            started.set()
            cancel.wait(2)
            raise MetadataQueryError("Query cancelled")

        engine = SimpleNamespace(execute=execute)
        self.controller.metadata_query_engine = lambda: engine
        task = asyncio.create_task(self.control.query("select 1"))
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            response = await self.http.get(API_PATH + "/context", headers=self.headers)
            self.assertEqual(response.status, 200)
            with self.assertRaises(ControlError) as error:
                await self.control.query("select 2")
            self.assertEqual(error.exception.code, "query_busy")
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(self.control.queries(), [])

    async def test_authentication_and_instance_identity(self):
        response = await self.http.get(API_PATH + "/context")
        self.assertEqual(response.status, 401)
        headers = {**self.headers, "X-Pulsar-Instance": "other"}
        response = await self.http.get(API_PATH + "/context", headers=headers)
        self.assertEqual(response.status, 409)
        self.assertNotIn("token", await response.text())
        self.assertEqual(self.session_path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(self.session["token"], json.dumps(self.state.to_dict()))

    async def test_result_registration_display_media_and_workspace_round_trip(self):
        image_path = self.root / "external.png"
        Image.new("RGB", (12, 9), "green").save(image_path)
        original = image_path.read_bytes()
        script_path = self.root / "analysis.py"
        script_path.write_text("print('original analysis')\n")
        workspace_path = self.root / "saved.json"

        def workflow():
            client = connect(session_file=self.session_path)
            tab = client.create_tab("Comparison")
            client.add_visualization("density", tab_id=tab["tab_id"])
            result = client.register_result(
                image_path,
                title="Working comparison",
                script_path=script_path,
                parameters={"time": 0.1},
                provenance={
                    "request": "Compare density",
                    "intent": "Test resolution sensitivity",
                    "inputs": [
                        {
                            "variable_id": "density",
                            "source_dataset": "run-a/output.bp",
                            "timestep": 1,
                        }
                    ],
                },
            )
            tile = client.add_result(result["result_id"], tab_id=tab["tab_id"])
            self.assertEqual(tile["publication_status"], "unpublished")
            self.assertEqual(
                client.result(result["result_id"])["parameters"], {"time": 0.1}
            )
            self.assertEqual(client.results(), [result])
            client.save_workspace(workspace_path)
            client.create_tab("Scratch")
            client.load_workspace(workspace_path)
            self.assertEqual(len(client.tabs()), 2)
            self.assertEqual(
                client.tabs()[-1]["tiles"][1]["working_result_id"], result["result_id"]
            )
            return result

        result = await asyncio.to_thread(workflow)
        image_path.write_bytes(b"overwritten")
        url = self.controller.result_store.tile(result["result_id"])["src"]
        response = await self.http.get(url)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Content-Type"], "image/png")
        self.assertEqual(await response.read(), original)
        response = await self.http.get(url.replace(result["result_id"], "not-a-uuid"))
        self.assertEqual(response.status, 404)

    @unittest.skipUnless(
        shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires FFmpeg tools"
    )
    async def test_movie_registration_and_seekable_media_through_real_client(self):
        from media_utils import frames_to_mp4_bytes

        image = self.root / "poster.png"
        Image.new("RGB", (16, 12), "blue").save(image)
        movie = self.root / "comparison.mp4"
        original = frames_to_mp4_bytes([image.read_bytes(), image.read_bytes()], fps=2)
        movie.write_bytes(original)

        def workflow():
            client = connect(session_file=self.session_path)
            result = client.register_result(
                image,
                title="Working movie",
                video_path=movie,
                frame_times=[0.0, 0.75],
                time_unit="s",
            )
            tab = client.create_tab("Movie")
            tile = client.add_result(result["result_id"], tab_id=tab["tab_id"])
            self.assertEqual(tile["media_type"], "video")
            self.assertEqual(tile["time_values"], [0.0, 0.75])
            self.assertEqual(tile["time_mode"], "physical_time")
            self.assertEqual(client.result(result["result_id"])["video"]["duration"], 1)
            return result

        result = await asyncio.to_thread(workflow)
        movie.write_bytes(b"changed original")
        url = self.controller.result_store.tile(result["result_id"])["src"]
        response = await self.http.get(url)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Content-Type"], "video/mp4")
        self.assertEqual(response.headers["Accept-Ranges"], "bytes")
        self.assertEqual(await response.read(), original)
        response = await self.http.get(url, headers={"Range": "bytes=0-127"})
        self.assertEqual(response.status, 206)
        self.assertEqual(
            response.headers["Content-Range"], f"bytes 0-127/{len(original)}"
        )
        self.assertEqual(await response.read(), original[:128])
        response = await self.http.get(url, headers={"Range": "bytes=-20"})
        self.assertEqual(response.status, 206)
        self.assertEqual(await response.read(), original[-20:])
        response = await self.http.get(
            url, headers={"Range": f"bytes={len(original)}-"}
        )
        self.assertEqual(response.status, 416)
        response = await self.http.get(url.replace("movie.mp4", "analysis.py"))
        self.assertEqual(response.status, 404)

    async def test_invalid_result_leaves_store_and_workspace_unchanged(self):
        before = self.controller.capture_workspace_history()
        response = await self.http.post(
            API_PATH + "/results",
            headers=self.headers,
            json={"title": "Missing", "image_path": str(self.root / "missing.png")},
        )
        self.assertEqual(response.status, 400)
        self.assertEqual(self.controller.result_store.list(), [])
        response = await self.http.post(
            API_PATH + "/result-views",
            headers=self.headers,
            json={"result_id": str(uuid4()), "tab_id": "tab-1"},
        )
        self.assertEqual(response.status, 404)
        self.assertEqual(self.controller.capture_workspace_history(), before)

    async def test_malformed_and_oversized_requests_leave_workspace_unchanged(self):
        before = self.controller.capture_workspace_history()
        for body in ("not json", "[]", '{"title":"Bad","extra":true}'):
            response = await self.http.post(
                API_PATH + "/tabs", headers=self.headers, data=body
            )
            self.assertEqual(response.status, 400)
        response = await self.http.post(
            API_PATH + "/tabs", headers=self.headers, data="x" * 16385
        )
        self.assertEqual(response.status, 413)
        self.assertEqual(self.controller.capture_workspace_history(), before)

    async def test_session_file_is_exclusive_and_removed_on_shutdown(self):
        with self.assertRaises(FileExistsError):
            register_control_api(self.server, self.controller, self.session_path)
        self.server.controller.on_server_exited()
        self.assertFalse(self.session_path.exists())

    async def test_client_rejects_wrong_version_and_unready_session(self):
        path = self.root / "bad-session.json"
        path.write_text(json.dumps({"api_version": 999}))
        with self.assertRaises(PulsarClientError) as error:
            connect(session_file=path)
        self.assertEqual(error.exception.code, "version_mismatch")
        path.write_text(json.dumps({"api_version": 1}))
        with self.assertRaises(PulsarClientError) as error:
            connect(session_file=path)
        self.assertEqual(error.exception.code, "not_ready")

    async def test_client_rejects_invalid_or_nonlocal_endpoints(self):
        path = self.root / "bad-session.json"
        for endpoint in (
            "https://127.0.0.1:8080/pulsar-api/v1",
            "http://example.com:8080/pulsar-api/v1",
            "http://127.0.0.1:invalid/pulsar-api/v1",
            "http://127.0.0.1/pulsar-api/v1",
        ):
            path.write_text(json.dumps({**self.session, "endpoint": endpoint}))
            with self.assertRaises(PulsarClientError):
                connect(session_file=path)

    async def test_nonfinite_metadata_is_valid_json(self):
        self.state.sourceRowsAll = [{"_key": "source", "minimum": float("nan")}]
        self.state.selectedSourceKeys = ["source"]
        response = await self.http.get(API_PATH + "/context", headers=self.headers)
        self.assertEqual(response.status, 200)
        text = await response.text()
        self.assertNotIn("NaN", text)


if __name__ == "__main__":
    unittest.main()
