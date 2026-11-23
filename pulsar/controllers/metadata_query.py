"""Restore and inspect metadata-query tiles through normal workspace operations."""

import json

from pulsar.metadata_query import MetadataQueryEngine, MetadataQueryError
from pulsar.models.grid import empty_grid_cell
from pulsar.query_results import QueryResultStore


class MetadataQueryControllerMixin:
    ACTION_BINDINGS = (("show_metadata_query_details", "show_metadata_query_details"),)
    TRIGGER_BINDINGS = ()
    STATE_CHANGE_BINDINGS = ()

    def metadata_query_engine(self):
        path = getattr(self.collection, "path", None)
        if path is None:
            raise MetadataQueryError(
                "Metadata SQL requires a local SQLite campaign index"
            )
        return MetadataQueryEngine(path, self.campaign_path)

    def query_result_store(self):
        if self.result_store is None:
            raise MetadataQueryError("Query-result storage is not configured")
        return QueryResultStore(
            self.result_store.directory / ".queries", self.campaign_path
        )

    def query_result_cell(self, query_id):
        try:
            return self.query_result_store().tile(query_id)
        except MetadataQueryError as error:
            cell = empty_grid_cell()
            cell.update(
                {
                    "query_result_id": query_id,
                    "variable_name": "Metadata query",
                    "display_title": "Query result unavailable",
                    "status": "error",
                    "note": str(error),
                }
            )
            return cell

    def show_metadata_query_details(self, cell_index, **_):
        if not isinstance(cell_index, int) or not self.is_valid_grid_index(cell_index):
            return
        query_id = self.state.gridCells[cell_index].get("query_result_id")
        if not query_id:
            return
        self.state.helpModalTitle = "Metadata query"
        try:
            result = self.query_result_store().get(query_id)
            self.state.helpModalText = json.dumps(
                {
                    key: value
                    for key, value in result.items()
                    if key not in {"rows", "references"}
                },
                indent=2,
            )
        except MetadataQueryError as error:
            self.state.helpModalText = str(error)
        self.state.showHelpModal = True
