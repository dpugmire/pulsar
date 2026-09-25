"""Context-menu state and action dispatch."""

from plugin_runtime import (
    is_plugin_visualization,
)
from pulsar.models.grid import (
    assign_cell,
    preserve_grid_geometry,
)
from pulsar.models.workspace_layout import pane_and_tab


class ContextMenuControllerMixin:
    ACTION_BINDINGS = (
        ("hide_context_menu", "hide_context_menu"),
        ("context_menu_item_add", "context_menu_item_add"),
        ("context_menu_item_select", "context_menu_item_select"),
        ("context_menu_tab_rename", "context_menu_tab_rename"),
        ("context_menu_tab_close", "context_menu_tab_close"),
        ("context_menu_cell_clear", "context_menu_cell_clear"),
        ("context_menu_cell_select", "context_menu_cell_select"),
        ("context_menu_cell_reset_view", "context_menu_cell_reset_view"),
        ("context_menu_cell_span_right", "context_menu_cell_span_right"),
        ("context_menu_cell_span_down", "context_menu_cell_span_down"),
        ("context_menu_cell_shrink_width", "context_menu_cell_shrink_width"),
        ("context_menu_cell_shrink_height", "context_menu_cell_shrink_height"),
        ("context_menu_cell_reset_span", "context_menu_cell_reset_span"),
        ("context_menu_cell_sources", "context_menu_cell_sources"),
        ("context_menu_cell_add_source", "context_menu_cell_add_source"),
        ("context_menu_cell_plot_settings", "context_menu_cell_plot_settings"),
        (
            "context_menu_cell_scalar_field_settings",
            "context_menu_cell_scalar_field_settings",
        ),
        (
            "context_menu_cell_pick_visualization",
            "context_menu_cell_pick_visualization",
        ),
        ("context_menu_cell_run_source_plugin", "context_menu_cell_run_source_plugin"),
    )
    TRIGGER_BINDINGS = (
        ("hide_context_menu_trigger", "hide_context_menu_trigger"),
        ("show_item_context_menu", "show_item_context_menu"),
        ("show_cell_context_menu", "show_cell_context_menu"),
        ("show_tab_context_menu", "show_tab_context_menu"),
    )
    STATE_CHANGE_BINDINGS = ()
    HISTORY_ACTIONS = {
        "context_menu_item_add": "Add plot",
        "context_menu_tab_rename": "Rename tab",
        "context_menu_tab_close": "Close tab",
        "context_menu_cell_clear": "Remove plot",
        "context_menu_cell_select": "Assign plot",
        "context_menu_cell_span_right": "Resize plot",
        "context_menu_cell_span_down": "Resize plot",
        "context_menu_cell_shrink_width": "Resize plot",
        "context_menu_cell_shrink_height": "Resize plot",
        "context_menu_cell_reset_span": "Reset plot size",
        "context_menu_cell_pick_visualization": "Change visualization",
        "context_menu_cell_run_source_plugin": "Change visualization",
    }
    HISTORY_TRIGGERS = {}

    def clear_context_menu_state(self) -> None:
        self.state.contextMenuVisible = False
        self.state.contextMenuKind = ""
        self.state.contextMenuItem = ""
        self.state.contextMenuItemLabel = ""
        self.state.contextMenuTabPaneId = ""
        self.state.contextMenuTabId = ""
        self.state.contextMenuTabCanClose = False
        self.state.contextMenuCellIndex = -1
        self.state.contextMenuCellHasVariable = False
        self.state.contextMenuCellCanAddSource = False
        self.state.contextMenuCellCanPlotSettings = False
        self.state.contextMenuCellCanScalarFieldSettings = False
        self.state.contextMenuCellCanResetView = False
        self.state.contextMenuCellVisualizationOptions = []
        self.state.contextMenuCellSelectedVisualization = ""
        self.state.contextMenuCellSourcePlugins = []

    def hide_context_menu(self, **_):
        self.clear_context_menu_state()

    def hide_context_menu_trigger(self, **_):
        self.hide_context_menu()

    def show_item_context_menu(self, item_name, x, y, **_):
        item = str(item_name or "").strip()
        if not item:
            return
        try:
            px = int(float(x))
        except Exception:
            px = 0
        try:
            py = int(float(y))
        except Exception:
            py = 0

        self.state.contextMenuKind = "item"
        self.state.contextMenuItem = item
        self.state.contextMenuItemLabel = self.variable_label(item)
        self.state.contextMenuTabPaneId = ""
        self.state.contextMenuTabId = ""
        self.state.contextMenuTabCanClose = False
        self.state.contextMenuCellIndex = -1
        self.state.contextMenuCellHasVariable = False
        self.state.contextMenuCellCanAddSource = False
        self.state.contextMenuCellVisualizationOptions = []
        self.state.contextMenuCellSelectedVisualization = ""
        self.state.contextMenuCellSourcePlugins = []
        self.state.contextMenuX = px
        self.state.contextMenuY = py
        self.state.contextMenuVisible = True

    def show_cell_context_menu(self, cell_index, x, y, **_):
        try:
            idx = int(cell_index)
        except Exception:
            return
        if not self.is_valid_grid_index(idx):
            return
        try:
            px = int(float(x))
        except Exception:
            px = 0
        try:
            py = int(float(y))
        except Exception:
            py = 0

        cells = self.normalize_grid_cells(self.state.gridCells)
        cell = dict(cells[idx] or {})
        has_var = bool(
            str(
                cell.get("variable_id", "") or cell.get("variable_name", "") or ""
            ).strip()
        )
        label = str(cell.get("variable_name", "") or "").strip() or f"Cell {idx + 1}"
        vis_opts = []
        for raw_vis in cell.get("visualization_options", []) or []:
            vis = str(raw_vis or "").strip()
            if vis and vis not in vis_opts:
                vis_opts.append(vis)
        selected_vis = str(
            cell.get("selected_visualization", "")
            or cell.get("visualization_name", "")
            or ""
        ).strip()
        if selected_vis and selected_vis not in vis_opts:
            vis_opts.append(selected_vis)
        targets = self.source_dialog_targets_for_anchor(idx, cells)
        can_add_source = bool(targets) and all(
            self.is_multi_source_plot1d_cell(cells[target]) for target in targets
        )
        is_plugin_cell = is_plugin_visualization(selected_vis)
        can_plot_settings = has_var and (
            str(cell.get("media_type", "") or "") == "plot1d" or is_plugin_cell
        )
        can_scalar_field_settings = has_var and self.is_scalar_field_cell(cell)
        media_type = str(cell.get("media_type", "") or "")
        can_reset_view = has_var and (
            media_type == "plot1d"
            or (bool(str(cell.get("src", "") or "").strip()) and media_type != "plot1d")
        )
        source_plugin_entries = (
            self.source_plugin_menu_entries_for_cell(cell) if has_var else []
        )

        self.state.contextMenuKind = "cell"
        self.state.contextMenuItem = label
        self.state.contextMenuItemLabel = label
        self.state.contextMenuTabPaneId = ""
        self.state.contextMenuTabId = ""
        self.state.contextMenuTabCanClose = False
        self.state.contextMenuCellIndex = idx
        self.state.contextMenuCellHasVariable = has_var
        self.state.contextMenuCellCanAddSource = can_add_source
        self.state.contextMenuCellCanPlotSettings = can_plot_settings
        self.state.contextMenuCellCanScalarFieldSettings = can_scalar_field_settings
        self.state.contextMenuCellCanResetView = can_reset_view
        self.state.contextMenuCellVisualizationOptions = vis_opts
        self.state.contextMenuCellSelectedVisualization = selected_vis
        self.state.contextMenuCellSourcePlugins = source_plugin_entries
        self.state.contextMenuX = px
        self.state.contextMenuY = py
        self.state.contextMenuVisible = True

    def show_tab_context_menu(self, pane_id, tab_id, x, y, **_):
        pane_id = str(pane_id or "")
        tab_id = str(tab_id or "")
        layout = self._workspace_layout()
        _pane, tab = pane_and_tab(layout, pane_id, tab_id)
        if tab is None:
            return
        try:
            px = int(float(x))
        except Exception:
            px = 0
        try:
            py = int(float(y))
        except Exception:
            py = 0

        tab_count = sum(
            len(pane.get("tabs", []) or [])
            for pane in layout.get("panes", []) or []
        )
        self.clear_context_menu_state()
        self.state.contextMenuKind = "tab"
        self.state.contextMenuItemLabel = str(tab.get("title", "View") or "View")
        self.state.contextMenuTabPaneId = pane_id
        self.state.contextMenuTabId = tab_id
        self.state.contextMenuTabCanClose = tab_count > 1
        self.state.contextMenuX = px
        self.state.contextMenuY = py
        self.state.contextMenuVisible = True

    def context_menu_tab_rename(self, title, **_):
        if title is not None:
            self.rename_workspace_tab(
                self.state.contextMenuTabPaneId,
                self.state.contextMenuTabId,
                title,
            )
        self.hide_context_menu()

    def context_menu_tab_close(self, confirmed=True, **_):
        if confirmed and bool(self.state.contextMenuTabCanClose):
            self.close_workspace_tab(
                self.state.contextMenuTabPaneId,
                self.state.contextMenuTabId,
            )
        self.hide_context_menu()

    def context_menu_item_add(self, **_):
        item = str(self.state.contextMenuItem or "").strip()
        if item:
            self.add_var_to_grid(item)
        self.hide_context_menu()

    def context_menu_item_select(self, **_):
        item = str(self.state.contextMenuItem or "").strip()
        if item:
            self.set_details_provenance_context(False)
            self.state.selectedVar = item
            self.state.draggedVar = item
        self.hide_context_menu()

    def context_menu_cell_clear(self, **_):
        try:
            idx = int(self.state.contextMenuCellIndex)
        except Exception:
            idx = -1
        if self.is_valid_grid_index(idx):
            self.clear_grid_cell(idx)
        self.hide_context_menu()

    def context_menu_cell_select(self, **_):
        try:
            idx = int(self.state.contextMenuCellIndex)
        except Exception:
            idx = -1
        if self.is_valid_grid_index(idx):
            self.set_active_grid_cell(idx, 0)
        self.hide_context_menu()

    def context_menu_cell_reset_view(self, **_):
        try:
            idx = int(self.state.contextMenuCellIndex)
        except Exception:
            idx = -1
        if self.is_valid_grid_index(idx):
            self.state.resetViewRequest = {
                "cell_index": idx,
                "nonce": int(getattr(self.state, "resetViewRequestNonce", 0) or 0) + 1,
            }
            self.state.resetViewRequestNonce = self.state.resetViewRequest["nonce"]
        self.hide_context_menu()

    def context_menu_cell_index(self) -> int:
        try:
            idx = int(self.state.contextMenuCellIndex)
        except Exception:
            return -1
        return idx if self.is_valid_grid_index(idx) else -1

    def context_menu_cell_span_right(self, **_):
        idx = self.context_menu_cell_index()
        if idx >= 0:
            self.span_grid_cell_right(idx)
        self.hide_context_menu()

    def context_menu_cell_span_down(self, **_):
        idx = self.context_menu_cell_index()
        if idx >= 0:
            self.span_grid_cell_down(idx)
        self.hide_context_menu()

    def context_menu_cell_shrink_width(self, **_):
        idx = self.context_menu_cell_index()
        if idx >= 0:
            self.shrink_grid_cell_width(idx)
        self.hide_context_menu()

    def context_menu_cell_shrink_height(self, **_):
        idx = self.context_menu_cell_index()
        if idx >= 0:
            self.shrink_grid_cell_height(idx)
        self.hide_context_menu()

    def context_menu_cell_reset_span(self, **_):
        idx = self.context_menu_cell_index()
        if idx >= 0:
            self.reset_grid_cell_span(idx)
        self.hide_context_menu()

    def context_menu_cell_sources(self, **_):
        try:
            idx = int(self.state.contextMenuCellIndex)
        except Exception:
            idx = -1
        if not self.is_valid_grid_index(idx):
            self.hide_context_menu()
            return

        self.open_source_dialog_for_cell(idx, prefer_multi=True)
        self.hide_context_menu()

    def context_menu_cell_add_source(self, **_):
        try:
            idx = int(self.state.contextMenuCellIndex)
        except Exception:
            idx = -1
        if not self.is_valid_grid_index(idx):
            self.hide_context_menu()
            return

        self.open_source_dialog_for_cell(idx, prefer_multi=True)
        self.hide_context_menu()

    def context_menu_cell_plot_settings(self, **_):
        try:
            idx = int(self.state.contextMenuCellIndex)
        except Exception:
            idx = -1
        if not self.is_valid_grid_index(idx):
            self.hide_context_menu()
            return

        cells = self.normalize_grid_cells(self.state.gridCells)
        cell = dict(cells[idx] or {})
        selected_vis = str(
            cell.get("selected_visualization", "")
            or cell.get("visualization_name", "")
            or ""
        )
        if str(cell.get("media_type", "") or "") != "plot1d":
            if is_plugin_visualization(selected_vis):
                self.state.activeGridCell = idx
                self.load_plugin_options_dialog(idx)
                self.hide_context_menu()
                return
            self.hide_context_menu()
            return

        self.state.activeGridCell = idx
        self.load_plot_settings_dialog(idx)
        self.hide_context_menu()

    def context_menu_cell_scalar_field_settings(self, **_):
        try:
            idx = int(self.state.contextMenuCellIndex)
        except Exception:
            idx = -1
        if not self.is_valid_grid_index(idx):
            self.hide_context_menu()
            return

        cells = self.normalize_grid_cells(self.state.gridCells)
        cell = dict(cells[idx] or {})
        if not self.is_scalar_field_cell(cell):
            self.hide_context_menu()
            return

        self.state.activeGridCell = idx
        self.load_scalar_field_settings_dialog(idx)
        self.hide_context_menu()

    def context_menu_cell_pick_visualization(self, value: str = "", **_):
        try:
            idx = int(self.state.contextMenuCellIndex)
        except Exception:
            idx = -1
        if not self.is_valid_grid_index(idx):
            self.hide_context_menu()
            return

        picked = str(value or "").strip()
        if not picked:
            self.hide_context_menu()
            return

        self.pick_grid_cell_visualization(idx, picked)
        self.hide_context_menu()

    def context_menu_cell_run_source_plugin(self, plugin_id: str = "", **_):
        try:
            idx = int(self.state.contextMenuCellIndex)
        except Exception:
            idx = -1
        if not self.is_valid_grid_index(idx):
            self.hide_context_menu()
            return

        plugin = str(plugin_id or "").strip()
        if not plugin:
            self.hide_context_menu()
            return

        cells = self.normalize_grid_cells(self.state.gridCells)
        existing = dict(cells[idx] or {})
        rendered_tile = {}
        try:
            tile = self.build_source_plugin_grid_cell(plugin, existing)
            assign_cell(cells, idx, preserve_grid_geometry(tile, existing))
            self.state.gridCells = self.normalize_grid_cells(cells)
            self.state.activeGridCell = idx
            rendered_tile = dict(self.state.gridCells[idx] or {})
        except Exception as e:
            err_cell = self.no_visualization_grid_cell(
                str(
                    existing.get("variable_id", "")
                    or existing.get("variable_name", "")
                    or ""
                ),
                f"Plugin {plugin} failed: {type(e).__name__}: {e}",
            )
            err_cell.update(
                {
                    k: v
                    for k, v in existing.items()
                    if k
                    in {
                        "source_dataset",
                        "schema_file_group",
                        "schema_mode",
                        "producer",
                        "casename",
                        "file",
                        "_source_key",
                    }
                }
            )
            assign_cell(cells, idx, preserve_grid_geometry(err_cell, existing))
            self.state.gridCells = self.normalize_grid_cells(cells)
            self.state.activeGridCell = idx
        if rendered_tile:
            variable_id = str(
                rendered_tile.get("variable_id", "")
                or rendered_tile.get("variable_name", "")
                or ""
            ).strip()
            if variable_id:
                self.set_details_provenance_context(True)
                self.state.selectedVar = variable_id
                self.state.draggedVar = variable_id
                self.update_selected_var_panels(
                    variable_id,
                    preferred_source_key=str(
                        rendered_tile.get("_source_key", "") or ""
                    ),
                    include_visualization_provenance=True,
                    preferred_visualization=str(
                        rendered_tile.get("selected_visualization", "")
                        or rendered_tile.get("visualization_name", "")
                        or ""
                    ),
                    provenance_tile=rendered_tile,
                )
        self.hide_context_menu()
