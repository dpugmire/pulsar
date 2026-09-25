"""Sanitized query, visualization, and workspace learning context."""

import hashlib
import math
from copy import deepcopy
from typing import Any, Dict, Iterable, Mapping, Optional

from pulsar.models.workspace_layout import grid_snapshot, normalized_workspace_root


_MAX_STRING_LENGTH = 1024
_MAX_LIST_LENGTH = 256

_PLOT_SETTING_FIELDS = (
    "x_auto",
    "x_min",
    "x_max",
    "x_scale",
    "y_auto",
    "y_min",
    "y_max",
    "y_scale",
    "line_width",
    "show_grid",
    "show_cursor",
    "background_color",
    "grid_color",
    "cursor_color",
)

_SCALAR_SETTING_FIELDS = (
    "show_heatmap",
    "show_contours",
    "colormap",
    "background",
    "range_auto",
    "range_min",
    "range_max",
    "show_colorbar",
    "show_axes",
    "contour_level_mode",
    "contour_values",
    "contour_min",
    "contour_max",
    "contour_count",
    "contour_color",
)


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float_value(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _json_value(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return None
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value[:_MAX_STRING_LENGTH]
    if isinstance(value, Mapping):
        return {
            str(key)[:128]: _json_value(item, depth + 1)
            for key, item in list(value.items())[:_MAX_LIST_LENGTH]
        }
    if isinstance(value, (list, tuple)):
        return [_json_value(item, depth + 1) for item in value[:_MAX_LIST_LENGTH]]
    return str(value)[:_MAX_STRING_LENGTH]


def stable_fingerprint(value: Any, kind: str = "value") -> str:
    text = str(value or "")
    if not text:
        return ""
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    return f"{kind}:sha256:{digest}"


def _filtered_settings(raw: Any, fields: Iterable[str]) -> Dict[str, Any]:
    source = dict(raw or {}) if isinstance(raw, Mapping) else {}
    return {
        field: _json_value(source[field])
        for field in fields
        if field in source
    }


def sanitized_grid_cell(cell: Any, index: int) -> Dict[str, Any]:
    raw = dict(cell or {}) if isinstance(cell, Mapping) else {}
    visualization = str(
        raw.get("selected_visualization", "")
        or raw.get("visualization_name", "")
        or ""
    )
    source_identity = str(
        raw.get("source_id", "")
        or raw.get("_source_key", "")
        or raw.get("source_dataset", "")
        or ""
    )
    result = {
        "cell_index": _int_value(index, -1),
        "variable_id": str(raw.get("variable_id", "") or "")[:_MAX_STRING_LENGTH],
        "visualization_id": visualization[:_MAX_STRING_LENGTH],
        "source_id": stable_fingerprint(source_identity, "source"),
        "media_type": str(raw.get("media_type", "") or "")[:128],
        "grid_row": _int_value(raw.get("grid_row", 1), 1),
        "grid_column": _int_value(raw.get("grid_col", 1), 1),
        "row_span": _int_value(raw.get("row_span", 1), 1),
        "column_span": _int_value(raw.get("col_span", 1), 1),
        "hidden": bool(raw.get("grid_hidden", False)),
    }
    plot_settings = _filtered_settings(
        raw.get("plot_settings", {}), _PLOT_SETTING_FIELDS
    )
    scalar_settings = _filtered_settings(
        raw.get("scalar_field_settings", {}), _SCALAR_SETTING_FIELDS
    )
    if plot_settings:
        result["plot_settings"] = plot_settings
    if scalar_settings:
        result["scalar_field_settings"] = scalar_settings
    plugin_id = str(raw.get("plugin_id", "") or "")
    if plugin_id:
        result["plugin_id"] = plugin_id[:_MAX_STRING_LENGTH]
    return result


def sanitized_grid(raw_grid: Any) -> Dict[str, Any]:
    grid = dict(raw_grid or {}) if isinstance(raw_grid, Mapping) else {}
    cells = list(grid.get("cells", []) or [])
    return {
        "rows": _int_value(grid.get("rows", 1), 1),
        "columns": _int_value(grid.get("columns", 1), 1),
        "layout_mode": str(grid.get("layout_mode", "uniform") or "uniform"),
        "sizing_mode": str(grid.get("sizing_mode", "static") or "static"),
        "column_sizes": _json_value(grid.get("column_sizes", [])),
        "row_sizes": _json_value(grid.get("row_sizes", [])),
        "column_weights": _json_value(grid.get("column_weights", [])),
        "row_weights": _json_value(grid.get("row_weights", [])),
        "active_cell": _int_value(grid.get("active_cell", -1), -1),
        "timeline_driver_cell": _int_value(
            grid.get("timeline_driver_cell", -1), -1
        ),
        "cells": [sanitized_grid_cell(cell, index) for index, cell in enumerate(cells)],
    }


def _sanitized_root(node: Any) -> Dict[str, Any]:
    raw = dict(node or {}) if isinstance(node, Mapping) else {}
    if str(raw.get("kind", "")) != "split":
        return {
            "kind": "pane",
            "pane_id": str(raw.get("pane_id", "") or ""),
        }
    return {
        "kind": "split",
        "split_id": str(raw.get("id", "") or ""),
        "direction": str(raw.get("direction", "horizontal") or "horizontal"),
        "ratio": _float_value(raw.get("ratio", 0.5), 0.5),
        "first": _sanitized_root(raw.get("first")),
        "second": _sanitized_root(raw.get("second")),
    }


def sanitized_workspace_snapshot(state: Any) -> Dict[str, Any]:
    layout_value = getattr(state, "workspaceLayout", {})
    layout = deepcopy(dict(layout_value or {})) if isinstance(layout_value, Mapping) else {}
    active_pane_id = str(layout.get("active_pane_id", "") or "")
    active_tab_id = str(layout.get("active_tab_id", "") or "")
    live_grid = grid_snapshot(state)

    panes = []
    for pane_position, raw_pane in enumerate(list(layout.get("panes", []) or [])):
        pane = dict(raw_pane or {}) if isinstance(raw_pane, Mapping) else {}
        pane_id = str(pane.get("id", "") or "")
        tabs = []
        for tab_position, raw_tab in enumerate(list(pane.get("tabs", []) or [])):
            tab = dict(raw_tab or {}) if isinstance(raw_tab, Mapping) else {}
            tab_id = str(tab.get("id", "") or "")
            tab_grid = (
                live_grid
                if pane_id == active_pane_id and tab_id == active_tab_id
                else tab.get("grid", {})
            )
            tabs.append(
                {
                    "tab_id": tab_id,
                    "tab_position": tab_position,
                    "grid": sanitized_grid(tab_grid),
                }
            )
        panes.append(
            {
                "pane_id": pane_id,
                "pane_position": pane_position,
                "active_tab_id": str(pane.get("active_tab_id", "") or ""),
                "tabs": tabs,
            }
        )

    return {
        "root": _sanitized_root(normalized_workspace_root(layout)),
        "active_pane_id": active_pane_id,
        "active_tab_id": active_tab_id,
        "panes": panes,
    }


def workspace_location(state: Any, cell_index: Optional[int] = None) -> Dict[str, Any]:
    result = {
        "pane_id": str(getattr(state, "workspaceActivePaneId", "") or ""),
        "tab_id": str(getattr(state, "workspaceActiveTabId", "") or ""),
        "grid_rows": _int_value(getattr(state, "gridRows", 1), 1),
        "grid_columns": _int_value(getattr(state, "gridCols", 1), 1),
    }
    if cell_index is not None:
        result["cell_index"] = _int_value(cell_index, -1)
    return result


def sanitized_query_context(
    state: Any,
    *,
    query_id: str,
    origin: str,
    target: str,
    action_plan: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    plan = (
        dict(action_plan)
        if isinstance(action_plan, Mapping)
        else dict(getattr(state, "activeViewerActionPlan", {}) or {})
    )
    return {
        "query_id": str(query_id or ""),
        "origin": str(origin or "manual"),
        "target": str(target or "catalog"),
        "action_plan": _json_value(plan),
        "query_filter": _json_value(getattr(state, "queryFilter", {}) or {}),
        "source_filters": _json_value(
            getattr(state, "querySourceFilters", []) or []
        ),
        "result_variable_count": len(
            list(getattr(state, "variableNames", []) or [])
        ),
        "result_source_count": _int_value(
            getattr(state, "querySourceRestrictionCount", 0), 0
        ),
    }
