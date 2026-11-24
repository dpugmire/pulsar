import json
import sqlite3
import asyncio
import io
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from db import CampaignDb
from PIL import Image
from pulsar.campaign_media import read_campaign_preview, register_campaign_media_route
from pulsar.campaign_overview import campaign_key

from pulsar.campaign_overview import (
    archive_inventory,
    archive_file_history,
    build_campaign_overview,
    campaign_overview_card,
    campaign_summary,
)
from pulsar.controllers.campaigns import CampaignOverviewControllerMixin
from sqlite_store import SQLiteCampaignCollection


def test_directory_startup_passes_all_archives_to_one_viewer(tmp_path):
    from pulsar.app import main

    for name in ["second.aca", "first.aca", "ignored.txt"]:
        (tmp_path / name).touch()
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "excluded.aca").touch()
    with patch("pulsar.app.PulsarApp") as app:
        main(["--campaign-directory", str(tmp_path)])
    assert app.call_args.kwargs["campaign_paths"] == [str(tmp_path / "first.aca"), str(tmp_path / "second.aca")]
    app.return_value.server.start.assert_called_once()


def make_archive(path):
    with sqlite3.connect(path) as con:
        con.executescript(
            "create table dataset(name text, uuid text, fileformat text, deltime int);"
            "create table campaign_identity(singleton int, uuid text);"
            "insert into campaign_identity values(1, 'shared-campaign-identity');"
        )
        con.executemany("insert into dataset values (?, ?, ?, 0)", [
            ("output.bp", "data-id", "ADIOS"),
            ("analysis.json", "config-id", "TEXT"),
            ("unrelated.json", "other-id", "TEXT"),
            ("plotted.bp", "plot-data-id", "ADIOS"),
        ])


def documents(path):
    return [
        {"campaign_path": str(path), "variable_type": "variable", "variable_id": "pressure", "source_dataset": "output.bp"},
        *[
            {"campaign_path": str(path), "variable_type": "image", "variable_id": variable,
             "source_dataset": "output.bp", "variable_path": f"plots/{step}",
             "visualization_name": "heatmap", "visualization_sequence_name": "pressure analysis",
             "visualization_sequence_metadata": {"configuration": "analysis.json", "plotted_data": "plot-data-id"},
             "visualization_item_metadata": {"step": step}}
            for variable in ["pressure", "current_z"] for step in range(2)
        ],
    ]


def test_copies_keep_separate_contents_and_packages_use_recorded_links(tmp_path):
    paths = [tmp_path / "original.aca", tmp_path / "copy.aca"]
    collection = SQLiteCampaignCollection(tmp_path / "sidecar.sqlite")
    try:
        for path in paths:
            make_archive(path)
            for doc in documents(path):
                collection.insert_one(doc)
        with patch("adios2.FileReader", side_effect=AssertionError("metadata scan read a payload")):
            overview = build_campaign_overview(collection, [str(path) for path in paths])
        assert [item["name"] for item in overview] == ["original", "copy"]
        assert overview[0]["uuid"] == overview[1]["uuid"]
        assert overview[0]["id"] != overview[1]["id"]
        for campaign in overview:
            assert len(campaign["results"]) == 1  # Frames and variable associations form one result.
            package = campaign["results"][0]
            assert {item["name"] for item in package["artifacts"]} == {"analysis.json", "plotted.bp"}
            assert {item["variable"] for item in package["inputs"]} == {"pressure", "current_z"}
            assert next(item for item in campaign["datasets"] if item["name"] == "output.bp")["explorable"]
            assert len(campaign["supporting_files"]) == 2
        assert overview[0]["results"][0]["id"] != overview[1]["results"][0]["id"]
    finally:
        collection.close()


def test_inventory_does_not_create_missing_archives(tmp_path):
    path = tmp_path / "missing.aca"
    assert archive_inventory(str(path))["error"]
    assert not path.exists()


