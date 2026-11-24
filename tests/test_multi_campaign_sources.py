"""Workspace source identity and rendering across archives with overlapping names."""

from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
from trame.app import get_server

from db import CampaignDb
from plugin_runtime import plot1d_payload
from pulsar.backends import LocalCampaignBackend
from pulsar.controllers import ControllerContext, PulsarController
from pulsar.models.source_selection import source_fields_from_row, source_filter_from_row, source_key_for_fields
from pulsar.models.workspace_state import parse_workspace_document, workspace_json
from pulsar.state import init_state
from query_parser import mongo_filter_matches
from sqlite_store import SQLiteCampaignCollection


@pytest.fixture
def campaigns(tmp_path):
    paths = [str(tmp_path / "a.aca"), str(tmp_path / "b.aca")]
    collection = SQLiteCampaignCollection(tmp_path / "viewer.sqlite")
    for path, maximum in zip(paths, [3.0, 30.0]):
        collection.insert_one({
            "campaign_path": path, "variable_id": "pressure", "variable_name": "pressure",
            "variable_path": "output.bp/pressure", "variable_type": "variable", "source_dataset": "output.bp",
            "metadata": {"Type": "double", "Shape": "3", "AvailableStepsCount": "1"},
            "min": 1.0, "max": maximum,
        })
    db = CampaignDb(collection)
    server = get_server(f"campaign-scope-{tmp_path.name}", client_type="vue3")
    init_state(server.state, db)
    server.state.gridLayoutMode = "uniform"
    controller = PulsarController(ControllerContext(
        server=server, backend=LocalCampaignBackend(db), db=db, collection=collection,
        parse_campaign=lambda *_args, **_kwargs: None, campaign_path=paths[0], campaign_paths=tuple(paths),
    ))
    controller.refresh_variable_list()

    def read(path, *_args, **_kwargs):
        multiplier = 1.0 if path == paths[0] else 10.0
        return np.arange(3), np.array([1, 2, 3]) * multiplier, "index"

    with patch.object(db, "_read_plot_series_cached", side_effect=read) as reader:
        yield controller, db, collection, paths, reader
    db.close()
    collection.close()


@pytest.mark.parametrize("identity", [
    {}, {"schema_file_group": "output", "schema_mode": "file_per_timestep"},
    {"source_collection_id": "runs", "source_collection_label": "Runs", "schema_name": "test"},
])
def test_identical_source_names_keep_distinct_campaign_identities(campaigns, identity):
    controller, db, collection, paths, _reader = campaigns
    if identity:
        for path in paths:
            document = collection.find_one({"campaign_path": path})
            document.pop("_id", None)
            collection.delete_many({"campaign_path": path})
            collection.insert_one({**document, **identity})
    summary = LocalCampaignBackend(db).get_source_summary({"variable_id": "pressure", "query": {}})
    assert summary["num_sources"] == 2
    sources = summary["sources"]
    assert {source["campaign_path"] for source in sources} == set(paths)
    assert len({source["id"] for source in sources}) == 2
    assert len({source_key_for_fields(source) for source in sources}) == 2
    for source in sources:
        fields = source_fields_from_row(source)
        assert fields["campaign_path"] == source["campaign_path"]
        assert source_filter_from_row(fields)["campaign_path"] == source["campaign_path"]


def test_source_restrictions_do_not_select_matching_paths_in_other_archives(campaigns):
    _controller, db, collection, paths, _reader = campaigns
    restricted = db.source_restriction_summary([{"variable_id": "pressure", "max": {"$gt": 10}}])
    assert restricted["count"] == 1
    docs = list(collection.find(restricted["filter"]))
    assert {doc["campaign_path"] for doc in docs} == {paths[1]}
    assert not mongo_filter_matches(restricted["filter"], {"campaign_path": paths[0], "source_dataset": "output.bp"})


