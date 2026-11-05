"""Verify Python commands against a real campaign and mounted Pulsar browser."""

import base64
import csv
import io
import json
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import adios2
import numpy as np
import pytest
from PIL import Image
from playwright.sync_api import expect

from pulsar.client import PulsarClientError, connect
from pulsar.models.grid import empty_grid_cell

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(
        os.environ.get("PULSAR_RUN_BROWSER_TESTS") != "1",
        reason="set PULSAR_RUN_BROWSER_TESTS=1 to run browser tests",
    ),
]


@contextmanager
def _running_viewer(campaign, root, number, *, initial_state=None):
    session_path = root / f"session-{number}.json"
    env = {
        **os.environ,
        "PULSAR_SQLITE_DB": str(root / "cache.sqlite"),
        "PULSAR_CACHE_DIR": str(root / "cache"),
        "PULSAR_RESULTS_DIR": str(root / "results"),
        "PULSAR_INTERACTION_LOG_DIR": "",
        "TRAME_SERVER": "true",
    }
    initial_path = root / f"initial-{number}.json"
    initial_path.write_text(json.dumps(initial_state or {}))
    script = """
import json, sys
from pulsar.app import PulsarApp
app = PulsarApp(sys.argv[1], control_session_path=sys.argv[2])
def seed(**_):
    with open(sys.argv[3]) as source, app.server.state:
        app.server.state.update(json.load(source))
app.server.controller.on_server_ready.add(seed)
app.server.start(port=0, host='127.0.0.1', open_browser=False, timeout=0)
"""
    with (root / f"server-{number}.log").open("w+") as output:
        process = subprocess.Popen(
            [sys.executable, "-c", script, str(campaign), str(session_path), str(initial_path)],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 20
            session = {}
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    output.seek(0)
                    pytest.fail(output.read())
                try:
                    session = json.loads(session_path.read_text())
                    if session.get("endpoint"):
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(0.05)
            assert session.get("endpoint")
            endpoint = urlsplit(session["endpoint"])
            yield (
                connect(session_file=session_path),
                f"http://{endpoint.netloc}/?sessionURL=ws://{endpoint.netloc}/ws",
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_python_time_seek_reports_different_source_samples(page, tmp_path, monkeypatch):
    Manager = pytest.importorskip("hpc_campaign").Manager
    monkeypatch.chdir(tmp_path)
    campaign = tmp_path / "time.aca"
    manager = Manager(archive=str(campaign))
    manager.open(create=True)
    manager.close()
    frames = []
    for color in ("red", "green", "blue", "yellow"):
        output = io.BytesIO()
        Image.new("RGB", (16, 16), color).save(output, format="PNG")
        frames.append("data:image/png;base64," + base64.b64encode(output.getvalue()).decode())
    cells = []
    for source, times, indices in (
        ("run-a", [0, 0.5, 1], [0, 5, 10]),
        ("run-b", [0, 0.4, 0.9, 1], [0, 4, 9, 10]),
    ):
        cell = empty_grid_cell()
        cell.update(
            variable_id="current_z", variable_name="current_z",
            source_id=source, source_dataset=source + "/output.bp",
            media_type="image_sequence", status="ok", src=frames[0], fps=2,
            frame_count=len(times), frame_sources=frames[:len(times)],
            frame_indices=indices, time_values=times, time_mode="physical_time", time_unit="s",
        )
        cells.append(cell)
    cursor = empty_grid_cell()
    cursor.update(
        variable_id="pressure", variable_name="pressure", source_id="run-a",
        source_dataset="run-a/output.bp", media_type="plot1d", status="ok", time_unit="s",
        plot={
            "x_label": "time", "y_label": "pressure",
            "x_min": 0, "x_max": 0.75, "y_min": 0, "y_max": 3,
            "data_x_min": 0, "data_x_max": 1, "data_y_min": 0, "data_y_max": 3,
            "series": [{"x": [0, 0.5, 1], "y": [1, 2, 3], "color": "#1565c0"}],
        },
    )
    cells.append(cursor)
    initial = {"gridCells": cells, "timelineDriverCell": 0}
    with _running_viewer(campaign, tmp_path, 1, initial_state=initial) as (viewer, url):
        page.goto(url, wait_until="networkidle")
        images = page.locator('img[data-grid-image-sequence="1"]')
        expect(images).to_have_count(2)
        # Seeking an inactive tab activates it and uses that tab's driver.
        tab_id = viewer.tabs()[0]["tab_id"]
        viewer.create_tab("Other")
        receipt = viewer.set_time(0.6, tab_id=tab_id)
        assert receipt["requested_time"] == 0.6
        assert receipt["physical_time"] == 0.5
        assert [item["physical_time"] for item in receipt["plots"]] == [0.5, 0.4, 0.5]
        assert [item["status"] for item in receipt["plots"]] == ["sample", "sample", "cursor"]
        assert [item["frame_index"] for item in receipt["plots"][:2]] == [5, 4]
        assert [item["source_dataset"] for item in receipt["plots"][:2]] == [
            "run-a/output.bp", "run-b/output.bp",
        ]
        expect(page.get_by_text("Time = 0.5", exact=True)).to_be_visible()
        expect(images.nth(0)).to_have_attribute("data-current-frame", "1")
        expect(images.nth(1)).to_have_attribute("data-current-frame", "1")
        expect(images.nth(0)).to_have_attribute("src", frames[1])
        page.get_by_title("Forward step", exact=True).click()
        expect(page.get_by_text("Time = 1", exact=True)).to_be_visible()
        # A completed command must not override subsequent manual slider use.
        assert viewer.set_time(-100, tab_id=tab_id)["physical_time"] == 0
        page.get_by_title("Play all", exact=True).click()
        end = viewer.set_time(100, tab_id=tab_id)
        assert end["physical_time"] == 1
        assert end["plots"][2]["physical_time"] == 0.75
        expect(page.get_by_title("Play all", exact=True)).to_be_visible()
        expect(images.nth(0)).to_have_attribute("data-current-frame", "2")
        expect(images.nth(1)).to_have_attribute("data-current-frame", "3")


@pytest.mark.parametrize("axis_kind", [None, "shot"])
def test_python_time_seek_rejects_nonphysical_axes(page, tmp_path, monkeypatch, axis_kind):
    Manager = pytest.importorskip("hpc_campaign").Manager
    monkeypatch.chdir(tmp_path)
    campaign = tmp_path / "steps.aca"
    manager = Manager(archive=str(campaign))
    manager.open(create=True)
    manager.close()
    cell = empty_grid_cell()
    output = io.BytesIO()
    Image.new("RGB", (16, 16), "red").save(output, format="PNG")
    frame = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()
    cell.update(
        variable_id="frame", variable_name="frame", media_type="image_sequence",
        status="ok", src=frame, frame_sources=[frame],
        frame_count=1, time_values=[15], time_mode="timestep",
    )
    if axis_kind:
        cell["selection_axis"] = {"id": "shot", "key": "shot", "kind": axis_kind,
                                  "values": [15, 16], "index": 0}
    with _running_viewer(campaign, tmp_path, 1, initial_state={"gridCells": [cell]}) as (viewer, url):
        page.goto(url, wait_until="networkidle")
        with pytest.raises(PulsarClientError) as error:
            viewer.set_time(0.5, tab_id=viewer.tabs()[0]["tab_id"])
        assert error.value.code == "time_unavailable"


def test_metadata_table_sort_inspection_csv_and_restart(page, tmp_path, monkeypatch):
    hpc_campaign = pytest.importorskip("hpc_campaign")
    monkeypatch.chdir(tmp_path)
    with adios2.Stream(str(tmp_path / "output.bp"), "w") as stream:
        stream.write("temperature", np.linspace(1.0, 4.0, 16))
    campaign = tmp_path / "metadata.aca"
    manager = hpc_campaign.Manager(archive=str(campaign))
    try:
        manager.data("output.bp", name="output.bp")
    finally:
        manager.close()
    workspace = tmp_path / "metadata.workspace.json"
    sql = "select variable_id,maximum as value from q_variables union all select variable_id,minimum from q_variables"
    for number in (1, 2):
        with _running_viewer(campaign, tmp_path, number) as (viewer, url):
            page.goto(url, wait_until="networkidle")
            page.locator("#pulsar-variable-column").wait_for(state="visible")
            if number == 1:
                result = viewer.query(sql, request="Temperature metadata range")
                assert sorted(row[1] for row in result["rows"]) == [1.0, 4.0]
                tab = viewer.create_tab("Metadata results")
                viewer.show_query(result["query_id"], tab_id=tab["tab_id"])
            else:
                viewer.load_workspace(workspace)
                assert viewer.query_result(result["query_id"])["rows"] == result["rows"]
            table = page.locator(".pulsar-query-result")
            expect(table).to_be_visible()
            expect(table.locator("tbody tr")).to_have_count(2)
            table.get_by_role("columnheader", name="value").click()
            expect(table.locator("tbody tr").first.locator("td").last).to_have_text("1")
            with page.expect_download() as download:
                table.get_by_role("link", name="Export CSV").click()
            with Path(download.value.path()).open(newline="") as stream:
                exported = list(csv.reader(stream))
            assert exported[0] == ["variable_id", "value"]
            assert sorted(float(row[1]) for row in exported[1:]) == [1.0, 4.0]
            page.get_by_role("button", name="Inspect query", exact=True).click()
            dialog = page.get_by_role("dialog")
            expect(dialog.locator("textarea").first).to_have_value(
                re.compile("select variable_id")
            )
            dialog.get_by_role("button", name="Close", exact=True).click()
            expect(dialog).not_to_be_visible()
            viewer.save_workspace(workspace)
            page.screenshot(path=str(tmp_path / "metadata-table.png"))


def test_plot_sources_follow_each_tile_and_restore_legacy_keys(
    page, tmp_path, monkeypatch
):
    Manager = pytest.importorskip("hpc_campaign").Manager
    if not hasattr(Manager, "publish_image"):
        pytest.skip("requires the atomic image writer")
    monkeypatch.chdir(tmp_path)
    campaign = tmp_path / "source-bindings.aca"
    sources = ["rusanov_128/output.bp", "rusanov_64/output.bp"]
    manager = Manager(archive=str(campaign))
    try:
        for value, (source, color) in enumerate(zip(sources, ("red", "blue"))):
            path = tmp_path / source
            path.parent.mkdir()
            with adios2.Stream(str(path), "w") as stream:
                stream.write("current_z", np.full((2, 2), float(value)))
            manager.data(source, name=source)
            output = io.BytesIO()
            Image.new("RGB", (16, 16), color).save(output, format="PNG")
            manager.publish_image(
                output.getvalue(),
                publication_id=str(uuid4()),
                title=f"current_z {source}",
                variables=[{"name": "current_z", "source_dataset": source}],
            )
    finally:
        manager.close()
    workspace = tmp_path / "legacy-sources.workspace.json"
    for number in (1, 2):
        with _running_viewer(campaign, tmp_path, number) as (viewer, url):
            page.goto(url, wait_until="networkidle")
            page.locator("#pulsar-variable-column").wait_for(state="visible")
            if number == 1:
                tab = viewer.create_tab("Sources comparison")
                result = viewer.query(
                    "select source_dataset,source_ref from q_sources "
                    "where source_dataset like 'rusanov_%'"
                )
                source_refs = dict(result["rows"])
                for index, source in enumerate(sources):
                    viewer.add_visualization(
                        "current_z", tab_id=tab["tab_id"],
                        source_ref=source_refs[source],
                    )
                    tile = viewer.tabs()[-1]["tiles"][index]
                    assert tile["source_dataset"] == source
                    assert tile["source_id"].startswith("local-source:v1:")
            else:
                viewer.load_workspace(workspace)
            for index in (0, 1, 0):
                page.locator(
                    f'.pulsar-dropcell[data-cell-index="{index}"] .pulsar-tile-header'
                ).click()
                page.get_by_role("button", name="SOURCES(2)", exact=True).click()
                dialog = page.get_by_role("dialog")
                row = dialog.get_by_role("row").filter(has_text=sources[index])
                expect(row.get_by_role("radio")).to_be_checked()
                expect(
                    dialog.get_by_role("radio").locator("visible=true")
                ).to_have_count(2)
                assert (
                    viewer.context()["selected_sources"][0]["source_dataset"]
                    == sources[index]
                )
                dialog.get_by_role("button", name="Close", exact=True).click()
                expect(dialog).not_to_be_visible()
            if number == 1:
                viewer.save_workspace(workspace)
                document = json.loads(workspace.read_text())
                grids = [document["state"]["grid"]]
                grids.extend(
                    tab["grid"]
                    for pane in document["state"]["workspace"]["panes"]
                    for tab in pane["tabs"]
                )
                for grid in grids:
                    for cell in grid["cells"]:
                        if cell.get("variable_id") == "current_z":
                            cell["source_id"] = cell["_source_key"] = (
                                "legacy|" + cell["source_dataset"]
                            )
                workspace.write_text(json.dumps(document))


def test_unpublished_result_and_provenance_survive_server_restart(
    page, tmp_path, monkeypatch
):
    hpc_campaign = pytest.importorskip("hpc_campaign")
    monkeypatch.chdir(tmp_path)
    with adios2.Stream("output.bp", "w") as stream:
        stream.write("temperature", np.linspace(1.0, 4.0, 16))
    campaign = tmp_path / "example.aca"
    manager = hpc_campaign.Manager(archive=str(campaign))
    try:
        manager.data("output.bp", name="output.bp")
    finally:
        manager.close()
    image_path = tmp_path / "external.png"
    Image.new("RGB", (16, 12), "blue").save(image_path)
    script_path = tmp_path / "analysis.py"
    script_path.write_text("print('immutable original analysis')\n")
    workspace_path = tmp_path / "comparison.json"
    with _running_viewer(campaign, tmp_path, 1) as (viewer, url):
        variable_id = next(
            item["variable_id"]
            for item in viewer.catalog()
            if item["variable_id"].endswith("temperature")
        )
        page.goto(url, wait_until="networkidle")
        page.locator("#pulsar-variable-column").wait_for(state="visible")
        tab = viewer.create_tab("Working comparison")
        viewer.add_visualization(variable_id, tab_id=tab["tab_id"])
        result = viewer.register_result(
            image_path,
            title="External comparison",
            script_path=script_path,
            parameters={"time": 0.1},
            provenance={
                "intent": "Inspect resolution sensitivity",
                "inputs": [
                    {
                        "variable_id": variable_id,
                        "source_dataset": "output.bp",
                        "timestep": 0,
                    }
                ],
            },
        )
        viewer.add_result(result["result_id"], tab_id=tab["tab_id"])
        badge = page.get_by_role("button", name="Inspect unpublished result")
        expect(badge).to_be_visible()
        badge.click()
        expect(page.locator("textarea[readonly]:visible")).to_have_value(
            json.dumps(result, indent=2)
        )
        page.get_by_role("button", name="Close", exact=True).click()
        expect(page.locator("textarea[readonly]:visible")).to_have_count(0)
        expect(page.locator(".pulsar-plot1d svg")).to_be_visible()
        viewer.save_workspace(workspace_path)
    image_path.write_bytes(b"overwritten original")
    script_path.write_text("overwritten original")
    with _running_viewer(campaign, tmp_path, 2) as (viewer, url):
        assert viewer.result(result["result_id"]) == result
        viewer.load_workspace(workspace_path)
        page.goto(url, wait_until="networkidle")
        expect(
            page.get_by_role("button", name="Inspect unpublished result")
        ).to_be_visible()
        expect(page.locator(".pulsar-plot1d svg")).to_be_visible()
        result_image = page.locator('img[src^="/pulsar-results/"]')
        expect(result_image).to_be_visible()
        page.wait_for_function(
            "() => { const image=document.querySelector('img[src^=\"/pulsar-results/\"]'); return image && image.complete && image.naturalWidth === 16; }"
        )
        assert len(viewer.tabs()[-1]["tiles"]) == 2
        assert (
            viewer.result(result["result_id"])["provenance"]["intent"]
            == "Inspect resolution sensitivity"
        )


def test_python_client_updates_live_browser_and_reads_browser_selection(
    page, tmp_path, monkeypatch
):
    hpc_campaign = pytest.importorskip("hpc_campaign")
    bp_path = tmp_path / "output.bp"
    with adios2.Stream(str(bp_path), "w") as stream:
        stream.write("temperature", np.linspace(1.0, 4.0, 16))
    campaign = tmp_path / "example.aca"
    monkeypatch.chdir(tmp_path)
    manager = hpc_campaign.Manager(archive=str(campaign))
    try:
        manager.data("output.bp", name="output.bp")
    finally:
        manager.close()

    session_path = tmp_path / "session.json"
    env = {
        **os.environ,
        "PULSAR_SQLITE_DB": str(tmp_path / "cache.sqlite"),
        "TRAME_SERVER": "true",
    }
    script = (
        "import sys; from pulsar.app import PulsarApp; "
        "app = PulsarApp(sys.argv[1], control_session_path=sys.argv[2]); "
        "app.server.start(port=0, host='127.0.0.1', open_browser=False, timeout=0)"
    )
    with (tmp_path / "server.log").open("w+") as output:
        process = subprocess.Popen(
            [sys.executable, "-c", script, str(campaign), str(session_path)],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 20
            session = {}
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    output.seek(0)
                    pytest.fail(
                        f"Pulsar exited before becoming ready:\n{output.read()}"
                    )
                try:
                    session = json.loads(session_path.read_text())
                    if session.get("endpoint"):
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(0.05)
            assert session.get("endpoint"), (
                "Pulsar control endpoint did not become ready"
            )
            viewer = connect(session_file=session_path)
            assert viewer.context()["campaign"]["ready"]
            variable_id = next(
                item["variable_id"]
                for item in viewer.catalog()
                if item["variable_id"].endswith("temperature")
            )
            endpoint = urlsplit(session["endpoint"])
            page.goto(
                f"http://{endpoint.netloc}/?sessionURL=ws://{endpoint.netloc}/ws",
                wait_until="networkidle",
            )
            page.locator("#pulsar-variable-column").wait_for(state="visible")
            tab = viewer.create_tab("Python comparison")
            expect(
                page.locator(f'.pulsar-workspace-tab[data-tab-id="{tab["tab_id"]}"]')
            ).to_contain_text("Python comparison")
            result = viewer.add_visualization(variable_id, tab_id=tab["tab_id"])
            assert result["media_type"] == "plot1d"
            expect(page.locator(".pulsar-plot1d svg")).to_be_visible()
            assert viewer.context()["selected_tiles"][0]["variable_id"] == variable_id

            # A browser operation must be visible to a newly connected script.
            page.get_by_role("button", name="New tab", exact=True).click()
            expect(page.locator(".pulsar-workspace-tab")).to_have_count(3)
            reconnected = connect(session_file=session_path)
            assert reconnected.context()["active_tab_id"] != tab["tab_id"]
            saved = next(
                item for item in reconnected.tabs() if item["tab_id"] == tab["tab_id"]
            )
            assert saved["tiles"][0]["variable_id"] == variable_id
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_publish_from_browser_and_python_then_restore_without_working_files(
    page, tmp_path, monkeypatch
):
    Manager = pytest.importorskip("hpc_campaign").Manager
    if not hasattr(Manager, "publish_image"):
        pytest.skip("requires the atomic image writer")
    monkeypatch.chdir(tmp_path)
    with adios2.Stream("output.bp", "w") as stream:
        stream.write("density", np.ones((2, 2)))
    campaign = tmp_path / "published.aca"
    manager = Manager(str(campaign))
    manager.open(create=True)
    manager.data("output.bp")
    manager.close()
    image = tmp_path / "comparison.png"
    Image.new("RGB", (32, 24), "green").save(image)
    with _running_viewer(campaign, tmp_path, 1) as (viewer, url):
        first = viewer.register_result(image, title="Browser plot")
        tab = viewer.create_tab("Keep comparisons")
        viewer.add_result(first["result_id"], tab_id=tab["tab_id"])
        workspace = tmp_path / "before-publication.json"
        viewer.save_workspace(workspace)
        page.goto(url, wait_until="networkidle")
        expect(
            page.get_by_role("button", name="Inspect unpublished result")
        ).to_be_visible()
        page.get_by_role("button", name="Publish result", exact=True).click()
        dialog = page.get_by_role("dialog")
        expect(dialog).to_contain_text("Publish result to campaign")
        dialog.get_by_label("Plot title").fill("Browser-published plot")
        dialog.get_by_role(
            "combobox", name="Associate with source variables (optional)", exact=True
        ).fill("density")
        page.get_by_role("option", name="density — output.bp").click()
        dialog.get_by_role("button", name="Publish", exact=True).click()
        expect(dialog.get_by_role("status")).to_contain_text("Published in campaign.")
        dialog.get_by_role("button", name="Close", exact=True).click()
        expect(
            page.get_by_role("button", name="Inspect published result")
        ).to_be_visible()
        expect(page.locator(".pulsar-working-result-badge")).to_have_text("Published")
        first_receipt = viewer.result(first["result_id"])["publication"]
        assert first_receipt["associations"] == [
            {"name": "density", "source_dataset": "output.bp", "role": "primary"}
        ]
        second = viewer.register_result(image, title="Python plot")
        viewer.add_result(second["result_id"], tab_id=tab["tab_id"])
        receipt = viewer.publish_result(second["result_id"])
        assert receipt["refresh_status"] == "ok"
        expect(
            page.get_by_role("button", name="Inspect published result")
        ).to_have_count(2)
        assert page.locator('img[src^="/pulsar-image/"]').evaluate_all(
            "images => images.length === 2 && images.every(i => i.complete && i.naturalWidth === 32)"
        )
        page.screenshot(path=str(tmp_path / "published.png"), full_page=True)
    # A new viewer and empty result store must still restore the old working ID.
    (tmp_path / "results").rename(tmp_path / "working-results-hidden")
    with _running_viewer(campaign, tmp_path, 2) as (viewer, url):
        viewer.load_workspace(workspace)
        page.goto(url, wait_until="networkidle")
        expect(
            page.get_by_role("button", name="Inspect published result")
        ).to_be_visible()
        image_element = page.locator('img[src^="/pulsar-image/"]')
        expect(image_element).to_be_visible()
        assert image_element.evaluate("i => i.complete && i.naturalWidth === 32")
        retry = viewer.publish_result(first["result_id"])
        assert retry["already_published"]
        assert retry["publication"] == first_receipt
        assert retry["refresh_status"] == "ok"
        catalog_plot = next(
            item
            for item in viewer.catalog()
            if item["label"] == "Browser-published plot"
        )
        tab = viewer.create_tab("From campaign catalogue")
        tile = viewer.add_visualization(
            catalog_plot["variable_id"], tab_id=tab["tab_id"]
        )
        assert tile["status"] == "ok"
        assert len(viewer.results()) == 2


def test_working_movie_plays_and_restores_after_restart(page, tmp_path, working_movie):
    Manager = pytest.importorskip("hpc_campaign").Manager
    campaign = tmp_path / "movie.aca"
    manager = Manager(str(campaign))
    manager.open(create=True)
    manager.close()
    before = campaign.read_bytes()
    preview = tmp_path / "preview.png"
    Image.new("RGB", (16, 12), "red").save(preview)
    workspace = tmp_path / "movie-workspace.json"
    with _running_viewer(campaign, tmp_path, 1) as (viewer, url):
        result = viewer.register_result(
            preview, title="Working comparison movie", video_path=working_movie
        )
        tab = viewer.create_tab("Comparison movie")
        tile = viewer.add_result(result["result_id"], tab_id=tab["tab_id"])
        assert tile["media_type"] == "video"
        assert tile["publication_status"] == "unpublished"
        viewer.save_workspace(workspace)
        page.goto(url, wait_until="networkidle")
        video = page.locator("video[data-grid-video]")
        expect(video).to_be_visible()
        expect(video).to_have_js_property("readyState", 4)
        assert video.evaluate("v => v.duration") == pytest.approx(1, abs=0.05)
        expect(
            page.get_by_role("button", name="Inspect unpublished result")
        ).to_be_visible()
        expect(
            page.get_by_role("button", name="Publish result", exact=True)
        ).to_have_count(0)
        page.get_by_role("button", name="Play all", exact=True).click()
        page.wait_for_function(
            "document.querySelector('video[data-grid-video]').currentTime > 0.15"
        )
        expect(page.get_by_role("button", name="Pause all", exact=True)).to_be_visible()
        page.get_by_role("button", name="Pause all", exact=True).click()
        assert video.evaluate("v => v.paused")
        page.get_by_role("button", name=">|", exact=True).click()
        page.wait_for_function(
            "document.querySelector('video[data-grid-video]').currentTime >= 0.45"
        )
    working_movie.write_bytes(b"original removed from use")
    preview.write_bytes(b"original removed from use")
    with _running_viewer(campaign, tmp_path, 2) as (viewer, url):
        viewer.load_workspace(workspace)
        page.goto(url, wait_until="networkidle")
        video = page.locator("video[data-grid-video]")
        expect(video).to_be_visible()
        expect(video).to_have_js_property("readyState", 4)
        assert video.evaluate("v => v.videoWidth") == 16
        assert video.evaluate("v => v.duration") == pytest.approx(1, abs=0.05)
        assert viewer.result(result["result_id"])["video"]["frame_count"] == 2
        page.screenshot(path=str(tmp_path / "movie-restored.png"), full_page=True)
    assert campaign.read_bytes() == before


def test_python_movie_publication_survives_restart_without_working_bundle(
    page, tmp_path, working_movie
):
    Manager = pytest.importorskip("hpc_campaign").Manager
    if not hasattr(Manager, "publish_video"):
        pytest.skip("requires atomic movie publication")
    campaign = tmp_path / "published-movie.aca"
    manager = Manager(str(campaign))
    manager.open(create=True)
    manager.close()
    preview = tmp_path / "preview.png"
    Image.new("RGB", (16, 12), "red").save(preview)
    workspace = tmp_path / "unpublished-movie-workspace.json"
    with _running_viewer(campaign, tmp_path, 1) as (viewer, url):
        result = viewer.register_result(
            preview, title="Published movie", video_path=working_movie
        )
        tab = viewer.create_tab("Published comparison")
        viewer.add_result(result["result_id"], tab_id=tab["tab_id"])
        viewer.save_workspace(workspace)
        receipt = viewer.publish_result(result["result_id"])
        assert receipt["publication_status"] == "published"
        assert receipt["refresh_status"] == "ok"
        assert receipt["publication"]["format"] == "hpc-campaign-published-video"
        page.goto(url, wait_until="networkidle")
        video = page.locator("video[data-grid-video]")
        expect(video).to_be_visible()
        expect(video).to_have_js_property("readyState", 4)
        assert video.get_attribute("src").startswith("/pulsar-media/")
        assert video.get_attribute("poster").startswith("/pulsar-image/")
        expect(
            page.get_by_role("button", name="Inspect published result")
        ).to_be_visible()
        page.get_by_role("button", name="Play all", exact=True).click()
        page.wait_for_function(
            "document.querySelector('video[data-grid-video]').currentTime > 0.15"
        )
    bundle = next((tmp_path / "results").glob("*/" + result["result_id"]))
    bundle.rename(tmp_path / "hidden-published-movie-bundle")
    working_movie.write_bytes(b"original overwritten")
    preview.write_bytes(b"original overwritten")
    committed = campaign.read_bytes()
    with _running_viewer(campaign, tmp_path, 2) as (viewer, url):
        viewer.load_workspace(workspace)
        page.goto(url, wait_until="networkidle")
        video = page.locator("video[data-grid-video]")
        expect(video).to_be_visible()
        expect(video).to_have_js_property("readyState", 4)
        assert video.evaluate("v => v.duration") == pytest.approx(1, abs=0.05)
        expect(
            page.get_by_role("button", name="Inspect published result")
        ).to_be_visible()
        retry = viewer.publish_result(result["result_id"])
        assert retry["already_published"]
        assert retry["publication"] == receipt["publication"]
        assert retry["refresh_status"] == "ok"
        product_id = "published-video:" + result["result_id"]
        assert product_id in [item["variable_id"] for item in viewer.catalog()]
        catalog_tab = viewer.create_tab("Campaign movie")
        tile = viewer.add_visualization(product_id, tab_id=catalog_tab["tab_id"])
        assert tile["media_type"] == "video" and tile["status"] == "ok"
        expect(page.locator("video[data-grid-video]")).to_have_js_property(
            "readyState", 4
        )
        page.screenshot(
            path=str(tmp_path / "published-movie-restored.png"), full_page=True
        )
    assert campaign.read_bytes() == committed


def test_physical_movie_times_survive_publication_and_restart(page, tmp_path):
    from hpc_campaign import Manager

    from media_utils import frames_to_mp4_bytes

    campaign = tmp_path / "timed-movie.aca"
    manager = Manager(str(campaign))
    manager.open(create=True)
    manager.close()
    frames = []
    for color in ("red", "red", "green", "blue"):
        buffer = io.BytesIO()
        Image.new("RGB", (16, 12), color).save(buffer, format="PNG")
        frames.append(buffer.getvalue())
    preview = tmp_path / "preview.png"
    preview.write_bytes(frames[0])
    movie = tmp_path / "timed.mp4"
    movie.write_bytes(frames_to_mp4_bytes(frames, fps=1))
    times = [2.0, 2.0, 2.75, 5.0]
    workspace = tmp_path / "timed-workspace.json"
    with _running_viewer(campaign, tmp_path, 1) as (viewer, url):
        result = viewer.register_result(
            preview,
            title="Physical-time movie",
            video_path=movie,
            frame_times=times,
            time_unit="s",
        )
        tab = viewer.create_tab("Physical time")
        viewer.add_result(result["result_id"], tab_id=tab["tab_id"])
        viewer.save_workspace(workspace)
        page.goto(url, wait_until="networkidle")
        video = page.locator("video[data-grid-video]")
        expect(video).to_have_attribute("data-time-mode", "physical_time")
        expect(video).to_have_js_property("readyState", 4)
        seek = viewer.set_time(2.75, tab_id=tab["tab_id"])
        assert seek["physical_time"] == 2.75
        assert seek["plots"][0]["physical_time"] == 2.75
        assert seek["plots"][0]["sample_index"] == 2
        expect(video).to_have_js_property("currentTime", 2)
        page.get_by_title("Play all", exact=True).click()
        expect(video).to_have_js_property("paused", False)
        expect(page.get_by_text("Time = 2.75", exact=True)).to_be_visible()
        expect(page.get_by_text("Time = 5", exact=True)).to_be_visible()
        expect(video).to_have_js_property("paused", True)
        page.get_by_role("button", name=">|", exact=True).click()
        expect(page.get_by_text("Time = 5", exact=True)).to_be_visible()
        page.wait_for_function(
            "document.querySelector('video[data-grid-video]').currentTime >= 2.99"
        )
        receipt = viewer.publish_result(result["result_id"])
        assert receipt["refresh_status"] == "ok"
        assert receipt["publication"]["video"]["time_values"] == times
    bundle = next((tmp_path / "results").glob("*/" + result["result_id"]))
    bundle.rename(tmp_path / "hidden-timed-bundle")
    with _running_viewer(campaign, tmp_path, 2) as (viewer, url):
        viewer.load_workspace(workspace)
        page.goto(url, wait_until="networkidle")
        video = page.locator("video[data-grid-video]")
        expect(video).to_have_attribute("data-time-mode", "physical_time")
        assert video.get_attribute("data-time-values") == "2,2,2.75,5"
        expect(video).to_have_js_property("readyState", 4)
        page.get_by_role("button", name="|<", exact=True).click()
        page.get_by_role("button", name=">>", exact=True).click()
        expect(page.get_by_text("Time = 2.75", exact=True)).to_be_visible()
        page.wait_for_function(
            "Math.abs(document.querySelector('video[data-grid-video]').currentTime - 2) < 0.02"
        )
        assert viewer.result(result["result_id"])["video"]["time_values"] == times