def test_file_added_timestamp_uses_current_identity_insert_history(tmp_path):
    path = tmp_path / "campaign.aca"
    make_archive(path)
    added_ns = 1_704_164_645_000_000_000  # 2024-01-02 03:04:05 UTC
    with sqlite3.connect(path) as con:
        con.executescript(
            "alter table dataset add column modtime int default 946684800000000000;"
            "create table entity_identity(kind text, local_id int, uuid text, active int);"
            "create table change_log(kind text, entity_uuid text, action text, timestamp_ns int);"
        )
        con.executemany("insert into entity_identity values ('dataset',?,?,?)", [
            (1, "active-identity", 1), (1, "retired-identity", 0), (4, "baseline-identity", 1),
        ])
        con.executemany("insert into change_log values ('dataset',?,?,?)", [
            ("active-identity", "insert", added_ns),
            ("active-identity", "insert", added_ns + 1000000000),
            ("active-identity", "update", added_ns - 1000000000),
            ("retired-identity", "insert", added_ns - 86400000000000),
            ("baseline-identity", "baseline", added_ns),
        ])
    inventory = archive_inventory(str(path))
    assert not inventory["error"]
    files = {item["name"]: item for item in inventory["datasets"]}
    assert files["output.bp"]["added_at"] == "2024-01-02T03:04:05+00:00"
    assert files["plotted.bp"]["added_at"] == ""
    card = campaign_overview_card(campaign_summary(str(path), [], inventory))
    displayed = {item["name"]: item for group in card["directories"] for item in group["datasets"]}
    assert displayed["output.bp"]["added_at"] == files["output.bp"]["added_at"]


def test_legacy_archive_has_unknown_added_timestamp(tmp_path):
    path = tmp_path / "legacy.aca"
    make_archive(path)
    with sqlite3.connect(path) as con:
        con.execute("alter table dataset add column modtime int default 1704164645000000000")
    inventory = archive_inventory(str(path))
    assert not inventory["error"]
    assert all(item["added_at"] == "" for item in inventory["datasets"])


def test_recorded_modified_time_uses_active_replicas_and_keeps_sizes_separate(tmp_path):
    path = tmp_path / "campaign.aca"
    make_archive(path)
    old = 1_704_164_645_000_000_000
    with sqlite3.connect(path) as con:
        con.executescript(
            "alter table dataset add column modtime int default 946684800000000000;"
            "create table host(hostname text);"
            "insert into host values('perlmutter');"
            "create table directory(name text);"
            "insert into directory values('/scratch/run');"
            "create table replica(datasetid int, hostid int, dirid int, name text, modtime int, size int, deltime int);"
        )
        con.executemany("insert into replica values(1,1,1,?,?,?,?)", [
            ("output.bp", old, 4096, 0),
            ("copy.bp", old + 1000000000, 8192, 0),
            ("deleted.bp", old + 2000000000, 16384, 1),
        ])
    inventory = archive_inventory(str(path))
    dataset = next(item for item in inventory["datasets"] if item["name"] == "output.bp")
    assert dataset["modified_at"] == "2024-01-02T03:04:06+00:00"
    assert dataset["added_at"] == ""
    assert [item["size_bytes"] for item in dataset["locations"]] == [4096, 8192]
    assert dataset["locations"][0]["host"] == "perlmutter"
    assert dataset["locations"][0]["path"] == "/scratch/run/output.bp"
    other = next(item for item in inventory["datasets"] if item["name"] == "plotted.bp")
    assert other["modified_at"] == "2000-01-01T00:00:00+00:00"


