"""Campaign publication, retry safety, and workspace preservation."""

import hashlib
import sqlite3
from copy import deepcopy
from io import BytesIO
from uuid import uuid4

import adios2
import numpy as np
import pytest
from PIL import Image
from trame.app import get_server

from db import CampaignDb
from ingest_campaign import parse_campaign
from pulsar.backends import LocalCampaignBackend
from pulsar.campaign_media import read_archived_image
from pulsar.control import ViewerControl
from pulsar.controllers.composer import PulsarController
from pulsar.controllers.context import ControllerContext
from pulsar.publications import PublicationError, load_publications
from pulsar.results import ResultStore
from pulsar.state import init_state
from sqlite_store import SQLiteCampaignCollection

Manager = pytest.importorskip("hpc_campaign").Manager
pytestmark = pytest.mark.skipif(
    not hasattr(Manager, "publish_image"), reason="requires the atomic image writer"
)


@pytest.fixture
def viewer(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    campaign = tmp_path / "campaign.aca"
    with adios2.Stream("output.bp", "w") as stream:
        stream.write("density", np.array([[1.0, 2.0], [3.0, 4.0]]))
    manager = Manager(str(campaign))
    manager.open(create=True)
    manager.data("output.bp")
    manager.close()
    collection = SQLiteCampaignCollection(tmp_path / "cache.sqlite", str(campaign))
    db = CampaignDb(collection)
    server = get_server(f"publication-{uuid4()}", client_type="vue3")
    init_state(server.state, db)
    controller = PulsarController(
        ControllerContext(
            server=server,
            backend=LocalCampaignBackend(db),
            db=db,
            collection=collection,
            parse_campaign=parse_campaign,
            campaign_path=str(campaign),
            result_store=ResultStore(tmp_path / "results", str(campaign)),
        )
    ).register()
    controller.ingest_campaign_every_time()
    assert server.state.dbOk, server.state.dbStatus
    yield ViewerControl(controller, "test"), controller, campaign
    db.close()
    collection._con.close()


def register(viewer, root, title="Comparison"):
    image = root / f"{uuid4()}.png"
    Image.new("RGB", (16, 12), "blue").save(image)
    script = root / "analysis.py"
    script.write_text("# analysis recipe, deliberately not published\n")
    return viewer.register_result(
        title=title,
        image_path=image,
        script_path=script,
        parameters={"example": 1},
        provenance={"intent": "Compare two runs"},
    )


@pytest.mark.parametrize("invalid", [False, True])
def test_publication_reader_closes_connection(viewer, tmp_path, monkeypatch, invalid):
    control, _, campaign = viewer
    result = register(control, tmp_path)
    control.publish_result(result["result_id"])
    connect = sqlite3.connect
    connections = []

    def track_connection(*args, **kwargs):
        # Also exercise cleanup when the publication schema is missing.
        connection = connect(":memory:") if invalid else connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr("pulsar.publications.sqlite3.connect", track_connection)
    if invalid:
        with pytest.raises(PublicationError):
            load_publications(campaign)
    else:
        assert result["result_id"] in load_publications(campaign)
    assert len(connections) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[0].execute("select 1")


def test_publication_preserves_all_tabs_and_recovers_without_bundle(viewer, tmp_path):
    control, controller, campaign = viewer
    result = register(control, tmp_path)
    other = register(control, tmp_path, "Unfinished")
    first = control.create_tab("Comparison A")
    control.add_result(result["result_id"], first["tab_id"])
    second = control.create_tab("Comparison B")
    control.add_result(result["result_id"], second["tab_id"])
    control.add_result(other["result_id"], second["tab_id"])
    saved = control.workspace()
    original_manifest = deepcopy(result)
    before = control.tabs()
    receipt = control.publish_result(result["result_id"], title="Published comparison")
    assert receipt["publication_status"] == "published"
    assert receipt["refresh_status"] == "ok"
    assert not receipt["already_published"]
    after = control.tabs()
    assert [(t["tab_id"], t["title"]) for t in after] == [
        (t["tab_id"], t["title"]) for t in before
    ]
    assert control.context()["active_tab_id"] == second["tab_id"]
    tiles = [tile for tab in after for tile in tab["tiles"]]
    assert [t["publication_status"] for t in tiles] == [
        "published",
        "published",
        "unpublished",
    ]
    assert controller.result_store.get(result["result_id"]) == original_manifest
    payload, mime = read_archived_image(campaign, receipt["publication"]["image_uuid"])
    assert mime == "image/png"
    assert hashlib.sha256(payload).hexdigest() == result["artifacts"]["image"]["sha256"]
    with sqlite3.connect(campaign) as con:
        embedded = b"".join(
            row[0]
            for row in con.execute("select data from file where data is not null")
        )
    assert b"Compare two runs" not in embedded
    assert b"analysis recipe" not in embedded
    # Resolve the old unpublished workspace from ACA, with the bundle unavailable.
    bundle = controller.result_store.directory / result["result_id"]
    bundle.rename(tmp_path / "hidden-bundle")
    control.restore_workspace(saved)
    control.controller.activate_workspace_tab(first["pane_id"], first["tab_id"])
    assert control.tabs()[1]["tiles"][0]["publication_status"] == "published"
    assert (
        control.result(result["result_id"])["publication"]["image_uuid"]
        == receipt["publication"]["image_uuid"]
    )
    retry = control.publish_result(result["result_id"], title="Do not overwrite")
    assert retry["already_published"]
    assert retry["publication"] == receipt["publication"]
    assert len(load_publications(campaign)) == 1
    # Both catalogue discovery and stored workspace references use archive bytes.
    product_id = "published-image:" + result["result_id"]
    assert product_id in [item["variable_id"] for item in control.catalog()]
    assert controller.db.get_first_movie_tiles_for_variable(product_id)[0][
        "src"
    ].startswith("/pulsar-image/")


def test_source_associations_share_one_image_and_refresh_catalogue(viewer, tmp_path):
    control, controller, campaign = viewer
    result = register(control, tmp_path)
    association = {"name": "density", "source_dataset": "output.bp", "role": "primary"}
    receipt = control.publish_result(result["result_id"], associations=[association])
    assert receipt["refresh_status"] == "ok"
    tiles = controller.db.get_first_movie_tiles_for_variable("density")
    assert any(
        tile["src"] == f"/pulsar-image/{receipt['publication']['image_uuid']}"
        for tile in tiles
    )
    groups = controller.db.grouped_variable_names()
    assert "Published plots" in [group["name"] for group in groups]
    with sqlite3.connect(campaign) as con:
        assert (
            con.execute("select count(*) from visualization_variable").fetchone()[0]
            == 1
        )
        assert (
            con.execute(
                "select count(*) from dataset where fileformat='IMAGE'"
            ).fetchone()[0]
            == 1
        )


def test_commit_survives_refresh_failure_and_retry_does_not_rewrite(
    viewer, tmp_path, monkeypatch
):
    control, controller, campaign = viewer
    result = register(control, tmp_path)
    tab = control.create_tab("Keep this tab")
    control.add_result(result["result_id"], tab["tab_id"])
    original_ingest = controller.parse_campaign

    def fail(*_, **__):
        raise RuntimeError("injected index rebuild failure")

    monkeypatch.setattr(controller, "parse_campaign", fail)
    receipt = control.publish_result(result["result_id"])
    assert receipt["publication_status"] == "published"
    assert receipt["refresh_status"] == "failed"
    assert "injected index rebuild failure" in receipt["refresh_error"]
    assert control.tabs()[-1]["tiles"][0]["publication_status"] == "published"
    committed_bytes = campaign.read_bytes()
    monkeypatch.setattr(controller, "parse_campaign", original_ingest)
    retry = control.publish_result(result["result_id"])
    assert retry["already_published"]
    assert retry["refresh_status"] == "ok"
    assert campaign.read_bytes() == committed_bytes


def test_invalid_association_and_missing_writer_do_not_change_campaign(
    viewer, tmp_path, monkeypatch
):
    control, controller, campaign = viewer
    result = register(control, tmp_path)
    before = campaign.read_bytes()
    with pytest.raises(ValueError, match="Unknown source variable"):
        controller.publish_result(
            result["result_id"],
            associations=[{"name": "typo", "source_dataset": "output.bp"}],
        )
    monkeypatch.setattr(Manager, "publish_image", None)
    with pytest.raises(PublicationError, match="Manager.publish_image"):
        controller.publish_result(result["result_id"])
    assert campaign.read_bytes() == before


def test_writer_rolls_back_image_on_failed_association_and_retries(viewer):
    _control, _controller, campaign = viewer
    buffer = BytesIO()
    Image.new("RGB", (8, 6), "red").save(buffer, format="PNG")
    identifier = str(uuid4())
    manager = Manager(str(campaign))
    manager.open()
    before = [tuple(row) for row in manager.con.execute("select * from dataset")]
    with pytest.raises(LookupError, match="not found"):
        manager.publish_image(
            buffer.getvalue(),
            publication_id=identifier,
            title="Failed",
            variables=[{"name": "density", "source_dataset": "missing.bp"}],
        )
    assert [
        tuple(row) for row in manager.con.execute("select * from dataset")
    ] == before
    assert not manager.con.in_transaction
    receipt = manager.publish_image(
        buffer.getvalue(), publication_id=identifier, title="Good"
    )
    assert (
        manager.publish_image(b"", publication_id=identifier, title="Retry") == receipt
    )
    manager.close()


def register_movie(control, tmp_path, working_movie):
    image = tmp_path / "preview.png"
    Image.new("RGB", (16, 12), "red").save(image)
    return control.register_result(
        title="Movie",
        image_path=image,
        video_path=working_movie,
        provenance={"intent": "Keep scientific provenance for a later step"},
    )


def test_movie_publication_embeds_video_and_preview_and_recovers_without_bundle(
    viewer, tmp_path, working_movie
):
    from pulsar.campaign_media import read_embedded_video

    control, controller, campaign = viewer
    result = register_movie(control, tmp_path, working_movie)
    first = control.create_tab("Movie A")
    control.add_result(result["result_id"], first["tab_id"])
    second = control.create_tab("Movie B")
    control.add_result(result["result_id"], second["tab_id"])
    saved = control.workspace()
    original_manifest = controller.result_store.get(result["result_id"])
    response = control.publish_result(result["result_id"], title="Published movie")
    assert response["refresh_status"] == "ok"
    record = response["publication"]
    assert record["format"] == "hpc-campaign-published-video"
    assert record["video"]["fps"] == 2
    assert record["video"]["frame_count"] == 2
    assert (
        read_embedded_video(campaign, record["video_uuid"])
        == working_movie.read_bytes()
    )
    assert (
        read_archived_image(campaign, record["image_uuid"])[0]
        == (tmp_path / "preview.png").read_bytes()
    )
    tiles = [t for tab in control.tabs() for t in tab["tiles"]]
    assert len(tiles) == 2
    assert all(
        t["media_type"] == "video" and t["publication_status"] == "published"
        for t in tiles
    )
    assert controller.result_store.get(result["result_id"]) == original_manifest
    with sqlite3.connect(campaign) as con:
        assert (
            con.execute(
                "select count(*) from dataset where fileformat='VIDEO'"
            ).fetchone()[0]
            == 1
        )
        assert (
            con.execute(
                "select count(*) from dataset where fileformat='IMAGE'"
            ).fetchone()[0]
            == 1
        )
        assert (
            con.execute("select count(*) from visualization_sequence").fetchone()[0]
            == 0
        )
        assert b"Keep scientific provenance" not in b"".join(
            r[0] for r in con.execute("select data from file where data is not null")
        )
    (controller.result_store.directory / result["result_id"]).rename(
        tmp_path / "hidden-movie-bundle"
    )
    control.restore_workspace(saved)
    assert (
        controller.state.gridCells[0]["src"] == f"/pulsar-media/{record['video_uuid']}"
    )
    assert (
        controller.state.gridCells[0]["poster"]
        == f"/pulsar-image/{record['image_uuid']}"
    )
    before_retry = campaign.read_bytes()
    retry = control.publish_result(result["result_id"])
    assert retry["already_published"] and retry["publication"] == record
    assert campaign.read_bytes() == before_retry
    assert control.result(result["result_id"])["publication"] == record
    assert control.results() == [
        {
            "result_id": result["result_id"],
            "title": record["title"],
            "publication_status": "published",
            "publication": record,
            "video": record["video"],
        }
    ]
    product = "published-video:" + result["result_id"]
    assert product in [item["variable_id"] for item in control.catalog()]
    assert "Published movies" in [
        g["name"] for g in controller.db.grouped_variable_names()
    ]
    catalog_tile = controller.db.get_first_movie_tiles_for_variable(product)[0]
    assert catalog_tile["fps"] == 2
    assert catalog_tile["frame_count"] == 2
    assert catalog_tile["poster"] == f"/pulsar-image/{record['image_uuid']}"


def test_movie_source_association_uses_video_item_and_image_thumbnail(
    viewer, tmp_path, working_movie
):
    control, controller, campaign = viewer
    result = register_movie(control, tmp_path, working_movie)
    response = control.publish_result(
        result["result_id"],
        associations=[{"name": "density", "source_dataset": "output.bp"}],
    )
    assert response["refresh_status"] == "ok"
    record = response["publication"]
    assert [item["variable_id"] for item in control.catalog()] == ["density"]
    assert "Published movies" not in [
        group["name"] for group in controller.db.grouped_variable_names()
    ]
    tile = next(
        t
        for t in controller.db.get_first_movie_tiles_for_variable("density")
        if t["media_type"] == "video"
    )
    assert tile["src"] == f"/pulsar-media/{record['video_uuid']}"
    assert tile["fps"] == 2
    with sqlite3.connect(campaign) as con:
        row = con.execute(
            "select vi.item_type, vi.item_uuid, s.thumbnail_itemuuid from visualization_sequence s join visualization_item vi on vi.visid=s.visid"
        ).fetchone()
        assert row == ("VIDEO", record["video_uuid"], record["image_uuid"])
        assert (
            con.execute("select count(*) from visualization_variable").fetchone()[0]
            == 1
        )


def test_movie_commit_and_refresh_failure_are_separate_and_retryable(
    viewer, tmp_path, working_movie, monkeypatch
):
    control, controller, campaign = viewer
    result = register_movie(control, tmp_path, working_movie)
    tab = control.create_tab("Keep movie")
    control.add_result(result["result_id"], tab["tab_id"])
    original = controller.parse_campaign

    def fail(*_args, **_kwargs):
        raise RuntimeError("injected movie index failure")

    monkeypatch.setattr(controller, "parse_campaign", fail)
    response = control.publish_result(result["result_id"])
    assert (
        response["publication_status"] == "published"
        and response["refresh_status"] == "failed"
    )
    assert control.tabs()[-1]["tiles"][0]["media_type"] == "video"
    assert control.tabs()[-1]["tiles"][0]["publication_status"] == "published"
    committed = campaign.read_bytes()
    monkeypatch.setattr(controller, "parse_campaign", original)
    retry = control.publish_result(result["result_id"])
    assert retry["already_published"] and retry["refresh_status"] == "ok"
    assert campaign.read_bytes() == committed


def test_missing_movie_writer_leaves_campaign_unchanged(
    viewer, tmp_path, working_movie, monkeypatch
):
    control, controller, campaign = viewer
    result = register_movie(control, tmp_path, working_movie)
    before = campaign.read_bytes()
    monkeypatch.setattr(Manager, "publish_video", None)
    with pytest.raises(PublicationError, match="Manager.publish_video"):
        controller.publish_result(result["result_id"])
    assert campaign.read_bytes() == before


def test_physical_time_survives_movie_publication_and_bundle_removal(
    viewer, tmp_path, working_movie
):
    control, controller, campaign = viewer
    image = tmp_path / "timed-preview.png"
    Image.new("RGB", (16, 12), "red").save(image)
    result = control.register_result(
        title="Timed movie",
        image_path=image,
        video_path=working_movie,
        frame_times=[0.25, 1.0],
        time_unit="s",
    )
    tab = control.create_tab("Timed result")
    control.add_result(result["result_id"], tab["tab_id"])
    saved = control.workspace()
    response = control.publish_result(
        result["result_id"],
        associations=[
            {"name": "density", "source_dataset": "output.bp"},
        ],
    )
    assert response["refresh_status"] == "ok"
    timing = response["publication"]["video"]
    assert timing["time_mode"] == "physical_time"
    assert timing["time_values"] == [0.25, 1.0]
    tile = next(
        t
        for t in controller.db.get_first_movie_tiles_for_variable("density")
        if t["media_type"] == "video"
    )
    assert tile["time_values"] == timing["time_values"]
    assert tile["time_unit"] == "s"
    bundle = controller.result_store.directory / result["result_id"]
    bundle.rename(tmp_path / "hidden-timed-bundle")
    control.restore_workspace(saved)
    assert controller.state.gridCells[0]["time_values"] == [0.25, 1.0]
    assert control.result(result["result_id"])["video"] == timing
    assert control.tabs()[-1]["tiles"][0]["time_mode"] == "physical_time"
    before = campaign.read_bytes()
    assert control.publish_result(result["result_id"])["already_published"]
    assert campaign.read_bytes() == before
