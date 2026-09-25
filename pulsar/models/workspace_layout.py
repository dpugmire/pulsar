"""Pure helpers for Pulsar's constrained pane, tab, and grid workspace."""

from copy import deepcopy
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from pulsar.models.grid import (
    DEFAULT_GRID_LAYOUT_MODE,
    assign_cell,
    cell_has_content,
    empty_grid_cell,
)


MAX_WORKSPACE_PANES = 4
MIN_SPLIT_RATIO = 0.15
MAX_SPLIT_RATIO = 0.85
DEFAULT_PANE_ID = "pane-1"
DEFAULT_TAB_ID = "tab-1"
DEFAULT_TAB_TITLE = "View 1"


GRID_STATE_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("gridRows", "rows"),
    ("gridCols", "columns"),
    ("gridLayoutMode", "layout_mode"),
    ("canvasCols", "canvas_columns"),
    ("canvasRowHeight", "canvas_row_height"),
    ("canvasSnapToGrid", "canvas_snap_to_grid"),
    ("canvasNudgeOthers", "canvas_nudge_others"),
    ("canvasShowGrid", "canvas_show_grid"),
    ("canvasZoom", "canvas_zoom"),
    ("canvasFitToView", "canvas_fit_to_view"),
    ("canvasDwellMs", "canvas_dwell_ms"),
    ("canvasSnapDeadZone", "canvas_snap_dead_zone"),
    ("canvasTransitionMs", "canvas_transition_ms"),
    ("canvasLayoutRevision", "canvas_layout_revision"),
    ("gridSizingMode", "sizing_mode"),
    ("gridCellSize", "cell_size"),
    ("gridMinCellSize", "minimum_cell_size"),
    ("gridMaxCellSize", "maximum_cell_size"),
    ("gridFitMinCellSize", "fit_minimum_cell_size"),
    ("gridMaxFitMinCellSize", "fit_maximum_cell_size"),
    ("gridColumnSizes", "column_sizes"),
    ("gridRowSizes", "row_sizes"),
    ("gridColumnWeights", "column_weights"),
    ("gridRowWeights", "row_weights"),
    ("gridColumnTemplate", "column_template"),
    ("gridRowTemplate", "row_template"),
    ("gridFitColumnTemplate", "fit_column_template"),
    ("gridFitRowTemplate", "fit_row_template"),
    ("gridCells", "cells"),
    ("activeGridCell", "active_cell"),
    ("selectedGridCellIndices", "selected_cells"),
    ("selectedGridCellMap", "selected_cell_map"),
    ("timelineDriverCell", "timeline_driver_cell"),
)


def grid_snapshot(state: Any) -> Dict[str, Any]:
    """Copy the complete renderable grid state from a Trame state object."""

    return {
        key: deepcopy(getattr(state, state_name, None))
        for state_name, key in GRID_STATE_FIELDS
    }


def apply_grid_snapshot(state: Any, snapshot: Mapping[str, Any]) -> None:
    """Load a grid snapshot into the legacy active-grid state fields."""

    for state_name, key in GRID_STATE_FIELDS:
        if key in snapshot:
            setattr(state, state_name, deepcopy(snapshot[key]))