def test_coverage_describes_bp_metadata_without_counting_variables_or_previews(tmp_path):
    inventory = {"uuid": "", "error": "", "datasets": [
        {"name": f"run/{name}.bp", "uuid": name, "fileformat": "ADIOS"}
        for name in ["output", "checkpoint"]
    ]}
    docs = [
        {"variable_type": "variable", "variable_id": variable, "source_dataset": dataset["name"],
         "metadata": {"Type": "double", "Shape": "64, 64", "AvailableStepsCount": "3"},
         "time_values": [0, 2, 4], "time_unit": "ms"}
        for dataset in inventory["datasets"] for variable in ["pressure", "density"]
    ]
    docs.extend({"variable_type": "image", "variable_id": "pressure", "source_dataset": "run/output.bp",
                 "visualization_name": "sample", "frame_index": step, "physical_time": step}
                for step in range(10))
    campaign = campaign_summary(str(tmp_path / "campaign.aca"), docs, inventory)
    card = campaign_overview_card(campaign)
    assert card["directories"][0]["coverage"] == "3 steps · t = 0–4 ms per BP file"
    assert campaign["datasets"][0]["coverage"] == "3 steps · t = 0–4 ms"
    assert len(campaign["datasets"][0]["variable_details"]) == 2
    assert campaign["datasets"][0]["variable_details"][0]["shape"] == "64, 64"

    # A second file with a different extent must not become a shared or summed range.
    docs[0]["time_values"] = docs[1]["time_values"] = [0, 1]
    varied = campaign_overview_card(campaign_summary(str(tmp_path / "campaign.aca"), docs, inventory))
    assert varied["directories"][0]["coverage"] == "Coverage varies by file"
    assert {file["coverage"] for file in varied["directories"][0]["datasets"]} == {
        "2 steps · t = 0–1 ms", "3 steps · t = 0–4 ms",
    }


def test_missing_or_invalid_coverage_is_not_inferred_from_plots_or_collection_counts(tmp_path):
    inventory = {"uuid": "", "error": "", "datasets": [
        {"name": "run/step0.bp", "uuid": "a", "fileformat": "ADIOS"},
        {"name": "run/step1.bp", "uuid": "b", "fileformat": "ADIOS"},
    ]}
    docs = [
        {"variable_type": "variable", "variable_id": "p", "source_dataset": "run/step0.bp",
         "schema_mode": "file_per_timestep", "schema_num_timesteps": 100,
         "metadata": {"AvailableStepsCount": "1"}, "physical_time": 0},
        {"variable_type": "variable", "variable_id": "p", "source_dataset": "run/step1.bp",
         "metadata": {"AvailableStepsCount": "bad"}, "time_values": [0, float("nan")]},
    ]
    campaign = campaign_summary(str(tmp_path / "campaign.aca"), docs, inventory)
    assert campaign["datasets"][0]["coverage"] == "1 step · t = 0"
    assert campaign["datasets"][1]["coverage"] == ""
    assert campaign_overview_card(campaign)["directories"][0]["coverage"] == "Partial coverage metadata"
    campaign = campaign_summary(str(tmp_path / "campaign.aca"), [
        {"variable_type": "image", "variable_id": "p", "source_dataset": "run/step1.bp",
         "visualization_name": "sample", "physical_time": 20},
    ], inventory)
    assert all(not dataset["coverage"] for dataset in campaign["datasets"])


def test_run_parameters_require_explicit_recorded_values_and_remain_scoped(tmp_path):
    inventory = {"uuid": "", "error": "", "datasets": [
        {"name": f"hll_128/{name}.bp", "uuid": name, "fileformat": "ADIOS"}
        for name in ["a", "b"]
    ]}
    docs = [{"variable_type": "variable", "variable_id": "p", "source_dataset": "hll_128/a.bp",
             "metadata": {"run_parameters": {"resolution": 128, "solver": "XGC"}}}]
    campaign = campaign_summary(str(tmp_path / "campaign.aca"), docs, inventory)
    assert campaign["datasets"][0]["parameters"] == [
        {"name": "resolution", "value": "128"}, {"name": "solver", "value": "XGC"},
    ]
    assert campaign["datasets"][1]["parameters"] == []
    assert campaign_overview_card(campaign)["directories"][0]["parameters"] == []


