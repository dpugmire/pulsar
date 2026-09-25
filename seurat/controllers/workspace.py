"""Tabbed workspace layout plus portable JSON save and load behavior."""

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

from seurat.native_file_dialog import (
    choose_workspace_load_path,
    choose_workspace_save_path,
)
from seurat.models import canvas_layout
from seurat.models import grid as grid_model
from seurat.models.timeline import toggle_timeline_driver
from seurat.models.workspace_layout import (
    active_pane_and_tab,
    add_workspace_tab as add_workspace_tab_model,
    apply_grid_snapshot,
    close_workspace_pane as close_workspace_pane_model,
    close_workspace_tab as close_workspace_tab_model,
    empty_grid_snapshot,
    grid_snapshot,
    initial_workspace_layout,
    move_workspace_grid_cell as move_workspace_grid_cell_model,
    move_workspace_tab as move_workspace_tab_model,
    move_workspace_tab_to_pane as move_workspace_tab_to_pane_model,
    normalized_workspace_root,
    normalized_tab_title,
    pane_and_tab,
    reorder_workspace_tab as reorder_workspace_tab_model,
    resize_workspace_split as resize_workspace_split_model,
    split_workspace as split_workspace_model,
    split_workspace_tab as split_workspace_tab_model,
    workspace_geometry,
)
from seurat.models.workspace_state import (
    WorkspaceStateError,
    default_workspace_filename,
    history_document,
    parse_workspace_document,
    validate_history_document,
    validate_live_history_state,
    validate_workspace_campaign,
    workspace_json,
)
from seurat.state import clear_right_panes


MAX_WORKSPACE_STATE_BYTES = 5 * 1024 * 1024

_HISTORY_TRANSIENT_GRID_FIELDS = (
    "canvas_snap_to_grid",
    "canvas_nudge_others",
    "canvas_show_grid",
    "canvas_zoom",
    "canvas_fit_to_view",
    "active_cell",
    "selected_cells",
    "selected_cell_map",
)
_HISTORY_TRANSIENT_GRID_DEFAULTS = {
    "canvas_snap_to_grid": True,
    "canvas_nudge_others": True,
    "canvas_show_grid": False,
    "canvas_zoom": canvas_layout.CANVAS_ZOOM_DEFAULT,
    "canvas_fit_to_view": False,
    "active_cell": -1,
    "selected_cells": [],
    "selected_cell_map": {},
}