def empty_grid_snapshot(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """Return an empty grid using the application's default layout mode."""

    result = deepcopy(dict(snapshot))
    try:
        rows = max(1, min(8, int(result.get("rows", 3))))
    except Exception:
        rows = 3
    try:
        columns = max(1, min(8, int(result.get("columns", 3))))
    except Exception:
        columns = 3
    result["rows"] = rows
    result["columns"] = columns
    result["layout_mode"] = DEFAULT_GRID_LAYOUT_MODE
    result["cells"] = (
        []
        if str(
            result.get("layout_mode", DEFAULT_GRID_LAYOUT_MODE)
            or DEFAULT_GRID_LAYOUT_MODE
        )
        == "freeform"
        else [empty_grid_cell() for _ in range(rows * columns)]
    )
    result["active_cell"] = -1
    result["selected_cells"] = []
    result["selected_cell_map"] = {}
    result["timeline_driver_cell"] = -1
    return result


def initial_workspace_layout(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "split_direction": "none",
        "split_ratio": 0.5,
        "root": {"kind": "pane", "pane_id": DEFAULT_PANE_ID},
        "active_pane_id": DEFAULT_PANE_ID,
        "active_tab_id": DEFAULT_TAB_ID,
        "panes": [
            {
                "id": DEFAULT_PANE_ID,
                "active_tab_id": DEFAULT_TAB_ID,
                "tabs": [
                    {
                        "id": DEFAULT_TAB_ID,
                        "title": DEFAULT_TAB_TITLE,
                        "grid": deepcopy(dict(snapshot)),
                    }
                ],
            }
        ],
    }


def _split_ratio(value: Any) -> float:
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        ratio = 0.5
    return max(MIN_SPLIT_RATIO, min(MAX_SPLIT_RATIO, ratio))


def _pane_leaf(pane_id: str) -> Dict[str, Any]:
    return {"kind": "pane", "pane_id": str(pane_id or "")}


def _legacy_workspace_root(layout: Mapping[str, Any]) -> Dict[str, Any]:
    panes = list(layout.get("panes", []) or [])
    if not panes:
        return _pane_leaf(DEFAULT_PANE_ID)
    if len(panes) == 1:
        return _pane_leaf(str(panes[0].get("id", "") or DEFAULT_PANE_ID))
    direction = (
        "vertical"
        if str(layout.get("split_direction", "")) == "vertical"
        else "horizontal"
    )
    return {
        "kind": "split",
        "id": "split-1",
        "direction": direction,
        "ratio": _split_ratio(layout.get("split_ratio", 0.5)),
        "first": _pane_leaf(str(panes[0].get("id", ""))),
        "second": _pane_leaf(str(panes[1].get("id", ""))),
    }


def normalized_workspace_root(layout: Mapping[str, Any]) -> Dict[str, Any]:
    root = layout.get("root")
    if not isinstance(root, Mapping):
        return _legacy_workspace_root(layout)

    def normalize(node: Any) -> Dict[str, Any]:
        if not isinstance(node, Mapping) or str(node.get("kind", "")) != "split":
            pane_id = str(node.get("pane_id", "") if isinstance(node, Mapping) else "")
            return _pane_leaf(pane_id)
        return {
            "kind": "split",
            "id": str(node.get("id", "") or "split"),
            "direction": (
                "vertical"
                if str(node.get("direction", "")) == "vertical"
                else "horizontal"
            ),
            "ratio": _split_ratio(node.get("ratio", 0.5)),
            "first": normalize(node.get("first")),
            "second": normalize(node.get("second")),
        }

    return normalize(root)


def workspace_pane_ids(layout: Mapping[str, Any]) -> Tuple[str, ...]:
    result = []

    def visit(node: Mapping[str, Any]) -> None:
        if node.get("kind") == "split":
            visit(node["first"])
            visit(node["second"])
        else:
            result.append(str(node.get("pane_id", "") or ""))

    visit(normalized_workspace_root(layout))
    return tuple(result)


def workspace_geometry(
    layout: Mapping[str, Any],
) -> Tuple[Dict[str, Dict[str, float]], Tuple[Dict[str, Any], ...]]:
    """Return normalized pane frames and split-handle geometry in percentages."""

    panes: Dict[str, Dict[str, float]] = {}
    splitters = []

    def visit(
        node: Mapping[str, Any], left: float, top: float, width: float, height: float
    ) -> None:
        if node.get("kind") != "split":
            panes[str(node.get("pane_id", "") or "")] = {
                "left": left,
                "top": top,
                "width": width,
                "height": height,
            }
            return
        ratio = _split_ratio(node.get("ratio", 0.5))
        direction = str(node.get("direction", "horizontal"))
        descriptor = {
            "id": str(node.get("id", "") or "split"),
            "direction": direction,
            "ratio": ratio,
            "container_left": left,
            "container_top": top,
            "container_width": width,
            "container_height": height,
        }
        if direction == "vertical":
            boundary = top + height * ratio
            descriptor.update(
                {
                    "left": left,
                    "top": boundary,
                    "span": width,
                }
            )
            visit(node["first"], left, top, width, height * ratio)
            visit(
                node["second"],
                left,
                boundary,
                width,
                height * (1.0 - ratio),
            )
        else:
            boundary = left + width * ratio
            descriptor.update(
                {
                    "left": boundary,
                    "top": top,
                    "span": height,
                }
            )
            visit(node["first"], left, top, width * ratio, height)
            visit(
                node["second"],
                boundary,
                top,
                width * (1.0 - ratio),
                height,
            )
        splitters.append(descriptor)

    visit(normalized_workspace_root(layout), 0.0, 0.0, 100.0, 100.0)
    return panes, tuple(splitters)


def _set_workspace_root(layout: Dict[str, Any], root: Mapping[str, Any]) -> None:
    normalized = normalized_workspace_root({"root": root})
    layout["root"] = normalized
    if normalized.get("kind") == "split":
        layout["split_direction"] = normalized["direction"]
        layout["split_ratio"] = normalized["ratio"]
    else:
        layout["split_direction"] = "none"
        layout["split_ratio"] = 0.5


def _replace_pane_leaf(
    node: Mapping[str, Any], pane_id: str, replacement: Mapping[str, Any]
) -> Tuple[Dict[str, Any], bool]:
    if node.get("kind") != "split":
        if str(node.get("pane_id", "")) == str(pane_id or ""):
            return deepcopy(dict(replacement)), True
        return deepcopy(dict(node)), False
    first, replaced = _replace_pane_leaf(node["first"], pane_id, replacement)
    if replaced:
        result = deepcopy(dict(node))
        result["first"] = first
        return result, True
    second, replaced = _replace_pane_leaf(node["second"], pane_id, replacement)
    result = deepcopy(dict(node))
    result["second"] = second
    return result, replaced


def _split_ids(node: Mapping[str, Any]) -> Tuple[str, ...]:
    if node.get("kind") != "split":
        return ()
    return (
        str(node.get("id", "") or ""),
        *_split_ids(node["first"]),
        *_split_ids(node["second"]),
    )


def _first_pane_id(node: Mapping[str, Any]) -> str:
    if node.get("kind") != "split":
        return str(node.get("pane_id", "") or "")
    return _first_pane_id(node["first"])


def _remove_pane_leaf(
    node: Mapping[str, Any], pane_id: str
) -> Tuple[Dict[str, Any], Optional[str], bool]:
    if node.get("kind") != "split":
        return deepcopy(dict(node)), None, False
    first = node["first"]
    second = node["second"]
    if first.get("kind") != "split" and str(first.get("pane_id", "")) == str(
        pane_id or ""
    ):
        return deepcopy(dict(second)), _first_pane_id(second), True
    if second.get("kind") != "split" and str(second.get("pane_id", "")) == str(
        pane_id or ""
    ):
        return deepcopy(dict(first)), _first_pane_id(first), True
    replaced_first, destination, removed = _remove_pane_leaf(first, pane_id)
    if removed:
        result = deepcopy(dict(node))
        result["first"] = replaced_first
        return result, destination, True
    replaced_second, destination, removed = _remove_pane_leaf(second, pane_id)
    result = deepcopy(dict(node))
    result["second"] = replaced_second
    return result, destination, removed


def _ordered_panes(
    panes: Iterable[Mapping[str, Any]], root: Mapping[str, Any]
) -> list:
    by_id = {str(pane.get("id", "")): pane for pane in panes}
    order = workspace_pane_ids({"root": root})
    return [by_id[pane_id] for pane_id in order if pane_id in by_id]


def _next_identifier(prefix: str, identifiers: Iterable[str]) -> str:
    used = {str(value or "") for value in identifiers}
    index = 1
    while f"{prefix}-{index}" in used:
        index += 1
    return f"{prefix}-{index}"


def pane_and_tab(
    layout: Mapping[str, Any], pane_id: str, tab_id: str
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    for pane in list(layout.get("panes", []) or []):
        if str(pane.get("id", "")) != str(pane_id or ""):
            continue
        for tab in list(pane.get("tabs", []) or []):
            if str(tab.get("id", "")) == str(tab_id or ""):
                return pane, tab
        return pane, None
    return None, None


def active_pane_and_tab(
    layout: Mapping[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    return pane_and_tab(
        layout,
        str(layout.get("active_pane_id", "") or ""),
        str(layout.get("active_tab_id", "") or ""),
    )


def normalized_tab_title(value: Any, fallback: str) -> str:
    title = " ".join(str(value or "").split())
    return (title or fallback)[:80]


def add_workspace_tab(
    layout: Mapping[str, Any], pane_id: str, snapshot: Mapping[str, Any]
) -> Tuple[Dict[str, Any], str]:
    result = deepcopy(dict(layout))
    panes = list(result.get("panes", []) or [])
    tab_ids = [
        str(tab.get("id", ""))
        for pane in panes
        for tab in list(pane.get("tabs", []) or [])
    ]
    tab_id = _next_identifier("tab", tab_ids)
    title = f"View {len(tab_ids) + 1}"
    target = next(
        (pane for pane in panes if str(pane.get("id", "")) == str(pane_id)),
        panes[0] if panes else None,
    )
    if target is None:
        return initial_workspace_layout(snapshot), DEFAULT_TAB_ID
    target.setdefault("tabs", []).append(
        {
            "id": tab_id,
            "title": title,
            "grid": empty_grid_snapshot(snapshot),
        }
    )
    target["active_tab_id"] = tab_id
    result["active_pane_id"] = target["id"]
    result["active_tab_id"] = tab_id
    result["panes"] = panes
    return result, tab_id


def split_workspace(
    layout: Mapping[str, Any],
    direction: str,
    snapshot: Mapping[str, Any],
    pane_id: str = "",
) -> Tuple[Dict[str, Any], Optional[str]]:
    result = deepcopy(dict(layout))
    panes = list(result.get("panes", []) or [])
    if len(panes) >= MAX_WORKSPACE_PANES:
        return result, None

    root = normalized_workspace_root(result)
    target_pane_id = str(pane_id or result.get("active_pane_id", "") or "")
    if target_pane_id not in workspace_pane_ids({"root": root}):
        return result, None

    pane_ids = [str(pane.get("id", "")) for pane in panes]
    tab_ids = [
        str(tab.get("id", ""))
        for pane in panes
        for tab in list(pane.get("tabs", []) or [])
    ]
    new_pane_id = _next_identifier("pane", pane_ids)
    tab_id = _next_identifier("tab", tab_ids)
    new_pane = {
        "id": new_pane_id,
        "active_tab_id": tab_id,
        "tabs": [
            {
                "id": tab_id,
                "title": f"View {len(tab_ids) + 1}",
                "grid": empty_grid_snapshot(snapshot),
            }
        ],
    }
    panes.append(new_pane)
    split_id = _next_identifier("split", _split_ids(root))
    replacement = {
        "kind": "split",
        "id": split_id,
        "direction": (
            "vertical" if str(direction) == "vertical" else "horizontal"
        ),
        "ratio": 0.5,
        "first": _pane_leaf(target_pane_id),
        "second": _pane_leaf(new_pane_id),
    }
    root, replaced = _replace_pane_leaf(root, target_pane_id, replacement)
    if not replaced:
        return result, None
    result["panes"] = _ordered_panes(panes, root)
    _set_workspace_root(result, root)
    result["active_pane_id"] = new_pane_id
    result["active_tab_id"] = tab_id
    return result, new_pane_id


def split_workspace_tab(
    layout: Mapping[str, Any],
    direction: str,
    snapshot: Mapping[str, Any],
    source_pane_id: str,
    tab_id: str,
    target_pane_id: str = "",
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Move a tab into a new pane split from an existing pane."""

    result = deepcopy(dict(layout))
    panes = list(result.get("panes", []) or [])
    if len(panes) >= MAX_WORKSPACE_PANES:
        return result, None

    root = normalized_workspace_root(result)
    target_id = str(target_pane_id or source_pane_id or "")
    if target_id not in workspace_pane_ids({"root": root}):
        return result, None

    source = next(
        (
            pane
            for pane in panes
            if str(pane.get("id", "")) == str(source_pane_id or "")
        ),
        None,
    )
    if source is None:
        return result, None
    source_tabs = list(source.get("tabs", []) or [])
    tab_index = next(
        (
            index
            for index, tab in enumerate(source_tabs)
            if str(tab.get("id", "")) == str(tab_id or "")
        ),
        -1,
    )
    if tab_index < 0:
        return result, None

    pane_ids = [str(pane.get("id", "")) for pane in panes]
    tab_ids = [
        str(tab.get("id", ""))
        for pane in panes
        for tab in list(pane.get("tabs", []) or [])
    ]
    moved_tab = source_tabs.pop(tab_index)
    if source_tabs:
        source["tabs"] = source_tabs
        if str(source.get("active_tab_id", "")) == str(tab_id or ""):
            source["active_tab_id"] = source_tabs[
                min(tab_index, len(source_tabs) - 1)
            ]["id"]
    else:
        replacement_tab_id = _next_identifier("tab", tab_ids)
        replacement_tab = {
            "id": replacement_tab_id,
            "title": f"View {len(tab_ids) + 1}",
            "grid": empty_grid_snapshot(snapshot),
        }
        source["tabs"] = [replacement_tab]
        source["active_tab_id"] = replacement_tab_id

    new_pane_id = _next_identifier("pane", pane_ids)
    panes.append(
        {
            "id": new_pane_id,
            "active_tab_id": moved_tab["id"],
            "tabs": [moved_tab],
        }
    )
    split_id = _next_identifier("split", _split_ids(root))
    replacement = {
        "kind": "split",
        "id": split_id,
        "direction": (
            "vertical" if str(direction) == "vertical" else "horizontal"
        ),
        "ratio": 0.5,
        "first": _pane_leaf(target_id),
        "second": _pane_leaf(new_pane_id),
    }
    root, replaced = _replace_pane_leaf(root, target_id, replacement)
    if not replaced:
        return deepcopy(dict(layout)), None
    result["panes"] = _ordered_panes(panes, root)
    _set_workspace_root(result, root)
    result["active_pane_id"] = new_pane_id
    result["active_tab_id"] = moved_tab["id"]
    return result, new_pane_id


def close_workspace_tab(
    layout: Mapping[str, Any], pane_id: str, tab_id: str
) -> Dict[str, Any]:
    result = deepcopy(dict(layout))
    panes = list(result.get("panes", []) or [])
    total_tabs = sum(len(list(pane.get("tabs", []) or [])) for pane in panes)
    if total_tabs <= 1:
        return result

    target = next(
        (pane for pane in panes if str(pane.get("id", "")) == str(pane_id)),
        None,
    )
    if target is None:
        return result
    tabs = list(target.get("tabs", []) or [])
    removed_index = next(
        (i for i, tab in enumerate(tabs) if str(tab.get("id", "")) == str(tab_id)),
        -1,
    )
    if removed_index < 0:
        return result
    del tabs[removed_index]
    if tabs:
        target["tabs"] = tabs
        if str(target.get("active_tab_id", "")) == str(tab_id):
            target["active_tab_id"] = tabs[min(removed_index, len(tabs) - 1)]["id"]
    else:
        root, _destination, removed = _remove_pane_leaf(
            normalized_workspace_root(result), str(target.get("id", ""))
        )
        if not removed:
            return result
        panes = [pane for pane in panes if pane is not target]
        _set_workspace_root(result, root)

    if not panes:
        return result
    active_pane = next(
        (
            pane
            for pane in panes
            if str(pane.get("id", ""))
            == str(result.get("active_pane_id", ""))
        ),
        panes[0],
    )
    active_tab_id = str(active_pane.get("active_tab_id", "") or "")
    if not any(
        str(tab.get("id", "")) == active_tab_id
        for tab in list(active_pane.get("tabs", []) or [])
    ):
        active_tab_id = str(active_pane["tabs"][0]["id"])
        active_pane["active_tab_id"] = active_tab_id
    result["panes"] = _ordered_panes(panes, normalized_workspace_root(result))
    result["active_pane_id"] = active_pane["id"]
    result["active_tab_id"] = active_tab_id
    return result


def close_workspace_pane(
    layout: Mapping[str, Any], pane_id: str
) -> Dict[str, Any]:
    result = deepcopy(dict(layout))
    panes = list(result.get("panes", []) or [])
    if len(panes) <= 1:
        return result
    closing = next(
        (pane for pane in panes if str(pane.get("id", "")) == str(pane_id)),
        None,
    )
    if closing is None:
        return result
    root, destination_id, removed = _remove_pane_leaf(
        normalized_workspace_root(result), pane_id
    )
    if not removed or not destination_id:
        return result
    destination = next(
        (
            pane
            for pane in panes
            if str(pane.get("id", "")) == str(destination_id)
        ),
        None,
    )
    if destination is None:
        return result
    destination.setdefault("tabs", []).extend(list(closing.get("tabs", []) or []))
    panes = [pane for pane in panes if pane is not closing]
    result["panes"] = _ordered_panes(panes, root)
    _set_workspace_root(result, root)
    if str(result.get("active_pane_id", "")) == str(pane_id):
        result["active_pane_id"] = destination["id"]
        result["active_tab_id"] = destination["active_tab_id"]
    return result


def move_workspace_tab(
    layout: Mapping[str, Any], pane_id: str, tab_id: str
) -> Dict[str, Any]:
    panes = list(layout.get("panes", []) or [])
    if len(panes) < 2:
        return deepcopy(dict(layout))
    source = next(
        (pane for pane in panes if str(pane.get("id", "")) == str(pane_id)),
        None,
    )
    if source is None:
        return deepcopy(dict(layout))
    ordered_ids = workspace_pane_ids(layout)
    source_order = ordered_ids.index(str(source.get("id", "")))
    destination_id = ordered_ids[(source_order + 1) % len(ordered_ids)]
    return move_workspace_tab_to_pane(
        layout,
        pane_id,
        tab_id,
        destination_id,
    )


def move_workspace_tab_to_pane(
    layout: Mapping[str, Any],
    source_pane_id: str,
    tab_id: str,
    destination_pane_id: str,
    insertion_index: Optional[int] = None,
) -> Dict[str, Any]:
    """Move a tab to a specific insertion slot in another pane."""

    if str(source_pane_id) == str(destination_pane_id):
        if insertion_index is None:
            return deepcopy(dict(layout))
        return reorder_workspace_tab(
            layout, source_pane_id, tab_id, insertion_index
        )

    result = deepcopy(dict(layout))
    panes = list(result.get("panes", []) or [])
    if len(panes) < 2:
        return result
    source = next(
        (
            pane
            for pane in panes
            if str(pane.get("id", "")) == str(source_pane_id)
        ),
        None,
    )
    destination = next(
        (
            pane
            for pane in panes
            if str(pane.get("id", "")) == str(destination_pane_id)
        ),
        None,
    )
    if source is None or destination is None:
        return result

    tabs = list(source.get("tabs", []) or [])
    tab_index = next(
        (i for i, tab in enumerate(tabs) if str(tab.get("id", "")) == str(tab_id)),
        -1,
    )
    if tab_index < 0:
        return result
    tab = tabs.pop(tab_index)
    destination_tabs = list(destination.get("tabs", []) or [])
    if insertion_index is None:
        destination_index = len(destination_tabs)
    else:
        try:
            destination_index = max(
                0, min(len(destination_tabs), int(insertion_index))
            )
        except (TypeError, ValueError):
            return result
    destination_tabs.insert(destination_index, tab)
    destination["tabs"] = destination_tabs
    destination["active_tab_id"] = tab["id"]
    if tabs:
        source["tabs"] = tabs
        if str(source.get("active_tab_id", "")) == str(tab_id):
            source["active_tab_id"] = tabs[min(tab_index, len(tabs) - 1)]["id"]
    else:
        root, _promoted_id, removed = _remove_pane_leaf(
            normalized_workspace_root(result), str(source_pane_id)
        )
        if removed:
            panes = [pane for pane in panes if pane is not source]
            _set_workspace_root(result, root)
    result["panes"] = _ordered_panes(panes, normalized_workspace_root(result))
    result["active_pane_id"] = destination["id"]
    result["active_tab_id"] = tab["id"]
    return result


def move_workspace_grid_cell(
    layout: Mapping[str, Any],
    source_pane_id: str,
    source_tab_id: str,
    source_index: int,
    destination_pane_id: str,
    destination_tab_id: str,
    destination_index: int,
) -> Dict[str, Any]:
    """Move one visualization between tab-owned grid snapshots."""

    result = deepcopy(dict(layout))
    source_pane, source_tab = pane_and_tab(
        result, source_pane_id, source_tab_id
    )
    destination_pane, destination_tab = pane_and_tab(
        result, destination_pane_id, destination_tab_id
    )
    if (
        source_pane is None
        or source_tab is None
        or destination_pane is None
        or destination_tab is None
        or source_tab is destination_tab
    ):
        return result

    try:
        source_cell_index = int(source_index)
        destination_cell_index = int(destination_index)
    except (TypeError, ValueError):
        return result

    source_grid = source_tab.get("grid", {})
    destination_grid = destination_tab.get("grid", {})
    if not isinstance(source_grid, dict) or not isinstance(destination_grid, dict):
        return result
    source_cells = [
        dict(cell) if isinstance(cell, dict) else empty_grid_cell()
        for cell in list(source_grid.get("cells", []) or [])
    ]
    destination_cells = [
        dict(cell) if isinstance(cell, dict) else empty_grid_cell()
        for cell in list(destination_grid.get("cells", []) or [])
    ]
    if not (
        0 <= source_cell_index < len(source_cells)
        and 0 <= destination_cell_index < len(destination_cells)
    ):
        return result
    source_cell = source_cells[source_cell_index]
    if not cell_has_content(source_cell):
        return result

    assign_cell(destination_cells, destination_cell_index, source_cell)
    assign_cell(source_cells, source_cell_index, empty_grid_cell())
    source_grid["cells"] = source_cells
    destination_grid["cells"] = destination_cells

    source_selected = [
        int(index)
        for index in list(source_grid.get("selected_cells", []) or [])
        if str(index).lstrip("-").isdigit()
        and int(index) != source_cell_index
    ]
    source_grid["selected_cells"] = source_selected
    source_grid["selected_cell_map"] = {
        str(index): True for index in source_selected
    }
    try:
        source_active = int(source_grid.get("active_cell", -1))
    except (TypeError, ValueError):
        source_active = -1
    if source_active == source_cell_index:
        source_grid["active_cell"] = -1

    destination_grid["active_cell"] = destination_cell_index
    destination_grid["selected_cells"] = [destination_cell_index]
    destination_grid["selected_cell_map"] = {
        str(destination_cell_index): True
    }
    for grid, cleared_index in (
        (source_grid, source_cell_index),
        (destination_grid, destination_cell_index),
    ):
        try:
            driver = int(grid.get("timeline_driver_cell", -1))
        except (TypeError, ValueError):
            driver = -1
        if driver == cleared_index:
            grid["timeline_driver_cell"] = -1

    destination_pane["active_tab_id"] = destination_tab["id"]
    result["active_pane_id"] = destination_pane["id"]
    result["active_tab_id"] = destination_tab["id"]
    return result


def reorder_workspace_tab(
    layout: Mapping[str, Any], pane_id: str, tab_id: str, insertion_index: int
) -> Dict[str, Any]:
    """Move a tab to an insertion slot within its current pane."""

    result = deepcopy(dict(layout))
    target = next(
        (
            pane
            for pane in list(result.get("panes", []) or [])
            if str(pane.get("id", "")) == str(pane_id or "")
        ),
        None,
    )
    if target is None:
        return result

    tabs = list(target.get("tabs", []) or [])
    source_index = next(
        (
            index
            for index, tab in enumerate(tabs)
            if str(tab.get("id", "")) == str(tab_id or "")
        ),
        -1,
    )
    if source_index < 0:
        return result
    try:
        destination = max(0, min(len(tabs), int(insertion_index)))
    except (TypeError, ValueError):
        return result

    tab = tabs.pop(source_index)
    if source_index < destination:
        destination -= 1
    tabs.insert(max(0, min(len(tabs), destination)), tab)
    target["tabs"] = tabs
    return result


def resize_workspace_split(
    layout: Mapping[str, Any], split_id: str, ratio: Any
) -> Dict[str, Any]:
    result = deepcopy(dict(layout))
    root = normalized_workspace_root(result)

    def update(node: Mapping[str, Any]) -> Tuple[Dict[str, Any], bool]:
        current = deepcopy(dict(node))
        if current.get("kind") != "split":
            return current, False
        if str(current.get("id", "")) == str(split_id or ""):
            current["ratio"] = _split_ratio(ratio)
            return current, True
        first, changed = update(current["first"])
        if changed:
            current["first"] = first
            return current, True
        second, changed = update(current["second"])
        current["second"] = second
        return current, changed

    root, changed = update(root)
    if changed:
        _set_workspace_root(result, root)
    return result