def test_file_history_is_bounded_and_uses_current_identity(tmp_path):
    path = tmp_path / "campaign.aca"
    make_archive(path)
    assert archive_file_history(str(path), "output.bp") == []
    with sqlite3.connect(path) as con:
        con.executescript(
            "create table entity_identity(kind text, local_id int, uuid text, active int);"
            "create table change_log(kind text, entity_uuid text, action text, timestamp_ns int);"
            "insert into entity_identity values('dataset',1,'current',1);"
            "insert into entity_identity values('dataset',1,'retired',0);"
            "insert into change_log values('dataset','retired','delete',1800000000000000000);"
        )
        con.executemany("insert into change_log values('dataset','current','update',?)",
                        [(1704164645000000000 + index * 1000000000,) for index in range(25)])
    history = archive_file_history(str(path), "output.bp")
    assert len(history) == 20
    assert all(event["action"] == "update" for event in history)
    assert history[0]["timestamp"] == "2024-01-02T03:04:29+00:00"
    assert archive_file_history(str(path), "plotted.bp") == []


def test_preview_uses_middle_ordered_frame_and_deduplicates_variable_associations(tmp_path):
    docs = [
        {
            "variable_type": "image", "variable_id": variable,
            "source_dataset": "output.bp", "visualization_name": "heatmap",
            "visualization_sequence_name": "pressure-sequence",
            "visualization_item_order": index,
            "visualization_item_uuid": f"image-{index}",
            "variable_path": f"plots/{index}",
        }
        for index in [4, 0, 3, 1, 2]
        for variable in ["pressure", "current_z"]
    ]
    inventory = {"uuid": "campaign", "datasets": [], "error": ""}
    with patch("adios2.FileReader", side_effect=AssertionError("preview selection read a payload")):
        summary = campaign_summary(str(tmp_path / "campaign.aca"), docs, inventory)
    assert len(summary["results"]) == 1
    preview = summary["results"][0]["_preview"]
    assert preview["uuid"] == "image-2"
    assert preview["variable_path"] == "plots/2"


def test_preview_uses_midpoint_of_physical_time_span(tmp_path):
    docs = [
        {
            "variable_type": "image", "variable_id": "pressure",
            "visualization_name": "heatmap", "visualization_sequence_name": "sequence",
            "visualization_item_order": index, "visualization_item_uuid": f"image-{index}",
            "physical_time": time, "time_unit": "ms",
        }
        for index, time in enumerate([0.0, 1.0, 4.0, 10.0, 20.0])
    ]
    summary = campaign_summary(str(tmp_path / "campaign.aca"), docs, {"uuid": "", "datasets": [], "error": ""})
    assert summary["results"][0]["_preview"]["uuid"] == "image-3"
    assert summary["results"][0]["caption"] == "pressure · t = 10 ms"


def test_even_and_single_frame_sequences_have_valid_middle_previews(tmp_path):
    for count in [1, 2, 4]:
        docs = [
            {"variable_type": "image", "visualization_name": "plot", "frame_index": index,
             "variable_path": f"frames/{index}", "physical_time": None}
            for index in range(count)
        ]
        summary = campaign_summary(str(tmp_path / "campaign.aca"), docs, {"uuid": "", "datasets": [], "error": ""})
        assert summary["results"][0]["_preview"]["frame_index"] == count // 2
        assert summary["results"][0]["caption"] == f"Frame {count // 2 + 1} of {count} · time not recorded"


def test_movie_caption_uses_recorded_range_and_sequence_image_caption_uses_selected_time(tmp_path):
    inventory = {"uuid": "", "datasets": [], "error": ""}
    docs = [{
        "variable_type": "video", "variable_id": "pressure", "source_dataset": "output.bp",
        "visualization_name": "movie", "visualization_item_uuid": "movie-id",
        "visualization_item_metadata": {"time_values": [0, 2, 5], "time_unit": "ms", "frame_count": 3},
    }]
    movie = campaign_summary(str(tmp_path / "campaign.aca"), docs, inventory)["results"][0]
    assert movie["caption"] == "pressure · Movie: t = 0–5 ms"
    docs = [{
        "variable_type": "image", "variable_id": "pressure", "source_dataset": "output.bp",
        "visualization_name": "heatmap", "visualization_item_order": index,
        "visualization_item_uuid": f"image-{index}",
        "visualization_sequence_metadata": {"time_values": [0, 2, 5], "time_unit": "ms"},
    } for index in range(3)]
    image = campaign_summary(str(tmp_path / "campaign.aca"), docs, inventory)["results"][0]
    assert image["caption"] == "pressure · t = 2 ms"


