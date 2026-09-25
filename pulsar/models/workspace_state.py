"""Versioned serialization for portable Pulsar workspace state."""

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

from pulsar.models.workspace_layout import (
    MAX_SPLIT_RATIO,
    MAX_WORKSPACE_PANES,
    MIN_SPLIT_RATIO,
    active_pane_and_tab,
    grid_snapshot,
    normalized_workspace_root,
)
from pulsar.models import canvas_layout
from pulsar.models import grid as grid_model
from pulsar.models.grid import DEFAULT_GRID_LAYOUT_MODE, cell_has_content


WORKSPACE_FORMAT = "pulsar-workspace"
WORKSPACE_VERSION = 2
HISTORY_FORMAT = "pulsar-workspace-history"
HISTORY_VERSION = 1

_CELL_FIELDS = (
    "variable_id",
    "variable_name",
    "visualization_name",
    "selected_visualization",
    "source_id",
    "_source_key",
    "_source_keys",
    "_source_fields_list",
    "source_dataset",
    "source_collection_id",
    "source_collection_label",
    "schema_name",
    "schema_file_group",
    "schema_role",
    "schema_mode",
    "producer",
    "casename",
    "file",
    "variable_path",
    "variable_location",
    "metadata",
    "min",
    "max",
    "plot_settings",
    "plugin_id",
    "plugin_label",
    "plugin_scope",
    "plugin_options",
    "scalar_field_settings",
    "grid_row",
    "grid_col",
    "row_span",
    "col_span",
    "grid_hidden",
    "tile_id",
    "tile_type",
    "canvas_x",
    "canvas_y",
    "canvas_w",
    "canvas_h",
)


class WorkspaceStateError(ValueError):
    """Raised when a workspace state document cannot be saved or loaded."""


def _state_value(state, name: str, default: Any) -> Any:
    return getattr(state, name, default)


def _json_copy(value: Any, description: str) -> Any:
    try:
        encoded = json.dumps(value, allow_nan=False)
        return json.loads(encoded)
    except (TypeError, ValueError) as e:
        raise WorkspaceStateError(
            f"{description} is not JSON serializable: {e}"
        ) from e


def _history_copy(value: Any, description: str) -> Any:
    """Return a session-only JSON-shaped copy that preserves NaN/Infinity."""

    try:
        encoded = json.dumps(value, allow_nan=True)
        return json.loads(encoded)
    except (TypeError, ValueError) as e:
        raise WorkspaceStateError(
            f"{description} is not history serializable: {e}"
        ) from e


def _invalid_json_constant(constant: str):
    raise ValueError(f"Invalid JSON number {constant}")


def _cell_state(
    cell: Dict[str, Any], index: int, *, for_history: bool = False
) -> Dict[str, Any]:
    copy_value = _history_copy if for_history else _json_copy
    return {
        field: copy_value(cell[field], f"Grid cell {index + 1} field {field}")
        for field in _CELL_FIELDS
        if field in cell
    }


