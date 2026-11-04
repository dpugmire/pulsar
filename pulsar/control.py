"""Opt-in local HTTP control of Pulsar's existing workspace operations."""

import atexit
import ipaddress
import json
import logging
import math
import os
import secrets
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from .client import API_VERSION
from .models import canvas_layout
from .models.grid import assign_cell, cell_has_content
from .models.workspace_layout import apply_grid_snapshot, grid_snapshot
from .models.workspace_state import parse_workspace_document, workspace_document
from .publications import PublicationError
from .results import ResultError

API_PATH = "/pulsar-api/v1"
_TILE_FIELDS = (
    "tile_id",
    "variable_id",
    "variable_name",
    "display_title",
    "source_dataset",
    "source_id",
    "_source_key",
    "_source_keys",
    "selected_visualization",
    "visualization_options",
    "media_type",
    "status",
    "note",
    "plot_settings",
    "scalar_field_settings",
    "selection_axis",
    "working_result_id",
    "publication_status",
    "publication_image_uuid",
    "publication_video_uuid",
    "time_mode",
    "time_values",
    "time_unit",
    "time_source",
)


class ControlError(ValueError):
    def __init__(self, message, *, code="invalid_request", status=400):
        super().__init__(message)
        self.code = code
        self.status = status


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise ControlError(f"{name} must be nonempty text of at most 1024 characters")
    return value.strip()


def _tile(cell, index):
    return {
        "cell_index": index,
        **{key: cell[key] for key in _TILE_FIELDS if key in cell},
    }


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