def test_non_time_coordinate_is_not_labeled_as_simulation_time_or_counted_as_steps(tmp_path):
    inventory = {"uuid": "", "error": "", "datasets": [{"name": "output.bp", "uuid": "a", "fileformat": "ADIOS"}]}
    docs = [{"variable_type": "variable", "variable_id": "signal", "source_dataset": "output.bp",
             "metadata": {"AvailableStepsCount": "1"}, "time_values": [1, 3, 5],
             "schema_num_timesteps": 3, "x_axis_variable": "shot",
             "axes": {"shot": {"kind": "shot", "label": "Shot number", "variable": "shot"}}}]
    dataset = campaign_summary(str(tmp_path / "campaign.aca"), docs, inventory)["datasets"][0]
    assert dataset["coverage"] == "1 step · Shot number = 1–5"


def test_movie_preview_frame_uses_recorded_physical_times(tmp_path):
    docs = [{
        "variable_type": "video", "visualization_name": "movie",
        "visualization_item_uuid": "video-id", "frame_count": 5,
        "time_values": [0.0, 1.0, 4.0, 10.0, 20.0],
    }]
    summary = campaign_summary(str(tmp_path / "campaign.aca"), docs, {"uuid": "", "datasets": [], "error": ""})
    assert summary["results"][0]["_preview"]["video_frame_index"] == 3


def test_movie_preview_decodes_middle_frame_instead_of_recorded_poster(working_movie):
    for index in [1, None]:
        descriptor = {"campaign_path": "/campaign.aca", "video_uuid": "movie", "video_frame_index": index, "uuid": "poster"}
        with patch("pulsar.campaign_media.read_embedded_video", return_value=working_movie.read_bytes()), patch(
            "pulsar.campaign_media.read_archived_image", side_effect=AssertionError("used the poster instead of a movie frame")
        ):
            preview = read_campaign_preview(descriptor)
        with Image.open(io.BytesIO(preview)) as image:
            red, green, blue = image.getpixel((4, 4))
        assert green > 80 and red < 40 and blue < 40


def test_movie_preview_falls_back_to_poster_if_decoding_is_unavailable():
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, format="PNG")
    with patch("pulsar.campaign_media.read_embedded_video", return_value=b"video"), patch(
        "pulsar.campaign_media._video_preview_bytes", return_value=None
    ), patch("pulsar.campaign_media.read_archived_image", return_value=(buffer.getvalue(), "image/png")):
        preview = read_campaign_preview({"campaign_path": "/campaign.aca", "video_uuid": "movie", "uuid": "poster"})
    with Image.open(io.BytesIO(preview)) as image:
        red, green, blue = image.getpixel((4, 4))
    assert red > 200 and green < 40 and blue < 40


def test_overview_shows_only_recorded_bp_datasets_and_three_visualizations(tmp_path):
    inventory = {
        "uuid": "campaign-id", "error": "",
        "datasets": [
            {"name": "output.bp", "uuid": "bp-id", "fileformat": "ADIOS"},
            {"name": "logical-output", "uuid": "logical-id", "fileformat": "ADIOS"},
            {"name": "misleading.bp", "uuid": "hdf5-id", "fileformat": "HDF5"},
            {"name": "config.json", "uuid": "config-id", "fileformat": "TEXT"},
        ],
    }
    campaign = campaign_summary(str(tmp_path / "archive.aca"), [], inventory)
    campaign["results"] = [
        {"id": "field", "title": "Raw scalar field", "kind": "Scalar field", "preview": "", "video": ""},
        *[
            {"id": f"plot-{index}", "title": f"Plot {index}", "kind": "Image", "preview": f"/preview/{index}", "metadata_text": "Detailed record"}
            for index in range(5)
        ],
    ]
    card = campaign_overview_card(campaign)
    root, ungrouped = card["directories"]
    assert [item["name"] for item in root["datasets"]] == ["logical-output", "output.bp"]
    assert [item["id"] for item in ungrouped["results"]] == ["plot-0", "plot-1", "plot-2"]
    assert "uuid" not in card
    assert "updated" not in card
    assert "supporting_files" not in card
    assert "metadata_text" not in ungrouped["results"][0]
    assert campaign["results"][1]["metadata_text"] == "Detailed record"


