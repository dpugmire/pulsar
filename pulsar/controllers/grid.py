"""Grid layout, selection, assignment, and timeline controller behavior."""

from collections.abc import Mapping
import json
from math import ceil
from typing import Any, Dict, List, Optional, Tuple

from pulsar.models import canvas_layout
from pulsar.models import grid as grid_model
from pulsar.models import grid_layout as grid_layout_model
from pulsar.models.grid import (
    area_slots,
    assign_cell,
    cell_has_content,
    clamp_int,
    empty_grid_cell,
    is_selectable_grid_cell,
    rebuild_spanning_cells,
)
from pulsar.models.source_selection import (
    source_key_for_fields,
)
from pulsar.models.timeline import (
    clear_timeline_driver,
    toggle_timeline_driver,
)


class GridControllerMixin:
    ACTION_BINDINGS = (
        ("set_grid_layout_mode", "set_grid_layout_mode"),
        ("set_canvas_snap_to_grid", "set_canvas_snap_to_grid"),
        ("set_canvas_nudge_others", "set_canvas_nudge_others"),
        ("set_canvas_show_grid", "set_canvas_show_grid"),
        ("set_canvas_columns", "set_canvas_columns"),
        ("adjust_canvas_default_tile_width", "adjust_canvas_default_tile_width"),
        ("adjust_canvas_zoom", "adjust_canvas_zoom"),
        ("set_canvas_fit_to_view", "set_canvas_fit_to_view"),
        ("set_grid_cell_size", "set_grid_cell_size"),
        ("set_grid_fit_min_cell_size", "set_grid_fit_min_cell_size"),
        ("set_grid_sizing_mode", "set_grid_sizing_mode"),
        ("reset_grid_track_sizes", "reset_grid_track_sizes_action"),
        ("set_grid_layout_size", "set_grid_layout_size"),
        ("add_var_to_grid", "add_var_to_grid"),
        ("set_active_grid_cell", "set_active_grid_cell"),
        ("toggle_timeline_driver_cell", "toggle_timeline_driver_cell"),
        ("clear_grid_cell", "clear_grid_cell"),
        ("move_grid_cell", "move_grid_cell"),
        ("add_grid_row", "add_grid_row"),
        ("delete_grid_row", "delete_grid_row"),
        ("add_grid_column", "add_grid_column"),
        ("delete_grid_column", "delete_grid_column"),
        ("span_grid_cell_right", "span_grid_cell_right"),
        ("span_grid_cell_down", "span_grid_cell_down"),
        ("shrink_grid_cell_width", "shrink_grid_cell_width"),
        ("shrink_grid_cell_height", "shrink_grid_cell_height"),
        ("reset_grid_cell_span", "reset_grid_cell_span"),
        ("assign_var_to_grid_cell", "assign_var_to_grid_cell"),
        ("pick_grid_cell_visualization", "pick_grid_cell_visualization"),
    )
    TRIGGER_BINDINGS = (
        ("set_grid_track_sizes_trigger", "set_grid_track_sizes_trigger"),
        ("set_grid_track_weights_trigger", "set_grid_track_weights_trigger"),
        (
            "commit_grid_track_resize_trigger",
            "commit_grid_track_resize_trigger",
        ),
        ("move_grid_cell_trigger", "move_grid_cell_trigger"),
        ("assign_var_to_grid_cell_trigger", "assign_var_to_grid_cell_trigger"),
        ("commit_canvas_layout_trigger", "commit_canvas_layout_trigger"),
        ("add_var_to_canvas_trigger", "add_var_to_canvas_trigger"),
        ("sync_canvas_fit_zoom_trigger", "sync_canvas_fit_zoom_trigger"),
    )
    STATE_CHANGE_BINDINGS = ()
    HISTORY_ACTIONS = {
        "set_grid_layout_mode": "Change layout mode",
        "set_canvas_columns": "Change canvas columns",
        "set_grid_cell_size": "Resize grid cells",
        "set_grid_fit_min_cell_size": "Resize fitted grid cells",
        "set_grid_sizing_mode": "Change grid sizing mode",
        "reset_grid_track_sizes": "Reset grid sizes",
        "set_grid_layout_size": "Resize grid",
        "add_var_to_grid": "Add plot",
        "set_active_grid_cell": "Assign plot",
        "toggle_timeline_driver_cell": "Change timeline driver",
        "clear_grid_cell": "Remove plot",
        "move_grid_cell": "Move plot",
        "add_grid_row": "Add grid row",
        "delete_grid_row": "Delete grid row",
        "add_grid_column": "Add grid column",
        "delete_grid_column": "Delete grid column",
        "span_grid_cell_right": "Resize plot",
        "span_grid_cell_down": "Resize plot",
        "shrink_grid_cell_width": "Resize plot",
        "shrink_grid_cell_height": "Resize plot",
        "reset_grid_cell_span": "Reset plot size",
        "assign_var_to_grid_cell": "Assign plot",
        "pick_grid_cell_visualization": "Change visualization",
    }
    HISTORY_TRIGGERS = {
        "set_grid_track_sizes_trigger": "Resize grid track",
        "set_grid_track_weights_trigger": "Resize grid track",
        "commit_grid_track_resize_trigger": "Resize grid track",
        "move_grid_cell_trigger": "Move plot",
        "assign_var_to_grid_cell_trigger": "Assign plot",
        "commit_canvas_layout_trigger": "Move or resize plot",
        "add_var_to_canvas_trigger": "Add plot",
    }

    grid_fit_template_from_weights = staticmethod(
        grid_layout_model.grid_fit_template_from_weights
    )
    grid_template_from_sizes = staticmethod(grid_layout_model.grid_template_from_sizes)
    normalize_size_list = staticmethod(grid_layout_model.normalize_size_list)
    normalize_weight_list = staticmethod(grid_layout_model.normalize_weight_list)

    def normalize_grid_layout_mode(self) -> str:
        mode = (
            str(
                getattr(
                    self.state,
                    "gridLayoutMode",
                    grid_model.DEFAULT_GRID_LAYOUT_MODE,
                )
                or grid_model.DEFAULT_GRID_LAYOUT_MODE
            )
            .strip()
            .lower()
        )
        self.state.gridLayoutMode = (
            mode
            if mode in grid_model.GRID_LAYOUT_MODES
            else grid_model.DEFAULT_GRID_LAYOUT_MODE
        )
        return self.state.gridLayoutMode

    def normalize_canvas_settings(self) -> None:
        self.state.canvasCols = canvas_layout.normalize_columns(
            getattr(self.state, "canvasCols", canvas_layout.CANVAS_COLUMNS)
        )
        self.state.canvasRowHeight = canvas_layout.CANVAS_ROW_HEIGHT
        self.state.canvasSnapToGrid = bool(
            getattr(self.state, "canvasSnapToGrid", True)
        )
        self.state.canvasNudgeOthers = bool(
            getattr(self.state, "canvasNudgeOthers", True)
        )
        self.state.canvasShowGrid = bool(
            getattr(self.state, "canvasShowGrid", False)
        )
        self.state.canvasZoom = canvas_layout.normalize_zoom(
            getattr(
                self.state,
                "canvasZoom",
                canvas_layout.CANVAS_ZOOM_DEFAULT,
            )
        )
        self.state.canvasFitToView = bool(
            getattr(self.state, "canvasFitToView", False)
        )
        self.state.canvasDefaultTileWidth = canvas_layout.normalize_drop_width(
            getattr(
                self.state,
                "canvasDefaultTileWidth",
                canvas_layout.CANVAS_DEFAULT_DROP_WIDTH,
            )
        )
        self.state.canvasDwellMs = canvas_layout.CANVAS_DWELL_MS
        self.state.canvasSnapDeadZone = canvas_layout.CANVAS_SNAP_DEAD_ZONE
        self.state.canvasTransitionMs = canvas_layout.CANVAS_TRANSITION_MS
        try:
            revision = int(getattr(self.state, "canvasLayoutRevision", 0))
        except Exception:
            revision = 0
        self.state.canvasLayoutRevision = max(0, revision)

    def canvas_columns(self) -> int:
        return canvas_layout.normalize_columns(
            getattr(self.state, "canvasCols", canvas_layout.CANVAS_COLUMNS)
        )

    @staticmethod
    def next_canvas_tile_id(cells: List[Dict[str, Any]]) -> str:
        existing = {
            str(cell.get("tile_id", "") or "") for cell in list(cells or [])
        }
        index = 1
        while f"tile-{index}" in existing:
            index += 1
        return f"tile-{index}"

    def grid_dimensions(self) -> Tuple[int, int]:
        rows = clamp_int(
            getattr(self.state, "gridRows", 3),
            3,
            self.GRID_MIN_ROWS,
            self.GRID_MAX_ROWS,
        )
        cols = clamp_int(
            getattr(self.state, "gridCols", 3),
            3,
            self.GRID_MIN_COLS,
            self.GRID_MAX_COLS,
        )
        self.state.gridRows = rows
        self.state.gridCols = cols
        self.state.gridMinRows = self.GRID_MIN_ROWS
        self.state.gridMinCols = self.GRID_MIN_COLS
        self.state.gridMaxRows = self.GRID_MAX_ROWS
        self.state.gridMaxCols = self.GRID_MAX_COLS
        return rows, cols

    def normalize_grid_sizing(self) -> None:
        mode = (
            str(getattr(self.state, "gridSizingMode", "static") or "static")
            .strip()
            .lower()
        )
        self.state.gridSizingMode = "fit" if mode == "fit" else "static"
        self.state.gridMinCellSize = clamp_int(
            getattr(self.state, "gridMinCellSize", 80), 80, 40, 1000
        )
        self.state.gridMaxCellSize = clamp_int(
            getattr(self.state, "gridMaxCellSize", 5000),
            5000,
            self.state.gridMinCellSize,
            10000,
        )
        self.state.gridCellSize = clamp_int(
            getattr(self.state, "gridCellSize", 300),
            300,
            self.state.gridMinCellSize,
            self.state.gridMaxCellSize,
        )
        self.state.gridMaxFitMinCellSize = clamp_int(
            getattr(self.state, "gridMaxFitMinCellSize", 5000),
            5000,
            self.state.gridMinCellSize,
            10000,
        )
        self.state.gridFitMinCellSize = clamp_int(
            getattr(self.state, "gridFitMinCellSize", 180),
            180,
            self.state.gridMinCellSize,
            self.state.gridMaxFitMinCellSize,
        )

    def publish_grid_track_templates(self) -> None:
        self.state.gridColumnTemplate = self.grid_template_from_sizes(
            list(self.state.gridColumnSizes or [])
        )
        self.state.gridRowTemplate = self.grid_template_from_sizes(
            list(self.state.gridRowSizes or [])
        )
        self.state.gridFitColumnTemplate = self.grid_fit_template_from_weights(
            list(self.state.gridColumnWeights or []),
            int(self.state.gridFitMinCellSize),
        )
        self.state.gridFitRowTemplate = self.grid_fit_template_from_weights(
            list(self.state.gridRowWeights or []),
            int(self.state.gridFitMinCellSize) + self.GRID_HEADER_HEIGHT,
        )

    def normalize_grid_track_sizes(
        self, rows: Optional[int] = None, cols: Optional[int] = None
    ) -> None:
        self.normalize_grid_sizing()
        if rows is None or cols is None:
            rows, cols = self.grid_dimensions()

        col_default = int(self.state.gridCellSize)
        row_default = int(self.state.gridCellSize) + self.GRID_HEADER_HEIGHT
        self.state.gridColumnSizes = self.normalize_size_list(
            getattr(self.state, "gridColumnSizes", []),
            int(cols),
            col_default,
            int(self.state.gridMinCellSize),
            int(self.state.gridMaxCellSize),
        )
        self.state.gridRowSizes = self.normalize_size_list(
            getattr(self.state, "gridRowSizes", []),
            int(rows),
            row_default,
            int(self.state.gridMinCellSize) + self.GRID_HEADER_HEIGHT,
            int(self.state.gridMaxCellSize) + self.GRID_HEADER_HEIGHT,
        )
        self.state.gridColumnWeights = self.normalize_weight_list(
            getattr(self.state, "gridColumnWeights", []),
            int(cols),
        )
        self.state.gridRowWeights = self.normalize_weight_list(
            getattr(self.state, "gridRowWeights", []),
            int(rows),
        )
        self.publish_grid_track_templates()

    def reset_grid_track_sizes(self) -> None:
        self.normalize_grid_sizing()
        rows, cols = self.grid_dimensions()
        self.state.gridColumnSizes = [int(self.state.gridCellSize) for _ in range(cols)]
        self.state.gridRowSizes = [
            int(self.state.gridCellSize) + self.GRID_HEADER_HEIGHT for _ in range(rows)
        ]
        self.state.gridColumnWeights = [1.0 for _ in range(cols)]
        self.state.gridRowWeights = [1.0 for _ in range(rows)]
        self.publish_grid_track_templates()

    def drop_grid_track(self, axis: str, index: int) -> None:
        if axis == "row":
            sizes = list(getattr(self.state, "gridRowSizes", []) or [])
            if 0 <= index < len(sizes):
                del sizes[index]
            self.state.gridRowSizes = sizes
            weights = list(getattr(self.state, "gridRowWeights", []) or [])
            if 0 <= index < len(weights):
                del weights[index]
            self.state.gridRowWeights = weights
        elif axis == "column":
            sizes = list(getattr(self.state, "gridColumnSizes", []) or [])
            if 0 <= index < len(sizes):
                del sizes[index]
            self.state.gridColumnSizes = sizes
            weights = list(getattr(self.state, "gridColumnWeights", []) or [])
            if 0 <= index < len(weights):
                del weights[index]
            self.state.gridColumnWeights = weights

    def grid_cell_count(self) -> int:
        if self.normalize_grid_layout_mode() == "freeform":
            return len(self.normalize_grid_cells(self.state.gridCells))
        rows, cols = self.grid_dimensions()
        return rows * cols

    def is_valid_grid_index(self, idx: int) -> bool:
        return 0 <= idx < self.grid_cell_count()

    def active_grid_index(self, cell_count: int = -1) -> int:
        try:
            idx = int(self.state.activeGridCell)
        except Exception:
            return -1
        if cell_count < 0:
            cell_count = self.grid_cell_count()
        return idx if 0 <= idx < cell_count else -1

    def normalize_grid_selection(
        self,
        raw_indices: Optional[List[Any]] = None,
        cells: Optional[List[Dict[str, Any]]] = None,
    ) -> List[int]:
        if cells is None:
            cells = self.normalize_grid_cells(self.state.gridCells)
        items = (
            raw_indices
            if raw_indices is not None
            else list(self.state.selectedGridCellIndices or [])
        )
        return grid_model.normalize_grid_selection(items, cells)

    def set_grid_selection(
        self, indices: List[int], active: Optional[int] = None
    ) -> None:
        cells = self.normalize_grid_cells(self.state.gridCells)
        selected = self.normalize_grid_selection(indices, cells)
        self.publish_grid_selection(selected)
        if active is not None and self.is_valid_grid_index(active):
            self.state.activeGridCell = int(active)

    def clear_timeline_driver_if_cell(self, idx: int) -> None:
        try:
            current = int(self.state.timelineDriverCell)
        except Exception:
            current = -1
        self.state.timelineDriverCell = clear_timeline_driver(current, [int(idx)])

    def publish_grid_selection(self, selected: List[int]) -> None:
        self.state.selectedGridCellIndices = selected
        self.state.selectedGridCellMap = grid_model.selection_map(selected)

    def source_dialog_targets_for_anchor(
        self, idx: int, cells: Optional[List[Dict[str, Any]]] = None
    ) -> List[int]:
        if cells is None:
            cells = self.normalize_grid_cells(self.state.gridCells)
        return grid_model.source_dialog_targets(
            cells,
            self.normalize_grid_selection(cells=cells),
            idx,
        )

    def source_row_for_variable(
        self, row: Dict[str, Any], variable_id: str
    ) -> Dict[str, str]:
        target = {
            "variable_id": str(variable_id or ""),
            "source_label": str(row.get("source_label", "") or ""),
            "source_dataset": str(row.get("source_dataset", "") or ""),
            "source_collection_id": str(
                row.get("source_collection_id", "") or ""
            ),
            "source_collection_label": str(
                row.get("source_collection_label", "") or ""
            ),
            "schema_file_group": str(row.get("schema_file_group", "") or ""),
            "schema_pattern": str(row.get("schema_pattern", "") or ""),
            "schema_mode": str(row.get("schema_mode", "") or ""),
            "producer": str(row.get("producer", "") or ""),
            "casename": str(row.get("casename", "") or ""),
            "file": str(row.get("file", "") or ""),
        }
        target["_key"] = source_key_for_fields(target)
        return target

    def normalize_grid_cells(
        self, raw_cells, rows=None, cols=None
    ) -> List[Dict[str, Any]]:
        if rows is None or cols is None:
            rows, cols = self.grid_dimensions()
        return grid_model.normalize_grid_cells(
            raw_cells,
            rows,
            cols,
            self.normalize_grid_layout_mode(),
            canvas_snap=bool(getattr(self.state, "canvasSnapToGrid", True)),
            canvas_columns=self.canvas_columns(),
        )

    def set_grid_layout(
        self, rows: int, cols: int, cells: List[Dict[str, Any]], active: int
    ) -> None:
        previous_rows, previous_cols = self.grid_dimensions()
        rows = clamp_int(rows, 3, self.GRID_MIN_ROWS, self.GRID_MAX_ROWS)
        cols = clamp_int(cols, 3, self.GRID_MIN_COLS, self.GRID_MAX_COLS)
        cells = self.normalize_grid_cells(cells, rows, cols)
        self.state.gridRows = rows
        self.state.gridCols = cols
        self.normalize_grid_track_sizes(rows, cols)
        self.state.gridCells = self.normalize_grid_cells(cells)
        self.state.activeGridCell = active if 0 <= active < rows * cols else -1
        try:
            if int(self.state.timelineDriverCell) >= rows * cols:
                self.state.timelineDriverCell = -1
        except Exception:
            self.state.timelineDriverCell = -1
        self.publish_grid_selection(
            self.normalize_grid_selection(cells=list(self.state.gridCells or []))
        )
        self.clear_context_menu_state()
        self.record_interaction(
            "workspace.layout_changed",
            source="grid_controls",
            payload={
                "change": "dimensions",
                "previous_rows": previous_rows,
                "previous_columns": previous_cols,
                "rows": rows,
                "columns": cols,
                "workspace": self.interaction_workspace_location(),
            },
        )
        self.clear_interaction_assignment()

    def legacy_cells_to_freeform(
        self,
        raw_cells: List[Dict[str, Any]],
        rows: int,
        cols: int,
    ) -> Tuple[List[Dict[str, Any]], Dict[int, int]]:
        """Convert visible legacy cells into compact freeform tiles."""

        result: List[Dict[str, Any]] = []
        geometries: List[Dict[str, Any]] = []
        index_map: Dict[int, int] = {}
        safe_cols = max(1, int(cols or 1))
        canvas_columns = self.canvas_columns()
        legacy_row_units = 12
        for source_index, raw_cell in enumerate(list(raw_cells or [])):
            cell = dict(raw_cell or {})
            if bool(cell.get("grid_hidden", False)) or not cell_has_content(cell):
                continue
            kind = canvas_layout.tile_type_for_cell(cell)
            min_w, min_h = canvas_layout.minimum_size(kind)
            default_w, default_h = canvas_layout.default_size(kind)
            row = clamp_int(cell.get("grid_row", 1), 1, 1, max(1, rows))
            col = clamp_int(cell.get("grid_col", 1), 1, 1, safe_cols)
            row_span = clamp_int(
                cell.get("row_span", 1), 1, 1, max(1, rows - row + 1)
            )
            col_span = clamp_int(
                cell.get("col_span", 1), 1, 1, max(1, safe_cols - col + 1)
            )
            left = round((col - 1) * canvas_columns / safe_cols)
            right = round(
                (col - 1 + col_span)
                * canvas_columns
                / safe_cols
            )
            width = max(min_w, right - left, default_w if safe_cols == 1 else 0)
            width = min(width, canvas_columns)
            left = max(0, min(left, canvas_columns - width))
            height = max(min_h, row_span * legacy_row_units, default_h)
            item = canvas_layout.geometry(
                self.next_canvas_tile_id(result),
                kind,
                left,
                (row - 1) * legacy_row_units,
                width,
                height,
                columns=canvas_columns,
            )
            if any(canvas_layout.overlaps(item, other) for other in geometries):
                item = canvas_layout.nearest_free(
                    item, geometries, columns=canvas_columns
                )
            cell = canvas_layout.geometry_to_cell(cell, item)
            cell["grid_hidden"] = False
            index_map[source_index] = len(result)
            result.append(cell)
            geometries.append(item)
        return result, index_map

    def freeform_cells_to_legacy(
        self,
        raw_cells: List[Dict[str, Any]],
        rows: int,
        cols: int,
    ) -> Tuple[List[Dict[str, Any]], int, int]:
        """Pack freeform tiles into a legacy matrix without discarding content."""

        cells = grid_model.normalize_freeform_cells(
            raw_cells,
            snap=bool(getattr(self.state, "canvasSnapToGrid", True)),
            columns=self.canvas_columns(),
        )
        count = len(cells)
        safe_cols = max(1, min(self.GRID_MAX_COLS, int(cols or 1)))
        safe_rows = max(1, min(self.GRID_MAX_ROWS, int(rows or 1)))
        if safe_rows * safe_cols < count:
            safe_rows = min(self.GRID_MAX_ROWS, max(safe_rows, ceil(count / safe_cols)))
        if safe_rows * safe_cols < count:
            safe_cols = self.GRID_MAX_COLS
            safe_rows = min(self.GRID_MAX_ROWS, ceil(count / safe_cols))
        if safe_rows * safe_cols < count:
            raise ValueError("Freeform canvas contains more than 64 tiles")

        packed = [empty_grid_cell() for _ in range(safe_rows * safe_cols)]
        for index, cell in enumerate(cells):
            item = dict(cell)
            item.update(grid_model.default_grid_geometry(index, safe_cols))
            packed[index] = item
        return packed, safe_rows, safe_cols

    def set_grid_layout_mode(self, mode: str, **_):
        requested = str(mode or "").strip().lower()
        if requested not in grid_model.GRID_LAYOUT_MODES:
            requested = grid_model.DEFAULT_GRID_LAYOUT_MODE
        previous = self.normalize_grid_layout_mode()
        if requested == previous:
            return

        rows, cols = self.grid_dimensions()
        try:
            active = int(getattr(self.state, "activeGridCell", -1))
        except Exception:
            active = -1
        selected = list(getattr(self.state, "selectedGridCellIndices", []) or [])

        if requested == "freeform":
            legacy_cells = self.normalize_grid_cells(self.state.gridCells, rows, cols)
            converted, index_map = self.legacy_cells_to_freeform(
                legacy_cells, rows, cols
            )
            self.state.gridLayoutMode = "freeform"
            self.normalize_canvas_settings()
            self.state.gridCells = grid_model.normalize_freeform_cells(
                converted,
                snap=bool(self.state.canvasSnapToGrid),
                columns=self.canvas_columns(),
            )
            self.state.activeGridCell = index_map.get(active, -1)
            remapped_selection = [
                index_map[index] for index in selected if index in index_map
            ]
            self.publish_grid_selection(
                self.normalize_grid_selection(
                    remapped_selection, list(self.state.gridCells or [])
                )
            )
            try:
                driver = int(getattr(self.state, "timelineDriverCell", -1))
            except Exception:
                driver = -1
            self.state.timelineDriverCell = index_map.get(driver, -1)
        elif previous == "freeform":
            try:
                packed, rows, cols = self.freeform_cells_to_legacy(
                    list(self.state.gridCells or []), rows, cols
                )
            except ValueError as error:
                self.state.canvasLayoutError = str(error)
                return
            self.state.gridLayoutMode = requested
            self.state.gridRows = rows
            self.state.gridCols = cols
            self.normalize_grid_track_sizes(rows, cols)
            self.state.gridCells = self.normalize_grid_cells(packed, rows, cols)
            self.state.activeGridCell = active if 0 <= active < len(packed) else -1
            self.publish_grid_selection(
                self.normalize_grid_selection(selected, list(self.state.gridCells or []))
            )
        else:
            self.state.gridLayoutMode = requested
            self.state.gridCells = self.normalize_grid_cells(
                self.state.gridCells, rows, cols
            )
            self.state.activeGridCell = (
                active if 0 <= active < rows * cols else -1
            )
            self.publish_grid_selection(
                self.normalize_grid_selection(cells=list(self.state.gridCells or []))
            )

        self.state.canvasLayoutError = ""
        self.state.canvasLayoutRevision = int(
            getattr(self.state, "canvasLayoutRevision", 0) or 0
        ) + 1
        self.record_interaction(
            "workspace.layout_changed",
            source="grid_controls",
            payload={
                "change": "layout_mode",
                "previous": previous,
                "current": requested,
                "workspace": self.interaction_workspace_location(),
            },
        )

    def set_canvas_snap_to_grid(self, value=True, **_):
        previous = bool(getattr(self.state, "canvasSnapToGrid", True))
        self.state.canvasSnapToGrid = bool(value)
        self.normalize_canvas_settings()
        if self.normalize_grid_layout_mode() == "freeform":
            self.state.gridCells = grid_model.normalize_freeform_cells(
                list(self.state.gridCells or []),
                snap=bool(self.state.canvasSnapToGrid),
                columns=self.canvas_columns(),
            )
            self.state.canvasLayoutRevision = int(self.state.canvasLayoutRevision) + 1
        if previous != bool(self.state.canvasSnapToGrid):
            self.record_interaction(
                "workspace.layout_changed",
                source="canvas_controls",
                payload={
                    "change": "canvas_snap",
                    "enabled": bool(self.state.canvasSnapToGrid),
                    "workspace": self.interaction_workspace_location(),
                },
            )

    def set_canvas_nudge_others(self, value=True, **_):
        self.state.canvasNudgeOthers = bool(value)
        self.normalize_canvas_settings()

    def set_canvas_show_grid(self, value=True, **_):
        self.state.canvasShowGrid = bool(value)
        self.normalize_canvas_settings()

    def set_canvas_columns(self, value=canvas_layout.CANVAS_COLUMNS, **_):
        previous = self.canvas_columns()
        columns = canvas_layout.normalize_columns(value)
        if columns == previous:
            return

        if self.normalize_grid_layout_mode() == "freeform":
            cells = self.normalize_grid_cells(self.state.gridCells)
            scaled = canvas_layout.scale_layout_columns(
                self.canvas_geometries(cells, columns=previous),
                previous,
                columns,
                snap=bool(getattr(self.state, "canvasSnapToGrid", True)),
            )
            geometry_by_id = {item["tile_id"]: item for item in scaled}
            updated_cells = [
                canvas_layout.geometry_to_cell(
                    cell,
                    geometry_by_id[str(cell.get("tile_id", "") or "")],
                )
                for cell in cells
            ]
            self.state.canvasCols = columns
            self.state.gridCells = updated_cells
            self.state.canvasLayoutRevision = int(
                getattr(self.state, "canvasLayoutRevision", 0) or 0
            ) + 1

        self.state.canvasCols = columns
        self.normalize_canvas_settings()
        self.state.canvasLayoutError = ""
        self.record_interaction(
            "workspace.layout_changed",
            source="canvas_controls",
            payload={
                "change": "canvas_columns",
                "previous": previous,
                "current": columns,
                "workspace": self.interaction_workspace_location(),
            },
        )

    def adjust_canvas_zoom(self, delta=0, **_):
        previous = canvas_layout.normalize_zoom(
            getattr(self.state, "canvasZoom", canvas_layout.CANVAS_ZOOM_DEFAULT)
        )
        was_fit = bool(getattr(self.state, "canvasFitToView", False))
        try:
            change = float(delta)
        except (TypeError, ValueError):
            change = 0.0
        zoom = canvas_layout.normalize_zoom(previous + change)
        self.state.canvasZoom = zoom
        self.state.canvasFitToView = False
        self.normalize_canvas_settings()
        if zoom == previous and not was_fit:
            return
        self.state.canvasLayoutRevision = int(
            getattr(self.state, "canvasLayoutRevision", 0) or 0
        ) + 1
        self.record_interaction(
            "workspace.layout_changed",
            source="canvas_controls",
            payload={
                "change": "canvas_zoom",
                "previous": previous,
                "current": zoom,
                "workspace": self.interaction_workspace_location(),
            },
        )

    def adjust_canvas_default_tile_width(self, delta=0, **_):
        previous = canvas_layout.normalize_drop_width(
            getattr(
                self.state,
                "canvasDefaultTileWidth",
                canvas_layout.CANVAS_DEFAULT_DROP_WIDTH,
            )
        )
        try:
            change = int(delta)
        except (TypeError, ValueError):
            change = 0
        width = canvas_layout.normalize_drop_width(previous + change)
        self.state.canvasDefaultTileWidth = width
        if width == previous:
            return
        self.record_interaction(
            "workspace.layout_changed",
            source="canvas_controls",
            payload={
                "change": "canvas_default_tile_width",
                "previous": previous,
                "current": width,
                "workspace": self.interaction_workspace_location(),
            },
        )

    def set_canvas_fit_to_view(self, value=True, **_):
        previous = bool(getattr(self.state, "canvasFitToView", False))
        self.state.canvasFitToView = bool(value)
        self.normalize_canvas_settings()
        self.state.canvasLayoutRevision = int(
            getattr(self.state, "canvasLayoutRevision", 0) or 0
        ) + 1
        if previous != bool(self.state.canvasFitToView):
            self.record_interaction(
                "workspace.layout_changed",
                source="canvas_controls",
                payload={
                    "change": "canvas_fit_to_view",
                    "enabled": bool(self.state.canvasFitToView),
                    "workspace": self.interaction_workspace_location(),
                },
            )

    def sync_canvas_fit_zoom_trigger(
        self,
        value,
        pane_id="",
        tab_id="",
        **_,
    ):
        if pane_id and str(pane_id) != str(self.state.workspaceActivePaneId or ""):
            return
        if tab_id and str(tab_id) != str(self.state.workspaceActiveTabId or ""):
            return
        if not bool(getattr(self.state, "canvasFitToView", False)):
            return
        self.state.canvasZoom = canvas_layout.normalize_zoom(value)

    @staticmethod
    def parse_canvas_payload(value: Any, default: Any):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (TypeError, ValueError):
                return default
        return value

    def canvas_geometries(
        self,
        cells: Optional[List[Dict[str, Any]]] = None,
        *,
        columns: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if cells is None:
            cells = self.normalize_grid_cells(self.state.gridCells)
        snap = bool(getattr(self.state, "canvasSnapToGrid", True))
        column_count = self.canvas_columns() if columns is None else columns
        return [
            canvas_layout.geometry_from_cell(
                cell,
                fallback_id=f"tile-{index + 1}",
                fallback_index=index,
                snap=snap,
                columns=column_count,
            )
            for index, cell in enumerate(cells)
        ]

    def commit_canvas_layout(
        self,
        layout_payload,
        active_tile_id: str = "",
        pane_id: str = "",
        tab_id: str = "",
    ) -> bool:
        if self.normalize_grid_layout_mode() != "freeform":
            return False
        if pane_id and str(pane_id) != str(self.state.workspaceActivePaneId or ""):
            return False
        if tab_id and str(tab_id) != str(self.state.workspaceActiveTabId or ""):
            return False

        payload = self.parse_canvas_payload(layout_payload, [])
        if not isinstance(payload, list) or len(payload) > canvas_layout.CANVAS_MAX_TILES:
            self.state.canvasLayoutError = "Invalid canvas layout payload"
            return False
        cells = self.normalize_grid_cells(self.state.gridCells)
        existing_by_id = {
            str(cell.get("tile_id", "") or ""): (index, cell)
            for index, cell in enumerate(cells)
        }
        if not existing_by_id and not payload:
            return True
        if any(not isinstance(item, dict) for item in payload):
            self.state.canvasLayoutError = "Canvas layout entries must be objects"
            return False
        payload_by_id = {
            str(item.get("tile_id", "") or ""): item for item in payload
        }
        if set(payload_by_id) != set(existing_by_id):
            self.state.canvasLayoutError = "Canvas layout tile IDs do not match"
            return False

        snap = bool(getattr(self.state, "canvasSnapToGrid", True))
        columns = self.canvas_columns()
        geometries: List[Dict[str, Any]] = []
        for tile_id, (_index, cell) in existing_by_id.items():
            proposed = payload_by_id[tile_id]
            geometries.append(
                canvas_layout.geometry(
                    tile_id,
                    cell.get("tile_type", canvas_layout.tile_type_for_cell(cell)),
                    proposed.get("x"),
                    proposed.get("y"),
                    proposed.get("w"),
                    proposed.get("h"),
                    snap=snap,
                    columns=columns,
                )
            )
        valid, message = canvas_layout.validate_layout(
            geometries, columns=columns
        )
        if not valid:
            self.state.canvasLayoutError = message
            return False

        geometry_by_id = {item["tile_id"]: item for item in geometries}
        self.state.gridCells = [
            canvas_layout.geometry_to_cell(
                cell, geometry_by_id[str(cell.get("tile_id", "") or "")]
            )
            for cell in cells
        ]
        active_id = str(active_tile_id or "")
        if active_id in existing_by_id:
            self.state.activeGridCell = existing_by_id[active_id][0]
        self.state.canvasLayoutError = ""
        self.state.canvasLayoutRevision = int(
            getattr(self.state, "canvasLayoutRevision", 0) or 0
        ) + 1
        self.record_interaction(
            "workspace.layout_changed",
            source="canvas_drag",
            payload={
                "change": "freeform_geometry",
                "tile_count": len(geometries),
                "active_tile_id": active_id,
                "workspace": self.interaction_workspace_location(
                    self.state.activeGridCell
                ),
            },
        )
        return True

    def commit_canvas_layout_trigger(
        self,
        layout_payload,
        active_tile_id="",
        pane_id="",
        tab_id="",
        **_,
    ):
        self.commit_canvas_layout(
            layout_payload,
            active_tile_id=active_tile_id,
            pane_id=pane_id,
            tab_id=tab_id,
        )

    def add_var_to_canvas(
        self,
        var_name: str,
        geometry_payload=None,
        *,
        sync_selection: bool = False,
    ) -> int:
        var = str(var_name or "").strip()
        if not var or self.normalize_grid_layout_mode() != "freeform":
            return -1
        cells = self.normalize_grid_cells(self.state.gridCells)
        if len(cells) >= canvas_layout.CANVAS_MAX_TILES:
            self.state.canvasLayoutError = "Freeform canvas reached its tile limit"
            return -1
        proposed = self.parse_canvas_payload(geometry_payload, {})
        if not isinstance(proposed, dict):
            proposed = {}
        tile_id = self.next_canvas_tile_id(cells)
        columns = self.canvas_columns()
        default_w = canvas_layout.normalize_drop_width(
            getattr(
                self.state,
                "canvasDefaultTileWidth",
                canvas_layout.CANVAS_DEFAULT_DROP_WIDTH,
            )
        )
        default_h = max(
            canvas_layout.minimum_size("plot")[1],
            default_w * 2,
        )
        item = canvas_layout.geometry(
            tile_id,
            "plot",
            proposed.get("x", 0),
            proposed.get("y", 0),
            proposed.get("w", default_w),
            proposed.get("h", default_h),
            snap=bool(getattr(self.state, "canvasSnapToGrid", True)),
            columns=columns,
        )
        others = self.canvas_geometries(cells)
        if any(canvas_layout.overlaps(item, other) for other in others):
            item = canvas_layout.nearest_free(item, others, columns=columns)

        placeholder = empty_grid_cell()
        placeholder.update(
            {
                "variable_id": var,
                "variable_name": self.variable_label(var),
                "display_title": self.variable_label(var),
                "status": "loading",
            }
        )
        placeholder = canvas_layout.geometry_to_cell(placeholder, item)
        cells.append(placeholder)
        self.state.gridCells = cells
        target = len(cells) - 1
        self.assign_var_to_grid_cell(target, var, sync_selection=sync_selection)

        cells = self.normalize_grid_cells(self.state.gridCells)
        if 0 <= target < len(cells):
            cell = dict(cells[target] or {})
            inferred = dict(cell)
            inferred["tile_type"] = ""
            kind = canvas_layout.tile_type_for_cell(inferred)
            cell["tile_type"] = kind
            current = canvas_layout.geometry_from_cell(
                cell,
                fallback_id=tile_id,
                fallback_index=target,
                snap=bool(self.state.canvasSnapToGrid),
                columns=columns,
            )
            min_w, min_h = canvas_layout.minimum_size(kind)
            current["w"] = max(min_w, current["w"])
            current["h"] = max(min_h, current["h"])
            current["x"] = min(
                current["x"], columns - current["w"]
            )
            other_geometry = [
                geometry
                for index, geometry in enumerate(self.canvas_geometries(cells))
                if index != target
            ]
            if any(canvas_layout.overlaps(current, other) for other in other_geometry):
                current = canvas_layout.nearest_free(
                    current, other_geometry, columns=columns
                )
            cells[target] = canvas_layout.geometry_to_cell(cell, current)
            self.state.gridCells = cells
        self.state.activeGridCell = target
        self.set_grid_selection([target], active=target)
        self.state.canvasLayoutRevision = int(self.state.canvasLayoutRevision) + 1
        self.state.canvasLayoutError = ""
        return target

    def add_var_to_canvas_trigger(
        self,
        var_name,
        geometry_payload=None,
        pane_id="",
        tab_id="",
        layout_payload="",
        **_,
    ):
        if pane_id and str(pane_id) != str(self.state.workspaceActivePaneId or ""):
            return
        if tab_id and str(tab_id) != str(self.state.workspaceActiveTabId or ""):
            return
        if layout_payload and not self.commit_canvas_layout(
            layout_payload,
            pane_id=pane_id,
            tab_id=tab_id,
        ):
            return
        self.add_var_to_canvas(var_name, geometry_payload, sync_selection=False)
        self.state.selectedVar = ""
        self.state.draggedVar = ""

    def set_grid_cell_size(self, size: int, **_):
        self.normalize_grid_sizing()
        self.state.gridCellSize = clamp_int(
            size, 300, self.state.gridMinCellSize, self.state.gridMaxCellSize
        )
        self.reset_grid_track_sizes()

    def set_grid_fit_min_cell_size(self, size: int, **_):
        self.normalize_grid_sizing()
        self.state.gridFitMinCellSize = clamp_int(
            size,
            180,
            self.state.gridMinCellSize,
            self.state.gridMaxFitMinCellSize,
        )
        self.normalize_grid_track_sizes()

    def set_grid_sizing_mode(self, mode: str, **_):
        previous = str(getattr(self.state, "gridSizingMode", "static") or "static")
        self.state.gridSizingMode = (
            "fit" if str(mode or "").strip().lower() == "fit" else "static"
        )
        self.normalize_grid_sizing()
        self.normalize_grid_track_sizes()
        current = str(self.state.gridSizingMode or "static")
        if current != previous:
            self.record_interaction(
                "workspace.layout_changed",
                source="grid_controls",
                payload={
                    "change": "sizing_mode",
                    "previous": previous,
                    "current": current,
                    "workspace": self.interaction_workspace_location(),
                },
            )

    def reset_grid_track_sizes_action(self, **_):
        self.reset_grid_track_sizes()

    def set_grid_track_sizes_trigger(self, axis: str, sizes="", **_):
        axis_name = str(axis or "").strip().lower()
        self.normalize_grid_sizing()
        rows, cols = self.grid_dimensions()
        if axis_name == "column":
            self.state.gridColumnSizes = self.normalize_size_list(
                sizes,
                cols,
                int(self.state.gridCellSize),
                int(self.state.gridMinCellSize),
                int(self.state.gridMaxCellSize),
            )
        elif axis_name == "row":
            self.state.gridRowSizes = self.normalize_size_list(
                sizes,
                rows,
                int(self.state.gridCellSize) + self.GRID_HEADER_HEIGHT,
                int(self.state.gridMinCellSize) + self.GRID_HEADER_HEIGHT,
                int(self.state.gridMaxCellSize) + self.GRID_HEADER_HEIGHT,
            )
        else:
            return
        self.state.gridSizingMode = "static"
        self.normalize_grid_track_sizes(rows, cols)
        self.record_interaction(
            "workspace.layout_changed",
            source="grid_resize",
            payload={
                "change": f"{axis_name}_sizes",
                "column_sizes": list(self.state.gridColumnSizes or []),
                "row_sizes": list(self.state.gridRowSizes or []),
                "workspace": self.interaction_workspace_location(),
            },
        )

    def set_grid_track_weights_trigger(self, axis: str, weights="", **_):
        axis_name = str(axis or "").strip().lower()
        self.normalize_grid_sizing()
        rows, cols = self.grid_dimensions()
        if axis_name == "column":
            self.state.gridColumnWeights = self.normalize_weight_list(weights, cols)
        elif axis_name == "row":
            self.state.gridRowWeights = self.normalize_weight_list(weights, rows)
        else:
            return
        self.state.gridSizingMode = "fit"
        self.normalize_grid_track_sizes(rows, cols)
        self.record_interaction(
            "workspace.layout_changed",
            source="grid_resize",
            payload={
                "change": f"{axis_name}_weights",
                "column_weights": list(self.state.gridColumnWeights or []),
                "row_weights": list(self.state.gridRowWeights or []),
                "workspace": self.interaction_workspace_location(),
            },
        )

    def commit_grid_track_resize_trigger(self, resize_payload="", **_):
        """Commit every axis changed by one pointer resize atomically."""

        payload = self.parse_canvas_payload(resize_payload, {})
        changes = payload.get("changes", []) if isinstance(payload, Mapping) else []
        if not isinstance(changes, list):
            return

        applied_axes = set()
        for change in changes[:2]:
            if not isinstance(change, Mapping):
                continue
            axis = str(change.get("axis", "") or "").strip().lower()
            if axis not in {"column", "row"} or axis in applied_axes:
                continue
            kind = str(change.get("kind", "") or "").strip().lower()
            values = change.get("values", "")
            if kind == "sizes":
                self.set_grid_track_sizes_trigger(axis, values)
            elif kind == "weights":
                self.set_grid_track_weights_trigger(axis, values)
            else:
                continue
            applied_axes.add(axis)

    def set_grid_layout_size(self, rows: int, cols: int, **_):
        if self.normalize_grid_layout_mode() == "freeform":
            return
        old_rows, old_cols = self.grid_dimensions()
        new_rows = clamp_int(rows, old_rows, self.GRID_MIN_ROWS, self.GRID_MAX_ROWS)
        new_cols = clamp_int(cols, old_cols, self.GRID_MIN_COLS, self.GRID_MAX_COLS)
        if new_rows == old_rows and new_cols == old_cols:
            return

        if self.normalize_grid_layout_mode() == "spanning":
            old_cells = self.normalize_grid_cells(
                self.state.gridCells, old_rows, old_cols
            )
            active = self.active_grid_index(old_rows * old_cols)
            new_active = -1
            if active >= 0:
                active_cell = old_cells[active]
                row = clamp_int(active_cell.get("grid_row", 1), 1, 1, old_rows)
                col = clamp_int(active_cell.get("grid_col", 1), 1, 1, old_cols)
                if row <= new_rows and col <= new_cols:
                    new_active = (row - 1) * new_cols + (col - 1)
            self.set_grid_layout(new_rows, new_cols, old_cells, new_active)
            return

        old_cells = self.normalize_grid_cells(self.state.gridCells, old_rows, old_cols)
        new_cells: List[Dict[str, Any]] = []
        for row in range(new_rows):
            for col in range(new_cols):
                if row < old_rows and col < old_cols:
                    new_cells.append(old_cells[row * old_cols + col])
                else:
                    new_cells.append(empty_grid_cell())

        active = self.active_grid_index(old_rows * old_cols)
        new_active = -1
        if active >= 0:
            active_row = active // old_cols
            active_col = active % old_cols
            if active_row < new_rows and active_col < new_cols:
                new_active = active_row * new_cols + active_col

        self.set_grid_layout(new_rows, new_cols, new_cells, new_active)

    def add_var_to_grid(self, var_name: str, **_):
        var = str(var_name or "").strip()
        if not var:
            return
        if self.normalize_grid_layout_mode() == "freeform":
            self.add_var_to_canvas(var, {}, sync_selection=True)
            return

        cells = self.normalize_grid_cells(self.state.gridCells)

        try:
            active = int(self.state.activeGridCell)
        except Exception:
            active = -1

        target = -1
        if self.is_valid_grid_index(active):
            if not str(
                cells[active].get("variable_id", "")
                or cells[active].get("variable_name", "")
                or ""
            ).strip():
                target = active

        if target < 0:
            for i, c in enumerate(cells):
                if not str(
                    c.get("variable_id", "") or c.get("variable_name", "") or ""
                ).strip():
                    target = i
                    break

        if target < 0:
            target = active if self.is_valid_grid_index(active) else 0

        source_row = {}
        if str(self.state.detailsSelectedVarId or "") == var:
            source_row = self.source_row_for_key(
                (self.state.selectedSourceKeys or [""])[0]
            )
        if self.maybe_handle_generated_scalar_plot(
            var,
            target,
            source_row=source_row or None,
            sync_selection=True,
        ):
            self.set_grid_selection([target], active=target)
            generated_cells = self.normalize_grid_cells(self.state.gridCells)
            self.record_visualization_assignment(
                target,
                generated_cells[target],
                source=self._interaction_assignment_source or "variable_add",
            )
            return

        try:
            assign_cell(
                cells,
                target,
                self.build_grid_cell_for_variable(var, source_row=source_row or None),
            )
        except Exception as e:
            err_cell = empty_grid_cell()
            err_cell["variable_id"] = var
            err_cell["variable_name"] = self.variable_label(var)
            err_cell["status"] = "error"
            err_cell["note"] = f"{type(e).__name__}: {e}"
            assign_cell(cells, target, err_cell)

        self.state.gridCells = self.normalize_grid_cells(cells)
        self.state.activeGridCell = target
        self.set_grid_selection([target], active=target)
        self.set_details_provenance_context(True)
        self.state.selectedVar = var
        self.state.draggedVar = var
        self.record_visualization_assignment(
            target,
            list(self.state.gridCells or [])[target],
            source=self._interaction_assignment_source or "variable_add",
        )

    def set_active_grid_cell(self, cell_index: int, ignore=0, multi=0, **_):
        try:
            if int(ignore):
                return
        except Exception:
            pass

        try:
            idx = int(cell_index)
        except Exception:
            return
        if not self.is_valid_grid_index(idx):
            return

        cells = self.normalize_grid_cells(self.state.gridCells)
        try:
            use_multi = bool(int(multi))
        except Exception:
            use_multi = False

        if use_multi:
            if not is_selectable_grid_cell(cells, idx):
                return
            selected = self.normalize_grid_selection(cells=cells)
            anchor = self.active_grid_index(len(cells))
            self.publish_grid_selection(
                grid_model.range_selection(cells, selected, anchor, idx)
            )
            self.state.activeGridCell = idx
            var = str(
                cells[idx].get("variable_id", "")
                or cells[idx].get("variable_name", "")
                or ""
            )
            if var:
                self.set_details_provenance_context(True)
                self.state.selectedVar = var
                self.state.draggedVar = var
                self.update_selected_var_panels(
                    var,
                    preferred_source_key=str(cells[idx].get("_source_key", "") or ""),
                    include_visualization_provenance=True,
                    preferred_visualization=str(
                        cells[idx].get("selected_visualization", "")
                        or cells[idx].get("visualization_name", "")
                        or ""
                    ),
                    provenance_tile=dict(cells[idx] or {}),
                )
            return

        self.state.activeGridCell = idx
        var = str(
            cells[idx].get("variable_id", "")
            or cells[idx].get("variable_name", "")
            or ""
        )
        if var:
            self.set_grid_selection([idx], active=idx)
            self.set_details_provenance_context(True)
            self.state.selectedVar = var
            self.state.draggedVar = var
            self.update_selected_var_panels(
                var,
                preferred_source_key=str(cells[idx].get("_source_key", "") or ""),
                include_visualization_provenance=True,
                preferred_visualization=str(
                    cells[idx].get("selected_visualization", "")
                    or cells[idx].get("visualization_name", "")
                    or ""
                ),
                provenance_tile=dict(cells[idx] or {}),
            )
            return

        selected = str(self.state.selectedVar or "").strip()
        if not selected:
            self.set_grid_selection([], active=idx)
            return

        source_row = {}
        if str(self.state.detailsSelectedVarId or "") == selected:
            source_row = self.source_row_for_key(
                (self.state.selectedSourceKeys or [""])[0]
            )
        if self.maybe_handle_generated_scalar_plot(
            selected,
            idx,
            source_row=source_row or None,
            sync_selection=True,
        ):
            self.set_grid_selection([idx], active=idx)
            generated_cells = self.normalize_grid_cells(self.state.gridCells)
            self.record_visualization_assignment(
                idx,
                generated_cells[idx],
                source=self._interaction_assignment_source or "empty_cell_selection",
            )
            return

        try:
            assign_cell(
                cells,
                idx,
                self.build_grid_cell_for_variable(
                    selected, source_row=source_row or None
                ),
            )
        except Exception as e:
            err_cell = empty_grid_cell()
            err_cell["variable_id"] = selected
            err_cell["variable_name"] = self.variable_label(selected)
            err_cell["status"] = "error"
            err_cell["note"] = f"{type(e).__name__}: {e}"
            assign_cell(cells, idx, err_cell)
        self.state.gridCells = self.normalize_grid_cells(cells)
        self.set_grid_selection([idx], active=idx)
        self.record_visualization_assignment(
            idx,
            list(self.state.gridCells or [])[idx],
            source=self._interaction_assignment_source or "empty_cell_selection",
        )

    def toggle_timeline_driver_cell(self, cell_index: int, **_):
        try:
            idx = int(cell_index)
        except Exception:
            return
        if not self.is_valid_grid_index(idx):
            return
        cells = self.normalize_grid_cells(self.state.gridCells)
        try:
            current = int(self.state.timelineDriverCell)
        except Exception:
            current = -1
        self.state.timelineDriverCell = toggle_timeline_driver(cells, current, idx)
        if int(self.state.timelineDriverCell) != current:
            self.record_interaction(
                "workspace.timeline_driver_changed",
                source="cell_controls",
                payload={
                    "previous_cell": current,
                    "current_cell": int(self.state.timelineDriverCell),
                    "workspace": self.interaction_workspace_location(idx),
                },
            )

    def clear_grid_cell(self, cell_index: int, **_):
        try:
            idx = int(cell_index)
        except Exception:
            return
        if not self.is_valid_grid_index(idx):
            return

        cells = self.normalize_grid_cells(self.state.gridCells)
        previous = dict(cells[idx] or {})
        if self.normalize_grid_layout_mode() == "freeform":
            cells.pop(idx)
            self.state.gridCells = cells
            selected = []
            for item in list(getattr(self.state, "selectedGridCellIndices", []) or []):
                try:
                    selected_index = int(item)
                except (TypeError, ValueError):
                    continue
                if selected_index != idx:
                    selected.append(
                        selected_index - 1 if selected_index > idx else selected_index
                    )
            self.publish_grid_selection(
                self.normalize_grid_selection(selected, cells)
            )
            try:
                active = int(getattr(self.state, "activeGridCell", -1))
            except Exception:
                active = -1
            if active == idx:
                self.state.activeGridCell = -1
            elif active > idx:
                self.state.activeGridCell = active - 1
            try:
                driver = int(getattr(self.state, "timelineDriverCell", -1))
            except Exception:
                driver = -1
            if driver == idx:
                self.state.timelineDriverCell = -1
            elif driver > idx:
                self.state.timelineDriverCell = driver - 1
            self.state.canvasLayoutRevision = int(
                getattr(self.state, "canvasLayoutRevision", 0) or 0
            ) + 1
        else:
            self.clear_timeline_driver_if_cell(idx)
            assign_cell(cells, idx, empty_grid_cell())
            self.state.gridCells = self.normalize_grid_cells(cells)
            self.publish_grid_selection(
                [
                    item
                    for item in self.normalize_grid_selection(
                        cells=list(self.state.gridCells or [])
                    )
                    if item != idx
                ]
            )
        variable_id = str(
            previous.get("variable_id", "")
            or previous.get("variable_name", "")
            or ""
        )
        if variable_id:
            assignment = self.interaction_assignment_reference(idx)
            self.record_interaction(
                "visualization.removed",
                source="cell_controls",
                payload={
                    "variable_id": variable_id,
                    "visualization_id": str(
                        previous.get("selected_visualization", "")
                        or previous.get("visualization_name", "")
                        or ""
                    ),
                    "query_id": self._interaction_query_id,
                    "workspace": self.interaction_workspace_location(idx),
                    **assignment,
                },
            )
            self.clear_interaction_assignment(idx)

    def move_grid_cell(self, from_index: int, to_index: int, **_):
        try:
            src = int(from_index)
            dst = int(to_index)
        except Exception:
            return
        if not self.is_valid_grid_index(src) or not self.is_valid_grid_index(dst):
            return
        if src == dst:
            return

        cells = self.normalize_grid_cells(self.state.gridCells)
        source = dict(cells[src] or {})
        if not str(
            source.get("variable_id", "") or source.get("variable_name", "") or ""
        ).strip():
            return

        # Move + overwrite: destination takes source tile, source is cleared.
        self.clear_timeline_driver_if_cell(src)
        self.clear_timeline_driver_if_cell(dst)
        assign_cell(cells, dst, source)
        assign_cell(cells, src, empty_grid_cell())
        self.state.gridCells = self.normalize_grid_cells(cells)
        self.state.activeGridCell = dst
        self.set_grid_selection([dst], active=dst)
        self.record_interaction(
            "workspace.cell_moved",
            source="grid_drag",
            payload={
                "source_cell": src,
                "destination_cell": dst,
                "variable_id": str(
                    source.get("variable_id", "")
                    or source.get("variable_name", "")
                    or ""
                ),
                "visualization_id": str(
                    source.get("selected_visualization", "")
                    or source.get("visualization_name", "")
                    or ""
                ),
                "workspace": self.interaction_workspace_location(dst),
            },
        )
        self.clear_interaction_assignment()

    def move_grid_cell_trigger(self, from_index, to_index, **_):
        self.move_grid_cell(from_index, to_index)

    def add_grid_row(self, **_):
        rows, cols = self.grid_dimensions()
        if rows >= self.GRID_MAX_ROWS:
            return

        cells = self.normalize_grid_cells(self.state.gridCells, rows, cols)
        active = self.active_grid_index(rows * cols)
        if self.normalize_grid_layout_mode() == "spanning":
            self.set_grid_layout(rows + 1, cols, cells, active)
            return

        new_cells = list(cells)
        new_cells.extend(empty_grid_cell() for _ in range(cols))
        self.set_grid_layout(rows + 1, cols, new_cells, active)

    def active_after_spanning_axis_removal(
        self,
        cells: List[Dict[str, Any]],
        active: int,
        rows: int,
        cols: int,
        remove_row: Optional[int] = None,
        remove_col: Optional[int] = None,
    ) -> int:
        if active < 0 or active >= len(cells):
            return -1
        cell = dict(cells[active] or {})
        if bool(cell.get("grid_hidden", False)):
            return -1

        row = clamp_int(cell.get("grid_row", 1), 1, 1, rows)
        col = clamp_int(cell.get("grid_col", 1), 1, 1, cols)
        row_span = clamp_int(cell.get("row_span", 1), 1, 1, max(1, rows - row + 1))
        col_span = clamp_int(cell.get("col_span", 1), 1, 1, max(1, cols - col + 1))

        if remove_row is not None:
            removed = remove_row + 1
            if row > removed:
                row -= 1
            elif row <= removed < row + row_span:
                row_span -= 1
                if row_span < 1:
                    return -1

        if remove_col is not None:
            removed = remove_col + 1
            if col > removed:
                col -= 1
            elif col <= removed < col + col_span:
                col_span -= 1
                if col_span < 1:
                    return -1

        new_cols = cols - 1 if remove_col is not None else cols
        new_rows = rows - 1 if remove_row is not None else rows
        if row < 1 or col < 1 or row > new_rows or col > new_cols:
            return -1
        return (row - 1) * new_cols + (col - 1)

    def remove_spanning_axis(
        self,
        cells: List[Dict[str, Any]],
        rows: int,
        cols: int,
        remove_row: Optional[int] = None,
        remove_col: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        new_rows = rows - 1 if remove_row is not None else rows
        new_cols = cols - 1 if remove_col is not None else cols
        adjusted: List[Dict[str, Any]] = []

        for raw_cell in cells:
            cell = dict(raw_cell or {})
            if bool(cell.get("grid_hidden", False)):
                continue

            row = clamp_int(cell.get("grid_row", 1), 1, 1, rows)
            col = clamp_int(cell.get("grid_col", 1), 1, 1, cols)
            row_span = clamp_int(cell.get("row_span", 1), 1, 1, max(1, rows - row + 1))
            col_span = clamp_int(cell.get("col_span", 1), 1, 1, max(1, cols - col + 1))

            if remove_row is not None:
                removed = remove_row + 1
                if row > removed:
                    row -= 1
                elif row <= removed < row + row_span:
                    row_span -= 1
                    if row_span < 1:
                        continue

            if remove_col is not None:
                removed = remove_col + 1
                if col > removed:
                    col -= 1
                elif col <= removed < col + col_span:
                    col_span -= 1
                    if col_span < 1:
                        continue

            if row < 1 or col < 1 or row > new_rows or col > new_cols:
                continue

            cell["grid_row"] = row
            cell["grid_col"] = col
            cell["row_span"] = min(row_span, max(1, new_rows - row + 1))
            cell["col_span"] = min(col_span, max(1, new_cols - col + 1))
            cell["grid_hidden"] = False
            adjusted.append(cell)

        return rebuild_spanning_cells(adjusted, new_rows, new_cols)

    def delete_grid_row(self, **_):
        rows, cols = self.grid_dimensions()
        if rows <= self.GRID_MIN_ROWS:
            return

        cells = self.normalize_grid_cells(self.state.gridCells, rows, cols)
        active = self.active_grid_index(rows * cols)
        remove_row = (active // cols) if active >= 0 else rows - 1
        self.drop_grid_track("row", remove_row)

        if self.normalize_grid_layout_mode() == "spanning":
            new_active = self.active_after_spanning_axis_removal(
                cells,
                active,
                rows,
                cols,
                remove_row=remove_row,
            )
            self.set_grid_layout(
                rows - 1,
                cols,
                self.remove_spanning_axis(cells, rows, cols, remove_row=remove_row),
                new_active,
            )
            return

        new_cells: List[Dict[str, Any]] = []
        for row in range(rows):
            if row == remove_row:
                continue
            start = row * cols
            new_cells.extend(cells[start : start + cols])

        new_active = -1
        if active >= 0:
            active_row = active // cols
            active_col = active % cols
            if active_row != remove_row:
                new_row = active_row - (1 if active_row > remove_row else 0)
                new_active = new_row * cols + active_col

        self.set_grid_layout(rows - 1, cols, new_cells, new_active)

    def add_grid_column(self, **_):
        rows, cols = self.grid_dimensions()
        if cols >= self.GRID_MAX_COLS:
            return

        cells = self.normalize_grid_cells(self.state.gridCells, rows, cols)
        active = self.active_grid_index(rows * cols)
        if self.normalize_grid_layout_mode() == "spanning":
            self.set_grid_layout(rows, cols + 1, cells, active)
            return

        new_cells: List[Dict[str, Any]] = []
        for row in range(rows):
            start = row * cols
            new_cells.extend(cells[start : start + cols])
            new_cells.append(empty_grid_cell())

        new_active = -1
        if active >= 0:
            active_row = active // cols
            active_col = active % cols
            new_active = active_row * (cols + 1) + active_col

        self.set_grid_layout(rows, cols + 1, new_cells, new_active)

    def delete_grid_column(self, **_):
        rows, cols = self.grid_dimensions()
        if cols <= self.GRID_MIN_COLS:
            return

        cells = self.normalize_grid_cells(self.state.gridCells, rows, cols)
        active = self.active_grid_index(rows * cols)
        remove_col = (active % cols) if active >= 0 else cols - 1
        self.drop_grid_track("column", remove_col)

        if self.normalize_grid_layout_mode() == "spanning":
            new_active = self.active_after_spanning_axis_removal(
                cells,
                active,
                rows,
                cols,
                remove_col=remove_col,
            )
            self.set_grid_layout(
                rows,
                cols - 1,
                self.remove_spanning_axis(cells, rows, cols, remove_col=remove_col),
                new_active,
            )
            return

        new_cells: List[Dict[str, Any]] = []
        for row in range(rows):
            start = row * cols
            for col in range(cols):
                if col != remove_col:
                    new_cells.append(cells[start + col])

        new_active = -1
        if active >= 0:
            active_row = active // cols
            active_col = active % cols
            if active_col != remove_col:
                new_col = active_col - (1 if active_col > remove_col else 0)
                new_active = active_row * (cols - 1) + new_col

        self.set_grid_layout(rows, cols - 1, new_cells, new_active)

    def can_place_span(
        self,
        cells: List[Dict[str, Any]],
        idx: int,
        row: int,
        col: int,
        row_span: int,
        col_span: int,
        rows: int,
        cols: int,
    ) -> bool:
        if row < 1 or col < 1 or row_span < 1 or col_span < 1:
            return False
        if row + row_span - 1 > rows or col + col_span - 1 > cols:
            return False

        requested = set(area_slots(row, col, row_span, col_span, cols))
        for other_idx, raw_cell in enumerate(cells):
            if other_idx == idx:
                continue
            cell = dict(raw_cell or {})
            if bool(cell.get("grid_hidden", False)):
                continue
            other_row = clamp_int(cell.get("grid_row", 1), 1, 1, rows)
            other_col = clamp_int(cell.get("grid_col", 1), 1, 1, cols)
            other_row_span = clamp_int(
                cell.get("row_span", 1), 1, 1, max(1, rows - other_row + 1)
            )
            other_col_span = clamp_int(
                cell.get("col_span", 1), 1, 1, max(1, cols - other_col + 1)
            )
            if (
                not cell_has_content(cell)
                and other_row_span == 1
                and other_col_span == 1
            ):
                continue
            other_slots = set(
                area_slots(other_row, other_col, other_row_span, other_col_span, cols)
            )
            if requested.intersection(other_slots):
                return False
        return True

    def update_grid_cell_span(
        self,
        cell_index: int,
        row_span: Optional[int] = None,
        col_span: Optional[int] = None,
    ) -> bool:
        try:
            idx = int(cell_index)
        except Exception:
            return False
        if not self.is_valid_grid_index(idx):
            return False
        if self.normalize_grid_layout_mode() != "spanning":
            return False

        rows, cols = self.grid_dimensions()
        cells = self.normalize_grid_cells(self.state.gridCells, rows, cols)
        cell = dict(cells[idx] or {})
        if bool(cell.get("grid_hidden", False)):
            return False

        row = clamp_int(cell.get("grid_row", 1), 1, 1, rows)
        col = clamp_int(cell.get("grid_col", 1), 1, 1, cols)
        new_row_span = clamp_int(
            row_span if row_span is not None else cell.get("row_span", 1),
            1,
            1,
            max(1, rows - row + 1),
        )
        new_col_span = clamp_int(
            col_span if col_span is not None else cell.get("col_span", 1),
            1,
            1,
            max(1, cols - col + 1),
        )
        if not self.can_place_span(
            cells, idx, row, col, new_row_span, new_col_span, rows, cols
        ):
            return False

        cell["row_span"] = new_row_span
        cell["col_span"] = new_col_span
        cells[idx] = cell
        self.state.gridCells = rebuild_spanning_cells(cells, rows, cols)
        self.state.activeGridCell = idx
        self.publish_grid_selection(
            self.normalize_grid_selection(cells=list(self.state.gridCells or []))
        )
        self.record_interaction(
            "workspace.cell_spanned",
            source="cell_controls",
            payload={
                "cell_index": idx,
                "row_span": new_row_span,
                "column_span": new_col_span,
                "workspace": self.interaction_workspace_location(idx),
            },
        )
        return True

    def span_grid_cell_right(self, cell_index: int, **_):
        rows, cols = self.grid_dimensions()
        cells = self.normalize_grid_cells(self.state.gridCells, rows, cols)
        try:
            idx = int(cell_index)
        except Exception:
            return
        if not self.is_valid_grid_index(idx):
            return
        cell = dict(cells[idx] or {})
        self.update_grid_cell_span(
            idx, col_span=clamp_int(cell.get("col_span", 1), 1, 1, cols) + 1
        )

    def span_grid_cell_down(self, cell_index: int, **_):
        rows, cols = self.grid_dimensions()
        cells = self.normalize_grid_cells(self.state.gridCells, rows, cols)
        try:
            idx = int(cell_index)
        except Exception:
            return
        if not self.is_valid_grid_index(idx):
            return
        cell = dict(cells[idx] or {})
        self.update_grid_cell_span(
            idx, row_span=clamp_int(cell.get("row_span", 1), 1, 1, rows) + 1
        )

    def shrink_grid_cell_width(self, cell_index: int, **_):
        rows, cols = self.grid_dimensions()
        cells = self.normalize_grid_cells(self.state.gridCells, rows, cols)
        try:
            idx = int(cell_index)
        except Exception:
            return
        if not self.is_valid_grid_index(idx):
            return
        cell = dict(cells[idx] or {})
        self.update_grid_cell_span(
            idx, col_span=clamp_int(cell.get("col_span", 1), 1, 1, cols) - 1
        )

    def shrink_grid_cell_height(self, cell_index: int, **_):
        rows, cols = self.grid_dimensions()
        cells = self.normalize_grid_cells(self.state.gridCells, rows, cols)
        try:
            idx = int(cell_index)
        except Exception:
            return
        if not self.is_valid_grid_index(idx):
            return
        cell = dict(cells[idx] or {})
        self.update_grid_cell_span(
            idx, row_span=clamp_int(cell.get("row_span", 1), 1, 1, rows) - 1
        )

    def reset_grid_cell_span(self, cell_index: int, **_):
        self.update_grid_cell_span(cell_index, row_span=1, col_span=1)

    def assign_var_to_grid_cell(
        self, cell_index: int, var_name: str, sync_selection: bool = True, **_
    ):
        try:
            idx = int(cell_index)
        except Exception:
            return
        if not self.is_valid_grid_index(idx):
            return

        var = str(var_name or "").strip()
        if not var:
            var = str(self.state.draggedVar or "").strip()
        if not var:
            var = str(self.state.selectedVar or "").strip()
        if not var:
            return

        cells = self.normalize_grid_cells(self.state.gridCells)
        source_row = {}
        if str(self.state.detailsSelectedVarId or "") == var:
            source_row = self.source_row_for_key(
                (self.state.selectedSourceKeys or [""])[0]
            )
        if self.maybe_handle_generated_scalar_plot(
            var,
            idx,
            source_row=source_row or None,
            sync_selection=sync_selection,
        ):
            self.set_grid_selection([idx], active=idx)
            generated_cells = self.normalize_grid_cells(self.state.gridCells)
            self.record_visualization_assignment(
                idx,
                generated_cells[idx],
                source=self._interaction_assignment_source
                or ("grid_drop" if not sync_selection else "cell_assignment"),
            )
            return

        try:
            assign_cell(
                cells,
                idx,
                self.build_grid_cell_for_variable(var, source_row=source_row or None),
            )
        except Exception as e:
            err_cell = empty_grid_cell()
            err_cell["variable_id"] = var
            err_cell["variable_name"] = self.variable_label(var)
            err_cell["status"] = "error"
            err_cell["note"] = f"{type(e).__name__}: {e}"
            assign_cell(cells, idx, err_cell)
        self.state.gridCells = self.normalize_grid_cells(cells)
        self.state.activeGridCell = idx
        self.set_grid_selection([idx], active=idx)
        if sync_selection:
            self.set_details_provenance_context(True)
            self.state.selectedVar = var
            self.state.draggedVar = var
        self.record_visualization_assignment(
            idx,
            list(self.state.gridCells or [])[idx],
            source=self._interaction_assignment_source
            or ("grid_drop" if not sync_selection else "cell_assignment"),
        )

    def assign_var_to_grid_cell_trigger(self, var_name, cell_index, **_):
        self.assign_var_to_grid_cell(cell_index, var_name, sync_selection=False)
        # After drag/drop, clear variable highlight in the left panel.
        self.state.selectedVar = ""
        self.state.draggedVar = ""

    def pick_grid_cell_visualization(self, cell_index: int, value=None, **_):
        try:
            idx = int(cell_index)
        except Exception:
            return
        if not self.is_valid_grid_index(idx):
            return

        cells = self.normalize_grid_cells(self.state.gridCells)
        previous_cell = dict(cells[idx] or {})
        var = str(
            cells[idx].get("variable_id", "")
            or cells[idx].get("variable_name", "")
            or ""
        ).strip()
        if not var:
            return

        picked = value
        if isinstance(picked, dict):
            picked = picked.get("value", "")
        picked = str(picked or "")

        try:
            existing_cell = cells[idx]
            current_filter = self.source_filter_from_cell(existing_cell)
            source_row = {}
            if current_filter:
                current_vis_names = self.visualization_names_for_source_filter(
                    var, current_filter
                )
                if picked not in current_vis_names:
                    source_row = self.source_row_for_visualization_pick(var, picked)

            if source_row:
                new_cell = self.build_grid_cell_for_variable(
                    var, preferred_vis=picked, source_row=source_row
                )
            else:
                new_cell = self.build_grid_cell_for_variable(
                    var, preferred_vis=picked, existing_cell=existing_cell
                )
            assign_cell(cells, idx, new_cell)
        except Exception as e:
            err_cell = empty_grid_cell()
            err_cell["variable_id"] = var
            err_cell["variable_name"] = self.variable_label(var)
            err_cell["status"] = "error"
            err_cell["note"] = f"{type(e).__name__}: {e}"
            assign_cell(cells, idx, err_cell)

        self.state.gridCells = self.normalize_grid_cells(cells)
        self.state.activeGridCell = idx
        self.set_grid_selection([idx], active=idx)
        self.set_details_provenance_context(True)
        self.state.selectedVar = var
        current_cell = dict(list(self.state.gridCells or [])[idx] or {})
        self.update_selected_var_panels(
            var,
            preferred_source_key=str(current_cell.get("_source_key", "") or ""),
            include_visualization_provenance=True,
            preferred_visualization=str(
                current_cell.get("selected_visualization", "")
                or current_cell.get("visualization_name", "")
                or ""
            ),
            provenance_tile=current_cell,
        )
        previous_visualization = str(
            previous_cell.get("selected_visualization", "")
            or previous_cell.get("visualization_name", "")
            or ""
        )
        selected_visualization = str(
            current_cell.get("selected_visualization", "")
            or current_cell.get("visualization_name", "")
            or ""
        )
        if (
            str(current_cell.get("status", "") or "") != "error"
            and selected_visualization
            and selected_visualization != previous_visualization
        ):
            assignment = self.interaction_assignment_reference(idx)
            self.record_interaction(
                "visualization.changed",
                source="grid_menu",
                payload={
                    "variable_id": var,
                    "previous_visualization": previous_visualization,
                    "selected_visualization": selected_visualization,
                    "candidate_visualizations": list(
                        current_cell.get("visualization_options", []) or []
                    ),
                    "query_id": self._interaction_query_id,
                    "workspace": self.interaction_workspace_location(idx),
                    **assignment,
                },
            )