def test_scoped_drop_and_workspace_restore_keep_each_plot_bound_to_its_archive(campaigns):
    controller, _db, _collection, paths, reader = campaigns
    for index, path in enumerate(paths):
        controller.assign_var_to_grid_cell_trigger("pressure", index, path)
    assert {call.args[0] for call in reader.call_args_list} == set(paths)
    assert controller.state.selectedCampaignPath == ""
    for index, path in enumerate(paths):
        cell = controller.state.gridCells[index]
        assert cell["campaign_path"] == path
        assert cell["_source_fields_list"][0]["campaign_path"] == path
        assert cell["plot"]["series"][0]["y"] == ([1.0, 2.0, 3.0] if index == 0 else [10.0, 20.0, 30.0])

    document = parse_workspace_document(workspace_json(controller.state, paths[0]))
    controller.state.selectedCampaignPath = paths[1]
    controller.state.campaignDatasetPath = "unrelated.bp"
    controller.restore_workspace_state(document)
    controller.refresh_grid_cells()
    assert [cell["campaign_path"] for cell in controller.state.gridCells[:2]] == paths
    assert controller.state.gridCells[0]["plot"]["series"][0]["y"] == [1.0, 2.0, 3.0]
    assert controller.state.gridCells[1]["plot"]["series"][0]["y"] == [10.0, 20.0, 30.0]


def test_freeform_drop_and_context_menu_add_use_the_event_campaign(campaigns):
    controller, _db, _collection, paths, _reader = campaigns
    controller.state.gridLayoutMode = "freeform"
    controller.state.gridCells = []
    controller.add_var_to_canvas_trigger("pressure", {"x": 0, "y": 0}, campaign_path=paths[1])
    assert controller.state.gridCells[0]["campaign_path"] == paths[1]
    controller.show_item_context_menu("pressure", 0, 0, paths[0])
    controller.context_menu_item_add()
    assert controller.state.gridCells[1]["campaign_path"] == paths[0]
    assert controller.state.selectedCampaignPath == ""


def test_comparison_plot_keeps_both_archives_after_navigation_changes(campaigns):
    controller, _db, _collection, paths, _reader = campaigns
    rows = [controller.first_query_source_row_for_variable("pressure", campaign_path=path) for path in paths]
    assert controller.set_generated_scalar_plot_sources_cell(0, "pressure", rows)
    controller.state.selectedCampaignPath = paths[1]
    controller.refresh_grid_cells()
    cell = controller.state.gridCells[0]
    assert {item["campaign_path"] for item in cell["_source_fields_list"]} == set(paths)
    assert [series["y"] for series in cell["plot"]["series"]] == [[1.0, 2.0, 3.0], [10.0, 20.0, 30.0]]


def test_missing_original_source_does_not_rebind_to_another_archive(campaigns):
    controller, _db, collection, paths, _reader = campaigns
    controller.assign_var_to_grid_cell_trigger("pressure", 0, paths[0])
    collection.delete_many({"campaign_path": paths[0]})
    controller.state.selectedCampaignPath = paths[1]
    for _ in range(2):
        controller.refresh_grid_cells()
        cell = controller.state.gridCells[0]
        assert cell["campaign_path"] == paths[0]
        assert cell["status"] != "ok"


@pytest.mark.parametrize("scope", ["variable", "source"])
def test_plugin_context_and_helpers_use_selected_archive_instead_of_startup(campaigns, scope):
    controller, db, _collection, paths, _reader = campaigns
    controller.state.selectedCampaignPath = paths[0]
    row = controller.first_query_source_row_for_variable("pressure", campaign_path=paths[1])
    contexts = []

    def render(context):
        contexts.append((context["campaign_path"], context["helpers"].campaign_path))
        return plot1d_payload([{"x": [0, 1], "y": [10, 20], "source_label": "test"}], "x", "pressure")

    plugin = SimpleNamespace(PLUGIN_ID="routing-test", LABEL="Routing test", SCOPE=scope, render=render)
    with patch("plugin_runtime.load_plugin", return_value=plugin), patch(
        "plugin_runtime.plugin_info", return_value=SimpleNamespace(scope=scope)
    ):
        if scope == "variable":
            cell = controller.build_plugin_grid_cell("pressure", "plugin:routing-test", source_row=row)
        else:
            cell = {"variable_id": "pressure", **source_fields_from_row(row)}
            cell = controller.build_source_plugin_grid_cell("routing-test", cell)
    assert contexts == [(paths[1], paths[1])]
    assert cell["campaign_path"] == paths[1]


def test_unqualified_legacy_source_ids_remain_stable():
    source = {"variable_id": "pressure", "source_dataset": "output.bp"}
    assert LocalCampaignBackend._source_id(source) == "local-source:v1:779c2d63a9a85199fb9424c616165dacdf561f502652a0d8a1eab2582f718d9b"
    assert source_key_for_fields(source) == "pressure|output.bp"