def test_directory_groups_keep_bp_paths_and_sample_visualizations_per_directory():
    def result(identifier, sources=(), stored=""):
        return {
            "id": identifier, "title": identifier, "kind": "Image",
            "preview": f"/preview/{identifier}", "dataset_path": stored,
            "inputs": [{"source": source} for source in sources],
        }

    campaign = {
        "id": "campaign", "name": "Campaign", "path": "/campaign.aca", "error": "",
        "datasets": [
            {"name": name, "fileformat": "ADIOS", "explorable": True}
            for name in ["hll_128/checkpoint.bp", "hll_128/output.bp", "hll_64/output.bp"]
        ],
        "results": [
            *[result(f"128-{index}", ["hll_128/output.bp"]) for index in range(5)],
            result("64", ["hll_64/output.bp"]),
            result("comparison", ["hll_128/output.bp", "hll_64/output.bp"]),
            result("stored", stored="hll_64/plots/pressure.png"),
            result("unrelated", stored="hll_640/plots/pressure.png"),
        ],
    }
    # Source associations take precedence over links to other BP files.
    campaign["results"][0]["artifacts"] = [{"name": "hll_64/output.bp"}]
    groups = {group["path"]: group for group in campaign_overview_card(campaign)["directories"]}
    assert list(groups) == ["hll_128", "hll_64", ""]
    assert [item["label"] for item in groups["hll_128"]["datasets"]] == ["checkpoint.bp", "output.bp"]
    assert groups["hll_64"]["datasets"][0]["name"] == "hll_64/output.bp"
    assert [item["id"] for item in groups["hll_128"]["results"]] == ["128-0", "128-1", "128-2"]
    assert [item["id"] for item in groups["hll_64"]["results"]] == ["64", "comparison", "stored"]
    assert [item["id"] for item in groups[""]["results"]] == ["unrelated"]


def test_group_dates_are_file_summaries_and_incomplete_addition_dates_stay_unknown():
    campaign = {
        "id": "c", "path": "/c.aca", "name": "c", "error": "", "results": [],
        "datasets": [
            {"name": "run/a.bp", "fileformat": "ADIOS", "explorable": False,
             "modified_at": "2024-01-02T00:00:00+00:00", "added_at": "2024-01-05T00:00:00+00:00"},
            {"name": "run/b.bp", "fileformat": "ADIOS", "explorable": False,
             "modified_at": "2024-01-04T00:00:00+00:00", "added_at": ""},
        ],
    }
    card = campaign_overview_card(campaign)
    assert card["modified_at"] == card["directories"][0]["modified_at"] == "2024-01-04T00:00:00+00:00"
    assert card["added_at"] == card["directories"][0]["added_at"] == ""
    campaign["datasets"][1]["added_at"] = "2024-01-06T00:00:00+00:00"
    card = campaign_overview_card(campaign)
    assert card["directories"][0]["added_at"] == "2024-01-05T00:00:00+00:00"
    assert card["added_at"] == ""  # A file addition is not campaign creation.