class WorkspaceControllerMixin:
    ACTION_BINDINGS = (
        ("activate_workspace_tab", "activate_workspace_tab"),
        ("add_workspace_tab", "add_workspace_tab"),
        ("rename_workspace_tab", "rename_workspace_tab"),
        ("close_workspace_tab", "close_workspace_tab"),
        ("split_workspace_pane", "split_workspace_pane"),
        ("close_workspace_pane", "close_workspace_pane"),
        ("move_workspace_tab", "move_workspace_tab"),
        ("save_workspace_state", "save_workspace_state"),
        ("save_workspace_state_as", "save_workspace_state_as"),
        ("load_workspace_state", "load_workspace_state"),
    )
    TRIGGER_BINDINGS = (
        ("move_workspace_grid_cell_trigger", "move_workspace_grid_cell"),
        ("move_workspace_canvas_tile_trigger", "move_workspace_canvas_tile"),
        ("move_workspace_tab_trigger", "move_workspace_tab"),
        ("reorder_workspace_tab_trigger", "reorder_workspace_tab"),
        ("resize_workspace_split_trigger", "resize_workspace_split"),
        ("split_workspace_tab_trigger", "split_workspace_tab"),
    )
    STATE_CHANGE_BINDINGS = ()
    HISTORY_ACTIONS = {
        "add_workspace_tab": "Add tab",
        "rename_workspace_tab": "Rename tab",
        "close_workspace_tab": "Close tab",
        "split_workspace_pane": "Split pane",
        "close_workspace_pane": "Close pane",
        "move_workspace_tab": "Move tab",
    }
    HISTORY_TRIGGERS = {
        "move_workspace_grid_cell_trigger": "Move plot between panes",
        "move_workspace_canvas_tile_trigger": "Move plot between panes",
        "move_workspace_tab_trigger": "Move tab",
        "reorder_workspace_tab_trigger": "Reorder tab",
        "resize_workspace_split_trigger": "Resize pane",
        "split_workspace_tab_trigger": "Split tab",
    }

    def capture_workspace_history(self) -> Dict[str, Any]:
        return history_document(self.state)

    def validate_workspace_history(self) -> None:
        validate_live_history_state(self.state)

    @staticmethod
    def _workspace_grids_by_tab(layout: Mapping[str, Any]) -> Dict[str, Any]:
        result = {}
        for pane in list(layout.get("panes", []) or []):
            for tab in list(pane.get("tabs", []) or []):
                tab_id = str(tab.get("id", "") or "")
                grid = tab.get("grid", {})
                if tab_id and isinstance(grid, Mapping):
                    result[tab_id] = grid
        return result

    def restore_workspace_history(self, document: Mapping[str, Any]) -> None:
        """Restore one validated semantic snapshot and rebuild derived tiles."""

        validated = validate_history_document(document)
        current_layout = self._stash_active_workspace_grid()
        current_pane_id = str(current_layout.get("active_pane_id", "") or "")
        current_tab_id = str(current_layout.get("active_tab_id", "") or "")
        current_grids = self._workspace_grids_by_tab(current_layout)
        saved_workspace = validated["workspace"]

        panes = []
        for saved_pane in list(saved_workspace.get("panes", []) or []):
            tabs = []
            for saved_tab in list(saved_pane.get("tabs", []) or []):
                tab_id = str(saved_tab.get("id", "") or "")
                runtime = self._runtime_grid_from_document(
                    saved_tab.get("grid", {})
                )
                current = current_grids.get(
                    tab_id, _HISTORY_TRANSIENT_GRID_DEFAULTS
                )
                for field in _HISTORY_TRANSIENT_GRID_FIELDS:
                    if field in current:
                        runtime[field] = deepcopy(current[field])
                runtime["canvas_layout_revision"] = int(
                    current.get("canvas_layout_revision", 0) or 0
                ) + 1
                runtime["needs_refresh"] = True
                tabs.append(
                    {
                        "id": tab_id,
                        "title": normalized_tab_title(
                            saved_tab.get("title", ""), "View"
                        ),
                        "grid": runtime,
                    }
                )
            panes.append(
                {
                    "id": str(saved_pane.get("id", "") or ""),
                    "active_tab_id": str(
                        saved_pane.get("active_tab_id", "") or ""
                    ),
                    "tabs": tabs,
                }
            )

        layout = {
            "root": deepcopy(saved_workspace.get("root", {})),
            "split_direction": str(
                saved_workspace.get("split_direction", "none") or "none"
            ),
            "split_ratio": float(
                saved_workspace.get("split_ratio", 0.5) or 0.5
            ),
            "active_pane_id": str(
                saved_workspace.get("active_pane_id", "") or ""
            ),
            "active_tab_id": str(
                saved_workspace.get("active_tab_id", "") or ""
            ),
            "panes": panes,
        }
        layout["root"] = normalized_workspace_root(layout)
        focused_pane, focused_tab = pane_and_tab(
            layout, current_pane_id, current_tab_id
        )
        if focused_pane is not None and focused_tab is not None:
            focused_pane["active_tab_id"] = current_tab_id
            layout["active_pane_id"] = current_pane_id
            layout["active_tab_id"] = current_tab_id
        self._publish_workspace_layout(layout)
        if not self._activate_workspace_target(
            layout["active_pane_id"],
            layout["active_tab_id"],
            stash=False,
        ):
            raise WorkspaceStateError(
                "History snapshot does not contain its active workspace tab"
            )
        self.clear_context_menu_state()

    def _workspace_layout(self) -> Dict[str, Any]:
        layout = getattr(self.state, "workspaceLayout", {})
        return deepcopy(layout) if isinstance(layout, Mapping) else {}

    def _publish_workspace_layout(self, layout: Mapping[str, Any]) -> None:
        published = deepcopy(dict(layout))
        root = normalized_workspace_root(published)
        published["root"] = root
        published["split_direction"] = (
            root.get("direction", "none") if root.get("kind") == "split" else "none"
        )
        published["split_ratio"] = (
            float(root.get("ratio", 0.5)) if root.get("kind") == "split" else 0.5
        )
        frames, splitters = workspace_geometry(published)
        self.state.workspaceLayout = published
        self.state.workspacePanes = deepcopy(list(published.get("panes", []) or []))
        self.state.workspacePaneFrames = deepcopy(frames)
        self.state.workspaceSplitters = deepcopy(list(splitters))
        self.state.workspaceSplitDirection = str(
            published.get("split_direction", "none") or "none"
        )
        self.state.workspaceSplitRatio = float(
            published.get("split_ratio", 0.5) or 0.5
        )
        self.state.workspaceActivePaneId = str(
            published.get("active_pane_id", "") or ""
        )
        self.state.workspaceActiveTabId = str(
            published.get("active_tab_id", "") or ""
        )

    def _stash_active_workspace_grid(self) -> Dict[str, Any]:
        layout = self._workspace_layout()
        _pane, tab = active_pane_and_tab(layout)
        if tab is not None:
            tab["grid"] = grid_snapshot(self.state)
        self._publish_workspace_layout(layout)
        return layout

    def _load_workspace_grid(self, snapshot: Mapping[str, Any]) -> None:
        needs_refresh = bool(snapshot.get("needs_refresh", False))
        apply_grid_snapshot(self.state, snapshot)
        self.normalize_canvas_settings()
        rows, cols = self.grid_dimensions()
        self.normalize_grid_track_sizes(rows, cols)
        self.state.gridCells = self.normalize_grid_cells(
            list(getattr(self.state, "gridCells", []) or []), rows, cols
        )
        try:
            active = int(getattr(self.state, "activeGridCell", -1))
        except Exception:
            active = -1
        self.state.activeGridCell = (
            active if self.is_valid_grid_index(active) else -1
        )
        self.publish_grid_selection(
            self.normalize_grid_selection(cells=list(self.state.gridCells or []))
        )
        if needs_refresh:
            self.refresh_grid_cells()

    def _runtime_grid_from_document(
        self, saved_grid: Mapping[str, Any]
    ) -> Dict[str, Any]:
        runtime = empty_grid_snapshot(grid_snapshot(self.state))
        try:
            rows = max(
                self.GRID_MIN_ROWS,
                min(self.GRID_MAX_ROWS, int(saved_grid.get("rows", 3))),
            )
        except Exception:
            rows = 3
        try:
            cols = max(
                self.GRID_MIN_COLS,
                min(self.GRID_MAX_COLS, int(saved_grid.get("columns", 3))),
            )
        except Exception:
            cols = 3
        requested_layout_mode = str(
            saved_grid.get(
                "layout_mode", grid_model.DEFAULT_GRID_LAYOUT_MODE
            )
            or grid_model.DEFAULT_GRID_LAYOUT_MODE
        )
        layout_mode = (
            requested_layout_mode
            if requested_layout_mode in {"uniform", "spanning", "freeform"}
            else grid_model.DEFAULT_GRID_LAYOUT_MODE
        )
        sizing_mode = (
            "fit" if str(saved_grid.get("sizing_mode", "")) == "fit" else "static"
        )
        cell_size = int(saved_grid.get("cell_size", 300) or 300)
        fit_minimum = int(
            saved_grid.get("fit_minimum_cell_size", 180) or 180
        )
        runtime.update(
            {
                "rows": rows,
                "columns": cols,
                "layout_mode": layout_mode,
                "canvas_columns": canvas_layout.normalize_columns(
                    saved_grid.get("canvas_columns", canvas_layout.CANVAS_COLUMNS)
                ),
                "canvas_row_height": canvas_layout.CANVAS_ROW_HEIGHT,
                "canvas_snap_to_grid": bool(
                    saved_grid.get("canvas_snap_to_grid", True)
                ),
                "canvas_nudge_others": bool(
                    saved_grid.get("canvas_nudge_others", True)
                ),
                "canvas_show_grid": bool(
                    saved_grid.get("canvas_show_grid", False)
                ),
                "canvas_zoom": canvas_layout.normalize_zoom(
                    saved_grid.get(
                        "canvas_zoom", canvas_layout.CANVAS_ZOOM_DEFAULT
                    )
                ),
                "canvas_fit_to_view": bool(
                    saved_grid.get("canvas_fit_to_view", False)
                ),
                "canvas_dwell_ms": canvas_layout.CANVAS_DWELL_MS,
                "canvas_snap_dead_zone": canvas_layout.CANVAS_SNAP_DEAD_ZONE,
                "canvas_transition_ms": canvas_layout.CANVAS_TRANSITION_MS,
                "canvas_layout_revision": 0,
                "sizing_mode": sizing_mode,
                "cell_size": cell_size,
                "fit_minimum_cell_size": fit_minimum,
                "column_sizes": self.normalize_size_list(
                    saved_grid.get("column_sizes", []),
                    cols,
                    cell_size,
                    int(runtime.get("minimum_cell_size", 80) or 80),
                    int(runtime.get("maximum_cell_size", 5000) or 5000),
                ),
                "row_sizes": self.normalize_size_list(
                    saved_grid.get("row_sizes", []),
                    rows,
                    cell_size + self.GRID_HEADER_HEIGHT,
                    int(runtime.get("minimum_cell_size", 80) or 80)
                    + self.GRID_HEADER_HEIGHT,
                    int(runtime.get("maximum_cell_size", 5000) or 5000)
                    + self.GRID_HEADER_HEIGHT,
                ),
                "column_weights": self.normalize_weight_list(
                    saved_grid.get("column_weights", []), cols
                ),
                "row_weights": self.normalize_weight_list(
                    saved_grid.get("row_weights", []), rows
                ),
            }
        )
        runtime["column_template"] = self.grid_template_from_sizes(
            runtime["column_sizes"]
        )
        runtime["row_template"] = self.grid_template_from_sizes(
            runtime["row_sizes"]
        )
        runtime["fit_column_template"] = self.grid_fit_template_from_weights(
            runtime["column_weights"], fit_minimum
        )
        runtime["fit_row_template"] = self.grid_fit_template_from_weights(
            runtime["row_weights"], fit_minimum + self.GRID_HEADER_HEIGHT
        )
        runtime["cells"] = self.normalize_grid_cells_for_workspace(
            list(saved_grid.get("cells", []) or []),
            rows,
            cols,
            layout_mode,
            bool(runtime["canvas_snap_to_grid"]),
            int(runtime["canvas_columns"]),
        )
        try:
            active = int(saved_grid.get("active_cell", -1))
        except Exception:
            active = -1
        cell_count = (
            len(runtime["cells"]) if layout_mode == "freeform" else rows * cols
        )
        runtime["active_cell"] = active if 0 <= active < cell_count else -1
        selected = self.normalize_grid_selection(
            list(saved_grid.get("selected_cells", []) or []), runtime["cells"]
        )
        runtime["selected_cells"] = selected
        runtime["selected_cell_map"] = {
            str(index): True for index in selected
        }
        try:
            driver = int(saved_grid.get("timeline_driver_cell", -1))
        except Exception:
            driver = -1
        runtime["timeline_driver_cell"] = (
            driver if 0 <= driver < cell_count else -1
        )
        runtime["needs_refresh"] = True
        return runtime

    def normalize_grid_cells_for_workspace(
        self,
        cells,
        rows: int,
        cols: int,
        layout_mode: str,
        canvas_snap: bool = True,
        canvas_columns: int = canvas_layout.CANVAS_COLUMNS,
    ):
        previous_mode = getattr(self.state, "gridLayoutMode", "uniform")
        previous_snap = getattr(self.state, "canvasSnapToGrid", True)
        previous_columns = getattr(
            self.state, "canvasCols", canvas_layout.CANVAS_COLUMNS
        )
        try:
            self.state.gridLayoutMode = layout_mode
            self.state.canvasSnapToGrid = bool(canvas_snap)
            self.state.canvasCols = canvas_layout.normalize_columns(canvas_columns)
            return self.normalize_grid_cells(cells, rows, cols)
        finally:
            self.state.gridLayoutMode = previous_mode
            self.state.canvasSnapToGrid = previous_snap
            self.state.canvasCols = previous_columns

    def _restore_workspace_layout(self, saved_workspace: Any) -> None:
        if not isinstance(saved_workspace, Mapping):
            self._publish_workspace_layout(
                initial_workspace_layout(grid_snapshot(self.state))
            )
            return

        active_pane_id = str(saved_workspace.get("active_pane_id", "") or "")
        active_tab_id = str(saved_workspace.get("active_tab_id", "") or "")
        panes = []
        for saved_pane in list(saved_workspace.get("panes", []) or []):
            tabs = []
            for saved_tab in list(saved_pane.get("tabs", []) or []):
                tab_id = str(saved_tab.get("id", "") or "")
                grid = (
                    grid_snapshot(self.state)
                    if tab_id == active_tab_id
                    else self._runtime_grid_from_document(
                        saved_tab.get("grid", {})
                    )
                )
                tabs.append(
                    {
                        "id": tab_id,
                        "title": normalized_tab_title(
                            saved_tab.get("title", ""), "View"
                        ),
                        "grid": grid,
                    }
                )
            panes.append(
                {
                    "id": str(saved_pane.get("id", "") or ""),
                    "active_tab_id": str(
                        saved_pane.get("active_tab_id", "") or ""
                    ),
                    "tabs": tabs,
                }
            )
        layout = {
            "split_direction": str(
                saved_workspace.get("split_direction", "none") or "none"
            ),
            "split_ratio": float(
                saved_workspace.get("split_ratio", 0.5) or 0.5
            ),
            "active_pane_id": active_pane_id,
            "active_tab_id": active_tab_id,
            "panes": panes,
        }
        if isinstance(saved_workspace.get("root"), Mapping):
            layout["root"] = deepcopy(dict(saved_workspace["root"]))
        layout["root"] = normalized_workspace_root(layout)
        self._publish_workspace_layout(layout)

    def _activate_workspace_target(
        self, pane_id: str, tab_id: str, *, stash: bool = True
    ) -> bool:
        layout = (
            self._stash_active_workspace_grid()
            if stash
            else self._workspace_layout()
        )
        pane, tab = pane_and_tab(layout, pane_id, tab_id)
        if pane is None or tab is None:
            return False
        pane["active_tab_id"] = tab["id"]
        layout["active_pane_id"] = pane["id"]
        layout["active_tab_id"] = tab["id"]
        self._publish_workspace_layout(layout)
        self._load_workspace_grid(tab.get("grid", {}))
        return True

    def activate_workspace_tab(self, pane_id: str, tab_id: str, **_):
        target_pane = str(pane_id or "")
        target_tab = str(tab_id or "")
        changed = (
            target_pane != str(getattr(self.state, "workspaceActivePaneId", "") or "")
            or target_tab != str(getattr(self.state, "workspaceActiveTabId", "") or "")
        )
        if self._activate_workspace_target(target_pane, target_tab) and changed:
            self.record_interaction(
                "workspace.tab_activated",
                source="tab_bar",
                payload={"pane_id": target_pane, "tab_id": target_tab},
            )

    def add_workspace_tab(self, pane_id: str = "", **_):
        layout = self._stash_active_workspace_grid()
        target_pane = str(pane_id or layout.get("active_pane_id", ""))
        layout, tab_id = add_workspace_tab_model(
            layout, target_pane, grid_snapshot(self.state)
        )
        self._publish_workspace_layout(layout)
        self._activate_workspace_target(
            str(layout.get("active_pane_id", "")), tab_id, stash=False
        )
        self.record_interaction(
            "workspace.tab_created",
            source="tab_bar",
            payload={"pane_id": target_pane, "tab_id": tab_id},
        )

    def rename_workspace_tab(
        self, pane_id: str, tab_id: str, title: str, **_
    ):
        layout = self._stash_active_workspace_grid()
        _pane, tab = pane_and_tab(layout, pane_id, tab_id)
        if tab is None or title is None:
            return
        previous_title = str(tab.get("title", "View"))
        tab["title"] = normalized_tab_title(title, previous_title)
        self._publish_workspace_layout(layout)
        if str(tab["title"]) == previous_title:
            return
        self.record_interaction(
            "workspace.tab_renamed",
            source="tab_menu",
            payload={
                "pane_id": str(pane_id or ""),
                "tab_id": str(tab_id or ""),
                "title_changed": True,
            },
        )

    def close_workspace_tab(
        self, pane_id: str, tab_id: str, confirmed: bool = True, **_
    ):
        if not confirmed:
            return
        layout = self._stash_active_workspace_grid()
        previous_layout = deepcopy(layout)
        layout = close_workspace_tab_model(layout, pane_id, tab_id)
        self._publish_workspace_layout(layout)
        self._activate_workspace_target(
            str(layout.get("active_pane_id", "")),
            str(layout.get("active_tab_id", "")),
            stash=False,
        )
        if layout != previous_layout:
            self.record_interaction(
                "workspace.tab_closed",
                source="tab_menu",
                payload={
                    "pane_id": str(pane_id or ""),
                    "tab_id": str(tab_id or ""),
                },
            )
            self.clear_interaction_assignment()

    def split_workspace_pane(
        self,
        direction: str = "horizontal",
        pane_id: str = "",
        **_,
    ):
        layout = self._stash_active_workspace_grid()
        layout, new_pane_id = split_workspace_model(
            layout,
            direction,
            grid_snapshot(self.state),
            pane_id=str(pane_id or layout.get("active_pane_id", "")),
        )
        self._publish_workspace_layout(layout)
        self._activate_workspace_target(
            str(layout.get("active_pane_id", "")),
            str(layout.get("active_tab_id", "")),
            stash=False,
        )
        if not new_pane_id:
            return
        self.record_interaction(
            "workspace.pane_split",
            source="pane_menu",
            payload={
                "source_pane_id": str(pane_id or ""),
                "new_pane_id": str(new_pane_id or ""),
                "direction": str(direction or "horizontal"),
            },
        )

    def split_workspace_tab(
        self,
        source_pane_id: str,
        tab_id: str,
        target_pane_id: str,
        direction: str,
        **_,
    ):
        layout = self._stash_active_workspace_grid()
        layout, new_pane_id = split_workspace_tab_model(
            layout,
            direction,
            grid_snapshot(self.state),
            source_pane_id,
            tab_id,
            target_pane_id,
        )
        if not new_pane_id:
            return
        self._publish_workspace_layout(layout)
        self._activate_workspace_target(
            str(layout.get("active_pane_id", "")),
            str(layout.get("active_tab_id", "")),
            stash=False,
        )
        self.record_interaction(
            "workspace.pane_split",
            source="tab_drag",
            payload={
                "source_pane_id": str(source_pane_id or ""),
                "target_pane_id": str(target_pane_id or ""),
                "new_pane_id": str(new_pane_id),
                "tab_id": str(tab_id or ""),
                "direction": (
                    "vertical" if str(direction) == "vertical" else "horizontal"
                ),
            },
        )
        self.clear_interaction_assignment()

    def close_workspace_pane(
        self, pane_id: str, confirmed: bool = True, **_
    ):
        if not confirmed:
            return
        layout = self._stash_active_workspace_grid()
        previous_layout = deepcopy(layout)
        layout = close_workspace_pane_model(layout, pane_id)
        self._publish_workspace_layout(layout)
        self._activate_workspace_target(
            str(layout.get("active_pane_id", "")),
            str(layout.get("active_tab_id", "")),
            stash=False,
        )
        if layout != previous_layout:
            self.record_interaction(
                "workspace.pane_closed",
                source="pane_menu",
                payload={"pane_id": str(pane_id or "")},
            )
            self.clear_interaction_assignment()

    def move_workspace_tab(
        self,
        pane_id: str,
        tab_id: str,
        destination_pane_id: str = "",
        insertion_index: Any = None,
        **_,
    ):
        layout = self._stash_active_workspace_grid()
        previous_layout = deepcopy(layout)
        if destination_pane_id:
            layout = move_workspace_tab_to_pane_model(
                layout,
                pane_id,
                tab_id,
                destination_pane_id,
                insertion_index,
            )
        else:
            layout = move_workspace_tab_model(layout, pane_id, tab_id)
        self._publish_workspace_layout(layout)
        self._activate_workspace_target(
            str(layout.get("active_pane_id", "")),
            str(layout.get("active_tab_id", "")),
            stash=False,
        )
        if layout != previous_layout:
            self.record_interaction(
                "workspace.tab_moved",
                source="tab_drag",
                payload={
                    "source_pane_id": str(pane_id or ""),
                    "destination_pane_id": str(destination_pane_id or ""),
                    "tab_id": str(tab_id or ""),
                    "insertion_index": insertion_index,
                },
            )
            self.clear_interaction_assignment()

    def reorder_workspace_tab(
        self, pane_id: str, tab_id: str, insertion_index: int, **_
    ):
        layout = self._stash_active_workspace_grid()
        previous_layout = deepcopy(layout)
        layout = reorder_workspace_tab_model(
            layout, pane_id, tab_id, insertion_index
        )
        self._publish_workspace_layout(layout)
        if layout != previous_layout:
            self.record_interaction(
                "workspace.tab_reordered",
                source="tab_drag",
                payload={
                    "pane_id": str(pane_id or ""),
                    "tab_id": str(tab_id or ""),
                    "insertion_index": insertion_index,
                },
            )
            self.clear_interaction_assignment()

    def move_workspace_grid_cell(
        self,
        source_pane_id: str,
        source_tab_id: str,
        source_index: int,
        destination_pane_id: str,
        destination_tab_id: str,
        destination_index: int,
        **_,
    ):
        previous_layout = self._stash_active_workspace_grid()
        layout = move_workspace_grid_cell_model(
            previous_layout,
            source_pane_id,
            source_tab_id,
            source_index,
            destination_pane_id,
            destination_tab_id,
            destination_index,
        )
        self._publish_workspace_layout(layout)
        self._activate_workspace_target(
            str(layout.get("active_pane_id", "")),
            str(layout.get("active_tab_id", "")),
            stash=False,
        )
        if layout != previous_layout:
            self.record_interaction(
                "workspace.cell_moved",
                source="workspace_drag",
                payload={
                    "source_pane_id": str(source_pane_id or ""),
                    "source_tab_id": str(source_tab_id or ""),
                    "source_cell": source_index,
                    "destination_pane_id": str(destination_pane_id or ""),
                    "destination_tab_id": str(destination_tab_id or ""),
                    "destination_cell": destination_index,
                },
            )
            self.clear_interaction_assignment()

    def move_workspace_canvas_tile(
        self,
        source_pane_id: str,
        source_tab_id: str,
        source_index: int,
        destination_pane_id: str,
        destination_tab_id: str,
        geometry_payload,
        **_,
    ):
        """Move one compact Freeform tile between two workspace tabs."""

        if (
            str(source_pane_id or "") == str(destination_pane_id or "")
            and str(source_tab_id or "") == str(destination_tab_id or "")
        ):
            return
        layout = self._stash_active_workspace_grid()
        _source_pane, source_tab = pane_and_tab(
            layout, source_pane_id, source_tab_id
        )
        _destination_pane, destination_tab = pane_and_tab(
            layout, destination_pane_id, destination_tab_id
        )
        if source_tab is None or destination_tab is None:
            return
        source_grid = source_tab.get("grid", {})
        destination_grid = destination_tab.get("grid", {})
        source_columns = canvas_layout.normalize_columns(
            source_grid.get("canvas_columns", canvas_layout.CANVAS_COLUMNS)
        )
        destination_columns = canvas_layout.normalize_columns(
            destination_grid.get("canvas_columns", canvas_layout.CANVAS_COLUMNS)
        )
        if (
            str(source_grid.get("layout_mode", "")) != "freeform"
            or str(destination_grid.get("layout_mode", "")) != "freeform"
        ):
            return
        source_cells = grid_model.normalize_freeform_cells(
            list(source_grid.get("cells", []) or []),
            snap=bool(source_grid.get("canvas_snap_to_grid", True)),
            columns=source_columns,
        )
        try:
            source_cell_index = int(source_index)
        except (TypeError, ValueError):
            return
        if not 0 <= source_cell_index < len(source_cells):
            return

        moved_cell = dict(source_cells.pop(source_cell_index) or {})
        destination_cells = grid_model.normalize_freeform_cells(
            list(destination_grid.get("cells", []) or []),
            snap=bool(destination_grid.get("canvas_snap_to_grid", True)),
            columns=destination_columns,
        )
        if len(destination_cells) >= canvas_layout.CANVAS_MAX_TILES:
            return
        existing_ids = {
            str(cell.get("tile_id", "") or "") for cell in destination_cells
        }
        if str(moved_cell.get("tile_id", "") or "") in existing_ids:
            moved_cell["tile_id"] = self.next_canvas_tile_id(destination_cells)
        proposed = self.parse_canvas_payload(geometry_payload, {})
        if not isinstance(proposed, dict):
            return
        target_geometry = canvas_layout.geometry(
            str(moved_cell.get("tile_id", "") or ""),
            moved_cell.get(
                "tile_type", canvas_layout.tile_type_for_cell(moved_cell)
            ),
            proposed.get("x", 0),
            proposed.get("y", 0),
            proposed.get("w", moved_cell.get("canvas_w", 8)),
            proposed.get("h", moved_cell.get("canvas_h", 6)),
            snap=bool(destination_grid.get("canvas_snap_to_grid", True)),
            columns=destination_columns,
        )
        destination_geometry = [
            canvas_layout.geometry_from_cell(
                cell,
                fallback_id=f"tile-{index + 1}",
                fallback_index=index,
                snap=bool(destination_grid.get("canvas_snap_to_grid", True)),
                columns=destination_columns,
            )
            for index, cell in enumerate(destination_cells)
        ]
        if any(
            canvas_layout.overlaps(target_geometry, item)
            for item in destination_geometry
        ):
            target_geometry = canvas_layout.nearest_free(
                target_geometry,
                destination_geometry,
                columns=destination_columns,
            )
        destination_cells.append(
            canvas_layout.geometry_to_cell(moved_cell, target_geometry)
        )
        destination_index = len(destination_cells) - 1

        def remap_index(value):
            try:
                index = int(value)
            except (TypeError, ValueError):
                return -1
            if index == source_cell_index:
                return -1
            return index - 1 if index > source_cell_index else index

        source_grid["cells"] = source_cells
        source_grid["active_cell"] = remap_index(
            source_grid.get("active_cell", -1)
        )
        source_grid["timeline_driver_cell"] = remap_index(
            source_grid.get("timeline_driver_cell", -1)
        )
        source_grid["selected_cells"] = [
            remapped
            for remapped in (
                remap_index(item)
                for item in list(source_grid.get("selected_cells", []) or [])
            )
            if remapped >= 0
        ]
        source_grid["selected_cell_map"] = {
            str(index): True for index in source_grid["selected_cells"]
        }
        source_grid["canvas_layout_revision"] = int(
            source_grid.get("canvas_layout_revision", 0) or 0
        ) + 1
        destination_grid["cells"] = destination_cells
        destination_grid["active_cell"] = destination_index
        destination_grid["selected_cells"] = [destination_index]
        destination_grid["selected_cell_map"] = {
            str(destination_index): True
        }
        destination_grid["canvas_layout_revision"] = int(
            destination_grid.get("canvas_layout_revision", 0) or 0
        ) + 1
        self._publish_workspace_layout(layout)
        self._activate_workspace_target(
            str(destination_pane_id or ""),
            str(destination_tab_id or ""),
            stash=False,
        )
        self.record_interaction(
            "workspace.cell_moved",
            source="canvas_drag",
            payload={
                "source_pane_id": str(source_pane_id or ""),
                "source_tab_id": str(source_tab_id or ""),
                "source_cell": source_cell_index,
                "destination_pane_id": str(destination_pane_id or ""),
                "destination_tab_id": str(destination_tab_id or ""),
                "destination_tile_id": str(
                    moved_cell.get("tile_id", "") or ""
                ),
            },
        )
        self.clear_interaction_assignment()

    def resize_workspace_split(self, split_id: str, ratio: float, **_):
        layout = self._stash_active_workspace_grid()
        previous_layout = deepcopy(layout)
        layout = resize_workspace_split_model(layout, split_id, ratio)
        self._publish_workspace_layout(layout)
        if layout != previous_layout:
            actual_ratio = next(
                (
                    float(item.get("ratio", 0.5) or 0.5)
                    for item in list(getattr(self.state, "workspaceSplitters", []) or [])
                    if str(item.get("id", "") or "") == str(split_id or "")
                ),
                0.5,
            )
            self.record_interaction(
                "workspace.pane_resized",
                source="splitter_drag",
                payload={
                    "split_id": str(split_id or ""),
                    "ratio": actual_ratio,
                },
            )

    def _set_workspace_error(self, message: str) -> None:
        self.state.workspaceStateStatus = ""
        self.state.workspaceStateError = str(message or "")

    def _apply_live_grid_sizing(self, sizing: Any) -> None:
        if not isinstance(sizing, Mapping):
            return

        mode = str(sizing.get("mode", "") or "").strip().lower()
        if mode in {"fit", "static"}:
            self.state.gridSizingMode = mode

        self.normalize_grid_sizing()
        rows, cols = self.grid_dimensions()
        column_sizes = sizing.get("column_sizes")
        row_sizes = sizing.get("row_sizes")
        column_weights = sizing.get("column_weights")
        row_weights = sizing.get("row_weights")

        if column_sizes not in (None, ""):
            self.state.gridColumnSizes = self.normalize_size_list(
                column_sizes,
                cols,
                int(self.state.gridCellSize),
                int(self.state.gridMinCellSize),
                int(self.state.gridMaxCellSize),
            )
        if row_sizes not in (None, ""):
            self.state.gridRowSizes = self.normalize_size_list(
                row_sizes,
                rows,
                int(self.state.gridCellSize) + self.GRID_HEADER_HEIGHT,
                int(self.state.gridMinCellSize) + self.GRID_HEADER_HEIGHT,
                int(self.state.gridMaxCellSize) + self.GRID_HEADER_HEIGHT,
            )
        if column_weights not in (None, ""):
            self.state.gridColumnWeights = self.normalize_weight_list(
                column_weights,
                cols,
            )
        if row_weights not in (None, ""):
            self.state.gridRowWeights = self.normalize_weight_list(
                row_weights,
                rows,
            )

        self.normalize_grid_track_sizes(rows, cols)

    def _restore_grid_sizing(
        self,
        grid: Mapping[str, Any],
        rows: int,
        cols: int,
    ) -> None:
        self.state.gridSizingMode = str(
            grid.get("sizing_mode", "static") or "static"
        )
        self.state.gridCellSize = grid.get("cell_size", 300)
        self.state.gridFitMinCellSize = grid.get(
            "fit_minimum_cell_size", 180
        )
        self.state.gridColumnSizes = list(grid.get("column_sizes", []) or [])
        self.state.gridRowSizes = list(grid.get("row_sizes", []) or [])
        self.state.gridColumnWeights = list(
            grid.get("column_weights", []) or []
        )
        self.state.gridRowWeights = list(grid.get("row_weights", []) or [])
        self.normalize_grid_track_sizes(rows, cols)

    def _save_workspace_to_path(self, path: str) -> bool:
        self._stash_active_workspace_grid()
        target = Path(path).expanduser().resolve()
        if target.suffix.lower() != ".json":
            target = Path(f"{target}.json")
        try:
            target.write_text(
                workspace_json(self.state, self.campaign_path),
                encoding="utf-8",
            )
        except Exception as e:
            self._set_workspace_error(
                f"Could not save state: {type(e).__name__}: {e}"
            )
            return False

        self.state.workspaceStatePath = str(target)
        self.state.workspaceStateStatus = f"Saved: {target}"
        self.state.workspaceStateError = ""
        self.record_interaction(
            "workspace.saved",
            source="workspace_menu",
            payload={"workspace": self.interaction_workspace_snapshot()},
        )
        if self.interaction_log is not None:
            try:
                self.interaction_log.checkpoint()
            except Exception:
                pass
        return True

    def save_workspace_state(self, live_grid_sizing=None, **_):
        current_path = str(self.state.workspaceStatePath or "")
        if not current_path:
            return self.save_workspace_state_as(live_grid_sizing)
        self._apply_live_grid_sizing(live_grid_sizing)
        self._save_workspace_to_path(current_path)

    def save_workspace_state_as(self, live_grid_sizing=None, **_):
        self._apply_live_grid_sizing(live_grid_sizing)
        try:
            path = choose_workspace_save_path(
                default_workspace_filename(self.campaign_path),
                current_path=str(self.state.workspaceStatePath or ""),
                campaign_path=self.campaign_path,
            )
        except Exception as e:
            self._set_workspace_error(
                f"Could not open Save As dialog: {type(e).__name__}: {e}"
            )
            return
        if path:
            self._save_workspace_to_path(path)

    def load_workspace_state(self, **_):
        try:
            path = choose_workspace_load_path(
                current_path=str(self.state.workspaceStatePath or ""),
                campaign_path=self.campaign_path,
            )
        except Exception as e:
            self._set_workspace_error(
                f"Could not open Load dialog: {type(e).__name__}: {e}"
            )
            return
        if not path:
            return

        source = Path(path).expanduser().resolve()
        try:
            if source.suffix.lower() != ".json":
                raise WorkspaceStateError("State file must have a .json extension")
            if source.stat().st_size > MAX_WORKSPACE_STATE_BYTES:
                raise WorkspaceStateError("State file exceeds the 5 MiB limit")
            document = parse_workspace_document(source.read_bytes())
            self.restore_workspace_state(document)
        except (WorkspaceStateError, TypeError, ValueError) as e:
            self._set_workspace_error(str(e))
            return
        except Exception as e:
            self._set_workspace_error(
                f"Could not load state: {type(e).__name__}: {e}"
            )
            return

        self.state.workspaceStatePath = str(source)
        self.state.workspaceStateStatus = f"Loaded: {source}"
        self.state.workspaceStateError = ""
        self.history.clear()
        self._interaction_query_id = ""
        self.clear_interaction_assignment()
        if str(self.state.queryText or "").strip():
            self.record_query_applied(
                origin="workspace_restore",
                target="catalog",
                action_plan=dict(self.state.activeViewerActionPlan or {}),
            )
        self.record_interaction(
            "workspace.loaded",
            source="workspace_menu",
            payload={"workspace": self.interaction_workspace_snapshot()},
        )
        if self.interaction_log is not None:
            try:
                self.interaction_log.checkpoint()
            except Exception:
                pass

    def restore_workspace_state(self, document: Dict[str, Any]) -> None:
        validate_workspace_campaign(document, self.campaign_path)
        saved_state = document["state"]
        catalog = saved_state["catalog"]
        grid = saved_state["grid"]
        visualization = saved_state["visualization"]

        self.state.variablePaneView = (
            "files"
            if str(catalog.get("variable_pane_view", "")) == "files"
            else "variables"
        )
        collapsed_by_view = catalog.get(
            "variable_group_collapsed_by_view",
            {"variables": {}, "files": {}},
        )
        self.state.variableGroupCollapsedByView = (
            dict(collapsed_by_view)
            if isinstance(collapsed_by_view, dict)
            else {"variables": {}, "files": {}}
        )
        self.state.showOnlyVisualizedVars = bool(
            catalog.get("show_only_visualized_variables", False)
        )
        self.state.queryText = str(catalog.get("query_text", "") or "")
        if not self.update_query_state():
            raise WorkspaceStateError(
                f"Saved query is not valid: {self.state.queryError}"
            )
        self.refresh_variable_list()
        viewer_action = catalog.get("viewer_action", {})
        self.state.activeViewerActionPlan = (
            dict(viewer_action) if isinstance(viewer_action, dict) else {}
        )
        self.state.activeNaturalLanguageQuery = str(
            catalog.get("natural_language_query", "") or ""
        )
        if self.state.activeNaturalLanguageQuery:
            self.state.queryViewLabel = self.state.activeNaturalLanguageQuery

        self.state.scalarPlotPolicy = str(
            visualization.get("scalar_plot_policy", "always") or "always"
        )
        self.normalize_scalar_plot_policy()
        self.state.canvasDefaultTileWidth = canvas_layout.normalize_drop_width(
            visualization.get(
                "canvas_default_tile_width",
                canvas_layout.CANVAS_DEFAULT_DROP_WIDTH,
            )
        )

        self.state.gridRows = grid.get("rows", 3)
        self.state.gridCols = grid.get("columns", 3)
        self.state.gridLayoutMode = str(
            grid.get("layout_mode", grid_model.DEFAULT_GRID_LAYOUT_MODE)
            or grid_model.DEFAULT_GRID_LAYOUT_MODE
        )
        self.state.canvasCols = grid.get(
            "canvas_columns", canvas_layout.CANVAS_COLUMNS
        )
        self.state.canvasSnapToGrid = bool(
            grid.get("canvas_snap_to_grid", True)
        )
        self.state.canvasNudgeOthers = bool(
            grid.get("canvas_nudge_others", True)
        )
        self.state.canvasShowGrid = bool(grid.get("canvas_show_grid", False))
        self.state.canvasZoom = grid.get(
            "canvas_zoom", canvas_layout.CANVAS_ZOOM_DEFAULT
        )
        self.state.canvasFitToView = bool(
            grid.get("canvas_fit_to_view", False)
        )
        self.normalize_canvas_settings()

        rows, cols = self.grid_dimensions()
        self._restore_grid_sizing(grid, rows, cols)
        self.state.gridCells = self.normalize_grid_cells(
            list(grid.get("cells", []) or []),
            rows,
            cols,
        )
        self.refresh_grid_cells()
        self._restore_grid_sizing(grid, rows, cols)

        try:
            active = int(grid.get("active_cell", -1))
        except Exception:
            active = -1
        self.state.activeGridCell = (
            active if self.is_valid_grid_index(active) else -1
        )
        selected = self.normalize_grid_selection(
            list(grid.get("selected_cells", []) or []),
            list(self.state.gridCells or []),
        )
        self.publish_grid_selection(selected)

        try:
            driver = int(grid.get("timeline_driver_cell", -1))
        except Exception:
            driver = -1
        self.state.timelineDriverCell = toggle_timeline_driver(
            list(self.state.gridCells or []),
            -1,
            driver,
        )

        selected_variable = str(
            catalog.get("selected_variable", "") or ""
        )
        if selected_variable not in list(self.state.variableNames or []):
            selected_variable = ""
        self.set_details_provenance_context(False)
        self.state.selectedVar = selected_variable
        self.state.draggedVar = ""
        if selected_variable:
            self.update_selected_var_panels(selected_variable)
        else:
            clear_right_panes(self.state)
        self.clear_context_menu_state()
        self._restore_workspace_layout(saved_state.get("workspace"))