def _grid_document(
    grid: Dict[str, Any], *, for_history: bool = False
) -> Dict[str, Any]:
    copy_value = _history_copy if for_history else _json_copy
    layout_mode = str(
        grid.get("layout_mode", DEFAULT_GRID_LAYOUT_MODE)
        or DEFAULT_GRID_LAYOUT_MODE
    )
    raw_cells = list(grid.get("cells", []) or [])
    if layout_mode == "freeform":
        raw_cells = [
            cell
            for cell in raw_cells
            if isinstance(cell, dict) and cell_has_content(cell)
        ]
    return {
        "rows": grid.get("rows", 3),
        "columns": grid.get("columns", 3),
        "layout_mode": layout_mode,
        "canvas_columns": grid.get(
            "canvas_columns", canvas_layout.CANVAS_COLUMNS
        ),
        "canvas_row_height": grid.get(
            "canvas_row_height", canvas_layout.CANVAS_ROW_HEIGHT
        ),
        "canvas_snap_to_grid": bool(grid.get("canvas_snap_to_grid", True)),
        "canvas_nudge_others": bool(grid.get("canvas_nudge_others", True)),
        "canvas_show_grid": bool(grid.get("canvas_show_grid", False)),
        "canvas_zoom": canvas_layout.normalize_zoom(
            grid.get("canvas_zoom", canvas_layout.CANVAS_ZOOM_DEFAULT)
        ),
        "canvas_fit_to_view": bool(grid.get("canvas_fit_to_view", False)),
        "sizing_mode": str(grid.get("sizing_mode", "static") or "static"),
        "cell_size": grid.get("cell_size", 300),
        "fit_minimum_cell_size": grid.get("fit_minimum_cell_size", 180),
        "column_sizes": copy_value(
            grid.get("column_sizes", []), "Grid column sizes"
        ),
        "row_sizes": copy_value(grid.get("row_sizes", []), "Grid row sizes"),
        "column_weights": copy_value(
            grid.get("column_weights", []), "Grid column weights"
        ),
        "row_weights": copy_value(
            grid.get("row_weights", []), "Grid row weights"
        ),
        "cells": [
            _cell_state(
                cell if isinstance(cell, dict) else {},
                index,
                for_history=for_history,
            )
            for index, cell in enumerate(raw_cells)
        ],
        "active_cell": grid.get("active_cell", -1),
        "selected_cells": copy_value(
            grid.get("selected_cells", []), "Selected grid cells"
        ),
        "timeline_driver_cell": grid.get("timeline_driver_cell", -1),
    }


def _workspace_document(state, *, for_history: bool = False) -> Dict[str, Any]:
    layout = deepcopy(_state_value(state, "workspaceLayout", {}) or {})
    if not isinstance(layout, dict) or not layout.get("panes"):
        return {}

    _pane, active_tab = active_pane_and_tab(layout)
    if active_tab is not None:
        active_tab["grid"] = grid_snapshot(state)

    panes = []
    for pane_index, pane in enumerate(list(layout.get("panes", []) or [])):
        tabs = []
        for tab_index, tab in enumerate(list(pane.get("tabs", []) or [])):
            grid = tab.get("grid", {})
            if not isinstance(grid, dict):
                grid = {}
            tabs.append(
                {
                    "id": str(tab.get("id", "") or f"tab-{tab_index + 1}"),
                    "title": str(tab.get("title", "") or f"View {tab_index + 1}"),
                    "grid": _grid_document(grid, for_history=for_history),
                }
            )
        panes.append(
            {
                "id": str(pane.get("id", "") or f"pane-{pane_index + 1}"),
                "active_tab_id": str(pane.get("active_tab_id", "") or ""),
                "tabs": tabs,
            }
        )
    return {
        "root": normalized_workspace_root(layout),
        "split_direction": str(
            layout.get("split_direction", "none") or "none"
        ),
        "split_ratio": layout.get("split_ratio", 0.5),
        "active_pane_id": str(layout.get("active_pane_id", "") or ""),
        "active_tab_id": str(layout.get("active_tab_id", "") or ""),
        "panes": panes,
    }


def _history_workspace(state, *, normalize: bool) -> Dict[str, Any]:
    workspace = _workspace_document(state, for_history=True)
    for pane in list(workspace.get("panes", []) or []):
        for tab in list(pane.get("tabs", []) or []):
            grid = dict(tab.get("grid", {}) or {})
            grid.pop("canvas_nudge_others", None)
            grid.pop("canvas_show_grid", None)
            grid.pop("canvas_zoom", None)
            grid.pop("canvas_fit_to_view", None)
            grid.pop("active_cell", None)
            grid.pop("selected_cells", None)
            grid["canvas_snap_to_grid"] = False
            if normalize and str(grid.get("layout_mode", "")) == "freeform":
                normalized = grid_model.normalize_freeform_cells(
                    list(grid.get("cells", []) or []),
                    snap=False,
                    columns=canvas_layout.normalize_columns(
                        grid.get("canvas_columns", canvas_layout.CANVAS_COLUMNS)
                    ),
                )
                grid["cells"] = [
                    _cell_state(cell, index, for_history=True)
                    for index, cell in enumerate(normalized)
                ]
            tab["grid"] = grid
    return workspace