def test_registered_package_metadata_survives_failed_data_ingestion(tmp_path):
    path = tmp_path / "campaign.aca"
    make_archive(path)
    with sqlite3.connect(path) as con:
        con.executescript(
            "create table visualization_sequence(visid int,name text,vistype text,metadata text);"
            "create table visualization_variable(visid int,datasetid int,variable_name text,role text);"
            "create table visualization_item(visid int,item_order int,item_type text,item_uuid text,metadata text);"
        )
        con.execute("insert into dataset values('plot.png','image-id','IMAGE',0)")
        con.execute("insert into visualization_sequence values(1,'plots/analysis','heatmap',?)", (json.dumps({"configuration": "analysis.json"}),))
        con.execute("insert into visualization_variable values(1,1,'pressure','primary')")
        con.execute("insert into visualization_item values(1,0,'IMAGE','image-id','{}')")
    collection = SQLiteCampaignCollection(tmp_path / "sidecar.sqlite")
    try:
        overview = build_campaign_overview(collection, [str(path)])
        result = overview[0]["results"][0]
        assert len(overview[0]["results"]) == 1
        assert result["inputs"] == [{"source": "output.bp", "variable": "pressure"}]
        assert result["artifacts"][0]["name"] == "analysis.json"
    finally:
        collection.close()


def test_unassociated_images_are_visible_without_invented_inputs(tmp_path):
    path = tmp_path / "campaign.aca"
    make_archive(path)
    with sqlite3.connect(path) as con:
        con.execute("insert into dataset values ('orphan.png', 'image-id', 'IMAGE', 0)")
    result = campaign_summary(str(path), [])["results"][0]
    assert result["title"] == "orphan.png"
    assert result["inputs"] == []
    assert json.loads(result["metadata_text"]) == []


def test_publication_is_one_package_across_multiple_source_associations(tmp_path):
    path = str(tmp_path / "archive.aca")
    docs = [
        {"variable_type": "video", "visualization_name": "published-videos/result", "association_source": "publication", "variable_id": variable, "source_dataset": source}
        for variable, source in [("pressure", "a.bp"), ("pressure", "b.bp")]
    ]
    summary = campaign_summary(path, docs, {"uuid": "", "datasets": [], "error": ""})
    assert len(summary["results"]) == 1
    assert len(summary["results"][0]["inputs"]) == 2


def test_scalar_plot_reads_the_selected_archive_not_the_startup_archive(tmp_path):
    collection = SQLiteCampaignCollection(tmp_path / "sidecar.sqlite")
    selected = str(tmp_path / "selected.aca")
    try:
        for path in [str(tmp_path / "startup.aca"), selected]:
            collection.insert_one({"campaign_path": path, "variable_id": "pressure", "variable_type": "variable", "source_dataset": "output.bp", "metadata": {"Shape": "4"}})
        db = CampaignDb(collection)
        with patch.object(db, "_read_plot_series_cached", return_value=(np.arange(4), np.arange(4), "index")) as read:
            tile = db.get_or_create_generated_scalar_plot_tile("startup.aca", "pressure", extra_filter={"campaign_path": selected})
        assert tile["status"] == "ok"
        assert read.call_args.args[0] == selected
    finally:
        collection.close()


def test_media_requests_disambiguate_matching_uuids_in_different_archives():
    async def check():
        callbacks = []
        server = SimpleNamespace(controller=SimpleNamespace(on_server_bind=SimpleNamespace(add=callbacks.append)))
        paths = ("/original.aca", "/copy.aca")
        register_campaign_media_route(server, paths)
        app = web.Application()
        callbacks[0](SimpleNamespace(app=app))
        async with TestClient(TestServer(app)) as client:
            with patch("pulsar.campaign_media.read_embedded_video", side_effect=lambda path, uuid: path.encode()):
                response = await client.get(f"/pulsar-media/shared-uuid?campaign={campaign_key(paths[1])}")
                assert response.status == 200
                assert await response.read() == b"/copy.aca"
                response = await client.get("/pulsar-media/shared-uuid?campaign=unknown")
                assert response.status == 404
    asyncio.run(check())


class OverviewController(CampaignOverviewControllerMixin):
    pass