def test_typed_catalog_query_intersects_source_clauses(campaigns):
    controller, _db, collection, paths, _reader = campaigns
    collection.insert_one({
        "campaign_path": paths[1], "variable_id": "valid", "variable_name": "valid",
        "variable_type": "variable", "source_dataset": "output.bp", "min": 1, "max": 1,
    })
    controller.state.queryText = (
        "var == 'pressure' and source(var == 'valid' and min == 1) "
        "and source(var == 'pressure' and max > 10)"
    )
    assert controller.update_query_state()
    assert controller.state.queryFilter["query_version"] == 1
    assert controller.state.querySourceRestrictionCount == 1
    matches = list(collection.find(controller.active_query_filter()))
    assert [(doc["campaign_path"], doc["variable_name"]) for doc in matches] == [(paths[1], "pressure")]


def test_invalid_source_filter_preserves_active_selection(campaigns):
    controller, _db, _collection, _paths, _reader = campaigns
    controller.state.sourceFilterText = "min > 0"
    controller.state.sourceRows = [{"_key": "selected", "variable_id": "pressure"}]
    controller.state.selectedSourceKeys = ["selected"]
    controller.state.sourceFilterDraftText = "min > None"
    controller.apply_source_dialog_filter()
    assert controller.state.sourceFilterText == "min > 0"
    assert controller.state.sourceRows == [{"_key": "selected", "variable_id": "pressure"}]
    assert controller.state.selectedSourceKeys == ["selected"]
    assert controller.state.sourceFilterError


@pytest.mark.parametrize("identity", [
    {},
    {"schema_file_group": "output", "schema_mode": "file_per_timestep"},
    {"source_collection_id": "runs", "schema_name": "test"},
])
@pytest.mark.parametrize("clauses, expected_indices", [
    ("source(var == 'absent')", []),
    ("source(var == 'valid' and min == 0) and source(var == 'valid' and min == 1)", []),
    ("source(var == 'valid' and min == 1)", [1]),
    ("source(var == 'unknown' and min > 0)", []),
    ("source(var == 'unknown' and min == None)", [0, 1]),
    ("source(var == 'unknown' and not (min > 0))", [0, 1]),
])
def test_typed_source_clause_edge_cases(campaigns, identity, clauses, expected_indices):
    controller, _db, collection, paths, _reader = campaigns
    for index, path in enumerate(paths):
        existing = collection.find_one({"campaign_path": path})
        collection.delete_many({"campaign_path": path})
        collection.insert_one({**existing, **identity})
        for name, extrema in [("valid", {"min": index, "max": index}), ("unknown", {})]:
            collection.insert_one({
                "campaign_path": path, "variable_id": name, "variable_name": name,
                "variable_type": "variable", "source_dataset": "output.bp",
                **identity, **extrema,
            })
    controller.state.queryText = "var == 'pressure' and " + clauses
    assert controller.update_query_state(), controller.state.queryError
    assert controller.state.querySourceRestrictionCount == len(expected_indices)
    matches = list(collection.find(controller.active_query_filter()))
    assert {doc["campaign_path"] for doc in matches} == {paths[index] for index in expected_indices}
    assert all(doc["variable_name"] == "pressure" for doc in matches)


def test_source_query_workspace_restore_into_fresh_controller(campaigns):
    from copy import deepcopy

    controller, db, collection, paths, _reader = campaigns
    controller.state.queryText = "var == 'pressure' and source(var == 'pressure' and max > 10)"
    assert controller.run_query()

    def selection(owner):
        summary = owner.application.get_source_summary({
            "variable_id": "pressure", "query": owner.active_query_filter(),
        })
        return {
            "catalog": deepcopy(owner.state.variableGroups),
            "sources": [(source["id"], source["campaign_path"], source["maximum"])
                        for source in summary["sources"]],
            "count": owner.state.querySourceRestrictionCount,
        }

    expected = selection(controller)
    assert expected["count"] == 1
    assert expected["sources"][0][1] == paths[1]
    document = parse_workspace_document(workspace_json(controller.state, paths[0]))
    server = get_server(f"query-restore-{paths[0]}", client_type="vue3")
    init_state(server.state, db)
    fresh = PulsarController(ControllerContext(
        server=server, backend=LocalCampaignBackend(db), db=db, collection=collection,
        parse_campaign=lambda *_args, **_kwargs: None, campaign_path=paths[0], campaign_paths=tuple(paths),
    ))
    assert not fresh.state.queryText
    fresh.restore_workspace_state(document)
    assert fresh.state.queryText == controller.state.queryText
    assert selection(fresh) == expected


