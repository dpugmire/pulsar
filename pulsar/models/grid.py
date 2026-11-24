"""Pure grid-cell geometry and selection operations."""

from typing import Any, Dict, List, Optional, Tuple

from . import canvas_layout


GridCell = Dict[str, Any]
GRID_LAYOUT_MODES = ("uniform", "spanning", "freeform")
DEFAULT_GRID_LAYOUT_MODE = "uniform"
GRID_LAYOUT_FIELDS = (
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


def clamp_int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        ivalue = int(value)
    except Exception:
        ivalue = default
    return max(minimum, min(maximum, ivalue))


def empty_grid_cell() -> GridCell:
    return {
        "variable_id": "",
        "variable_name": "",
        "display_title": "",
        "visualization_name": "",
        "selected_visualization": "",
        "visualization_options": [],
        "source_id": "",
        "_source_key": "",
        "_source_keys": [],
        "_source_fields_list": [],
        "source_dataset": "",
        "source_collection_id": "",
        "source_collection_label": "",
        "producer": "",
        "casename": "",
        "file": "",
        "src": "",
        "media_type": "",
        "fps": 0,
        "frame_count": 0,
        "frame_indices": [],
        "frame_sources": [],
        "time_values": [],
        "time_mode": "timestep",
        "axes": {},
        "dimension_axes": [],
        "plot_x_axis": "",
        "plot_axis_key": "",
        "selection_axis": {},
        "schema_default_axis": "",
        "axis_sync_status": "",
        "plot": {},
        "plot_settings": {},
        "plugin_id": "",
        "plugin_label": "",
        "plugin_options": {},
        "plugin_options_schema": [],
        "scalar_field_settings": {},
        "scalar_field_axes": {},
        "scalar_field_colorbar_min": "",
        "scalar_field_colorbar_max": "",
        "grid_row": 1,
        "grid_col": 1,
        "row_span": 1,
        "col_span": 1,
        "grid_hidden": False,
        "tile_id": "",
        "tile_type": "plot",
        "canvas_x": 0,
        "canvas_y": 0,
        "canvas_w": canvas_layout.CANVAS_DEFAULT_SIZE[0],
        "canvas_h": canvas_layout.CANVAS_DEFAULT_SIZE[1],
        "status": "empty",
        "note": "",
    }


def default_grid_geometry(index: int, cols: int) -> GridCell:
    safe_cols = max(1, int(cols or 1))
    return {
        "grid_row": (index // safe_cols) + 1,
        "grid_col": (index % safe_cols) + 1,
        "row_span": 1,
        "col_span": 1,
        "grid_hidden": False,
    }


def merge_grid_geometry(cell: GridCell, index: int, rows: int, cols: int) -> GridCell:
    base = dict(cell or {})
    defaults = default_grid_geometry(index, cols)
    row = clamp_int(
        base.get("grid_row", defaults["grid_row"]),
        defaults["grid_row"],
        1,
        rows,
    )
    col = clamp_int(
        base.get("grid_col", defaults["grid_col"]),
        defaults["grid_col"],
        1,
        cols,
    )
    base["grid_row"] = row
    base["grid_col"] = col
    base["row_span"] = clamp_int(
        base.get("row_span", 1),
        1,
        1,
        max(1, rows - row + 1),
    )
    base["col_span"] = clamp_int(
        base.get("col_span", 1),
        1,
        1,
        max(1, cols - col + 1),
    )
    base["grid_hidden"] = bool(base.get("grid_hidden", False))
    return base


def cell_has_content(cell: GridCell) -> bool:
    if str(cell.get("variable_id", "") or cell.get("variable_name", "") or "").strip():
        return True
    if str(cell.get("src", "") or cell.get("media_type", "") or "").strip():
        return True
    if cell.get("plot"):
        return True
    return str(cell.get("status", "") or "") not in {"", "empty"}


def normalize_freeform_cells(
    raw_cells,
    snap: bool = True,
    columns: int = canvas_layout.CANVAS_COLUMNS,
) -> List[GridCell]:
    """Return a compact collection of visible canvas tiles."""

    cells: List[GridCell] = []
    geometries: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_item in list(raw_cells or []):
        base = empty_grid_cell()
        if isinstance(raw_item, dict):
            base.update(raw_item)
        if bool(base.get("grid_hidden", False)) or not cell_has_content(base):
            continue
        fallback_index = len(cells)
        fallback_id = f"tile-{fallback_index + 1}"
        item = canvas_layout.geometry_from_cell(
            base,
            fallback_id=fallback_id,
            fallback_index=fallback_index,
            snap=snap,
            columns=columns,
        )
        candidate_id = str(item["tile_id"] or fallback_id)
        if candidate_id in seen_ids:
            suffix = 2
            while f"{candidate_id}-{suffix}" in seen_ids:
                suffix += 1
            candidate_id = f"{candidate_id}-{suffix}"
            item["tile_id"] = candidate_id
        seen_ids.add(candidate_id)
        if any(canvas_layout.overlaps(item, existing) for existing in geometries):
            item = canvas_layout.nearest_free(item, geometries, columns=columns)
        base = canvas_layout.geometry_to_cell(base, item)
        base["grid_hidden"] = False
        cells.append(base)
        geometries.append(item)
    return cells


def preserve_grid_geometry(cell: GridCell, existing: GridCell) -> GridCell:
    merged = dict(cell or {})
    if isinstance(existing, dict):
        for field in GRID_LAYOUT_FIELDS:
            if field in existing:
                merged[field] = existing[field]
    return merged


def assign_cell(cells: List[GridCell], index: int, cell: GridCell) -> None:
    existing = cells[index] if 0 <= index < len(cells) else {}
    cells[index] = preserve_grid_geometry(cell, existing)


def empty_grid_cell_like(existing: GridCell) -> GridCell:
    return preserve_grid_geometry(empty_grid_cell(), existing)


def area_slots(
    row: int,
    col: int,
    row_span: int,
    col_span: int,
    cols: int,
) -> List[int]:
    return [
        (r - 1) * cols + (c - 1)
        for r in range(row, row + row_span)
        for c in range(col, col + col_span)
    ]


def empty_cell_at(index: int, cols: int, hidden: bool = False) -> GridCell:
    cell = empty_grid_cell()
    cell.update(default_grid_geometry(index, cols))
    cell["grid_hidden"] = bool(hidden)
    return cell


def rebuild_spanning_cells(
    raw_cells: List[GridCell],
    rows: int,
    cols: int,
) -> List[GridCell]:
    count = rows * cols
    merged: List[GridCell] = []
    for index, item in enumerate(raw_cells or []):
        base = empty_grid_cell()
        if isinstance(item, dict):
            base.update(item)
        merged.append(merge_grid_geometry(base, index, rows, cols))
    while len(merged) < count:
        merged.append(empty_cell_at(len(merged), cols))

    cells = [empty_cell_at(index, cols) for index in range(count)]
    occupied: set[int] = set()

    def first_open_area(row_span: int, col_span: int) -> Optional[Tuple[int, int]]:
        for row in range(1, rows - row_span + 2):
            for col in range(1, cols - col_span + 2):
                slots = area_slots(row, col, row_span, col_span, cols)
                if all(slot not in occupied for slot in slots):
                    return row, col
        return None

    def place(
        cell: GridCell,
        row: int,
        col: int,
        row_span: int,
        col_span: int,
    ) -> None:
        anchor = (row - 1) * cols + (col - 1)
        item = dict(cell or {})
        item["grid_row"] = row
        item["grid_col"] = col
        item["row_span"] = row_span
        item["col_span"] = col_span
        item["grid_hidden"] = False
        cells[anchor] = item
        for slot in area_slots(row, col, row_span, col_span, cols):
            occupied.add(slot)
            if slot != anchor:
                cells[slot] = empty_cell_at(slot, cols, hidden=True)

    anchors = [
        cell
        for cell in merged
        if not bool(cell.get("grid_hidden", False))
        and (
            cell_has_content(cell)
            or int(cell.get("row_span", 1) or 1) > 1
            or int(cell.get("col_span", 1) or 1) > 1
        )
    ]

    for cell in anchors:
        row = clamp_int(cell.get("grid_row", 1), 1, 1, rows)
        col = clamp_int(cell.get("grid_col", 1), 1, 1, cols)
        row_span = clamp_int(
            cell.get("row_span", 1),
            1,
            1,
            max(1, rows - row + 1),
        )
        col_span = clamp_int(
            cell.get("col_span", 1),
            1,
            1,
            max(1, cols - col + 1),
        )
        slots = area_slots(row, col, row_span, col_span, cols)
        if any(slot in occupied for slot in slots):
            open_area = first_open_area(row_span, col_span)
            if open_area is None:
                continue
            row, col = open_area
        place(cell, row, col, row_span, col_span)

    return cells


def normalize_grid_cells(
    raw_cells,
    rows: int,
    cols: int,
    layout_mode: str = DEFAULT_GRID_LAYOUT_MODE,
    canvas_snap: bool = True,
    canvas_columns: int = canvas_layout.CANVAS_COLUMNS,
) -> List[GridCell]:
    if str(layout_mode or DEFAULT_GRID_LAYOUT_MODE).strip().lower() == "freeform":
        return normalize_freeform_cells(
            raw_cells,
            snap=bool(canvas_snap),
            columns=canvas_columns,
        )
    count = rows * cols
    spanning = (
        str(layout_mode or DEFAULT_GRID_LAYOUT_MODE).strip().lower()
        == "spanning"
    )
    raw_items = list(raw_cells or [])
    items = raw_items if spanning else raw_items[:count]
    cells: List[GridCell] = []
    for index, item in enumerate(items):
        base = empty_grid_cell()
        if isinstance(item, dict):
            base.update(item)
        if spanning:
            base = merge_grid_geometry(base, index, rows, cols)
        else:
            base.update(default_grid_geometry(index, cols))
        cells.append(base)
    while len(cells) < count:
        cells.append(empty_cell_at(len(cells), cols))
    return rebuild_spanning_cells(cells, rows, cols) if spanning else cells


def is_selectable_grid_cell(cells: List[GridCell], index: int) -> bool:
    if index < 0 or index >= len(cells):
        return False
    cell = dict(cells[index] or {})
    if bool(cell.get("grid_hidden", False)):
        return False
    return bool(
        str(cell.get("variable_id", "") or cell.get("variable_name", "") or "").strip()
    )


def normalize_grid_selection(raw_indices, cells: List[GridCell]) -> List[int]:
    selected: List[int] = []
    for raw_index in raw_indices or []:
        try:
            index = int(raw_index)
        except Exception:
            continue
        if index in selected or not is_selectable_grid_cell(cells, index):
            continue
        selected.append(index)
    return selected


def selection_map(selected: List[int]) -> Dict[str, bool]:
    return {str(index): True for index in selected}


def range_selection(
    cells: List[GridCell],
    selected: List[int],
    anchor: int,
    index: int,
) -> List[int]:
    if not is_selectable_grid_cell(cells, index):
        return normalize_grid_selection(selected, cells)
    normalized = normalize_grid_selection(selected, cells)
    if not is_selectable_grid_cell(cells, anchor):
        anchor = normalized[0] if normalized else index
    start, end = sorted((anchor, index))
    selected_set = set(normalized)
    selected_set.update(
        item
        for item in range(start, end + 1)
        if is_selectable_grid_cell(cells, item)
    )
    return [item for item in range(len(cells)) if item in selected_set]


def source_dialog_targets(
    cells: List[GridCell],
    selected: List[int],
    anchor: int,
) -> List[int]:
    if not is_selectable_grid_cell(cells, anchor):
        return []
    normalized = normalize_grid_selection(selected, cells)
    if anchor in normalized and len(normalized) > 1:
        return normalized
    return [anchor]
