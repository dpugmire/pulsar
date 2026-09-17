import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np


try:
    import adios2  # noqa: F401
except ModuleNotFoundError:
    adios2 = types.ModuleType("adios2")
    adios2.FileReader = object
    sys.modules["adios2"] = adios2


from application import SeuratApplication
from controllers import _variable_groups_from_navigation, attach_controllers
from db import CampaignDb
from query_parser import python_query_to_filters, python_query_to_mongo
from seurat.controllers.catalog import _filter_variable_groups
from seurat.controllers.composer import CONTROLLER_TYPES
from seurat.models.workspace_state import parse_workspace_document, workspace_json
from sqlite_store import SQLiteCampaignCollection
from state_init import init_state


class RecordingEvent:
    def __init__(self):
        self.callbacks = []

    def add(self, callback):
        self.callbacks.append(callback)


class RecordingController:
    def __init__(self):
        self.actions = {}
        self.triggers = {}
        self.on_server_ready = RecordingEvent()

    def add(self, name):
        def register(callback):
            self.actions[name] = callback
            return callback

        return register

    def set(self, name, clear=False):
        if clear:
            self.actions.pop(name, None)
        return self.add(name)

    def trigger(self, name):
        def register(callback):
            self.triggers[name] = callback
            return callback

        return register


class RecordingState(SimpleNamespace):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.change_callbacks = {}

    def change(self, *_names):
        def register(callback):
            for name in _names:
                self.change_callbacks.setdefault(name, []).append(callback)
            return callback

        return register


class RecordingInteractionLog:
    enabled = True

    def __init__(self):
        self.events = []

    def record(self, event_type, *, source, payload):
        event_id = f"event:{len(self.events) + 1}"
        self.events.append((event_type, source, payload))
        return event_id

    def checkpoint(self):
        pass


class VariableCatalogSearchTests(unittest.TestCase):
    def setUp(self):
        self.groups = [
            {
                "name": "0D",
                "variables": [
                    {
                        "id": "internal_energy",
                        "name": "internal_energy",
                        "label": "Internal Energy",
                        "path": "run-a/scalars.bp/internal_energy",
                        "source_dataset": "run-a/scalars.bp",
                    }
                ],
            },
            {
                "name": "run-b/output",
                "file_count": 2,
                "variables": [
                    {
                        "id": "density",
                        "name": "density",
                        "label": "Density",
                        "path": "run-b/output.bp/density",
                        "source_dataset": "run-b/output.bp",
                    },
                    {
                        "id": "temperature",
                        "name": "temperature",
                        "label": "Temperature",
                        "path": "run-b/output.bp/temperature",
                        "source_dataset": "run-b/output.bp",
                    },
                ],
            },
        ]

    def test_search_matches_variable_fields_case_insensitively(self):
        by_label = _filter_variable_groups(self.groups, "ENERGY")
        by_path = _filter_variable_groups(self.groups, "output.bp/temp")

        self.assertEqual(
            [item["id"] for item in by_label[0]["variables"]],
            ["internal_energy"],
        )
        self.assertEqual(by_path[0]["name"], "run-b/output")
        self.assertEqual(
            [item["id"] for item in by_path[0]["variables"]],
            ["temperature"],
        )

    def test_group_match_keeps_all_variables(self):
        filtered = _filter_variable_groups(self.groups, "RUN-B")

        self.assertEqual(len(filtered), 1)
        self.assertEqual(
            [item["id"] for item in filtered[0]["variables"]],
            ["density", "temperature"],
        )

    def test_empty_search_restores_catalog_and_no_match_is_empty(self):
        self.assertEqual(
            _filter_variable_groups(self.groups, "   "),
            self.groups,
        )
        self.assertEqual(
            _filter_variable_groups(self.groups, "not-present"),
            [],
        )
        self.assertEqual(len(self.groups[1]["variables"]), 2)


class CampaignDbNavigationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        db_path = Path(self.temp_dir.name) / "campaign.sqlite"
        self.collection = SQLiteCampaignCollection(db_path, "/campaign/example.aca")
        self.addCleanup(self.collection._con.close)

        documents = [
            {
                "campaign_path": "/campaign/example.aca",
                "variable_id": "density",
                "variable_name": "density",
                "variable_type": "variable",
                "source_dataset": "run-a/output.bp",
                "variable_path": "run-a/output.bp/density",
                "producer": "alpha",
                "metadata": {"Shape": "64,64", "AvailableStepsCount": "4"},
            },
            {
                "campaign_path": "/campaign/example.aca",
                "variable_id": "density",
                "variable_name": "density",
                "variable_type": "variable",
                "source_dataset": "run-b/output.bp",
                "variable_path": "run-b/output.bp/density",
                "producer": "beta",
                "metadata": {"Shape": "32,32", "AvailableStepsCount": "3"},
            },
            {
                "campaign_path": "/campaign/example.aca",
                "variable_id": "temperature",
                "variable_name": "temperature",
                "variable_type": "variable",
                "source_dataset": "run-a/scalars.bp",
                "variable_path": "run-a/scalars.bp/temperature",
                "producer": "alpha",
                "metadata": {"Shape": "8", "AvailableStepsCount": "8"},
            },
            {
                "campaign_path": "/campaign/example.aca",
                "variable_id": "step",
                "variable_name": "step",
                "variable_type": "variable",
                "source_dataset": "run-a/scalars.bp",
                "variable_path": "run-a/scalars.bp/step",
                "producer": "alpha",
                "metadata": {"Shape": "1", "AvailableStepsCount": "1"},
            },
            {
                "campaign_path": "/campaign/example.aca",
                "variable_id": "density",
                "variable_name": "density",
                "variable_type": "image",
                "source_dataset": "run-a/output.bp",
                "variable_path": "run-a/images/density.0000.png",
                "producer": "alpha",
                "visualization_name": "heatmap",
                "frame_index": 0,
                "metadata": {"Shape": "480,480"},
            },
        ]
        for document in documents:
            self.collection.insert_one(document)

        self.db = CampaignDb(self.collection)
        self.addCleanup(self.db.close)

    def test_scalar_plot_uses_steps_without_explicit_time_values(self):
        class PlotReader:
            def __init__(self):
                self.reads = []

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, path, **kwargs):
                self.reads.append((path, kwargs))
                return [10.0, 20.0, 30.0]

        reader = PlotReader()
        metadata = {"SingleValue": True, "AvailableStepsCount": "3"}
        with patch("db.FileReader", return_value=reader):
            x, y, x_label = CampaignDb._read_plot_series(
                "/campaign/example.aca",
                "run-a/output.bp/internal_energy",
                metadata,
            )

        self.assertEqual(x.tolist(), [0.0, 1.0, 2.0])
        self.assertEqual(y.tolist(), [10.0, 20.0, 30.0])
        self.assertEqual(x_label, "step")
        self.assertEqual(
            reader.reads,
            [
                (
                    "run-a/output.bp/internal_energy",
                    {"step_selection": [0, 3]},
                )
            ],
        )

    def test_scalar_plot_uses_only_explicit_matching_time_values(self):
        explicit_values, explicit_label = CampaignDb._plot_timeline_values(
            3,
            [0.0, 0.25, 1.0],
        )
        self.assertEqual(explicit_values.tolist(), [0.0, 0.25, 1.0])
        self.assertEqual(explicit_label, "time")
        self.assertEqual(
            CampaignDb._plot_timeline_values(3, [0.0, 1.0])[0].tolist(),
            [0.0, 1.0, 2.0],
        )
        self.assertEqual(
            CampaignDb._plot_timeline_values(3, None)[1],
            "step",
        )

    def test_rank_one_scalar_plot_uses_schema_time_values(self):
        class PlotReader:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _path, **_kwargs):
                return [2.0, 4.0, 8.0]

        metadata = {"Shape": "3", "AvailableStepsCount": "1"}
        with patch("db.FileReader", return_value=PlotReader()):
            x, y, x_label = CampaignDb._read_plot_series(
                "/campaign/example.aca",
                "run-a/output.bp/scalars/energy",
                metadata,
                [0.0, 0.5, 2.0],
            )

        self.assertEqual(x.tolist(), [0.0, 0.5, 2.0])
        self.assertEqual(y.tolist(), [2.0, 4.0, 8.0])
        self.assertEqual(x_label, "time")

    def test_rank_one_scalar_plot_uses_declared_shot_axis(self):
        class PlotReader:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _path, **_kwargs):
                return [3.5, 4.0, 4.5]

        axes = {
            "shot": {
                "id": "shot",
                "key": "lasernet:laser_runs:shot",
                "kind": "shot",
                "label": "Shot number",
                "values": [15.0, 16.0, 17.0],
            }
        }
        metadata = {"Shape": "3", "AvailableStepsCount": "1"}
        with patch("db.FileReader", return_value=PlotReader()):
            x, y, x_label = CampaignDb._read_plot_series(
                "/campaign/example.aca",
                "run.bp/data/meshes/scalars/energy/value",
                metadata,
                axes=axes,
                plot_x_axis="shot",
                selection_axis="shot",
            )

        self.assertEqual(x.tolist(), [15.0, 16.0, 17.0])
        self.assertEqual(y.tolist(), [3.5, 4.0, 4.5])
        self.assertEqual(x_label, "Shot number")

    def test_rank_two_waveform_reads_selected_signal_and_coordinate_rows(self):
        class PlotReader:
            def __init__(self):
                self.calls = []
                self.values = {
                    "run.bp/trace/signal": np.asarray(
                        [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
                    ),
                    "run.bp/trace/time": np.asarray(
                        [[0.0, 0.5, 1.0], [0.1, 0.6, 1.1]]
                    ),
                }

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, path, **kwargs):
                self.calls.append((path, kwargs))
                values = self.values[path]
                if "start" in kwargs:
                    row = int(kwargs["start"][0])
                    return values[row : row + 1]
                return values

        reader = PlotReader()
        axes = {
            "shot": {
                "id": "shot",
                "key": "lasernet:laser_runs:shot",
                "kind": "shot",
                "label": "Shot number",
                "values": [15.0, 16.0],
            },
            "trace_time": {
                "id": "trace_time",
                "key": "lasernet:laser_runs:trace_time",
                "kind": "within_shot_time",
                "label": "Time within shot",
                "unit": "s",
                "layout": "per_selection",
                "variable_path": "run.bp/trace/time",
                "shape": [2, 3],
            },
        }
        metadata = {"Shape": "2, 3", "AvailableStepsCount": "1"}
        with patch("db.FileReader", return_value=reader):
            x, y, x_label = CampaignDb._read_plot_series(
                "/campaign/example.aca",
                "run.bp/trace/signal",
                metadata,
                axes=axes,
                plot_x_axis="trace_time",
                selection_axis="shot",
                selection_index=1,
            )

        self.assertEqual(x.tolist(), [0.1, 0.6, 1.1])
        self.assertEqual(y.tolist(), [4.0, 5.0, 6.0])
        self.assertEqual(x_label, "Time within shot (s)")
        self.assertEqual(
            reader.calls,
            [
                (
                    "run.bp/trace/signal",
                    {"start": [1, 0], "count": [1, 3]},
                ),
                (
                    "run.bp/trace/time",
                    {"start": [1, 0], "count": [1, 3]},
                ),
            ],
        )

    def test_generated_waveform_tile_preserves_selection_and_plot_axes(self):
        class PlotReader:
            def __init__(self):
                self.calls = []
                self.close_calls = 0
                self.values = {
                    "run.bp/trace/signal": np.asarray(
                        [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
                    ),
                    "run.bp/trace/time": np.asarray(
                        [[0.0, 0.5, 1.0], [0.1, 0.6, 1.1]]
                    ),
                }

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def close(self):
                self.close_calls += 1

            def read(self, path, **kwargs):
                self.calls.append((path, kwargs))
                values = self.values[path]
                row = int(kwargs["start"][0])
                return values[row : row + 1]

        shot_key = "lasernet:laser_runs:shot"
        trace_time_key = "lasernet:laser_runs:trace_time"
        self.collection.insert_one(
            {
                "campaign_path": "/campaign/example.aca",
                "variable_id": "trace/signal",
                "variable_name": "trace/signal",
                "display_name": "Trace",
                "variable_type": "variable",
                "source_dataset": "run.bp",
                "variable_path": "run.bp/trace/signal",
                "metadata": {"Shape": "2, 3", "AvailableStepsCount": "1"},
                "axes": {
                    "shot": {
                        "id": "shot",
                        "key": shot_key,
                        "kind": "shot",
                        "label": "Shot number",
                        "values": [15.0, 16.0],
                    },
                    "trace_time": {
                        "id": "trace_time",
                        "key": trace_time_key,
                        "kind": "within_shot_time",
                        "label": "Time within shot",
                        "unit": "s",
                        "layout": "per_selection",
                        "variable_path": "run.bp/trace/time",
                        "shape": [2, 3],
                    },
                },
                "dimension_axes": ["shot", "trace_time"],
                "plot_x_axis": "trace_time",
                "selection_axis": "shot",
                "schema_default_axis": "shot",
            }
        )
        reader = PlotReader()

        with patch("db.FileReader", return_value=reader) as reader_factory:
            tile = self.db.get_or_create_generated_scalar_plot_tile(
                "/campaign/example.aca",
                "trace/signal",
                selection_index=1,
            )
            first_tile = self.db.get_or_create_generated_scalar_plot_tile(
                "/campaign/example.aca",
                "trace/signal",
                selection_index=0,
            )

        reader_factory.assert_called_once_with("/campaign/example.aca")
        self.assertEqual(tile["variable_name"], "Trace")
        self.assertEqual(tile["display_title"], "Trace")
        self.assertEqual(tile["plot"]["y_label"], "Trace")
        self.assertEqual(tile["selection_axis"]["index"], 1)
        self.assertEqual(tile["selection_axis"]["value"], 16.0)
        self.assertEqual(tile["selection_axis"]["key"], shot_key)
        self.assertTrue(tile["selection_axis"]["default"])
        self.assertEqual(tile["plot_axis_key"], trace_time_key)
        self.assertEqual(tile["plot"]["x_axis_key"], trace_time_key)
        self.assertEqual(tile["plot"]["x_label"], "Time within shot (s)")
        self.assertEqual(tile["plot"]["series"][0]["x"], [0.1, 0.6, 1.1])
        self.assertEqual(tile["plot"]["series"][0]["y"], [4.0, 5.0, 6.0])
        self.assertEqual(first_tile["plot"]["series"][0]["y"], [1.0, 2.0, 3.0])
        self.assertEqual(
            reader.calls,
            [
                ("run.bp/trace/signal", {"start": [1, 0], "count": [1, 3]}),
                ("run.bp/trace/time", {"start": [1, 0], "count": [1, 3]}),
                ("run.bp/trace/signal", {"start": [0, 0], "count": [1, 3]}),
                ("run.bp/trace/time", {"start": [0, 0], "count": [1, 3]}),
            ],
        )
        self.db.close()
        self.assertEqual(reader.close_calls, 1)

    def test_source_collection_maps_global_selection_across_members(self):
        members = [
            {
                "source_dataset": "run-a.bp",
                "length": 2,
                "offset": 0,
                "member_index": 0,
                "partition_label": "Run 10",
                "partition_value": 10.0,
                "order_value": 10.0,
            },
            {
                "source_dataset": "run-b.bp",
                "length": 1,
                "offset": 2,
                "member_index": 1,
                "partition_label": "Run 11",
                "partition_value": 11.0,
                "order_value": 11.0,
            },
        ]
        for member in members:
            dataset = member["source_dataset"]
            length = member["length"]
            self.collection.insert_one(
                {
                    "campaign_path": "/campaign/example.aca",
                    "variable_id": "trace/signal",
                    "variable_name": "trace/signal",
                    "display_name": "Trace",
                    "variable_type": "variable",
                    "source_dataset": dataset,
                    "variable_path": f"{dataset}/trace/signal",
                    "metadata": {"Shape": f"{length}, 3"},
                    "axes": {
                        "shot": {
                            "id": "shot",
                            "key": "demo:png:shot",
                            "kind": "shot",
                            "label": "Shot number",
                            "variable": "shots/value",
                            "variable_path": f"{dataset}/shots/value",
                            "values": list(range(15, 15 + length)),
                        },
                        "trace_time": {
                            "id": "trace_time",
                            "key": "demo:runs:trace_time",
                            "kind": "within_shot_time",
                            "label": "Time within shot",
                            "unit": "s",
                            "layout": "per_selection",
                            "variable_path": f"{dataset}/trace/time",
                            "shape": [length, 3],
                        },
                    },
                    "dimension_axes": ["shot", "trace_time"],
                    "plot_x_axis": "trace_time",
                    "selection_axis": "shot",
                    "schema_default_axis": "shot",
                    "source_collection_id": "png",
                    "source_collection_label": "PNG",
                    "source_collection_mode": "concatenate",
                    "source_collection_axis": "shot",
                    "source_collection_member_index": member["member_index"],
                    "source_collection_member_count": 2,
                    "source_collection_offset": member["offset"],
                    "source_collection_length": length,
                    "source_collection_total_length": 3,
                    "source_collection_partition_label": member["partition_label"],
                    "source_collection_partition_value": member["partition_value"],
                }
            )

        class PlotReader:
            def __init__(self):
                self.values = {
                    "run-a.bp/shots/value": np.asarray([15.0, 16.0]),
                    "run-b.bp/shots/value": np.asarray([15.0]),
                    "run-a.bp/trace/signal": np.asarray(
                        [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
                    ),
                    "run-b.bp/trace/signal": np.asarray([[7.0, 8.0, 9.0]]),
                    "run-a.bp/trace/time": np.asarray(
                        [[0.0, 0.5, 1.0], [0.0, 0.5, 1.0]]
                    ),
                    "run-b.bp/trace/time": np.asarray([[0.0, 0.5, 1.0]]),
                }

            def read(self, path, **kwargs):
                values = self.values[path]
                if "start" in kwargs:
                    row = int(kwargs["start"][0])
                    return values[row : row + 1]
                return values

            def close(self):
                pass

        reader = PlotReader()
        with patch("db.FileReader", return_value=reader):
            tile = self.db.get_or_create_generated_scalar_plot_tile(
                "/campaign/example.aca",
                "trace/signal",
                source_filter={"source_collection_id": "png"},
                selection_index=2,
            )

        self.assertEqual(tile["source_collection_id"], "png")
        self.assertEqual(tile["plot"]["series"][0]["y"], [7.0, 8.0, 9.0])
        self.assertEqual(tile["plot"]["series"][0]["source_label"], "Run 11")
        self.assertEqual(tile["selection_axis"]["values"], [0.0, 1.0, 2.0])
        self.assertEqual(
            tile["selection_axis"]["labels"],
            [
                "1 / 3 · Run 10 · Shot number 15",
                "2 / 3 · Run 10 · Shot number 16",
                "3 / 3 · Run 11 · Shot number 15",
            ],
        )
        self.assertEqual(tile["selection_axis"]["index"], 2)

        summary = self.db.variable_min_max_summary("trace/signal")
        self.assertEqual(summary["num_sources"], 1)
        self.assertEqual(summary["sources"][0]["source_label"], "PNG")
        self.assertEqual(summary["sources"][0]["num_timesteps"], 3)
        self.assertEqual(
            summary["sources"][0]["source_datasets"],
            ["run-a.bp", "run-b.bp"],
        )

        state, controller = self.make_controller()
        owner = controller.actions["toggle_sources"].__self__
        state.variableLabelsById["trace/signal"] = "trace"
        owner.update_selected_var_panels("trace/signal")
        png_row = next(
            row
            for row in state.sourceRowsAll
            if row.get("source_collection_id") == "png"
        )
        with patch("db.FileReader", return_value=reader):
            cell = owner.generated_scalar_plot_cell_for_source_rows(
                "trace/signal",
                [png_row],
                {},
                allow_multi_sources=False,
            )
            regenerated = owner.regenerate_axis_selected_plot(cell, 2)

        self.assertEqual(cell["source_collection_id"], "png")
        self.assertEqual(len(cell["selection_axis"]["values"]), 3)
        self.assertEqual(
            cell["selection_axis"]["labels"][-1],
            "3 / 3 · Run 11 · Shot number 15",
        )
        self.assertEqual(regenerated["source_collection_id"], "png")
        self.assertEqual(regenerated["plot"]["series"][0]["y"], [7.0, 8.0, 9.0])

    def test_scalar_plot_candidate_preserves_declared_time_values(self):
        self.collection.insert_one(
            {
                "campaign_path": "/campaign/example.aca",
                "variable_id": "internal_energy",
                "variable_name": "internal_energy",
                "variable_type": "variable",
                "source_dataset": "run-a/output.bp",
                "variable_path": "run-a/output.bp/internal_energy",
                "time_source": "variable:time",
                "time_values": [0.0, 0.25, 1.0],
                "metadata": {"SingleValue": True, "AvailableStepsCount": "3"},
            }
        )

        candidate = self.db.scalar_plot_candidate("internal_energy")

        self.assertEqual(candidate["time_source"], "variable:time")
        self.assertEqual(candidate["time_values"], [0.0, 0.25, 1.0])

    def test_waveform_plot_candidate_preserves_axis_descriptors(self):
        axes = {
            "shot": {
                "id": "shot",
                "key": "lasernet:laser_runs:shot",
                "values": [15.0, 16.0],
            },
            "trace_time": {
                "id": "trace_time",
                "key": "lasernet:laser_runs:trace_time",
                "variable_path": "run.bp/trace/time",
                "shape": [2, 3],
            },
        }
        self.collection.insert_one(
            {
                "campaign_path": "/campaign/example.aca",
                "variable_id": "trace/signal",
                "variable_name": "trace/signal",
                "variable_type": "variable",
                "source_dataset": "run.bp",
                "variable_path": "run.bp/trace/signal",
                "metadata": {"Shape": "2, 3", "AvailableStepsCount": "1"},
                "axes": axes,
                "dimension_axes": ["shot", "trace_time"],
                "plot_x_axis": "trace_time",
                "selection_axis": "shot",
            }
        )

        candidate = self.db.scalar_plot_candidate("trace/signal")

        self.assertEqual(candidate["axes"], axes)
        self.assertEqual(candidate["dimension_axes"], ["shot", "trace_time"])
        self.assertEqual(candidate["plot_x_axis"], "trace_time")
        self.assertEqual(candidate["selection_axis"], "shot")

    def make_controller(self, interaction_log=None):
        state = RecordingState()
        init_state(state, self.db)
        state.gridLayoutMode = "uniform"
        state.variableLabelsById = {
            "density": "density",
            "temperature": "temperature",
        }
        server = SimpleNamespace(state=state, controller=RecordingController())
        attach_controllers(
            server=server,
            db=self.db,
            collection=self.collection,
            parse_campaign=lambda *_args, **_kwargs: None,
            campaign_path="/campaign/example.aca",
            interaction_log=interaction_log,
        )
        return state, server.controller

    def test_controller_records_normalized_query_and_workspace_events(self):
        interaction_log = RecordingInteractionLog()
        state, controller = self.make_controller(interaction_log)

        state.queryText = 'id == "density"'
        self.assertTrue(controller.actions["run_query"]())
        controller.actions["add_workspace_tab"]("pane-1")

        self.assertEqual(
            [event_type for event_type, _source, _payload in interaction_log.events],
            ["query.applied", "workspace.tab_created"],
        )
        query_payload = interaction_log.events[0][2]
        self.assertEqual(query_payload["origin"], "manual")
        self.assertEqual(query_payload["target"], "catalog")
        self.assertEqual(query_payload["result_variable_count"], 1)
        self.assertNotIn("queryText", query_payload)
        self.assertNotIn('id == "density"', str(query_payload))

    def test_controller_registration_contract_is_complete(self):
        state, controller = self.make_controller()

        self.assertEqual(
            set(controller.actions),
            {
                "activate_workspace_tab",
                "adjust_canvas_default_tile_width",
                "adjust_canvas_zoom",
                "add_workspace_tab",
                "add_grid_column",
                "add_grid_row",
                "add_var_to_grid",
                "apply_plot_settings",
                "apply_plugin_options",
                "apply_query_proposal",
                "apply_scalar_field_settings",
                "apply_scalar_field_options_patch",
                "apply_source_dialog",
                "apply_source_dialog_filter",
                "assign_var_to_grid_cell",
                "cancel_plot_settings",
                "cancel_plugin_options",
                "cancel_scalar_field_settings",
                "cancel_scalar_field_options_assistant",
                "cancel_scalar_plot_generation",
                "cancel_source_dialog",
                "clear_all_sources",
                "clear_grid_cell",
                "clear_query",
                "clear_source_filter",
                "close_workspace_pane",
                "close_workspace_tab",
                "close_query_assistant",
                "close_help_modal",
                "close_provenance_dialog",
                "confirm_scalar_plot_generation",
                "context_menu_cell_add_source",
                "context_menu_cell_clear",
                "context_menu_cell_pick_visualization",
                "context_menu_cell_plot_settings",
                "context_menu_cell_reset_span",
                "context_menu_cell_reset_view",
                "context_menu_cell_run_source_plugin",
                "context_menu_cell_scalar_field_settings",
                "context_menu_cell_select",
                "context_menu_cell_shrink_height",
                "context_menu_cell_shrink_width",
                "context_menu_cell_sources",
                "context_menu_cell_span_down",
                "context_menu_cell_span_right",
                "context_menu_item_add",
                "context_menu_item_select",
                "context_menu_tab_close",
                "context_menu_tab_rename",
                "delete_grid_column",
                "delete_grid_row",
                "hide_context_menu",
                "move_grid_cell",
                "move_workspace_tab",
                "load_workspace_state",
                "open_plot_settings_plugin_options",
                "open_provenance_dialog",
                "open_query_assistant",
                "open_scalar_field_options_assistant",
                "open_source_query_assistant",
                "open_visualization_assistant",
                "pick_grid_cell_visualization",
                "pick_tile_visualization",
                "pick_var",
                "reset_grid_cell_span",
                "reset_grid_track_sizes",
                "reset_plot_settings",
                "reset_plugin_options",
                "reset_scalar_field_settings",
                "rename_workspace_tab",
                "run_query",
                "save_workspace_state",
                "save_workspace_state_as",
                "select_all_sources",
                "select_source",
                "select_var",
                "set_active_axis_selection",
                "set_active_grid_cell",
                "set_canvas_nudge_others",
                "set_canvas_columns",
                "set_canvas_fit_to_view",
                "set_canvas_show_grid",
                "set_canvas_snap_to_grid",
                "set_dragged_var",
                "set_grid_cell_size",
                "set_grid_fit_min_cell_size",
                "set_grid_layout_mode",
                "set_grid_layout_size",
                "set_grid_sizing_mode",
                "show_query_help",
                "show_source_filter_help",
                "shrink_grid_cell_height",
                "shrink_grid_cell_width",
                "sort_sources",
                "source_dialog_select",
                "span_grid_cell_down",
                "span_grid_cell_right",
                "split_workspace_pane",
                "toggle_add_source",
                "toggle_scalar_field_background",
                "toggle_movie_details",
                "toggle_provenance_node_details",
                "toggle_source_visibility",
                "toggle_sources",
                "toggle_timeline_driver_cell",
                "toggle_variable_group",
                "translate_query_request",
                "translate_scalar_field_options_request",
                "update_plot_background_color",
                "update_plot_cursor_color",
                "update_plot_grid_color",
                "update_plot_series_color",
                "update_plot_series_line_style",
                "update_plugin_option_value",
                "update_scalar_field_contour_color",
                "validate_query_proposal",
                "undo_workspace",
                "redo_workspace",
            },
        )
        self.assertEqual(
            set(controller.triggers),
            {
                "add_var_to_canvas_trigger",
                "assign_var_to_grid_cell_trigger",
                "commit_canvas_layout_trigger",
                "commit_grid_track_resize_trigger",
                "hide_context_menu_trigger",
                "move_grid_cell_trigger",
                "move_workspace_canvas_tile_trigger",
                "move_workspace_grid_cell_trigger",
                "move_workspace_tab_trigger",
                "reorder_workspace_tab_trigger",
                "resize_workspace_split_trigger",
                "set_grid_track_sizes_trigger",
                "set_grid_track_weights_trigger",
                "sync_canvas_fit_zoom_trigger",
                "show_cell_context_menu",
                "show_item_context_menu",
                "show_tab_context_menu",
                "split_workspace_tab_trigger",
                "undo_workspace_trigger",
                "redo_workspace_trigger",
            },
        )

    def test_active_axis_selection_synchronizes_only_matching_axis_keys(self):
        state, controller = self.make_controller()

        def axis_cell(axis_key, values):
            return {
                "variable_id": axis_key,
                "variable_name": axis_key,
                "media_type": "plot1d",
                "status": "ok",
                "plot_axis_key": axis_key,
                "selection_axis": {
                    "id": axis_key.rsplit(":", 1)[-1],
                    "key": axis_key,
                    "label": "Shot number",
                    "values": values,
                    "index": 0,
                    "value": values[0],
                },
            }

        shot_key = "lasernet:laser_runs:shot"
        cells = [
            axis_cell(shot_key, [15.0, 16.0]),
            axis_cell(shot_key, [15.0, 16.0]),
            axis_cell("lasernet:laser_runs:trace_time", [0.0, 0.5]),
            {
                "variable_id": "static",
                "variable_name": "static",
                "status": "ok",
            },
        ]
        state.gridCells = cells
        state.activeGridCell = 2
        state.timelineDriverCell = 0

        controller.actions["set_active_axis_selection"](1)

        self.assertEqual(state.gridCells[0]["selection_axis"]["value"], 16.0)
        self.assertEqual(state.gridCells[1]["selection_axis"]["index"], 1)
        self.assertEqual(state.gridCells[1]["axis_sync_status"], "synchronized")
        self.assertEqual(state.gridCells[2]["axis_sync_status"], "incompatible")
        self.assertEqual(state.gridCells[3]["axis_sync_status"], "static")

    def test_active_axis_selection_marks_missing_numeric_value_unavailable(self):
        state, controller = self.make_controller()
        shot_key = "lasernet:laser_runs:shot"
        state.gridCells = [
            {
                "variable_id": "driver",
                "variable_name": "driver",
                "status": "ok",
                "selection_axis": {
                    "id": "shot",
                    "key": shot_key,
                    "values": [15.0, 16.0],
                },
            },
            {
                "variable_id": "sparse",
                "variable_name": "sparse",
                "status": "ok",
                "selection_axis": {
                    "id": "shot",
                    "key": shot_key,
                    "values": [15.0, 17.0],
                },
            },
        ]
        state.activeGridCell = 0
        state.timelineDriverCell = -1

        controller.actions["set_active_axis_selection"](1)

        self.assertEqual(state.gridCells[0]["selection_axis"]["value"], 16.0)
        self.assertEqual(state.gridCells[1]["axis_sync_status"], "unavailable")
        self.assertEqual(
            set(state.change_callbacks),
            {
                "selectedVar",
                "showOnlyVisualizedVars",
                "variablePaneView",
                "variableSearchText",
            },
        )
        self.assertEqual(len(controller.on_server_ready.callbacks), 1)

        owner = controller.actions["undo_workspace"].__self__
        for controller_type in CONTROLLER_TYPES:
            action_methods = dict(controller_type.ACTION_BINDINGS)
            for action_name in getattr(controller_type, "HISTORY_ACTIONS", {}):
                callback = controller.actions[action_name]
                self.assertTrue(hasattr(callback, "__wrapped__"), action_name)
                self.assertEqual(
                    callback.__wrapped__,
                    getattr(owner, action_methods[action_name]),
                )
            trigger_methods = dict(controller_type.TRIGGER_BINDINGS)
            for trigger_name in getattr(controller_type, "HISTORY_TRIGGERS", {}):
                callback = controller.triggers[trigger_name]
                self.assertTrue(hasattr(callback, "__wrapped__"), trigger_name)
                self.assertEqual(
                    callback.__wrapped__,
                    getattr(owner, trigger_methods[trigger_name]),
                )

    def test_workspace_tabs_preserve_independent_grid_state(self):
        state, controller = self.make_controller()
        state.gridCells[0]["variable_id"] = "density"
        state.gridCells[0]["variable_name"] = "density"

        controller.actions["add_workspace_tab"]("pane-1")

        self.assertEqual(state.workspaceActiveTabId, "tab-2")
        self.assertEqual(state.gridLayoutMode, "uniform")
        self.assertEqual(len(state.gridCells), 9)
        self.assertTrue(all(cell["status"] == "empty" for cell in state.gridCells))

        controller.actions["activate_workspace_tab"]("pane-1", "tab-1")

        self.assertEqual(state.workspaceActiveTabId, "tab-1")
        self.assertEqual(state.gridCells[0]["variable_id"], "density")

    def test_workspace_tab_edits_support_undo_redo(self):
        state, controller = self.make_controller()

        controller.actions["add_workspace_tab"]("pane-1")

        self.assertEqual(len(state.workspacePanes[0]["tabs"]), 2)
        self.assertTrue(state.workspaceCanUndo)
        self.assertEqual(state.workspaceUndoLabel, "Add tab")
        self.assertTrue(controller.actions["undo_workspace"]())
        self.assertEqual(len(state.workspacePanes[0]["tabs"]), 1)
        self.assertEqual(state.workspaceActiveTabId, "tab-1")
        self.assertTrue(state.workspaceCanRedo)

        self.assertTrue(controller.actions["redo_workspace"]())
        self.assertEqual(len(state.workspacePanes[0]["tabs"]), 2)
        self.assertEqual(state.workspaceActiveTabId, "tab-1")

    def test_canvas_geometry_undo_preserves_transient_view_controls(self):
        state, controller = self.make_controller()
        controller.actions["add_var_to_grid"]("density")
        controller.actions["set_grid_layout_mode"]("freeform")
        cell = state.gridCells[0]
        before = (
            cell["canvas_x"],
            cell["canvas_y"],
            cell["canvas_w"],
            cell["canvas_h"],
        )
        payload = json.dumps(
            [
                {
                    "tile_id": cell["tile_id"],
                    "x": 10,
                    "y": 4,
                    "w": cell["canvas_w"],
                    "h": cell["canvas_h"],
                }
            ]
        )
        controller.triggers["commit_canvas_layout_trigger"](
            payload,
            cell["tile_id"],
            state.workspaceActivePaneId,
            state.workspaceActiveTabId,
        )
        state.canvasShowGrid = True
        state.canvasZoom = 0.5
        state.canvasFitToView = True
        state.canvasDefaultTileWidth = 9

        self.assertTrue(controller.actions["undo_workspace"]())

        restored = state.gridCells[0]
        self.assertEqual(
            (
                restored["canvas_x"],
                restored["canvas_y"],
                restored["canvas_w"],
                restored["canvas_h"],
            ),
            before,
        )
        self.assertTrue(state.canvasShowGrid)
        self.assertEqual(state.canvasZoom, 0.5)
        self.assertTrue(state.canvasFitToView)
        self.assertEqual(state.canvasDefaultTileWidth, 9)

    def test_canvas_snap_toggle_is_transient_and_does_not_create_history(self):
        state, controller = self.make_controller()
        owner = controller.actions["undo_workspace"].__self__
        before_entry_count = len(owner.history.undo_entries)

        controller.actions["set_canvas_snap_to_grid"](False)

        self.assertFalse(state.canvasSnapToGrid)
        self.assertEqual(len(owner.history.undo_entries), before_entry_count)

    def test_grid_track_resize_commits_all_axes_as_one_history_entry(self):
        state, controller = self.make_controller()
        controller.actions["set_grid_layout_mode"]("uniform")
        before_columns = list(state.gridColumnSizes)
        before_rows = list(state.gridRowSizes)
        resized_columns = [before_columns[0] + 30, *before_columns[1:]]
        resized_rows = [before_rows[0] + 25, *before_rows[1:]]
        owner = controller.actions["undo_workspace"].__self__
        before_entry_count = len(owner.history.undo_entries)

        controller.triggers["commit_grid_track_resize_trigger"](
            json.dumps(
                {
                    "changes": [
                        {
                            "axis": "column",
                            "kind": "sizes",
                            "values": resized_columns,
                        },
                        {
                            "axis": "row",
                            "kind": "sizes",
                            "values": resized_rows,
                        },
                    ]
                }
            )
        )

        self.assertEqual(state.gridColumnSizes, resized_columns)
        self.assertEqual(state.gridRowSizes, resized_rows)
        self.assertEqual(len(owner.history.undo_entries), before_entry_count + 1)
        self.assertEqual(state.workspaceUndoLabel, "Resize grid track")

        self.assertTrue(controller.actions["undo_workspace"]())
        self.assertEqual(state.gridColumnSizes, before_columns)
        self.assertEqual(state.gridRowSizes, before_rows)

        self.assertTrue(controller.actions["redo_workspace"]())
        self.assertEqual(state.gridColumnSizes, resized_columns)
        self.assertEqual(state.gridRowSizes, resized_rows)

    def test_new_workspace_edit_clears_redo_stack(self):
        state, controller = self.make_controller()
        controller.actions["add_workspace_tab"]("pane-1")
        controller.actions["undo_workspace"]()
        self.assertTrue(state.workspaceCanRedo)

        controller.actions["rename_workspace_tab"]("pane-1", "tab-1", "Analysis")

        self.assertFalse(state.workspaceCanRedo)
        self.assertEqual(state.workspaceUndoLabel, "Rename tab")

    def test_canvas_default_tile_width_is_shared_across_workspace_tabs(self):
        state, controller = self.make_controller()

        controller.actions["adjust_canvas_default_tile_width"](3)
        controller.actions["add_workspace_tab"]("pane-1")

        self.assertEqual(state.canvasDefaultTileWidth, 5)
        controller.actions["activate_workspace_tab"]("pane-1", "tab-1")
        self.assertEqual(state.canvasDefaultTileWidth, 5)

    def test_workspace_tabs_preserve_independent_canvas_column_counts(self):
        state, controller = self.make_controller()
        controller.actions["set_grid_layout_mode"]("freeform")
        controller.actions["set_canvas_columns"](48)

        controller.actions["add_workspace_tab"]("pane-1")
        controller.actions["set_canvas_columns"](12)

        controller.actions["activate_workspace_tab"]("pane-1", "tab-1")
        self.assertEqual(state.canvasCols, 48)

        controller.actions["activate_workspace_tab"]("pane-1", "tab-2")
        self.assertEqual(state.canvasCols, 12)

    def test_workspace_tabs_preserve_independent_canvas_zoom_and_fit(self):
        state, controller = self.make_controller()
        controller.actions["set_grid_layout_mode"]("freeform")
        controller.actions["adjust_canvas_zoom"](-0.25)
        controller.actions["set_canvas_fit_to_view"](True)

        controller.actions["add_workspace_tab"]("pane-1")
        controller.actions["adjust_canvas_zoom"](0.25)
        self.assertEqual(state.canvasZoom, 1.0)
        self.assertFalse(state.canvasFitToView)

        controller.actions["activate_workspace_tab"]("pane-1", "tab-1")
        self.assertEqual(state.canvasZoom, 0.75)
        self.assertTrue(state.canvasFitToView)

        controller.actions["activate_workspace_tab"]("pane-1", "tab-2")
        self.assertEqual(state.canvasZoom, 1.0)
        self.assertFalse(state.canvasFitToView)

    def test_tab_context_menu_renames_and_closes_target_tab(self):
        state, controller = self.make_controller()
        controller.actions["add_workspace_tab"]("pane-1")

        controller.triggers["show_tab_context_menu"](
            "pane-1", "tab-1", 125.8, 42.2
        )

        self.assertTrue(state.contextMenuVisible)
        self.assertEqual(state.contextMenuKind, "tab")
        self.assertEqual(state.contextMenuItemLabel, "View 1")
        self.assertEqual(state.contextMenuTabPaneId, "pane-1")
        self.assertEqual(state.contextMenuTabId, "tab-1")
        self.assertTrue(state.contextMenuTabCanClose)
        self.assertEqual((state.contextMenuX, state.contextMenuY), (125, 42))

        controller.actions["context_menu_tab_rename"]("Overview")
        self.assertEqual(state.workspacePanes[0]["tabs"][0]["title"], "Overview")
        self.assertFalse(state.contextMenuVisible)

        controller.triggers["show_tab_context_menu"](
            "pane-1", "tab-1", 20, 30
        )
        controller.actions["context_menu_tab_close"](True)
        self.assertEqual(
            [tab["id"] for tab in state.workspacePanes[0]["tabs"]],
            ["tab-2"],
        )

        controller.triggers["show_tab_context_menu"](
            "pane-1", "tab-2", 20, 30
        )
        self.assertFalse(state.contextMenuTabCanClose)
        controller.actions["context_menu_tab_close"](True)
        self.assertEqual(len(state.workspacePanes[0]["tabs"]), 1)

    def test_workspace_split_and_move_tab_actions_are_constrained(self):
        state, controller = self.make_controller()
        controller.actions["add_workspace_tab"]("pane-1")
        controller.actions["split_workspace_pane"]("horizontal")

        self.assertEqual(len(state.workspacePanes), 2)
        self.assertEqual(state.workspaceSplitDirection, "horizontal")

        controller.actions["move_workspace_tab"]("pane-1", "tab-2")

        self.assertEqual(state.workspaceActivePaneId, "pane-2")
        self.assertEqual(state.workspaceActiveTabId, "tab-2")
        self.assertEqual(len(state.workspacePanes), 2)

        controller.actions["close_workspace_pane"]("pane-2", False)
        self.assertEqual(len(state.workspacePanes), 2)

    def test_workspace_supports_nested_splits_and_resizing(self):
        state, controller = self.make_controller()
        controller.actions["split_workspace_pane"]("horizontal", "pane-1")
        controller.actions["split_workspace_pane"]("vertical", "pane-1")
        controller.actions["split_workspace_pane"]("vertical", "pane-2")

        self.assertEqual(len(state.workspacePanes), 4)
        self.assertEqual(len(state.workspaceSplitters), 3)
        self.assertEqual(
            set(state.workspacePaneFrames),
            {"pane-1", "pane-2", "pane-3", "pane-4"},
        )

        controller.triggers["resize_workspace_split_trigger"]("split-1", 0.7)

        self.assertAlmostEqual(state.workspaceLayout["root"]["ratio"], 0.7)
        self.assertAlmostEqual(state.workspacePaneFrames["pane-2"]["left"], 70.0)

    def test_workspace_tab_reorder_trigger_preserves_active_tab(self):
        state, controller = self.make_controller()
        controller.actions["add_workspace_tab"]("pane-1")
        controller.actions["add_workspace_tab"]("pane-1")

        controller.triggers["reorder_workspace_tab_trigger"](
            "pane-1", "tab-1", 3
        )

        self.assertEqual(
            [tab["id"] for tab in state.workspacePanes[0]["tabs"]],
            ["tab-2", "tab-3", "tab-1"],
        )
        self.assertEqual(state.workspaceActiveTabId, "tab-3")

    def test_workspace_tab_move_trigger_targets_a_pane_insertion_slot(self):
        state, controller = self.make_controller()
        controller.actions["add_workspace_tab"]("pane-1")
        controller.actions["split_workspace_pane"]("horizontal", "pane-1")

        controller.triggers["move_workspace_tab_trigger"](
            "pane-1", "tab-1", "pane-2", 0
        )

        self.assertEqual(
            [tab["id"] for tab in state.workspacePanes[0]["tabs"]],
            ["tab-2"],
        )
        self.assertEqual(
            [tab["id"] for tab in state.workspacePanes[1]["tabs"]],
            ["tab-1", "tab-3"],
        )
        self.assertEqual(state.workspaceActivePaneId, "pane-2")
        self.assertEqual(state.workspaceActiveTabId, "tab-1")

    def test_workspace_tab_split_trigger_is_atomic_and_undoable(self):
        interaction_log = RecordingInteractionLog()
        state, controller = self.make_controller(interaction_log)
        controller.actions["add_workspace_tab"]("pane-1")

        controller.triggers["split_workspace_tab_trigger"](
            "pane-1", "tab-1", "pane-1", "vertical"
        )

        self.assertEqual(len(state.workspacePanes), 2)
        self.assertEqual(state.workspaceLayout["root"]["direction"], "vertical")
        self.assertEqual(
            [tab["id"] for tab in state.workspacePanes[0]["tabs"]], ["tab-2"]
        )
        self.assertEqual(
            [tab["id"] for tab in state.workspacePanes[1]["tabs"]], ["tab-1"]
        )
        self.assertEqual(state.workspaceActivePaneId, "pane-2")
        self.assertEqual(state.workspaceActiveTabId, "tab-1")
        self.assertEqual(
            interaction_log.events[-1][:2],
            ("workspace.pane_split", "tab_drag"),
        )

        self.assertTrue(controller.actions["undo_workspace"]())
        self.assertEqual(len(state.workspacePanes), 1)
        self.assertEqual(
            [tab["id"] for tab in state.workspacePanes[0]["tabs"]],
            ["tab-1", "tab-2"],
        )

    def test_workspace_grid_move_trigger_activates_the_destination_pane(self):
        state, controller = self.make_controller()
        state.gridCells[0].update(
            {
                "variable_id": "density",
                "variable_name": "density",
                "status": "ready",
            }
        )
        state.timelineDriverCell = 0
        controller.actions["split_workspace_pane"]("horizontal", "pane-1")
        controller.actions["set_grid_layout_mode"]("uniform")
        controller.actions["activate_workspace_tab"]("pane-1", "tab-1")

        controller.triggers["move_workspace_grid_cell_trigger"](
            "pane-1", "tab-1", 0, "pane-2", "tab-2", 4
        )

        self.assertEqual(state.workspaceActivePaneId, "pane-2")
        self.assertEqual(state.workspaceActiveTabId, "tab-2")
        self.assertEqual(state.gridCells[4]["variable_id"], "density")
        self.assertEqual(state.gridCells[0]["variable_id"], "")
        self.assertEqual(state.activeGridCell, 4)
        self.assertEqual(state.selectedGridCellIndices, [4])
        self.assertEqual(state.timelineDriverCell, -1)
        self.assertEqual(
            state.workspacePanes[0]["tabs"][0]["grid"]["cells"][0][
                "variable_id"
            ],
            "",
        )

    def test_workspace_freeform_move_places_tile_in_destination_canvas(self):
        state, controller = self.make_controller()
        state.gridCells[0].update(
            {
                "variable_id": "density",
                "variable_name": "density",
                "status": "ready",
            }
        )
        controller.actions["set_grid_layout_mode"]("freeform")
        controller.actions["split_workspace_pane"]("horizontal", "pane-1")
        controller.actions["set_grid_layout_mode"]("freeform")

        controller.triggers["move_workspace_canvas_tile_trigger"](
            "pane-1",
            "tab-1",
            0,
            "pane-2",
            "tab-2",
            json.dumps({"x": 6, "y": 5, "w": 8, "h": 6}),
        )

        self.assertEqual(state.workspaceActivePaneId, "pane-2")
        self.assertEqual(state.workspaceActiveTabId, "tab-2")
        self.assertEqual(len(state.gridCells), 1)
        self.assertEqual(state.gridCells[0]["variable_id"], "density")
        self.assertEqual(
            (
                state.gridCells[0]["canvas_x"],
                state.gridCells[0]["canvas_y"],
                state.gridCells[0]["canvas_w"],
                state.gridCells[0]["canvas_h"],
            ),
            (6, 5, 8, 6),
        )
        source_grid = state.workspacePanes[0]["tabs"][0]["grid"]
        self.assertEqual(source_grid["cells"], [])
        self.assertTrue(controller.actions["undo_workspace"]())
        self.assertEqual(state.workspaceActivePaneId, "pane-2")
        self.assertEqual(state.gridCells, [])
        source_grid = state.workspacePanes[0]["tabs"][0]["grid"]
        self.assertEqual(source_grid["cells"][0]["variable_id"], "density")

        self.assertTrue(controller.actions["redo_workspace"]())
        self.assertEqual(state.workspaceActivePaneId, "pane-2")
        self.assertEqual(state.gridCells[0]["variable_id"], "density")
        self.assertEqual(
            state.workspacePanes[0]["tabs"][0]["grid"]["cells"], []
        )

    def test_server_ready_lifecycle_reingests_and_refreshes_catalog(self):
        state = RecordingState()
        init_state(state, self.db)
        controller = RecordingController()
        server = SimpleNamespace(state=state, controller=controller)
        parse_calls = []

        def parse_campaign(campaign_path, collection, **kwargs):
            parse_calls.append((campaign_path, kwargs))
            collection.insert_one(
                {
                    "campaign_path": campaign_path,
                    "variable_id": "energy",
                    "variable_name": "energy",
                    "variable_type": "variable",
                    "source_dataset": "run/scalars.bp",
                    "metadata": {"SingleValue": True, "AvailableStepsCount": "3"},
                }
            )

        attach_controllers(
            server=server,
            db=self.db,
            collection=self.collection,
            parse_campaign=parse_campaign,
            campaign_path="/campaign/example.aca",
            image_association_schema_path="/schemas/images.yaml",
            campaign_schema_path="/schemas/campaign.yaml",
        )

        controller.on_server_ready.callbacks[0]()

        self.assertEqual(
            parse_calls,
            [
                (
                    "/campaign/example.aca",
                    {
                        "image_association_schema_path": "/schemas/images.yaml",
                        "campaign_schema_path": "/schemas/campaign.yaml",
                    },
                )
            ],
        )
        self.assertEqual(state.variableNames, ["energy"])
        self.assertIn("variables=1", state.dbStatus)

    def test_workspace_save_save_as_and_load_restore_semantic_grid(self):
        state, controller = self.make_controller()
        controller.actions["set_grid_layout_size"](2, 2)
        state.gridLayoutMode = "spanning"
        state.gridCells[0].update(
            {
                "variable_id": "density",
                "variable_name": "density",
                "visualization_name": "heatmap",
                "selected_visualization": "heatmap",
                "source_dataset": "run-a/output.bp",
                "col_span": 2,
                "src": "data:image/png;base64,not-persisted",
                "frame_sources": ["not-persisted"],
                "status": "ready",
            }
        )
        state.activeGridCell = 0
        state.selectedGridCellIndices = [0]
        state.selectedGridCellMap = {"0": True}

        owner = controller.actions["save_workspace_state"].__self__
        state_path = Path(self.temp_dir.name) / "custom-layout.json"
        live_grid_sizing = {
            "mode": "static",
            "column_sizes": "410,275",
            "row_sizes": "465,350",
            "column_weights": "2.5,0.5",
            "row_weights": "3,1",
        }
        with patch(
            "seurat.controllers.workspace.choose_workspace_save_path",
            return_value=str(state_path),
        ):
            controller.actions["save_workspace_state"](live_grid_sizing)

        document = parse_workspace_document(state_path.read_bytes())
        saved_grid = document["state"]["grid"]
        saved_cell = document["state"]["grid"]["cells"][0]
        self.assertNotIn("src", saved_cell)
        self.assertNotIn("frame_sources", saved_cell)
        self.assertEqual(saved_grid["sizing_mode"], "static")
        self.assertEqual(saved_grid["column_sizes"], [410, 275])
        self.assertEqual(saved_grid["row_sizes"], [465, 350])
        self.assertEqual(saved_grid["column_weights"], [2.5, 0.5])
        self.assertEqual(saved_grid["row_weights"], [3.0, 1.0])
        self.assertEqual(state.workspaceStatePath, str(state_path.resolve()))
        self.assertEqual(
            state.workspaceStateStatus,
            f"Saved: {state_path.resolve()}",
        )
        state.gridLayoutMode = "uniform"
        state.gridRows = 3
        state.gridCols = 3
        state.gridCells = []
        state.activeGridCell = -1
        state.selectedGridCellIndices = []
        state.selectedGridCellMap = {}
        state.gridColumnSizes = [300, 300, 300]
        state.gridRowSizes = [332, 332, 332]

        rebuilt_tile = {
            "variable_id": "density",
            "variable_name": "density",
            "visualization_name": "heatmap",
            "selected_visualization": "heatmap",
            "source_dataset": "run-a/output.bp",
            "media_type": "image_sequence",
            "src": "data:image/png;base64,rebuilt",
            "frame_count": 1,
            "frame_indices": [0],
            "frame_sources": ["data:image/png;base64,rebuilt"],
            "time_values": [0],
            "status": "ok",
        }
        with patch(
            "seurat.controllers.workspace.choose_workspace_load_path",
            return_value=str(state_path),
        ), patch.object(
            owner.db,
            "get_first_movie_tiles_for_variable",
            return_value=[rebuilt_tile],
        ):
            controller.actions["load_workspace_state"]()

        self.assertEqual((state.gridRows, state.gridCols), (2, 2))
        self.assertEqual(state.gridLayoutMode, "spanning")
        self.assertEqual(state.gridCells[0]["variable_id"], "density")
        self.assertEqual(
            state.gridCells[0]["selected_visualization"],
            "heatmap",
        )
        self.assertEqual(state.gridCells[0]["col_span"], 2)
        self.assertEqual(
            state.gridCells[0]["src"],
            "data:image/png;base64,rebuilt",
        )
        self.assertEqual(state.activeGridCell, 0)
        self.assertEqual(state.selectedGridCellIndices, [0])
        self.assertEqual(state.gridColumnSizes, [410, 275])
        self.assertEqual(state.gridRowSizes, [465, 350])
        self.assertEqual(state.gridColumnTemplate, "410px 275px")
        self.assertEqual(state.gridRowTemplate, "465px 350px")
        self.assertEqual(
            state.workspaceStateStatus,
            f"Loaded: {state_path.resolve()}",
        )
        self.assertEqual(state.workspaceStateError, "")
        self.assertFalse(state.workspaceCanUndo)
        self.assertFalse(state.workspaceCanRedo)

        state.queryText = "var == 'density'"
        controller.actions["save_workspace_state"]()
        saved_again = parse_workspace_document(state_path.read_bytes())
        self.assertEqual(
            saved_again["state"]["catalog"]["query_text"],
            "var == 'density'",
        )

    def test_workspace_fit_sizing_round_trip_restores_track_weights(self):
        state, controller = self.make_controller()
        owner = controller.actions["save_workspace_state"].__self__
        owner._apply_live_grid_sizing(
            {
                "mode": "fit",
                "column_sizes": "420,310,205",
                "row_sizes": "470,360,250",
                "column_weights": "3,1.5,0.5",
                "row_weights": "2.5,1,0.25",
            }
        )
        serialized = parse_workspace_document(
            workspace_json(state, "/campaign/example.aca")
        )

        state.gridSizingMode = "static"
        state.gridColumnWeights = [1.0, 1.0, 1.0]
        state.gridRowWeights = [1.0, 1.0, 1.0]
        owner.restore_workspace_state(serialized)

        self.assertEqual(state.gridSizingMode, "fit")
        self.assertEqual(state.gridColumnWeights, [3.0, 1.5, 0.5])
        self.assertEqual(state.gridRowWeights, [2.5, 1.0, 0.25])
        self.assertEqual(
            state.gridFitColumnTemplate,
            "minmax(180px, 3fr) minmax(180px, 1.5fr) "
            "minmax(180px, 0.5fr)",
        )
        self.assertEqual(
            state.gridFitRowTemplate,
            "minmax(212px, 2.5fr) minmax(212px, 1fr) "
            "minmax(212px, 0.25fr)",
        )

    def test_workspace_layout_round_trip_restores_tabs_and_split(self):
        state, controller = self.make_controller()
        owner = controller.actions["save_workspace_state"].__self__
        state.canvasDefaultTileWidth = 7
        controller.actions["add_workspace_tab"]("pane-1")
        controller.actions["rename_workspace_tab"](
            "pane-1", "tab-1", "2D Fields"
        )
        controller.actions["rename_workspace_tab"](
            "pane-1", "tab-2", "1D Trends"
        )
        controller.actions["split_workspace_pane"]("horizontal")
        controller.triggers["resize_workspace_split_trigger"]("split-1", 0.68)
        serialized = parse_workspace_document(
            workspace_json(state, "/campaign/example.aca")
        )

        controller.actions["close_workspace_pane"]("pane-2")
        state.canvasDefaultTileWidth = 2
        self.assertEqual(len(state.workspacePanes), 1)

        owner.restore_workspace_state(serialized)

        self.assertEqual(state.canvasDefaultTileWidth, 7)
        self.assertEqual(state.workspaceSplitDirection, "horizontal")
        self.assertAlmostEqual(state.workspaceLayout["root"]["ratio"], 0.68)
        self.assertEqual(len(state.workspacePanes), 2)
        self.assertEqual(
            [
                tab["title"]
                for pane in state.workspacePanes
                for tab in pane["tabs"]
            ],
            ["2D Fields", "1D Trends", "View 3"],
        )
        self.assertEqual(state.workspaceActivePaneId, "pane-2")
        self.assertEqual(state.workspaceActiveTabId, "tab-3")

    def test_workspace_round_trip_retains_cross_pane_tab_order(self):
        state, controller = self.make_controller()
        owner = controller.actions["save_workspace_state"].__self__
        controller.actions["add_workspace_tab"]("pane-1")
        controller.actions["split_workspace_pane"]("horizontal", "pane-1")
        controller.triggers["move_workspace_tab_trigger"](
            "pane-1", "tab-1", "pane-2", 0
        )
        serialized = parse_workspace_document(
            workspace_json(state, "/campaign/example.aca")
        )

        controller.actions["move_workspace_tab"]("pane-2", "tab-1")
        owner.restore_workspace_state(serialized)

        self.assertEqual(len(state.workspacePanes), 2)
        self.assertEqual(
            [tab["id"] for tab in state.workspacePanes[0]["tabs"]],
            ["tab-2"],
        )
        self.assertEqual(
            [tab["id"] for tab in state.workspacePanes[1]["tabs"]],
            ["tab-1", "tab-3"],
        )
        self.assertEqual(state.workspaceActivePaneId, "pane-2")
        self.assertEqual(state.workspaceActiveTabId, "tab-1")

    def test_workspace_round_trip_retains_a_cross_pane_visualization_move(self):
        state, controller = self.make_controller()
        owner = controller.actions["save_workspace_state"].__self__
        state.gridCells[0].update(
            {
                "variable_id": "density",
                "variable_name": "density",
                "status": "ready",
            }
        )
        controller.actions["split_workspace_pane"]("horizontal", "pane-1")
        controller.actions["set_grid_layout_mode"]("uniform")
        controller.actions["activate_workspace_tab"]("pane-1", "tab-1")
        controller.triggers["move_workspace_grid_cell_trigger"](
            "pane-1", "tab-1", 0, "pane-2", "tab-2", 4
        )
        serialized = parse_workspace_document(
            workspace_json(state, "/campaign/example.aca")
        )

        controller.triggers["move_workspace_grid_cell_trigger"](
            "pane-2", "tab-2", 4, "pane-1", "tab-1", 0
        )
        owner.restore_workspace_state(serialized)

        self.assertEqual(state.workspaceActivePaneId, "pane-2")
        self.assertEqual(state.workspaceActiveTabId, "tab-2")
        self.assertEqual(state.gridCells[4]["variable_id"], "density")
        self.assertEqual(
            state.workspacePanes[0]["tabs"][0]["grid"]["cells"][0][
                "variable_id"
            ],
            "",
        )

    def test_workspace_refresh_uses_source_plugin_rehydration(self):
        state, controller = self.make_controller()
        state.gridCells[0].update(
            {
                "variable_id": "density",
                "variable_name": "density",
                "visualization_name": "plugin:source-test",
                "selected_visualization": "plugin:source-test",
                "plugin_scope": "source",
                "plugin_options": {"mode": "summary"},
            }
        )
        owner = controller.actions["save_workspace_state"].__self__
        rebuilt = {
            **state.gridCells[0],
            "src": "data:image/png;base64,rebuilt",
        }

        with patch.object(
            owner,
            "build_source_plugin_grid_cell",
            return_value=rebuilt,
        ) as source_builder, patch.object(
            owner,
            "build_plugin_grid_cell",
        ) as variable_builder:
            owner.refresh_grid_cells()

        source_builder.assert_called_once()
        variable_builder.assert_not_called()
        self.assertEqual(state.gridCells[0]["src"], rebuilt["src"])

    def test_existing_grouping_is_stable_and_deduplicates_sources(self):
        self.assertEqual(
            self.db.grouped_variable_names(),
            [
                {
                    "name": "0D",
                    "variables": [
                        {
                            "id": "temperature",
                            "name": "temperature",
                            "label": "temperature",
                            "path": "temperature",
                            "source_dataset": "run-a/scalars.bp",
                        }
                    ],
                },
                {
                    "name": "2D",
                    "variables": [
                        {
                            "id": "density",
                            "name": "density",
                            "label": "density",
                            "path": "density",
                            "source_dataset": "run-a/output.bp",
                        }
                    ],
                },
            ],
        )

    def test_schema_variable_groups_override_shape_grouping(self):
        self.collection.insert_one(
            {
                "campaign_path": "/campaign/example.aca",
                "variable_id": "fields/P",
                "variable_name": "P",
                "variable_type": "variable",
                "source_dataset": "run-a/m3dc1.bp",
                "variable_path": "run-a/m3dc1.bp",
                "variable_group": "fields",
                "variable_group_order": 0,
                "role": "field",
                "metadata": {"Shape": "27894,20", "AvailableStepsCount": "51"},
            }
        )
        self.collection.insert_one(
            {
                "campaign_path": "/campaign/example.aca",
                "variable_id": "scalars/toroidal_current",
                "variable_name": "toroidal_current",
                "variable_type": "variable",
                "source_dataset": "run-a/m3dc1.bp",
                "variable_path": "run-a/m3dc1.bp",
                "variable_group": "scalars",
                "variable_group_order": 2,
                "role": "scalar_trace",
                "metadata": {"Shape": "10001", "AvailableStepsCount": "1"},
            }
        )

        groups = self.db.grouped_variable_names()

        self.assertEqual(
            [group["name"] for group in groups],
            ["fields", "scalars", "0D", "2D"],
        )
        self.assertEqual(groups[0]["variables"][0]["id"], "fields/P")
        self.assertEqual(
            groups[1]["variables"][0]["id"],
            "scalars/toroidal_current",
        )

    def test_schema_display_name_is_used_without_changing_variable_identity(self):
        variable_id = "data/meshes/traces/PNG_digitizer_Ch2_Trace/signal"
        self.collection.insert_one(
            {
                "campaign_path": "/campaign/example.aca",
                "variable_id": variable_id,
                "variable_name": variable_id,
                "display_name": "PNG_digitizer_Ch2_Trace",
                "variable_type": "variable",
                "source_dataset": "run-a/laser.bp5",
                "variable_path": f"run-a/laser.bp5/{variable_id}",
                "variable_group": "waveforms",
                "variable_group_order": 0,
                "role": "waveform",
                "metadata": {"Shape": "3,4", "AvailableStepsCount": "1"},
            }
        )

        variable_group = next(
            group
            for group in self.db.grouped_variable_names()
            if group["name"] == "waveforms"
        )
        variable = variable_group["variables"][0]
        self.assertEqual(variable["id"], variable_id)
        self.assertEqual(variable["name"], variable_id)
        self.assertEqual(variable["label"], "PNG_digitizer_Ch2_Trace")

        file_group = next(
            group
            for group in self.db.grouped_variables_by_source_dataset()
            if group["name"] == "run-a/laser.bp5"
        )
        self.assertEqual(
            file_group["variables"][0]["label"],
            "PNG_digitizer_Ch2_Trace",
        )

        navigation = SeuratApplication(self.db).get_navigation(
            {
                "view": "variables",
                "query": {"variable_id": variable_id},
                "only_visualized": False,
            }
        )
        self.assertEqual(
            navigation[0]["children"][0]["label"],
            "PNG_digitizer_Ch2_Trace",
        )
        self.assertEqual(
            navigation[0]["children"][0]["resource"]["variable_id"],
            variable_id,
        )

    def test_only_visualized_preserves_current_catalog_behavior(self):
        groups = self.db.grouped_variable_names(only_visualized=True)

        self.assertEqual([group["name"] for group in groups], ["2D"])
        self.assertEqual(
            [variable["id"] for variable in groups[0]["variables"]],
            ["density"],
        )

    def test_file_grouping_lists_variables_under_each_source_dataset(self):
        groups = self.db.grouped_variables_by_source_dataset()

        self.assertEqual(
            [group["name"] for group in groups],
            ["run-a/output", "run-a/scalars", "run-b/output"],
        )
        self.assertEqual(
            [[variable["id"] for variable in group["variables"]] for group in groups],
            [["density"], ["temperature"], ["density"]],
        )

    def test_file_grouping_honors_only_visualized(self):
        groups = self.db.grouped_variables_by_source_dataset(only_visualized=True)

        self.assertEqual([group["name"] for group in groups], ["run-a/output"])
        self.assertEqual([variable["id"] for variable in groups[0]["variables"]], ["density"])

    def test_file_grouping_uses_schema_declared_file_per_timestep_group(self):
        for source_dataset in ("xgc.3d.00010.bp", "xgc.3d.00012.bp"):
            self.collection.insert_one(
                {
                    "campaign_path": "/campaign/example.aca",
                    "variable_id": "potential",
                    "variable_name": "potential",
                    "variable_type": "variable",
                    "source_dataset": source_dataset,
                    "producer": "xgc",
                    "schema_file_group": "xgc_3d",
                    "schema_mode": "file_per_timestep",
                    "schema_pattern": "xgc.3d.*.bp",
                    "schema_num_timesteps": 2,
                    "metadata": {"Shape": "64,64"},
                }
            )

        groups = self.db.grouped_variables_by_source_dataset(
            extra_filter={"producer": "xgc"}
        )

        self.assertEqual([group["name"] for group in groups], ["xgc.3d.*"])
        self.assertEqual(groups[0]["file_count"], 2)
        self.assertEqual(
            [variable["id"] for variable in groups[0]["variables"]],
            ["potential"],
        )

        summary = self.db.variable_min_max_summary(
            "potential",
            extra_filter={"producer": "xgc"},
        )
        self.assertEqual(summary["num_sources"], 1)
        self.assertEqual(summary["sources"][0]["source_label"], "xgc.3d.*")

        navigation = SeuratApplication(self.db).get_navigation(
            {
                "view": "files",
                "query": {"producer": "xgc"},
                "only_visualized": False,
            }
        )
        self.assertEqual(navigation[0]["resource"]["file_count"], 2)
        self.assertEqual(
            _variable_groups_from_navigation(navigation)[0]["file_count"],
            2,
        )

    def test_schema_file_counts_use_timestep_metadata(self):
        schema_groups = {
            "xgc_3d": "xgc.3d.*.bp",
            "xgc_f3d": "xgc.f3d.*.bp",
            "xgc_fsourcediag": "xgc.fsourcediag.*.bp",
        }
        for schema_file_group, schema_pattern in schema_groups.items():
            self.collection.insert_one(
                {
                    "campaign_path": "/campaign/example.aca",
                    "variable_id": "potential",
                    "variable_name": "potential",
                    "variable_type": "variable",
                    "source_dataset": schema_file_group,
                    "producer": "schema-count-test",
                    "schema_file_group": schema_file_group,
                    "schema_mode": "file_per_timestep",
                    "schema_pattern": schema_pattern,
                    "schema_num_timesteps": 5,
                    "metadata": {"Shape": "64,64"},
                }
            )

        for step in (10, 12, 14, 16, 18):
            self.collection.insert_one(
                {
                    "campaign_path": "/campaign/example.aca",
                    "variable_id": "potential",
                    "variable_name": "potential",
                    "variable_type": "image",
                    "source_dataset": f"xgc.3d.{step:05d}.bp",
                    "producer": "schema-count-test",
                    "schema_file_group": "xgc_3d",
                    "schema_mode": "file_per_timestep",
                    "schema_pattern": "xgc.3d.*.bp",
                    "schema_num_timesteps": 5,
                    "visualization_name": "heatmap",
                }
            )

        groups = self.db.grouped_variables_by_source_dataset(
            extra_filter={"producer": "schema-count-test"}
        )

        self.assertEqual(
            {group["name"]: group.get("file_count") for group in groups},
            {
                "xgc.3d.*": 5,
                "xgc.f3d.*": 5,
                "xgc.fsourcediag.*": 5,
            },
        )

    def test_source_filter_preserves_the_matching_concrete_source(self):
        groups = self.db.grouped_variable_names(
            extra_filter={"source_dataset": "run-b/output.bp"}
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["variables"][0]["id"], "density")
        self.assertEqual(
            groups[0]["variables"][0]["source_dataset"],
            "run-b/output.bp",
        )

    def test_application_projection_round_trips_to_legacy_ui_payload(self):
        expected = self.db.grouped_variable_names()
        application = SeuratApplication(self.db)

        navigation = application.get_navigation(
            {
                "view": "variables",
                "query": {},
                "only_visualized": False,
                "parent_id": None,
            }
        )

        self.assertEqual(_variable_groups_from_navigation(navigation), expected)
        self.assertEqual(navigation[0]["id"], "variable-group:0D")
        self.assertEqual(navigation[0]["children"][0]["id"], "variable:temperature")
        self.assertEqual(navigation[1]["count"], 1)

    def test_application_forwards_catalog_filters(self):
        application = SeuratApplication(self.db)

        navigation = application.get_navigation(
            {
                "view": "variables",
                "query": {"source_dataset": "run-b/output.bp"},
                "only_visualized": False,
            }
        )
        groups = _variable_groups_from_navigation(navigation)

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["variables"][0]["id"], "density")
        self.assertEqual(
            groups[0]["variables"][0]["source_dataset"],
            "run-b/output.bp",
        )

    def test_literal_contains_query_executes_in_sqlite(self):
        application = SeuratApplication(self.db)

        navigation = application.get_navigation(
            {
                "view": "variables",
                "query": python_query_to_mongo(
                    "contains(source, 'run-a/scalars')"
                ),
                "only_visualized": False,
            }
        )

        self.assertEqual(
            [
                child["resource"]["variable_id"]
                for node in navigation
                for child in node["children"]
            ],
            ["temperature"],
        )

    def test_source_restriction_combines_maximum_and_dataset_substring(self):
        self.collection.insert_one(
            {
                "campaign_path": "/campaign/example.aca",
                "variable_id": "pressure",
                "variable_name": "pressure",
                "variable_type": "variable",
                "source_dataset": "run-128/output.bp",
                "variable_path": "run-128/output.bp/pressure",
                "min": 1.0,
                "max": 9.0,
            }
        )
        self.collection.insert_one(
            {
                "campaign_path": "/campaign/example.aca",
                "variable_id": "pressure",
                "variable_name": "pressure",
                "variable_type": "variable",
                "source_dataset": "run-64/output.bp",
                "variable_path": "run-64/output.bp/pressure",
                "min": 1.0,
                "max": 12.0,
            }
        )
        _query_filter, source_filters = python_query_to_filters(
            'source(id == "pressure" and max > 5.0 and '
            'contains(source_dataset, "128"))'
        )

        summary = self.db.source_restriction_summary(source_filters)

        self.assertEqual(summary["count"], 1)
        self.assertEqual(
            summary["filter"],
            {"source_dataset": {"$in": ["run-128/output.bp"]}},
        )

    def test_source_restriction_preserves_concrete_source_when_producer_is_shared(self):
        for source_dataset, max_value in (
            ("mhd-low/output.bp", 6.0),
            ("mhd-high/output.bp", 8.0),
        ):
            self.collection.insert_one(
                {
                    "campaign_path": "/campaign/example.aca",
                    "variable_id": "rho",
                    "variable_name": "rho",
                    "variable_type": "variable",
                    "source_dataset": source_dataset,
                    "producer": "mhd",
                    "variable_path": f"{source_dataset}/rho",
                    "min": 1.0,
                    "max": max_value,
                    "metadata": {"Shape": "64,64"},
                }
            )
            self.collection.insert_one(
                {
                    "campaign_path": "/campaign/example.aca",
                    "variable_id": "pressure",
                    "variable_name": "pressure",
                    "variable_type": "variable",
                    "source_dataset": source_dataset,
                    "producer": "mhd",
                    "variable_path": f"{source_dataset}/pressure",
                    "min": 1.0,
                    "max": 10.0,
                    "metadata": {"Shape": "64,64"},
                }
            )

        _query_filter, source_filters = python_query_to_filters(
            'source(id == "rho" and max < 7)'
        )

        restriction = self.db.source_restriction_summary(source_filters)
        pressure_summary = self.db.variable_min_max_summary(
            "pressure",
            extra_filter=restriction["filter"],
        )

        self.assertEqual(restriction["count"], 1)
        self.assertEqual(
            restriction["filter"],
            {"source_dataset": {"$in": ["mhd-low/output.bp"]}},
        )
        self.assertEqual(
            [source["source_dataset"] for source in pressure_summary["sources"]],
            ["mhd-low/output.bp"],
        )

    def test_source_restriction_uses_source_level_extrema_not_frame_extrema(self):
        for source_dataset, aggregate_max, frame_max in (
            ("mhd-low/output.bp", 3.5, 1.0),
            ("mhd-high/output.bp", 8.0, 2.0),
        ):
            self.collection.insert_one(
                {
                    "campaign_path": "/campaign/example.aca",
                    "variable_id": "pressure",
                    "variable_name": "pressure",
                    "variable_type": "variable",
                    "source_dataset": source_dataset,
                    "producer": "mhd",
                    "variable_path": f"{source_dataset}/pressure",
                    "min": 1.0,
                    "max": aggregate_max,
                    "metadata": {"Shape": "64,64"},
                }
            )
            self.collection.insert_one(
                {
                    "campaign_path": "/campaign/example.aca",
                    "variable_id": "pressure",
                    "variable_name": "pressure",
                    "variable_type": "scalarField",
                    "source_dataset": source_dataset,
                    "producer": "mhd",
                    "visualization_name": "heatmap",
                    "variable_path": f"visualizations/{source_dataset}/pressure.0",
                    "frame_index": 0,
                    "min": 0.0,
                    "max": frame_max,
                    "metadata": {"Shape": "64,64"},
                }
            )

        _query_filter, source_filters = python_query_to_filters(
            'source(id == "pressure" and max < 4)'
        )

        restriction = self.db.source_restriction_summary(source_filters)
        pressure_summary = self.db.variable_min_max_summary(
            "pressure",
            extra_filter=restriction["filter"],
        )

        self.assertEqual(restriction["count"], 1)
        self.assertEqual(
            restriction["filter"],
            {"source_dataset": {"$in": ["mhd-low/output.bp"]}},
        )
        self.assertEqual(
            [source["source_dataset"] for source in pressure_summary["sources"]],
            ["mhd-low/output.bp"],
        )
        self.assertEqual(pressure_summary["sources"][0]["max"], 3.5)

    def test_source_restriction_prefers_variable_extrema_for_exact_matches(self):
        self.collection.insert_one(
            {
                "campaign_path": "/campaign/example.aca",
                "variable_id": "pressure",
                "variable_name": "pressure",
                "variable_type": "variable",
                "source_dataset": "mhd-rounded/output.bp",
                "producer": "mhd",
                "variable_path": "mhd-rounded/output.bp/pressure",
                "min": 1.0,
                "max": 3.5,
                "metadata": {"Shape": "64,64"},
            }
        )
        self.collection.insert_one(
            {
                "campaign_path": "/campaign/example.aca",
                "variable_id": "pressure",
                "variable_name": "pressure",
                "variable_type": "scalarField",
                "source_dataset": "mhd-rounded/output.bp",
                "producer": "mhd",
                "visualization_name": "heatmap",
                "variable_path": "visualizations/mhd-rounded/output.bp/pressure.0",
                "frame_index": 0,
                "min": 0.0,
                "max": 3.5001,
                "metadata": {"Shape": "64,64"},
            }
        )

        _query_filter, source_filters = python_query_to_filters(
            'source(id == "pressure" and max == 3.5)'
        )

        restriction = self.db.source_restriction_summary(source_filters)

        self.assertEqual(restriction["count"], 1)
        self.assertEqual(
            restriction["filter"],
            {"source_dataset": {"$in": ["mhd-rounded/output.bp"]}},
        )

    def test_application_file_navigation_uses_file_nodes(self):
        application = SeuratApplication(self.db)

        navigation = application.get_navigation(
            {
                "view": "files",
                "query": {},
                "only_visualized": False,
            }
        )

        self.assertEqual(
            [node["label"] for node in navigation],
            ["run-a/output", "run-a/scalars", "run-b/output"],
        )
        self.assertTrue(all(node["kind"] == "file" for node in navigation))
        self.assertEqual(navigation[0]["children"][0]["resource"]["variable_id"], "density")
        self.assertEqual(
            navigation[0]["children"][0]["resource"]["source_dataset"],
            "run-a/output.bp",
        )

    def test_application_source_summary_and_lookup_share_source_identity(self):
        application = SeuratApplication(self.db)

        summary = application.get_source_summary(
            {"variable_id": "density", "query": {}}
        )
        source = application.find_source(
            {
                "variable_id": "density",
                "visualization_name": "heatmap",
                "query": {},
            }
        )

        run_a = next(
            item
            for item in summary["sources"]
            if item["source_dataset"] == "run-a/output.bp"
        )
        self.assertIsNotNone(source)
        self.assertEqual(source["id"], run_a["id"])
        self.assertTrue(source["id"].startswith("local-source:v1:"))

    def test_controller_refresh_preserves_variable_groups_state_contract(self):
        state = RecordingState(
            queryFilter={},
            querySourceRestrictionFilter={},
            showOnlyVisualizedVars=False,
            variableGroupCollapsed={},
            variableSearchText="TEMP",
        )
        server = SimpleNamespace(state=state, controller=RecordingController())
        refresh = attach_controllers(
            server=server,
            db=self.db,
            collection=self.collection,
            parse_campaign=lambda *_args, **_kwargs: None,
            campaign_path="/campaign/example.aca",
        )

        refresh()

        self.assertEqual(state.variableGroups, self.db.grouped_variable_names())
        self.assertEqual(
            [
                variable["id"]
                for group in state.filteredVariableGroups
                for variable in group["variables"]
            ],
            ["temperature"],
        )
        self.assertEqual(state.variableNames, ["temperature", "density"])
        self.assertEqual(
            state.variableLabelsById,
            {"temperature": "temperature", "density": "density"},
        )
        self.assertEqual(state.variableGroupCollapsed, {"0D": True, "2D": True})
        self.assertTrue(state.dbOk)
        self.assertEqual(state.dbStatus, "Connected")
        self.assertIn("run_query", server.controller.actions)
        self.assertEqual(len(server.controller.on_server_ready.callbacks), 1)

    def test_controller_refresh_supports_file_view(self):
        state = RecordingState(
            queryFilter={},
            querySourceRestrictionFilter={},
            showOnlyVisualizedVars=False,
            variablePaneView="files",
            variableGroupCollapsed={},
            variableGroupCollapsedByView={"variables": {}, "files": {}},
        )
        server = SimpleNamespace(state=state, controller=RecordingController())
        refresh = attach_controllers(
            server=server,
            db=self.db,
            collection=self.collection,
            parse_campaign=lambda *_args, **_kwargs: None,
            campaign_path="/campaign/example.aca",
        )

        refresh()

        self.assertEqual(
            [group["name"] for group in state.variableGroups],
            ["run-a/output", "run-a/scalars", "run-b/output"],
        )
        self.assertEqual(state.variableNames, ["density", "temperature"])
        self.assertEqual(
            state.variableGroupCollapsedByView["files"],
            {
                "run-a/output": True,
                "run-a/scalars": True,
                "run-b/output": True,
            },
        )

        server.controller.actions["toggle_variable_group"]("run-a/output")
        state.variablePaneView = "variables"
        refresh()
        server.controller.actions["toggle_variable_group"]("0D")

        state.variablePaneView = "files"
        refresh()
        self.assertFalse(state.variableGroupCollapsed["run-a/output"])

        state.variablePaneView = "variables"
        refresh()
        self.assertFalse(state.variableGroupCollapsed["0D"])

    def test_sources_dialog_opens_for_details_when_active_cell_is_empty(self):
        state = RecordingState()
        init_state(state, self.db)
        state.detailsSelectedVar = "density"
        state.detailsSelectedVarId = "density"
        state.selectedVar = "density"
        state.variableLabelsById = {"density": "density"}
        state.sourceRowsAll = [{"_key": "density-source"}]
        state.sourceRows = list(state.sourceRowsAll)
        state.selectedSourceKeys = ["density-source"]
        state.activeGridCell = 0

        server = SimpleNamespace(state=state, controller=RecordingController())
        attach_controllers(
            server=server,
            db=self.db,
            collection=self.collection,
            parse_campaign=lambda *_args, **_kwargs: None,
            campaign_path="/campaign/example.aca",
        )

        server.controller.actions["toggle_sources"]()

        self.assertTrue(state.showSourcesModal)
        self.assertEqual(state.sourceDialogTitle, "Sources: density")
        self.assertEqual(state.sourceDialogCellIndex, -1)
        self.assertEqual(state.sourceDialogTargetCellIndices, [])
        self.assertEqual(state.sourceDialogInitialSelectedSourceKeys, ["density-source"])

        server.controller.actions["apply_source_dialog"]()

        self.assertFalse(state.showSourcesModal)
        self.assertFalse(state.sourceDialogStatusIsError)
        self.assertEqual(state.detailsSelectedVarId, "density")

    def test_source_dialog_apply_refreshes_details_provenance(self):
        self.collection.insert_one(
            {
                "campaign_path": "/campaign/example.aca",
                "variable_id": "density",
                "variable_name": "density",
                "variable_type": "image",
                "source_dataset": "run-b/output.bp",
                "variable_path": "run-b/images/density.0000.png",
                "producer": "beta",
                "visualization_name": "heatmap",
                "visualization_kind": "scalar_field",
                "frame_index": 0,
                "metadata": {"Shape": "480,480"},
            }
        )

        state, controller = self.make_controller()
        owner = controller.actions["toggle_sources"].__self__
        owner.update_selected_var_panels("density")
        self.assertEqual(state.detailsProvenanceKind, "variable")
        self.assertNotIn("heatmap", state.detailsProvenanceChain)
        source_keys = {
            row["source_dataset"]: row["_key"] for row in state.sourceRowsAll
        }
        run_a_key = source_keys["run-a/output.bp"]
        run_b_key = source_keys["run-b/output.bp"]
        run_a_row = next(
            row for row in state.sourceRowsAll if row["_key"] == run_a_key
        )
        state.gridCells[0].update(
            owner.build_grid_cell_for_variable(
                "density",
                preferred_vis="heatmap",
                source_row=run_a_row,
            )
        )
        state.activeGridCell = 0
        state.selectedVar = "density"
        state.draggedVar = "density"

        controller.actions["set_active_grid_cell"](0)
        self.assertEqual(state.detailsProvenanceKind, "visualization")
        self.assertEqual(
            state.detailsProvenanceChain,
            "heatmap --> visualization --> density --> run-a/output.bp",
        )
        self.assertEqual(
            [node["shape"] for node in state.detailsProvenanceNodes],
            ["box", "box", "box", "cylinder"],
        )

        controller.actions["toggle_sources"]()
        self.assertIn("run-a/output", state.detailsProvenanceChain)

        controller.actions["source_dialog_select"](run_b_key)
        controller.actions["apply_source_dialog"]()

        self.assertFalse(state.showSourcesModal)
        self.assertEqual(state.gridCells[0]["source_dataset"], "run-b/output.bp")
        self.assertEqual(state.detailsProvenanceKind, "visualization")
        self.assertEqual(
            state.detailsProvenanceChain,
            "heatmap --> visualization: scalar_field --> density --> run-b/output.bp",
        )
        self.assertEqual(state.detailsProvenanceNodes[0]["kind"], "visualization")
        self.assertEqual(state.detailsProvenanceNodes[-1]["label"], "run-b/output.bp")

    def test_plugin_plot1d_source_dialog_applies_multiple_labeled_sources(self):
        for source_dataset, producer in (
            ("run-a/scalars.bp", "alpha"),
            ("run-b/scalars.bp", "beta"),
        ):
            self.collection.insert_one(
                {
                    "campaign_path": "/campaign/example.aca",
                    "variable_id": "internal_energy",
                    "variable_name": "internal_energy",
                    "variable_type": "variable",
                    "source_dataset": source_dataset,
                    "variable_path": f"{source_dataset}/internal_energy",
                    "producer": producer,
                    "metadata": {
                        "SingleValue": True,
                        "AvailableStepsCount": "3",
                    },
                }
            )

        def render_plugin(_campaign_path, _plugin_id, candidate, options=None):
            source_dataset = candidate["source_fields"]["source_dataset"]
            offset = 0.0 if source_dataset.startswith("run-a") else 10.0
            return {
                "media_type": "plot1d",
                "display_title": "internal_energy time series",
                "plot": {
                    "x_label": "step",
                    "y_label": "internal_energy",
                    "x_min": 0.0,
                    "x_max": 2.0,
                    "y_min": offset,
                    "y_max": offset + 2.0,
                    "data_x_min": 0.0,
                    "data_x_max": 2.0,
                    "data_y_min": offset,
                    "data_y_max": offset + 2.0,
                    "series": [
                        {
                            "x": [0.0, 1.0, 2.0],
                            "y": [offset, offset + 1.0, offset + 2.0],
                            "source_label": "internal_energy",
                            "source_key": "scalar",
                        }
                    ],
                },
                "status": "ok",
                "note": "plugin: profile_timeseries",
            }

        state, controller = self.make_controller()
        owner = controller.actions["toggle_sources"].__self__
        state.variableLabelsById["internal_energy"] = "internal_energy"

        with patch(
            "seurat.controllers.visualization.render_plugin_tile",
            side_effect=render_plugin,
        ):
            owner.update_selected_var_panels("internal_energy")
            source_keys = [row["_key"] for row in state.sourceRowsAll]
            first_row = state.sourceRowsAll[0]
            state.gridCells[0].update(
                {
                    "variable_id": "internal_energy",
                    "variable_name": "internal_energy",
                    "media_type": "plot1d",
                    "visualization_name": "plugin:profile_timeseries",
                    "selected_visualization": "plugin:profile_timeseries",
                    "source_dataset": first_row["source_dataset"],
                    "_source_key": source_keys[0],
                    "_source_keys": [source_keys[0]],
                    "plot": render_plugin(
                        "", "", {"source_fields": first_row}
                    )["plot"],
                    "status": "ok",
                }
            )
            state.activeGridCell = 0
            state.detailsSelectedVar = "internal_energy"
            state.detailsSelectedVarId = "internal_energy"
            state.selectedVar = "internal_energy"
            state.selectedSourceKeys = [source_keys[0]]
            state.contextMenuCellIndex = 0

            controller.actions["context_menu_cell_sources"]()
            self.assertEqual(state.sourceDialogMode, "add")

            controller.actions["source_dialog_select"](source_keys[1])
            controller.actions["apply_source_dialog"]()

        cell = state.gridCells[0]
        self.assertEqual(cell["selected_visualization"], "plugin:profile_timeseries")
        self.assertEqual(cell["_source_keys"], source_keys)
        self.assertEqual(
            [series["source_label"] for series in cell["plot"]["series"]],
            ["run-a/scalars.bp", "run-b/scalars.bp"],
        )

    def test_explicit_schema_source_without_visualization_does_not_fall_back(self):
        for schema_file_group, schema_pattern in (
            ("xgc_3d", "xgc.3d.*.bp"),
            ("xgc_f3d", "xgc.f3d.*.bp"),
        ):
            self.collection.insert_one(
                {
                    "campaign_path": "/campaign/example.aca",
                    "variable_id": "potential",
                    "variable_name": "potential",
                    "variable_type": "variable",
                    "source_dataset": schema_file_group,
                    "schema_file_group": schema_file_group,
                    "schema_mode": "file_per_timestep",
                    "schema_pattern": schema_pattern,
                    "metadata": {"Shape": "64,64", "Min": "-1", "Max": "1"},
                }
            )

        self.collection.insert_one(
            {
                "campaign_path": "/campaign/example.aca",
                "variable_id": "potential",
                "variable_name": "potential",
                "variable_type": "image",
                "source_dataset": "xgc.3d.00010.bp",
                "schema_file_group": "xgc_3d",
                "schema_mode": "file_per_timestep",
                "schema_pattern": "xgc.3d.*.bp",
                "visualization_name": "heatmap",
                "visualization_kind": "mesh-field",
                "variable_path": "visualizations/potential.png",
                "frame_index": 10,
            }
        )

        state = RecordingState()
        init_state(state, self.db)
        state.variableLabelsById = {"potential": "potential"}
        state.gridCells[0].update(
            {
                "variable_id": "potential",
                "variable_name": "potential",
                "visualization_name": "heatmap",
                "selected_visualization": "heatmap",
                "schema_file_group": "xgc_3d",
                "schema_mode": "file_per_timestep",
                "status": "ready",
            }
        )
        state.activeGridCell = 0

        server = SimpleNamespace(state=state, controller=RecordingController())
        attach_controllers(
            server=server,
            db=self.db,
            collection=self.collection,
            parse_campaign=lambda *_args, **_kwargs: None,
            campaign_path="/campaign/example.aca",
        )

        server.controller.actions["toggle_sources"]()
        f3d_key = next(
            row["_key"]
            for row in state.sourceRows
            if row["schema_file_group"] == "xgc_f3d"
        )
        server.controller.actions["source_dialog_select"](f3d_key)
        server.controller.actions["apply_source_dialog"]()

        cell = state.gridCells[0]
        self.assertEqual(cell["schema_file_group"], "xgc_f3d")
        self.assertEqual(cell["status"], "no-visualizations")
        self.assertEqual(cell["note"], "No visualization for source xgc.f3d.*")
        self.assertFalse(state.showSourcesModal)

    def test_grid_layout_controller_preserves_cell_geometry(self):
        state, controller = self.make_controller()

        controller.actions["set_grid_layout_size"](2, 4)

        self.assertEqual((state.gridRows, state.gridCols), (2, 4))
        self.assertEqual(len(state.gridCells), 8)
        self.assertEqual(
            [
                (cell["grid_row"], cell["grid_col"])
                for cell in state.gridCells
            ],
            [
                (1, 1),
                (1, 2),
                (1, 3),
                (1, 4),
                (2, 1),
                (2, 2),
                (2, 3),
                (2, 4),
            ],
        )
        self.assertTrue(
            all(
                cell["row_span"] == 1
                and cell["col_span"] == 1
                and not cell["grid_hidden"]
                for cell in state.gridCells
            )
        )

        controller.actions["add_grid_row"]()
        self.assertEqual((state.gridRows, state.gridCols), (3, 4))
        self.assertEqual(len(state.gridCells), 12)

        state.activeGridCell = 1
        controller.actions["delete_grid_column"]()
        self.assertEqual((state.gridRows, state.gridCols), (3, 3))
        self.assertEqual(len(state.gridCells), 9)
        self.assertEqual(state.activeGridCell, -1)

    def test_freeform_layout_converts_content_and_commits_stable_geometry(self):
        state, controller = self.make_controller()
        for index, variable_id in enumerate(("density", "temperature")):
            state.gridCells[index].update(
                {
                    "variable_id": variable_id,
                    "variable_name": variable_id,
                    "status": "ready",
                }
            )
        state.activeGridCell = 0
        state.selectedGridCellIndices = [0]
        state.selectedGridCellMap = {"0": True}

        controller.actions["set_grid_layout_mode"]("freeform")

        self.assertEqual(state.gridLayoutMode, "freeform")
        self.assertEqual(len(state.gridCells), 2)
        self.assertEqual(
            [cell["tile_id"] for cell in state.gridCells],
            ["tile-1", "tile-2"],
        )
        self.assertTrue(state.canvasSnapToGrid)
        self.assertTrue(state.canvasNudgeOthers)

        geometry = [
            {
                "tile_id": cell["tile_id"],
                "x": cell["canvas_x"],
                "y": cell["canvas_y"] + (12 if index == 0 else 0),
                "w": cell["canvas_w"],
                "h": cell["canvas_h"],
            }
            for index, cell in enumerate(state.gridCells)
        ]
        controller.triggers["commit_canvas_layout_trigger"](
            json.dumps(geometry),
            "tile-1",
            "pane-1",
            "tab-1",
        )

        self.assertEqual(state.gridCells[0]["canvas_y"], 12)
        self.assertEqual(state.activeGridCell, 0)
        self.assertEqual(state.canvasLayoutError, "")

        overlapping = [dict(item, x=0, y=0) for item in geometry]
        controller.triggers["commit_canvas_layout_trigger"](
            json.dumps(overlapping),
            "tile-1",
            "pane-1",
            "tab-1",
        )
        self.assertIn("overlap", state.canvasLayoutError)
        self.assertEqual(state.gridCells[0]["canvas_y"], 12)

    def test_freeform_canvas_column_change_preserves_visual_geometry(self):
        state, controller = self.make_controller()
        for index, variable_id in enumerate(("density", "temperature")):
            state.gridCells[index].update(
                {
                    "variable_id": variable_id,
                    "variable_name": variable_id,
                    "status": "ready",
                }
            )
        controller.actions["set_grid_layout_mode"]("freeform")
        before = [
            (cell["canvas_x"] / 24, cell["canvas_w"] / 24)
            for cell in state.gridCells
        ]

        controller.actions["set_canvas_columns"](48)

        after = [
            (cell["canvas_x"] / 48, cell["canvas_w"] / 48)
            for cell in state.gridCells
        ]
        self.assertEqual(state.canvasCols, 48)
        self.assertEqual(after, before)
        self.assertEqual(state.canvasLayoutError, "")

        controller.actions["set_canvas_columns"](30)
        self.assertEqual(state.canvasCols, 24)

    def test_freeform_variable_insert_commits_neighbor_layout_before_add(self):
        state, controller = self.make_controller()
        for index, variable_id in enumerate(("density", "temperature")):
            state.gridCells[index].update(
                {
                    "variable_id": variable_id,
                    "variable_name": variable_id,
                    "status": "ready",
                }
            )
        controller.actions["set_grid_layout_mode"]("freeform")
        existing_layout = [
            {
                "tile_id": cell["tile_id"],
                "x": cell["canvas_x"] + (8 if index == 1 else 0),
                "y": cell["canvas_y"],
                "w": cell["canvas_w"],
                "h": cell["canvas_h"],
            }
            for index, cell in enumerate(state.gridCells)
        ]

        controller.triggers["add_var_to_canvas_trigger"](
            "density",
            json.dumps({"x": 8, "y": 0, "w": 8, "h": 12}),
            "pane-1",
            "tab-1",
            json.dumps(existing_layout),
        )

        self.assertEqual(len(state.gridCells), 3)
        self.assertEqual(state.gridCells[1]["canvas_x"], 16)
        self.assertEqual(state.gridCells[2]["canvas_x"], 8)
        self.assertEqual(state.canvasLayoutError, "")

    def test_freeform_configured_drop_size_survives_field_classification(self):
        state, controller = self.make_controller()
        controller.actions["set_grid_layout_mode"]("freeform")
        state.canvasDefaultTileWidth = 4
        owner = controller.actions["save_workspace_state"].__self__
        field_cell = {
            "variable_id": "density",
            "variable_name": "density",
            "variable_type": "scalarField",
            "status": "ready",
        }

        with patch.object(
            owner,
            "build_grid_cell_for_variable",
            return_value=field_cell,
        ):
            controller.triggers["add_var_to_canvas_trigger"](
                "density",
                json.dumps({"x": 0, "y": 0, "w": 4, "h": 4}),
                "pane-1",
                "tab-1",
                "",
            )

        self.assertEqual(len(state.gridCells), 1)
        self.assertEqual(state.gridCells[0]["tile_type"], "field")
        self.assertEqual(state.gridCells[0]["canvas_w"], 4)
        self.assertEqual(state.gridCells[0]["canvas_h"], 4)

    def test_move_and_clear_cell_reset_timeline_driver_and_selection(self):
        state, controller = self.make_controller()
        state.gridCells[0].update(
            {
                "variable_id": "density",
                "variable_name": "density",
                "status": "ready",
                "frame_count": 3,
                "frame_indices": [0, 1, 2],
                "time_values": [0.0, 0.5, 1.0],
            }
        )

        controller.actions["toggle_timeline_driver_cell"](0)
        self.assertEqual(state.timelineDriverCell, 0)

        controller.actions["move_grid_cell"](0, 4)

        self.assertEqual(state.timelineDriverCell, -1)
        self.assertEqual(state.gridCells[0]["variable_id"], "")
        self.assertEqual(state.gridCells[4]["variable_id"], "density")
        self.assertEqual(state.activeGridCell, 4)
        self.assertEqual(state.selectedGridCellIndices, [4])
        self.assertEqual(state.selectedGridCellMap, {"4": True})

        controller.actions["toggle_timeline_driver_cell"](4)
        self.assertEqual(state.timelineDriverCell, 4)

        controller.actions["clear_grid_cell"](4)
        self.assertEqual(state.timelineDriverCell, -1)
        self.assertEqual(state.gridCells[4]["variable_id"], "")
        self.assertEqual(state.selectedGridCellIndices, [])
        self.assertEqual(state.selectedGridCellMap, {})

    def test_spanning_cell_hides_and_restores_covered_slot(self):
        state, controller = self.make_controller()
        state.gridLayoutMode = "spanning"
        state.gridCells[0].update(
            {
                "variable_id": "density",
                "variable_name": "density",
                "status": "ready",
            }
        )

        controller.actions["span_grid_cell_right"](0)

        self.assertEqual(state.gridCells[0]["col_span"], 2)
        self.assertTrue(state.gridCells[1]["grid_hidden"])
        self.assertEqual(state.activeGridCell, 0)

        controller.actions["shrink_grid_cell_width"](0)

        self.assertEqual(state.gridCells[0]["col_span"], 1)
        self.assertFalse(state.gridCells[1]["grid_hidden"])

    def test_shift_selection_includes_contiguous_selectable_cells(self):
        state, controller = self.make_controller()
        for index in range(5):
            state.gridCells[index].update(
                {
                    "variable_id": "density",
                    "variable_name": "density",
                    "status": "ready",
                }
            )
        state.activeGridCell = 0
        state.selectedGridCellIndices = [0]
        state.selectedGridCellMap = {"0": True}

        controller.actions["set_active_grid_cell"](4, multi=1)

        self.assertEqual(state.activeGridCell, 4)
        self.assertEqual(state.selectedGridCellIndices, [0, 1, 2, 3, 4])
        self.assertEqual(
            state.selectedGridCellMap,
            {str(index): True for index in range(5)},
        )

    def test_unimplemented_navigation_views_fail_explicitly(self):
        application = SeuratApplication(self.db)

        for view in ("objects", "campaign"):
            with self.subTest(view=view):
                with self.assertRaisesRegex(ValueError, f"Unsupported navigation view: {view}"):
                    application.get_navigation({"view": view})


if __name__ == "__main__":
    unittest.main()