class ViewerControl:
    """A narrow adapter over the same operations used by the browser."""

    def __init__(self, controller, instance_id):
        self.controller = controller
        self.state = controller.state
        self.instance_id = instance_id

    def context(self):
        state = self.state
        cells = list(state.gridCells or [])
        selected = [
            index
            for index in list(state.selectedGridCellIndices or [])
            if isinstance(index, int) and 0 <= index < len(cells)
        ]
        return {
            "instance_id": self.instance_id,
            "campaign": {
                "path": self.controller.campaign_path,
                "ready": bool(state.dbOk),
                "status": str(state.dbStatus or ""),
            },
            "active_pane_id": state.workspaceActivePaneId,
            "active_tab_id": state.workspaceActiveTabId,
            "selected_variable_id": str(state.selectedVar or ""),
            "source_selection_variable_id": str(state.detailsSelectedVarId or ""),
            "selected_source_keys": list(state.selectedSourceKeys or []),
            "selected_sources": [
                self.controller.source_row_for_key(key)
                for key in list(state.selectedSourceKeys or [])
            ],
            "active_cell_index": state.activeGridCell,
            "selected_tiles": [_tile(cells[index], index) for index in selected],
            "query": str(state.queryText or ""),
            "timeline_driver_cell_index": state.timelineDriverCell,
            "scalar_plot_policy": state.scalarPlotPolicy,
        }

    def catalog(self):
        labels = self.state.variableLabelsById or {}
        return [
            {"variable_id": name, "label": labels.get(name, name)}
            for name in list(self.state.variableNames or [])
        ]

    def tabs(self):
        layout = self.controller._workspace_layout()
        result = []
        for pane in layout.get("panes", []):
            for tab in pane.get("tabs", []):
                active = tab["id"] == self.state.workspaceActiveTabId
                grid = grid_snapshot(self.state) if active else tab.get("grid", {})
                result.append(
                    {
                        "pane_id": pane["id"],
                        "tab_id": tab["id"],
                        "title": tab["title"],
                        "active": active,
                        "layout_mode": grid.get("layout_mode"),
                        "tiles": [
                            _tile(cell, index)
                            for index, cell in enumerate(grid.get("cells", []))
                            if cell_has_content(cell)
                        ],
                    }
                )
        return result

    def create_tab(self, title, pane_id=None):
        title = _text(title, "title")
        pane_id = (
            self.state.workspaceActivePaneId
            if pane_id is None
            else _text(pane_id, "pane_id")
        )
        if not any(
            pane.get("id") == pane_id
            for pane in self.controller._workspace_layout().get("panes", [])
        ):
            raise ControlError("Unknown workspace pane", code="not_found", status=404)
        with self.controller.history.transaction("Add tab"):
            self.controller.add_workspace_tab(pane_id)
            tab_id = self.state.workspaceActiveTabId
            self.controller.rename_workspace_tab(pane_id, tab_id, title)
        return next(tab for tab in self.tabs() if tab["tab_id"] == tab_id)

    def results(self):
        manifests = {item["result_id"]: item for item in self._result_store().list()}
        for result_id, record in self.controller.published_results().items():
            manifests[result_id] = {
                **manifests.get(
                    result_id, {"result_id": result_id, "title": record["title"]}
                ),
                "title": record["title"],
                "publication_status": "published",
                "publication": record,
                **({"video": record["video"]} if "video" in record else {}),
            }
        return list(manifests.values())

    def publish_result(self, result_id, title=None, associations=None):
        try:
            return self.controller.publish_result(
                result_id, title=title, associations=associations
            )
        except (PublicationError, ResultError, OSError) as error:
            raise ControlError(
                str(error), code="publication_failed", status=409
            ) from error

    def workspace(self):
        return workspace_document(self.state, self.controller.campaign_path)

    def restore_workspace(self, document):
        try:
            document = parse_workspace_document(json.dumps(document, allow_nan=False))
            self.controller.restore_workspace_state(document)
        except (ValueError, TypeError) as error:
            raise ControlError(str(error), code="invalid_workspace") from error
        self.controller.history.clear()
        self.controller.record_interaction(
            "workspace.loaded",
            source="python_client",
            payload={"workspace": self.controller.interaction_workspace_snapshot()},
        )
        return self.context()

    def result(self, result_id):
        try:
            record = self.controller.published_results().get(result_id)
            if record:
                try:
                    manifest = (
                        self.controller.result_store.get(result_id)
                        if self.controller.result_store
                        else {}
                    )
                except ResultError:
                    manifest = {}
                return {
                    **manifest,
                    "result_id": result_id,
                    "title": record["title"],
                    "publication_status": "published",
                    "publication": record,
                    **({"video": record["video"]} if "video" in record else {}),
                }
            return self._result_store().get(result_id)
        except (ResultError, PublicationError) as error:
            raise ControlError(
                str(error), code="result_unavailable", status=404
            ) from error

    def _result_store(self):
        if self.controller.result_store is None:
            raise ControlError(
                "Working-result storage is not configured", code="not_ready", status=409
            )
        return self.controller.result_store

    def register_result(self, **arguments):
        try:
            return self._result_store().register(**arguments)
        except (ResultError, OSError, TypeError) as error:
            raise ControlError(str(error), code="invalid_result") from error

    def add_result(self, result_id, tab_id):
        tab_id = _text(tab_id, "tab_id")
        tab = next((tab for tab in self.tabs() if tab["tab_id"] == tab_id), None)
        if tab is None:
            raise ControlError("Unknown workspace tab", code="not_found", status=404)
        try:
            tile = self.controller.result_tile(result_id)
        except (ResultError, PublicationError) as error:
            raise ControlError(
                str(error), code="result_unavailable", status=404
            ) from error
        previous_layout = self.controller._workspace_layout()
        previous_grid = grid_snapshot(self.state)
        previous_selected = self.state.selectedVar, self.state.draggedVar
        try:
            with self.controller.history.transaction("Add working result"):
                self.controller.activate_workspace_tab(tab["pane_id"], tab_id)
                cells = self.controller.normalize_grid_cells(self.state.gridCells)
                if self.controller.normalize_grid_layout_mode() == "freeform":
                    if len(cells) >= canvas_layout.CANVAS_MAX_TILES:
                        raise ControlError(
                            "Freeform canvas reached its tile limit",
                            code="workspace_full",
                            status=409,
                        )
                    columns = self.controller.canvas_columns()
                    width = canvas_layout.normalize_drop_width(
                        self.state.canvasDefaultTileWidth
                    )
                    item = canvas_layout.geometry(
                        self.controller.next_canvas_tile_id(cells),
                        "image",
                        0,
                        0,
                        width,
                        width * 2,
                        columns=columns,
                    )
                    item = canvas_layout.nearest_free(
                        item, self.controller.canvas_geometries(cells), columns=columns
                    )
                    tile = canvas_layout.geometry_to_cell(tile, item)
                    cells.append(tile)
                    index = len(cells) - 1
                    self.state.canvasLayoutRevision = (
                        int(self.state.canvasLayoutRevision) + 1
                    )
                else:
                    index = next(
                        (
                            i
                            for i, cell in enumerate(cells)
                            if not cell_has_content(cell)
                            and not cell.get("grid_hidden")
                        ),
                        -1,
                    )
                    if index < 0:
                        raise ControlError(
                            "The target tab has no empty cells",
                            code="workspace_full",
                            status=409,
                        )
                    assign_cell(cells, index, tile)
                self.state.gridCells = self.controller.normalize_grid_cells(cells)
                self.controller.set_grid_selection([index], active=index)
                self.state.selectedVar = ""
                self.state.draggedVar = ""
                result = {
                    "pane_id": tab["pane_id"],
                    "tab_id": tab_id,
                    **_tile(self.state.gridCells[index], index),
                }
        except Exception:
            self.controller._publish_workspace_layout(previous_layout)
            apply_grid_snapshot(self.state, previous_grid)
            self.state.selectedVar, self.state.draggedVar = previous_selected
            raise
        return result

    def add_visualization(self, variable_id, tab_id):
        variable_id = _text(variable_id, "variable_id")
        tab_id = _text(tab_id, "tab_id")
        if not bool(self.state.dbOk):
            raise ControlError(
                "Campaign is not available", code="not_ready", status=409
            )
        if variable_id not in list(self.state.variableNames or []):
            raise ControlError(
                "Variable is not in the current catalog", code="not_found", status=404
            )
        tab = next((tab for tab in self.tabs() if tab["tab_id"] == tab_id), None)
        if tab is None:
            raise ControlError("Unknown workspace tab", code="not_found", status=404)
        if self.state.showScalarPlotDialog:
            raise ControlError(
                "Finish the pending scalar plot request first",
                code="confirmation_required",
                status=409,
            )
        previous_layout = self.controller._workspace_layout()
        previous_grid = grid_snapshot(self.state)
        previous_selection = {
            name: deepcopy(getattr(self.state, name))
            for name in (
                "selectedVar",
                "draggedVar",
            )
        }
        try:
            with self.controller.history.transaction("Add plot"):
                self.controller.activate_workspace_tab(tab["pane_id"], tab_id)
                self.controller._interaction_assignment_source = "python_client"
                try:
                    if self.controller.normalize_grid_layout_mode() == "freeform":
                        index = self.controller.add_var_to_canvas(
                            variable_id, {}, sync_selection=True
                        )
                        if index < 0:
                            raise ControlError(
                                "Freeform canvas reached its tile limit",
                                code="workspace_full",
                                status=409,
                            )
                    else:
                        cells = self.controller.normalize_grid_cells(
                            self.state.gridCells
                        )
                        index = next(
                            (
                                index
                                for index, cell in enumerate(cells)
                                if not cell_has_content(cell)
                                and not cell.get("grid_hidden")
                            ),
                            -1,
                        )
                        if index < 0:
                            raise ControlError(
                                "The target tab has no empty cells",
                                code="workspace_full",
                                status=409,
                            )
                        self.controller.assign_var_to_grid_cell(index, variable_id)
                finally:
                    self.controller._interaction_assignment_source = ""
                if self.state.showScalarPlotDialog:
                    self.controller.cancel_scalar_plot_generation()
                    raise ControlError(
                        "Scalar plot generation requires browser confirmation; choose Always in the viewer to enable automatic generation",
                        code="confirmation_required",
                        status=409,
                    )
                cell = list(self.state.gridCells or [])[index]
                if cell.get("status") != "ok" or not cell.get("media_type"):
                    raise ControlError(
                        str(cell.get("note") or "No visualization is available"),
                        code="visualization_unavailable",
                        status=409,
                    )
                result = {
                    "pane_id": tab["pane_id"],
                    "tab_id": tab_id,
                    **_tile(cell, index),
                }
        except Exception:
            # History restores semantic state by rebuilding tiles. If the
            # renderer itself failed, keep the already displayed payloads too.
            self.controller._publish_workspace_layout(previous_layout)
            apply_grid_snapshot(self.state, previous_grid)
            for name, value in previous_selection.items():
                setattr(self.state, name, value)
            raise
        return result


