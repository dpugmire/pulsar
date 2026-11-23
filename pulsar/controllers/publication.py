"""Publish working images/movies and refresh the campaign without rebuilding the workspace."""

import sqlite3
from copy import deepcopy

from pulsar.models.grid import preserve_grid_geometry
from pulsar.publications import (
    PublicationError,
    load_publications,
    publication_id,
    published_tile,
)


class PublicationControllerMixin:
    ACTION_BINDINGS = (
        ("open_publish_result", "open_publish_result"),
        ("cancel_publish_result", "cancel_publish_result"),
        ("confirm_publish_result", "confirm_publish_result"),
    )
    TRIGGER_BINDINGS = ()
    STATE_CHANGE_BINDINGS = ()

    def published_results(self):
        return load_publications(self.campaign_path)

    def result_tile(self, result_id):
        result_id = publication_id(result_id)
        record = self.published_results().get(result_id)
        if record:
            return published_tile(record)
        if self.result_store is None:
            raise PublicationError("Working-result storage is not configured")
        return self.result_store.tile(result_id)

    def _publication_associations(self, associations):
        if associations is None:
            return []
        if not isinstance(associations, list) or len(associations) > 64:
            raise PublicationError(
                "associations must be a list of at most 64 source-qualified variables"
            )
        result = []
        for spec in associations:
            if not isinstance(spec, dict) or set(spec) - {
                "name",
                "source_dataset",
                "role",
            }:
                raise PublicationError(
                    "Each association requires name and source_dataset, with optional role"
                )
            item = {
                key: spec.get(key, "primary" if key == "role" else "")
                for key in ("name", "source_dataset", "role")
            }
            if any(
                not isinstance(value, str) or not value.strip() or len(value) > 1024
                for value in item.values()
            ):
                raise PublicationError(
                    "Association fields must be nonempty text of at most 1024 characters"
                )
            item = {key: value.strip() for key, value in item.items()}
            source = next(
                (
                    doc
                    for doc in self.collection.find(
                        {
                            "variable_type": "variable",
                            "source_dataset": item["source_dataset"],
                        }
                    )
                    if item["name"]
                    in {doc.get("variable_id"), doc.get("variable_name_physical")}
                ),
                None,
            )
            if source is None:
                raise PublicationError(
                    f"Unknown source variable: {item['name']} in {item['source_dataset']}"
                )
            if item not in result:
                result.append(item)
        return result

    def _mark_publication(self, record):
        layout = deepcopy(self._stash_active_workspace_grid())
        identifier = record["publication_id"]
        for pane in layout.get("panes", []):
            for tab in pane.get("tabs", []):
                grid = tab.get("grid", {})
                grid["cells"] = [
                    preserve_grid_geometry(published_tile(record), cell)
                    if cell.get("working_result_id") == identifier
                    else cell
                    for cell in grid.get("cells", [])
                ]
                grid["needs_refresh"] = True
        self._publish_workspace_layout(layout)
        self.state.gridCells = [
            preserve_grid_geometry(published_tile(record), cell)
            if cell.get("working_result_id") == identifier
            else cell
            for cell in list(self.state.gridCells or [])
        ]

    def _refresh_after_publication(self):
        self.plugin_source_variables_cache.clear()
        self.ingest_campaign_every_time()
        if not self.state.dbOk:
            raise PublicationError(str(self.state.dbStatus))
        self.refresh_grid_cells()
        self._stash_active_workspace_grid()

    def publish_result(self, result_id, *, title=None, associations=None):
        result_id = publication_id(result_id)
        existing = self.published_results().get(result_id)
        if existing is None:
            if not self.state.dbOk:
                raise PublicationError("Campaign is not available")
            associations = self._publication_associations(associations)
            if self.result_store is None:
                raise PublicationError("Working-result storage is not configured")
            manifest = self.result_store.get(result_id)
            title = manifest["title"] if title is None else title
            if not isinstance(title, str) or not title.strip() or len(title) > 1024:
                raise PublicationError(
                    "title must be nonempty text of at most 1024 characters"
                )
            preview = self.result_store.artifact(result_id, "image")
            is_video = "video" in manifest["artifacts"]
            payload = (
                self.result_store.artifact(result_id, "video") if is_video else preview
            )
            try:
                from hpc_campaign import Manager
            except ImportError as error:
                raise PublicationError(
                    'Publishing requires hpc-campaign; install Pulsar with the "publish" extra'
                ) from error
            method_name = "publish_video" if is_video else "publish_image"
            if not callable(getattr(Manager, method_name, None)):
                raise PublicationError(
                    f"Publishing requires an hpc-campaign build with Manager.{method_name}"
                )
            # ADIOS CampaignReaders keep SQLite handles open. Release them before
            # reserving a writer, then reopen lazily after the committed update.
            self.db.close()
            manager = Manager(self.campaign_path)
            try:
                arguments = {
                    "publication_id": result_id,
                    "title": title,
                    "variables": associations,
                }
                if is_video:
                    arguments.update(preview=preview, video_metadata=manifest["video"])
                record = getattr(manager, method_name)(payload, **arguments)
            except (
                OSError,
                ValueError,
                LookupError,
                RuntimeError,
                sqlite3.Error,
            ) as error:
                raise PublicationError(f"Publication failed: {error}") from error
            finally:
                manager.close()
        else:
            record = existing
        response = {
            "publication_status": "published",
            "publication": record,
            "already_published": existing is not None,
        }
        try:
            self._mark_publication(record)
            self._refresh_after_publication()
            response["refresh_status"] = "ok"
        except Exception as error:  # noqa: BLE001 - preserve the receipt after any refresh failure
            # The archive commit is durable. Returning this receipt lets callers
            # retry refresh with the same ID without a second archive write.
            response["refresh_status"] = "failed"
            response["refresh_error"] = f"{type(error).__name__}: {error}"
        return response

    def open_publish_result(self, cell_index, **_):
        if not isinstance(cell_index, int) or not self.is_valid_grid_index(cell_index):
            return
        cell = self.state.gridCells[cell_index]
        if not cell.get("working_result_id"):
            return
        self.state.publishResultCampaign = self.campaign_path
        self.state.publishResultId = cell["working_result_id"]
        self.state.publishResultTitle = cell.get("display_title") or cell.get(
            "variable_name", ""
        )
        self.state.publishResultAssociations = []
        self.state.publishResultStatus = ""
        self.state.publishResultCommitted = (
            cell.get("publication_status") == "published"
        )
        self.state.showPublishResult = True
        choices = []
        for source in self.collection.find(
            {"variable_type": "variable"},
            {"variable_id": 1, "variable_name_physical": 1, "source_dataset": 1},
        ):
            name = source.get("variable_name_physical") or source.get("variable_id")
            dataset = source.get("source_dataset")
            if name and dataset:
                item = {
                    "title": f"{name} — {dataset}",
                    "value": {
                        "name": name,
                        "source_dataset": dataset,
                        "role": "primary",
                    },
                }
                if item not in choices:
                    choices.append(item)
        self.state.publishResultChoices = choices

    def cancel_publish_result(self, **_):
        self.state.showPublishResult = False

    def confirm_publish_result(self, **_):
        try:
            response = self.publish_result(
                self.state.publishResultId,
                title=self.state.publishResultTitle,
                associations=list(self.state.publishResultAssociations or []),
            )
            self.state.publishResultStatus = (
                "Published in campaign."
                if response["refresh_status"] == "ok"
                else "Published; refresh failed. Click Retry refresh. "
                + response["refresh_error"]
            )
            self.state.publishResultCommitted = True
        except (OSError, ValueError) as error:
            self.state.publishResultStatus = str(error)