def history_document(state) -> Dict[str, Any]:
    """Return the compact semantic workspace subset used by undo/redo.

    View controls and selection are intentionally omitted.  Geometry is
    validated without snapping so a history entry can preserve fractional
    coordinates even if the user's current snap preference later changes.
    """

    document = {
        "format": HISTORY_FORMAT,
        "version": HISTORY_VERSION,
        "workspace": _history_workspace(state, normalize=True),
    }
    validate_history_document(document)
    return document


def validate_live_history_state(state) -> None:
    """Validate live history-relevant state without repairing its geometry."""

    validate_history_document(
        {
            "format": HISTORY_FORMAT,
            "version": HISTORY_VERSION,
            "workspace": _history_workspace(state, normalize=False),
        }
    )


def validate_history_document(value: Any) -> Dict[str, Any]:
    """Validate and return an in-memory undo/redo snapshot."""

    document = _require_mapping(value, "History snapshot")
    if document.get("format") != HISTORY_FORMAT:
        raise WorkspaceStateError("Unsupported history snapshot format")
    if document.get("version") != HISTORY_VERSION:
        raise WorkspaceStateError(
            "Unsupported history snapshot version: "
            f"{document.get('version')!r}; expected {HISTORY_VERSION}"
        )
    _validate_workspace_layout(document.get("workspace"))
    return _history_copy(document, "History snapshot")


def default_workspace_filename(campaign_path: str) -> str:
    name = Path(str(campaign_path or "")).name
    stem = Path(name).stem if name else "pulsar"
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    return f"{safe_stem or 'pulsar'}.json"


def workspace_document(state, campaign_path: str) -> Dict[str, Any]:
    """Return the durable, semantic subset of the current Trame state."""

    active_grid = _grid_document(grid_snapshot(state))
    campaign_name = Path(str(campaign_path or "")).name
    if not campaign_name:
        raise WorkspaceStateError("Cannot save state without a campaign name")

    return {
        "format": WORKSPACE_FORMAT,
        "version": WORKSPACE_VERSION,
        "campaign": {
            "name": campaign_name,
        },
        "state": {
            "catalog": {
                "variable_pane_view": str(
                    _state_value(state, "variablePaneView", "variables")
                    or "variables"
                ),
                "variable_group_collapsed_by_view": _json_copy(
                    _state_value(
                        state,
                        "variableGroupCollapsedByView",
                        {"variables": {}, "files": {}},
                    ),
                    "Variable group state",
                ),
                "show_only_visualized_variables": bool(
                    _state_value(state, "showOnlyVisualizedVars", False)
                ),
                "selected_variable": str(
                    _state_value(state, "selectedVar", "") or ""
                ),
                "query_text": str(_state_value(state, "queryText", "") or ""),
                "viewer_action": _json_copy(
                    _state_value(state, "activeViewerActionPlan", {}),
                    "Active viewer action",
                ),
                "natural_language_query": str(
                    _state_value(state, "activeNaturalLanguageQuery", "") or ""
                ),
            },
            "grid": active_grid,
            "workspace": _workspace_document(state),
            "visualization": {
                "scalar_plot_policy": str(
                    _state_value(state, "scalarPlotPolicy", "always") or "always"
                ),
                "canvas_default_tile_width": canvas_layout.normalize_drop_width(
                    _state_value(
                        state,
                        "canvasDefaultTileWidth",
                        canvas_layout.CANVAS_DEFAULT_DROP_WIDTH,
                    )
                ),
            },
        },
    }