def register_control_api(server, controller, session_file):
    """Register local routes and own a private connection file for this process."""
    from aiohttp import web

    path = Path(session_file).expanduser().absolute()
    token = secrets.token_urlsafe(32)
    instance_id = str(uuid4())
    descriptor = {
        "api_version": API_VERSION,
        "instance_id": instance_id,
        "token": token,
        "endpoint": None,
    }
    # Reserve the name without replacing an existing file or following a symlink.
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    inode = os.fstat(fd).st_ino
    handle = os.fdopen(fd, "w", encoding="utf-8")
    control = ViewerControl(controller, instance_id)

    def write_descriptor():
        handle.seek(0)
        json.dump(descriptor, handle)
        handle.truncate()
        handle.flush()

    write_descriptor()

    def cleanup(**_):
        handle.close()
        try:
            if path.lstat().st_ino == inode:
                path.unlink()
        except FileNotFoundError:
            pass

    atexit.register(cleanup)
    server.controller.on_server_exited.add(cleanup)

    def on_ready(**_):
        descriptor["endpoint"] = f"http://127.0.0.1:{server.port}{API_PATH}"
        write_descriptor()
        print(f"Pulsar control session: {path}", flush=True)

    def on_bind(http_server):
        async def dispatch(request):
            try:
                try:
                    local = ipaddress.ip_address(request.remote or "").is_loopback
                except ValueError:
                    local = False
                if not local or not secrets.compare_digest(
                    request.headers.get("Authorization", ""), f"Bearer {token}"
                ):
                    raise ControlError(
                        "Pulsar control authentication failed",
                        code="unauthorized",
                        status=401,
                    )
                if request.headers.get("X-Pulsar-Instance") != instance_id:
                    raise ControlError(
                        "Wrong Pulsar instance", code="instance_mismatch", status=409
                    )
                route = request.path[len(API_PATH) :]
                payload = {}
                if request.method == "POST":
                    limit = {"/results": 160 * 1024, "/workspace": 5 * 1024 * 1024}.get(
                        route, 16384
                    )
                    if (
                        request.content_length is not None
                        and request.content_length > limit
                    ):
                        raise ControlError("Control request is too large", status=413)
                    raw = bytearray()
                    async for chunk in request.content.iter_chunked(4096):
                        raw.extend(chunk)
                        if len(raw) > limit:
                            raise ControlError(
                                "Control request is too large", status=413
                            )
                    try:
                        payload = json.loads(raw)
                    except (ValueError, UnicodeError) as error:
                        raise ControlError("Expected a JSON request object") from error
                    if not isinstance(payload, dict):
                        raise ControlError("Expected a JSON request object")
                    allowed = {
                        "/tabs": {"title", "pane_id"},
                        "/visualizations": {"variable_id", "tab_id"},
                        "/results": {
                            "title",
                            "image_path",
                            "video_path",
                            "frame_times",
                            "time_unit",
                            "time_source",
                            "script_path",
                            "parameters",
                            "provenance",
                        },
                        "/result-views": {"result_id", "tab_id"},
                        "/publications": {"result_id", "title", "associations"},
                        "/workspace": {"format", "version", "campaign", "state"},
                    }[route]
                    if set(payload) - allowed:
                        raise ControlError("Unsupported control arguments")
                with server.state:
                    if request.method == "GET":
                        if route.startswith("/results/"):
                            result = control.result(request.match_info["result_id"])
                        else:
                            result = {
                                "/context": control.context,
                                "/catalog": control.catalog,
                                "/tabs": control.tabs,
                                "/results": control.results,
                                "/workspace": control.workspace,
                            }[route]()
                    elif route == "/tabs":
                        result = control.create_tab(
                            payload.get("title"), payload.get("pane_id")
                        )
                    elif route == "/visualizations":
                        result = control.add_visualization(
                            payload.get("variable_id"), payload.get("tab_id")
                        )
                    elif route == "/results":
                        result = control.register_result(**payload)
                    elif route == "/publications":
                        result = control.publish_result(
                            payload.get("result_id"),
                            payload.get("title"),
                            payload.get("associations"),
                        )
                    elif route == "/workspace":
                        result = control.restore_workspace(payload)
                    else:
                        result = control.add_result(
                            payload.get("result_id"), payload.get("tab_id")
                        )
                return web.json_response(
                    {"api_version": API_VERSION, "result": _json_safe(result)},
                    headers={"Cache-Control": "no-store"},
                )
            except ControlError as error:
                return web.json_response(
                    {
                        "api_version": API_VERSION,
                        "error": {"code": error.code, "message": str(error)},
                    },
                    status=error.status,
                    headers={"Cache-Control": "no-store"},
                )
            except Exception:
                logging.getLogger(__name__).exception("Pulsar control operation failed")
                return web.json_response(
                    {
                        "api_version": API_VERSION,
                        "error": {
                            "code": "internal_error",
                            "message": "Pulsar control operation failed; inspect the server log",
                        },
                    },
                    status=500,
                )

        for route in (
            "/context",
            "/catalog",
            "/tabs",
            "/results",
            "/results/{result_id}",
            "/workspace",
        ):
            http_server.app.router.add_get(API_PATH + route, dispatch)
        for route in (
            "/tabs",
            "/visualizations",
            "/results",
            "/result-views",
            "/publications",
            "/workspace",
        ):
            http_server.app.router.add_post(API_PATH + route, dispatch)

    server.controller.on_server_bind.add(on_bind)
    server.controller.on_server_ready.add(on_ready)
    return control