def test_list_selection_is_campaign_scoped_and_uses_recorded_file_links(tmp_path):
    paths = [tmp_path / "original.aca", tmp_path / "copy.aca"]
    for path in paths:
        make_archive(path)
    campaigns = [campaign_summary(str(path), documents(path)) for path in paths]
    controller = OverviewController()
    controller._campaign_overview_records = campaigns
    controller.state = SimpleNamespace(campaignSelection={}, campaignDisplay="overview", showCampaignPackage=False)
    controller.select_campaign_overview_entry({"kind": "file", "campaign_path": str(paths[1]), "dataset_name": "output.bp"})
    selected = controller.state.campaignSelection
    assert selected["campaign_path"] == str(paths[1])
    assert selected["dataset_name"] == "output.bp"
    assert selected["results"][0]["id"] == campaigns[1]["results"][0]["id"]
    assert selected["results"][0]["id"] != campaigns[0]["results"][0]["id"]
    assert selected["explorable"]
    assert "variable_details" not in selected  # Full file metadata is fetched through Details.
    assert "metadata_text" not in selected
    assert controller.state.campaignDisplay == "overview"
    assert not controller.state.showCampaignPackage
    controller.select_campaign_overview_entry({"kind": "file", "campaign_path": str(paths[1]), "dataset_name": "plotted.bp"})
    assert controller.state.campaignSelection["results"]  # Explicit plotted-data artifact link.
    controller.select_campaign_overview_entry({"kind": "file", "campaign_path": str(paths[1]), "dataset_name": "analysis.json"})
    assert controller.state.campaignSelection["dataset_name"] == "plotted.bp"  # Supporting files are not BP rows.
    controller.select_campaign_overview_entry({"kind": "directory", "campaign_path": str(paths[1]), "directory_path": "."})
    assert controller.state.campaignSelection["title"] == "Campaign root"
    assert controller.state.campaignSelection["file_count"] == 2
    controller.select_campaign_overview_entry({"kind": "campaign", "campaign_path": str(paths[0])})
    assert controller.state.campaignSelection["title"] == "original"
    assert controller.state.campaignSelection["file_count"] == 2
    for invalid in [None, {"kind": "unknown", "campaign_path": str(paths[0])},
                    {"kind": "directory", "campaign_path": str(paths[0]), "directory_path": "missing"},
                    {"kind": "campaign", "campaign_path": "missing.aca"}]:
        controller.select_campaign_overview_entry(invalid)
        assert controller.state.campaignSelection["title"] == "original"


def test_dataset_navigation_and_package_inspection_preserve_campaign_scope(tmp_path):
    path = tmp_path / "campaign.aca"
    make_archive(path)
    campaign = campaign_summary(str(path), documents(path))
    controller = OverviewController()
    controller._campaign_overview_records = [campaign]
    result = campaign["results"][0]
    controller._campaign_result_records = {result["id"]: result}
    controller.refresh_variable_list = Mock()
    controller.state = SimpleNamespace(showCampaignPackage=False)
    controller.inspect_campaign_result(result["id"])
    assert controller.state.showCampaignPackage
    assert "_preview" not in controller.state.campaignPackage
    controller.explore_campaign_dataset("unknown.aca", "output.bp")
    controller.refresh_variable_list.assert_not_called()
    controller.explore_campaign_dataset(str(path), "output.bp")
    assert controller.state.selectedCampaignPath == str(path)
    assert controller.state.campaignDatasetPath == "output.bp"
    assert controller.state.campaignDisplay == "workspace"
    assert not controller.state.showCampaignPackage
    controller.inspect_campaign_file(str(path), "output.bp")
    assert controller.state.campaignFile["variables"] == ["pressure"]
    assert controller.state.campaignFile["variable_details"][0]["name"] == "pressure"
    assert controller.state.campaignFile["history"] == []
    assert controller.state.showCampaignPackage
    # The campaign's Open button uses the same action without a dataset scope.
    controller.state.selectedVar = "pressure"
    controller.explore_campaign_dataset(str(path))
    assert controller.state.selectedCampaignPath == str(path)
    assert controller.state.campaignDatasetPath == ""
    assert controller.state.selectedVar == ""
    assert controller.state.campaignDisplay == "workspace"