def workspace_json(state, campaign_path: str) -> str:
    try:
        return (
            json.dumps(
                workspace_document(state, campaign_path),
                allow_nan=False,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
    except (TypeError, ValueError) as e:
        raise WorkspaceStateError(
            f"Workspace state is not JSON serializable: {e}"
        ) from e


def _require_mapping(value: Any, description: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise WorkspaceStateError(f"{description} must be a JSON object")
    return value


def parse_workspace_document(content: Any) -> Dict[str, Any]:
    """Parse and validate the outer structure of a workspace JSON document."""

    if isinstance(content, bytes):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as e:
            raise WorkspaceStateError("State file must be UTF-8 JSON") from e
    elif isinstance(content, str):
        text = content
    else:
        raise WorkspaceStateError("State file content must be text or bytes")

    try:
        value = json.loads(
            text,
            parse_constant=_invalid_json_constant,
        )
    except (json.JSONDecodeError, ValueError) as e:
        raise WorkspaceStateError(f"Invalid JSON: {e}") from e

    document = _require_mapping(value, "State file")
    if document.get("format") != WORKSPACE_FORMAT:
        raise WorkspaceStateError(
            f'Unsupported state format: {document.get("format")!r}'
        )
    if document.get("version") != WORKSPACE_VERSION:
        raise WorkspaceStateError(
            "Unsupported state version: "
            f"{document.get('version')!r}; expected {WORKSPACE_VERSION}"
        )

    campaign = _require_mapping(document.get("campaign"), "campaign")
    campaign_name = campaign.get("name")
    if not isinstance(campaign_name, str) or not campaign_name.strip():
        raise WorkspaceStateError("campaign.name must be a non-empty string")

    saved_state = _require_mapping(document.get("state"), "state")
    _require_mapping(saved_state.get("catalog"), "state.catalog")
    grid = _require_mapping(saved_state.get("grid"), "state.grid")
    _require_mapping(saved_state.get("visualization"), "state.visualization")

    _validate_grid_document(grid, "state.grid")
    workspace = saved_state.get("workspace")
    if workspace is not None:
        _validate_workspace_layout(workspace)

    return document


def _validate_grid_document(grid: Any, description: str) -> None:
    grid = _require_mapping(grid, description)
    cells = grid.get("cells")
    if not isinstance(cells, list):
        raise WorkspaceStateError(f"{description}.cells must be a JSON array")
    layout_mode = str(
        grid.get("layout_mode", DEFAULT_GRID_LAYOUT_MODE)
        or DEFAULT_GRID_LAYOUT_MODE
    )
    limit = canvas_layout.CANVAS_MAX_TILES if layout_mode == "freeform" else 64
    if len(cells) > limit:
        label = (
            f"{limit}-tile limit"
            if layout_mode == "freeform"
            else "8x8 grid limit"
        )
        raise WorkspaceStateError(f"{description}.cells exceeds the {label}")
    for index, cell in enumerate(cells):
        if not isinstance(cell, dict):
            raise WorkspaceStateError(
                f"{description}.cells[{index}] must be a JSON object"
            )
    if layout_mode == "freeform":
        columns = canvas_layout.normalize_columns(
            grid.get("canvas_columns", canvas_layout.CANVAS_COLUMNS)
        )
        geometries = [
            canvas_layout.geometry_from_cell(
                cell,
                fallback_id="",
                fallback_index=index,
                snap=bool(grid.get("canvas_snap_to_grid", True)),
                columns=columns,
            )
            for index, cell in enumerate(cells)
        ]
        valid, message = canvas_layout.validate_layout(
            geometries, columns=columns
        )
        if not valid:
            raise WorkspaceStateError(f"{description}: {message}")


def _validate_workspace_layout(value: Any) -> None:
    workspace = _require_mapping(value, "state.workspace")
    panes = workspace.get("panes")
    if not isinstance(panes, list) or not 1 <= len(panes) <= MAX_WORKSPACE_PANES:
        raise WorkspaceStateError(
            f"state.workspace.panes must contain one to {MAX_WORKSPACE_PANES} panes"
        )
    pane_ids = set()
    tab_ids = set()
    active_tab_by_pane = {}
    total_tabs = 0
    for pane_index, pane_value in enumerate(panes):
        pane = _require_mapping(
            pane_value, f"state.workspace.panes[{pane_index}]"
        )
        pane_id = pane.get("id")
        if not isinstance(pane_id, str) or not pane_id or pane_id in pane_ids:
            raise WorkspaceStateError("Workspace pane IDs must be unique strings")
        pane_ids.add(pane_id)
        tabs = pane.get("tabs")
        if not isinstance(tabs, list) or not tabs:
            raise WorkspaceStateError("Each workspace pane must contain a tab")
        total_tabs += len(tabs)
        pane_tab_ids = set()
        for tab_index, tab_value in enumerate(tabs):
            tab = _require_mapping(
                tab_value,
                f"state.workspace.panes[{pane_index}].tabs[{tab_index}]",
            )
            tab_id = tab.get("id")
            if not isinstance(tab_id, str) or not tab_id or tab_id in tab_ids:
                raise WorkspaceStateError("Workspace tab IDs must be unique strings")
            tab_ids.add(tab_id)
            pane_tab_ids.add(tab_id)
            _validate_grid_document(
                tab.get("grid"),
                f"state.workspace.panes[{pane_index}].tabs[{tab_index}].grid",
            )
        pane_active_tab = pane.get("active_tab_id")
        if pane_active_tab not in pane_tab_ids:
            raise WorkspaceStateError(
                "Each workspace pane active_tab_id must reference one of its tabs"
            )
        active_tab_by_pane[pane_id] = pane_active_tab

    if total_tabs > 64:
        raise WorkspaceStateError("state.workspace exceeds the 64 tab limit")

    active_pane_id = workspace.get("active_pane_id")
    active_tab_id = workspace.get("active_tab_id")
    if active_pane_id not in pane_ids:
        raise WorkspaceStateError("state.workspace.active_pane_id is not present")
    if active_tab_id not in tab_ids:
        raise WorkspaceStateError("state.workspace.active_tab_id is not present")
    if active_tab_by_pane.get(active_pane_id) != active_tab_id:
        raise WorkspaceStateError(
            "state.workspace.active_tab_id must belong to the active pane"
        )

    root = workspace.get("root")
    if root is None and len(panes) > 2:
        raise WorkspaceStateError(
            "state.workspace.root is required for more than two panes"
        )
    if root is not None:
        split_ids = set()
        leaf_ids = []

        def validate_node(node_value: Any, description: str) -> None:
            node = _require_mapping(node_value, description)
            kind = node.get("kind")
            if kind == "pane":
                pane_id = node.get("pane_id")
                if not isinstance(pane_id, str) or not pane_id:
                    raise WorkspaceStateError(
                        f"{description}.pane_id must be a non-empty string"
                    )
                leaf_ids.append(pane_id)
                return
            if kind != "split":
                raise WorkspaceStateError(
                    f"{description}.kind must be pane or split"
                )
            split_id = node.get("id")
            if (
                not isinstance(split_id, str)
                or not split_id
                or split_id in split_ids
            ):
                raise WorkspaceStateError(
                    "Workspace split IDs must be unique strings"
                )
            split_ids.add(split_id)
            if len(split_ids) >= MAX_WORKSPACE_PANES:
                raise WorkspaceStateError(
                    "state.workspace.root exceeds the split limit"
                )
            if node.get("direction") not in {"horizontal", "vertical"}:
                raise WorkspaceStateError(
                    f"{description}.direction must be horizontal or vertical"
                )
            ratio = node.get("ratio")
            if (
                isinstance(ratio, bool)
                or not isinstance(ratio, (int, float))
                or not MIN_SPLIT_RATIO <= float(ratio) <= MAX_SPLIT_RATIO
            ):
                raise WorkspaceStateError(
                    f"{description}.ratio must be between "
                    f"{MIN_SPLIT_RATIO:g} and {MAX_SPLIT_RATIO:g}"
                )
            validate_node(node.get("first"), f"{description}.first")
            validate_node(node.get("second"), f"{description}.second")

        validate_node(root, "state.workspace.root")
        if len(leaf_ids) != len(set(leaf_ids)) or set(leaf_ids) != pane_ids:
            raise WorkspaceStateError(
                "state.workspace.root must reference each pane exactly once"
            )


def validate_workspace_campaign(
    document: Dict[str, Any], campaign_path: str
) -> None:
    saved_name = str(document.get("campaign", {}).get("name", "") or "")
    current_name = Path(str(campaign_path or "")).name
    if saved_name != current_name:
        raise WorkspaceStateError(
            f'State file is for campaign "{saved_name}", '
            f'not "{current_name or campaign_path}"'
        )