@pytest.mark.parametrize("operation", ["get_navigation", "resolve_source_restriction"])
def test_global_query_backend_failure_preserves_selection(campaigns, operation):
    from copy import deepcopy
    from pulsar.backends.contracts import QueryExecutionError

    controller, _db, _collection, _paths, _reader = campaigns
    controller.state.queryText = "var == 'pressure'"
    assert controller.run_query()
    controller.state.sourceRows = [{"_key": "chosen", "variable_id": "pressure"}]
    controller.state.selectedSourceKeys = ["chosen"]
    fields = ("queryFilter", "querySourceFilters", "querySourceRestrictionFilter",
              "querySourceRestrictionCount", "queryViewLabel", "variableGroups",
              "sourceRows", "selectedSourceKeys")
    previous = {field: deepcopy(getattr(controller.state, field)) for field in fields}
    controller.state.queryText = "var == 'pressure' and source(max > 10)"
    with patch.object(controller.application, operation, side_effect=QueryExecutionError("backend offline")):
        assert not controller.run_query()
    assert {field: getattr(controller.state, field) for field in fields} == previous
    assert "backend offline" in controller.state.queryError
    assert controller.state.queryStatus == "Query ERROR · active query unchanged"


def test_source_filter_backend_failure_preserves_selection(campaigns):
    from copy import deepcopy
    from pulsar.backends.contracts import QueryExecutionError

    controller, _db, _collection, _paths, _reader = campaigns
    controller.state.sourceFilterText = "min > 0"
    controller.state.sourceRowsAll = [{"_key": "chosen", "variable_id": "pressure", "min_value": 1}]
    controller.state.sourceRows = deepcopy(controller.state.sourceRowsAll)
    controller.state.selectedSourceKeys = ["chosen"]
    previous = deepcopy(controller.state.sourceRows)
    controller.state.sourceFilterDraftText = "source(max > 10)"
    with patch.object(controller.application, "resolve_source_restriction",
                      side_effect=QueryExecutionError("backend offline")):
        controller.apply_source_dialog_filter()
    assert controller.state.sourceFilterText == "min > 0"
    assert controller.state.sourceRows == previous
    assert controller.state.selectedSourceKeys == ["chosen"]
    assert "backend offline" in controller.state.sourceFilterError


@pytest.mark.parametrize("draft, expected_names", [
    ("max > 10", ["large"]),
    ("max < 10", ["small"]),
    ("", ["large", "small"]),
])
def test_source_filter_click_payload_overrides_stale_model(campaigns, draft, expected_names):
    controller, _db, _collection, _paths, _reader = campaigns
    controller.state.sourceRowsAll = [
        {"_key": "large", "variable_id": "pressure", "source_dataset": "large", "max_value": 30},
        {"_key": "small", "variable_id": "pressure", "source_dataset": "small", "max_value": 3},
    ]
    controller.state.sourceRows = list(controller.state.sourceRowsAll)
    controller.state.sourceFilterDraftText = "min > None"
    controller.apply_source_dialog_filter(draft)
    assert not controller.state.sourceFilterError
    assert controller.state.sourceFilterDraftText == draft
    assert controller.state.sourceFilterText == draft
    assert [row["_key"] for row in controller.state.sourceRows] == expected_names


def test_invalid_click_payload_preserves_filter_when_model_is_still_valid(campaigns):
    controller, _db, _collection, _paths, _reader = campaigns
    controller.state.sourceFilterText = "max > 10"
    controller.state.sourceFilterDraftText = "max > 10"
    controller.state.sourceRows = [{"_key": "chosen", "max_value": 30}]
    controller.state.selectedSourceKeys = ["chosen"]
    controller.apply_source_dialog_filter("max > None")
    assert controller.state.sourceFilterDraftText == "max > None"
    assert controller.state.sourceFilterText == "max > 10"
    assert controller.state.sourceRows == [{"_key": "chosen", "max_value": 30}]
    assert controller.state.selectedSourceKeys == ["chosen"]
    assert controller.state.sourceFilterError
