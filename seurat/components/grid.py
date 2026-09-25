"""Visualization grid and layout controls."""

from trame.app import TrameComponent
from trame.widgets import html
from trame.widgets import vuetify3 as vuetify

from seurat.models import canvas_layout
from seurat.widgets import GridRuntime

from .dialogs import (
    PlotSettingsPanel,
    PluginOptionsPanel,
    ProvenanceDialog,
    ScalarFieldAssistantPanel,
    ScalarFieldSettingsPanel,
    ScalarPlotDialog,
    SourceDialog,
)


def _build_grid_size_picker(ctrl):
    with html.Div(classes="seurat-toolbar-menu", style="margin-top:10px; width:100%;"):
        with html.Button(
            classes="seurat-grid-size-trigger",
            raw_attrs=['type="button"'],
            title="Grid size",
        ):
            html.Span("Grid size", classes="seurat-grid-size-trigger-label")
            html.Span("{{ gridRows + ' x ' + gridCols + ' ▾' }}", classes="seurat-grid-size-trigger-value")
        with vuetify.VMenu(
            activator="parent",
            location="bottom start",
            close_on_content_click=False,
        ):
            with vuetify.VCard(classes="seurat-grid-size-popover", elevation=4):
                with vuetify.VCardText(class_="pa-2"):
                    html.Div("Grid size", classes="seurat-toolbar-popover-title")
                    with html.Div(classes="seurat-grid-picker"):
                        for picker_row in range(1, 9):
                            for picker_col in range(1, 9):
                                html.Button(
                                    "",
                                    classes="seurat-grid-picker-cell",
                                    click=(ctrl.set_grid_layout_size, f"[{picker_row}, {picker_col}]"),
                                    raw_attrs=[
                                        'type="button"',
                                        f'title="{picker_row} x {picker_col}"',
                                        f':class="{{ selected: gridRows >= {picker_row} && gridCols >= {picker_col}, current: gridRows === {picker_row} && gridCols === {picker_col} }}"',
                                    ],
                                )
                    html.Div(
                        "{{ gridRows + ' x ' + gridCols }}",
                        class_="text-caption seurat-grid-picker-label",
                    )
                    with html.Div(classes="seurat-grid-layout-stepper"):
                        html.Span("Rows", class_="text-caption seurat-grid-layout-stepper-label")
                        html.Button(
                            "-",
                            classes="seurat-grid-layout-btn",
                            click=ctrl.delete_grid_row,
                            raw_attrs=['type="button"', ':disabled="gridRows <= gridMinRows"'],
                            title="Delete active row or last row",
                        )
                        html.Span("{{ gridRows }}", class_="text-caption text-center")
                        html.Button(
                            "+",
                            classes="seurat-grid-layout-btn",
                            click=ctrl.add_grid_row,
                            raw_attrs=['type="button"', ':disabled="gridRows >= gridMaxRows"'],
                            title="Add row",
                        )
                    with html.Div(classes="seurat-grid-layout-stepper"):
                        html.Span("Cols", class_="text-caption seurat-grid-layout-stepper-label")
                        html.Button(
                            "-",
                            classes="seurat-grid-layout-btn",
                            click=ctrl.delete_grid_column,
                            raw_attrs=['type="button"', ':disabled="gridCols <= gridMinCols"'],
                            title="Delete active column or last column",
                        )
                        html.Span("{{ gridCols }}", class_="text-caption text-center")
                        html.Button(
                            "+",
                            classes="seurat-grid-layout-btn",
                            click=ctrl.add_grid_column,
                            raw_attrs=['type="button"', ':disabled="gridCols >= gridMaxCols"'],
                            title="Add column",
                        )


def _build_canvas_zoom_controls(ctrl):
    with vuetify.Template(v_if="gridLayoutMode === 'freeform'"):
        with html.Div(
            classes="seurat-canvas-zoom-controls",
            raw_attrs=['aria-label="Canvas zoom controls"'],
        ):
            html.Button(
                "−",
                classes="seurat-canvas-zoom-button",
                click=(ctrl.adjust_canvas_zoom, "[-0.25]"),
                raw_attrs=[
                    'type="button"',
                    'aria-label="Zoom out"',
                    ':disabled="!canvasFitToView && Number(canvasZoom || 1) <= 0.25"',
                ],
                title="Zoom out",
            )
            html.Span(
                "{{ Math.round(Number(canvasZoom || 1) * 100) + '%' }}",
                classes="seurat-canvas-zoom-value",
                raw_attrs=['data-canvas-zoom-label="1"'],
            )
            html.Button(
                "+",
                classes="seurat-canvas-zoom-button",
                click=(ctrl.adjust_canvas_zoom, "[0.25]"),
                raw_attrs=[
                    'type="button"',
                    'aria-label="Zoom in"',
                    ':disabled="!canvasFitToView && Number(canvasZoom || 1) >= 2"',
                ],
                title="Zoom in",
            )
            html.Button(
                "Fit",
                classes="seurat-canvas-fit-button",
                click=(ctrl.set_canvas_fit_to_view, "[true]"),
                raw_attrs=[
                    'type="button"',
                    ':aria-pressed="canvasFitToView ? \'true\' : \'false\'"',
                    ':class="{ active: canvasFitToView }"',
                ],
                title="Fit all tiles in the canvas",
            )


def _build_grid_settings_popover(ctrl):
    html.Div("Settings", classes="seurat-toolbar-popover-title")
    with html.Div(classes="seurat-settings-section"):
        html.Div("Layout", classes="seurat-settings-section-title")
        html.Div("Cell layout", classes="seurat-grid-sizing-section-label")
        with html.Div(classes="seurat-grid-sizing-mode seurat-layout-mode-selector"):
            html.Button(
                "Uniform",
                classes="seurat-grid-sizing-mode-btn",
                click=(ctrl.set_grid_layout_mode, "['uniform']"),
                raw_attrs=[
                    'type="button"',
                    ':class="{ active: gridLayoutMode === \'uniform\' }"',
                ],
                title="Use one cell per grid slot",
            )
            html.Button(
                "Spanning",
                classes="seurat-grid-sizing-mode-btn",
                click=(ctrl.set_grid_layout_mode, "['spanning']"),
                raw_attrs=[
                    'type="button"',
                    ':class="{ active: gridLayoutMode === \'spanning\' }"',
                ],
                title="Allow cells to span multiple rows or columns",
            )
            html.Button(
                "Freeform",
                classes="seurat-grid-sizing-mode-btn",
                click=(ctrl.set_grid_layout_mode, "['freeform']"),
                raw_attrs=[
                    'type="button"',
                    ':class="{ active: gridLayoutMode === \'freeform\' }"',
                ],
                title="Place and resize tiles on a snapping canvas",
            )
        with vuetify.Template(v_if="gridLayoutMode === 'freeform'"):
            html.Div("Canvas behavior", classes="seurat-grid-sizing-section-label")
            with html.Div(classes="seurat-canvas-settings"):
                html.Button(
                    "Snap to grid",
                    classes="seurat-canvas-toggle",
                    click=(ctrl.set_canvas_snap_to_grid, "[!canvasSnapToGrid]"),
                    raw_attrs=[
                        'type="button"',
                        ':aria-pressed="canvasSnapToGrid ? \'true\' : \'false\'"',
                        ':class="{ active: canvasSnapToGrid }"',
                    ],
                )
                html.Button(
                    "Nudge others",
                    classes="seurat-canvas-toggle",
                    click=(ctrl.set_canvas_nudge_others, "[!canvasNudgeOthers]"),
                    raw_attrs=[
                        'type="button"',
                        ':aria-pressed="canvasNudgeOthers ? \'true\' : \'false\'"',
                        ':class="{ active: canvasNudgeOthers }"',
                    ],
                )
                html.Button(
                    "Show grid",
                    classes="seurat-canvas-toggle",
                    click=(ctrl.set_canvas_show_grid, "[!canvasShowGrid]"),
                    raw_attrs=[
                        'type="button"',
                        ':aria-pressed="canvasShowGrid ? \'true\' : \'false\'"',
                        ':class="{ active: canvasShowGrid }"',
                    ],
                )
            html.Div("New plot size", classes="seurat-grid-sizing-section-label")
            with html.Div(classes="seurat-size-stepper"):
                html.Button(
                    "−",
                    classes="seurat-grid-layout-btn",
                    click=(ctrl.adjust_canvas_default_tile_width, "[-1]"),
                    raw_attrs=[
                        'type="button"',
                        'aria-label="Decrease new plot size"',
                        ':disabled="Number(canvasDefaultTileWidth || 2) <= 2"',
                    ],
                    title="Decrease new plot size",
                )
                html.Span(
                    "{{ Number(canvasDefaultTileWidth || 2) + ' columns' }}",
                    classes="seurat-size-stepper-value seurat-canvas-default-size-value",
                )
                html.Button(
                    "+",
                    classes="seurat-grid-layout-btn",
                    click=(ctrl.adjust_canvas_default_tile_width, "[1]"),
                    raw_attrs=[
                        'type="button"',
                        'aria-label="Increase new plot size"',
                        ':disabled="Number(canvasDefaultTileWidth || 2) >= 12"',
                    ],
                    title="Increase new plot size",
                )
            html.Div(
                "Applies to drops in every tab; height stays square.",
                classes="seurat-canvas-settings-hint",
            )
            html.Div("Grid columns", classes="seurat-grid-sizing-section-label")
            with html.Div(classes="seurat-canvas-column-options"):
                for columns in canvas_layout.CANVAS_COLUMN_CHOICES:
                    html.Button(
                        str(columns),
                        classes="seurat-canvas-column-option",
                        click=(ctrl.set_canvas_columns, f"[{columns}]"),
                        raw_attrs=[
                            'type="button"',
                            f'aria-label="{columns} columns"',
                            f':aria-pressed="Number(canvasCols) === {columns} ? \'true\' : \'false\'"',
                            f':class="{{ active: Number(canvasCols) === {columns} }}"',
                        ],
                    )
            html.Div(
                "Drag tile headers. Resize from any edge or corner.",
                classes="seurat-canvas-settings-hint",
            )
        with vuetify.Template(v_if="gridLayoutMode !== 'freeform'"):
            html.Div("Size mode", classes="seurat-grid-sizing-section-label")
            with html.Div(classes="seurat-grid-sizing-mode"):
                html.Button(
                    "Static",
                    classes="seurat-grid-sizing-mode-btn",
                    click=(ctrl.set_grid_sizing_mode, "['static']"),
                    raw_attrs=[
                        'type="button"',
                        ':class="{ active: gridSizingMode !== \'fit\' }"',
                    ],
                    title="Use fixed-size cells",
                )
                html.Button(
                    "Fit window",
                    classes="seurat-grid-sizing-mode-btn",
                    click=(ctrl.set_grid_sizing_mode, "['fit']"),
                    raw_attrs=[
                        'type="button"',
                        ':class="{ active: gridSizingMode === \'fit\' }"',
                    ],
                    title="Resize cells to fill the grid viewport",
                )
        with vuetify.Template(v_if="gridLayoutMode !== 'freeform' && gridSizingMode !== 'fit'"):
            html.Div("Cell size", classes="seurat-grid-sizing-section-label")
            with html.Div(classes="seurat-size-stepper"):
                html.Button(
                    "-",
                    classes="seurat-grid-layout-btn",
                    click=(ctrl.set_grid_cell_size, "[Number(gridCellSize || 300) - 10]"),
                    raw_attrs=['type="button"'],
                    title="Decrease cell size",
                )
                html.Input(
                    v_model=("gridCellSize",),
                    classes="seurat-size-stepper-input",
                    change=(ctrl.set_grid_cell_size, "[$event.target.value]"),
                    raw_attrs=[
                        'type="number"',
                        ':min="gridMinCellSize"',
                        ':max="gridMaxCellSize"',
                        'step="10"',
                        'aria-label="Cell size"',
                    ],
                )
                html.Button(
                    "+",
                    classes="seurat-grid-layout-btn",
                    click=(ctrl.set_grid_cell_size, "[Number(gridCellSize || 300) + 10]"),
                    raw_attrs=['type="button"'],
                    title="Increase cell size",
                )
                html.Span("px", classes="seurat-size-stepper-unit")
            html.Button(
                "Reset track sizes",
                classes="seurat-grid-reset-tracks-btn",
                click=ctrl.reset_grid_track_sizes,
                raw_attrs=['type="button"'],
                title="Reset all rows and columns to the current cell size",
            )
        with vuetify.Template(v_if="gridLayoutMode !== 'freeform' && gridSizingMode === 'fit'"):
            html.Div("Minimum cell size", classes="seurat-grid-sizing-section-label")
            with html.Div(classes="seurat-size-stepper"):
                html.Button(
                    "-",
                    classes="seurat-grid-layout-btn",
                    click=(ctrl.set_grid_fit_min_cell_size, "[Number(gridFitMinCellSize || 180) - 10]"),
                    raw_attrs=['type="button"'],
                    title="Decrease minimum cell size",
                )
                html.Input(
                    v_model=("gridFitMinCellSize",),
                    classes="seurat-size-stepper-input",
                    change=(ctrl.set_grid_fit_min_cell_size, "[$event.target.value]"),
                    raw_attrs=[
                        'type="number"',
                        ':min="gridMinCellSize"',
                        ':max="gridMaxFitMinCellSize"',
                        'step="10"',
                        'aria-label="Minimum cell size"',
                    ],
                )
                html.Button(
                    "+",
                    classes="seurat-grid-layout-btn",
                    click=(ctrl.set_grid_fit_min_cell_size, "[Number(gridFitMinCellSize || 180) + 10]"),
                    raw_attrs=['type="button"'],
                    title="Increase minimum cell size",
                )
                html.Span("px", classes="seurat-size-stepper-unit")
        with vuetify.Template(v_if="gridLayoutMode !== 'freeform'"):
            _build_grid_size_picker(ctrl)
    with html.Div(classes="seurat-settings-section"):
        html.Div("Scalar plots", classes="seurat-settings-section-title")
        with html.Div(classes="seurat-settings-row"):
            html.Span("Create curves", class_="text-caption")
            with html.Select(
                v_model=("scalarPlotPolicy",),
                classes="seurat-scalar-plot-policy",
                title="Generated scalar plot behavior",
            ):
                html.Option("Ask", value="ask")
                html.Option("Generate", value="always")
                html.Option("Never", value="never")


def _build_grid_layout_controls(ctrl):
    with html.Div(classes="seurat-grid-layout-controls"):
        with html.Div(classes="seurat-toolbar-menu"):
            html.Button(
                "⚙",
                classes="seurat-toolbar-menu-btn seurat-toolbar-icon-btn",
                raw_attrs=[
                    'type="button"',
                    'aria-label="Settings"',
                ],
                title="Settings",
            )
            with vuetify.VMenu(
                activator="parent",
                location="bottom end",
                close_on_content_click=False,
            ):
                with vuetify.VCard(classes="seurat-settings-popover", elevation=4):
                    with vuetify.VCardText(class_="pa-2"):
                        _build_grid_settings_popover(ctrl)


def _build_workspace_tab_bars(ctrl):
    with vuetify.Template(v_for="(pane, paneIndex) in workspacePanes", key="pane.id"):
        with html.Div(
            classes="seurat-workspace-tab-bar",
            raw_attrs=[
                ":class=\"[paneIndex === 0 ? 'seurat-workspace-slot-first' : 'seurat-workspace-slot-second', pane.id === workspaceActivePaneId ? 'is-active-pane' : '']\"",
                ':data-pane-frame-id="pane.id"',
                ":style=\"{"
                " '--pane-left': Number(((workspacePaneFrames || {})[pane.id] || {}).left || 0) + '%',"
                " '--pane-top': Number(((workspacePaneFrames || {})[pane.id] || {}).top || 0) + '%',"
                " '--pane-width': Number(((workspacePaneFrames || {})[pane.id] || {}).width || 100) + '%',"
                " '--pane-height': Number(((workspacePaneFrames || {})[pane.id] || {}).height || 100) + '%'"
                "}\"",
            ],
        ):
            with html.Div(classes="seurat-workspace-tabs-viewport"):
                with html.Div(
                    classes="seurat-workspace-tabs",
                    role="tablist",
                    raw_attrs=[':data-pane-id="pane.id"'],
                ):
                    with vuetify.Template(v_for="tab in pane.tabs", key="tab.id"):
                        with html.Div(
                            classes="seurat-workspace-tab-shell",
                            raw_attrs=[
                                ':class="{ \'is-pane-tab-active\': pane.active_tab_id === tab.id, \'is-workspace-active\': workspaceActiveTabId === tab.id }"',
                            ],
                        ):
                            html.Button(
                                "{{ tab.title }}",
                                classes="seurat-workspace-tab",
                                click=(ctrl.activate_workspace_tab, "[pane.id, tab.id]"),
                                raw_attrs=[
                                    'type="button"',
                                    'role="tab"',
                                    ':aria-selected="pane.active_tab_id === tab.id ? \'true\' : \'false\'"',
                                    ':class="{ \'is-pane-tab-active\': pane.active_tab_id === tab.id, \'is-workspace-active\': workspaceActiveTabId === tab.id }"',
                                    ':title="tab.title"',
                                    ':data-pane-id="pane.id"',
                                    ':data-tab-id="tab.id"',
                                    'aria-haspopup="menu"',
                                    'draggable="true"',
                                ],
                            )
                            html.Button(
                                "×",
                                v_if="workspacePanes.reduce((count, item) => count + ((item.tabs || []).length), 0) > 1",
                                classes="seurat-workspace-tab-close",
                                click=(
                                    ctrl.close_workspace_tab,
                                    "[pane.id, tab.id, window.confirm('Close this tab and remove its visualizations?')]",
                                ),
                                raw_attrs=[
                                    'type="button"',
                                    ':aria-label="\'Close \' + tab.title"',
                                    ':title="\'Close \' + tab.title"',
                                ],
                            )
                    html.Button(
                        "+",
                        classes="seurat-workspace-tab-add",
                        click=(ctrl.add_workspace_tab, "[pane.id]"),
                        raw_attrs=['type="button"', 'aria-label="New tab"'],
                        title="New tab",
                    )


def _build_inactive_workspace_grids(ctrl):
    with vuetify.Template(v_for="(pane, paneIndex) in workspacePanes", key="pane.id"):
        with vuetify.Template(v_if="pane.id !== workspaceActivePaneId"):
            with vuetify.Template(v_for="tab in pane.tabs", key="tab.id"):
                with vuetify.Template(v_if="tab.id === pane.active_tab_id"):
                    with html.Div(
                        classes="seurat-main-grid seurat-workspace-grid-preview",
                        click=(ctrl.activate_workspace_tab, "[pane.id, tab.id]"),
                        raw_attrs=[
                            ":class=\"[paneIndex === 0 ? 'seurat-workspace-slot-first' : 'seurat-workspace-slot-second', { 'seurat-freeform-preview': tab.grid.layout_mode === 'freeform' }]\"",
                            ':data-pane-frame-id="pane.id"',
                            ':data-pane-id="pane.id"',
                            ':data-tab-id="tab.id"',
                            ':data-layout-mode="tab.grid.layout_mode"',
                            ':data-grid-cols="tab.grid.columns"',
                            ':data-grid-rows="tab.grid.rows"',
                            ':data-canvas-cols="tab.grid.canvas_columns || 24"',
                            ':data-canvas-row-height="tab.grid.canvas_row_height || 24"',
                            ':data-canvas-snap="tab.grid.canvas_snap_to_grid === false ? 0 : 1"',
                            ':data-canvas-nudge="tab.grid.canvas_nudge_others === false ? 0 : 1"',
                            ':data-canvas-zoom="tab.grid.canvas_zoom || 1"',
                            ':data-canvas-fit="tab.grid.canvas_fit_to_view ? 1 : 0"',
                            'role="button"',
                            'tabindex="0"',
                            ':aria-label="\'Activate \' + tab.title + \' pane\'"',
                            ":style=\"('display:grid;'"
                            " + ((tab.grid.sizing_mode === 'fit')"
                            " ? ('grid-template-columns:' + String(tab.grid.fit_column_template || ('repeat(' + tab.grid.columns + ', minmax(' + Number(tab.grid.fit_minimum_cell_size || 180) + 'px, 1fr))')) + ';'"
                            " + 'grid-template-rows:' + String(tab.grid.fit_row_template || ('repeat(' + tab.grid.rows + ', minmax(' + (Number(tab.grid.fit_minimum_cell_size || 180) + 32) + 'px, 1fr))')) + ';'"
                            " + 'justify-content:stretch;align-content:stretch;')"
                            " : ('grid-template-columns:' + String(tab.grid.column_template || ('repeat(' + tab.grid.columns + ', ' + Number(tab.grid.cell_size || 300) + 'px)')) + ';'"
                            " + 'grid-template-rows:' + String(tab.grid.row_template || ('repeat(' + tab.grid.rows + ', ' + (Number(tab.grid.cell_size || 300) + 32) + 'px)')) + ';'"
                            " + 'justify-content:center;align-content:start;'))"
                            " + '--pane-left:' + Number(((workspacePaneFrames || {})[pane.id] || {}).left || 0) + '%;'"
                            " + '--pane-top:' + Number(((workspacePaneFrames || {})[pane.id] || {}).top || 0) + '%;'"
                            " + '--pane-width:' + Number(((workspacePaneFrames || {})[pane.id] || {}).width || 100) + '%;'"
                            " + '--pane-height:' + Number(((workspacePaneFrames || {})[pane.id] || {}).height || 100) + '%;'"
                            " + 'min-height:0;overflow:auto;width:100%;height:100%;box-sizing:border-box;border:1px solid #cfcfcf;')\"",
                        ],
                    ):
                        with html.Div(
                            classes="seurat-canvas-grid-overlay",
                            v_if="tab.grid.layout_mode === 'freeform' && tab.grid.canvas_show_grid",
                            raw_attrs=[
                                'aria-hidden="true"',
                                ':data-grid-columns="tab.grid.canvas_columns || 24"',
                                ":style=\"{ height: (((Math.max(12, Math.ceil(Math.max(0, ...(tab.grid.cells || []).map(tile => Number((tile && tile.canvas_y) || 0) + Number((tile && tile.canvas_h) || 0))))) * Number(tab.grid.canvas_row_height || 24)) + Number(tab.grid.canvas_row_height || 24)) + 'px') }\"",
                            ],
                        ):
                            with vuetify.Template(
                                v_for="line in Math.max(0, Number(tab.grid.canvas_columns || 24) - 1)",
                                key="'vertical-' + line",
                            ):
                                html.Div(
                                    classes="seurat-canvas-grid-line is-vertical",
                                    raw_attrs=[
                                        ':class="{ \'is-major\': line % 4 === 0 }"',
                                        ':data-grid-line="line"',
                                        ":style=\"{ left: ((line * 100 / Number(tab.grid.canvas_columns || 24)) + '%') }\"",
                                    ],
                                )
                            with vuetify.Template(
                                v_for="line in Math.max(12, Math.ceil(Math.max(0, ...(tab.grid.cells || []).map(tile => Number((tile && tile.canvas_y) || 0) + Number((tile && tile.canvas_h) || 0)))))",
                                key="'horizontal-' + line",
                            ):
                                html.Div(
                                    classes="seurat-canvas-grid-line is-horizontal",
                                    raw_attrs=[
                                        ':class="{ \'is-major\': line % 4 === 0 }"',
                                        ':data-grid-line="line"',
                                        ":style=\"{ top: ((line * Number(tab.grid.canvas_row_height || 24)) + 'px') }\"",
                                    ],
                                )
                        html.Div(
                            classes="seurat-canvas-placeholder seurat-canvas-preview-placeholder",
                            v_if="tab.grid.layout_mode === 'freeform'",
                            raw_attrs=['aria-hidden="true"'],
                        )
                        with vuetify.Template(
                            v_for="(tile, i) in tab.grid.cells", key="i"
                        ):
                            with html.Div(
                                classes="seurat-dropcell seurat-workspace-preview-cell",
                                raw_attrs=[
                                    ':data-cell-index="i"',
                                    ':data-pane-id="pane.id"',
                                    ':data-tab-id="tab.id"',
                                    ':data-cell-filled="((tile && tile.variable_name) ? 1 : 0)"',
                                    ':data-selection-axis="JSON.stringify((tile && tile.selection_axis) || {})"',
                                    ':data-axis-sync-status="(tile && tile.axis_sync_status) || \'\'"',
                                    ':data-tile-id="(tile && tile.tile_id) || (\'tile-\' + (i + 1))"',
                                    ':data-tile-type="(tile && tile.tile_type) || \'plot\'"',
                                    ':data-canvas-x="Number((tile && tile.canvas_x) || 0)"',
                                    ':data-canvas-y="Number((tile && tile.canvas_y) || 0)"',
                                    ':data-canvas-w="Number((tile && tile.canvas_w) || 4)"',
                                    ':data-canvas-h="Number((tile && tile.canvas_h) || 3)"',
                                    ":style=\"((tab.grid.layout_mode === 'freeform')"
                                    " ? ('position:absolute;left:calc(' + (Number((tile && tile.canvas_x) || 0) * 100 / Number(tab.grid.canvas_columns || 24)) + '% + 2px);top:' + ((Number((tile && tile.canvas_y) || 0) * Number(tab.grid.canvas_row_height || 24)) + 2) + 'px;width:calc(' + (Number((tile && tile.canvas_w) || 4) * 100 / Number(tab.grid.canvas_columns || 24)) + '% - 4px);height:' + ((Number((tile && tile.canvas_h) || 3) * Number(tab.grid.canvas_row_height || 24)) - 4) + 'px;border-radius:7px;box-shadow:0 2px 7px rgba(18,32,50,.14);')"
                                    " : ((tab.grid.layout_mode === 'spanning')"
                                    " ? ('grid-row:' + Number((tile && tile.grid_row) || (Math.floor(i / tab.grid.columns) + 1)) + ' / span ' + Number((tile && tile.row_span) || 1) + ';grid-column:' + Number((tile && tile.grid_col) || ((i % tab.grid.columns) + 1)) + ' / span ' + Number((tile && tile.col_span) || 1) + ';')"
                                    " : ''))"
                                    " + 'overflow:hidden;display:flex;flex-direction:column;position:relative;box-sizing:border-box;border:1px solid #cfcfcf;'"
                                    " + ((tab.grid.layout_mode === 'spanning' && tile && tile.grid_hidden) ? 'display:none;' : '')\"",
                                ],
                            ):
                                with vuetify.Template(v_if="tile && tile.variable_name"):
                                    html.Div(
                                        "{{ tile.display_title || tile.variable_name || 'variable' }}",
                                        classes="seurat-workspace-preview-title",
                                    )
                                    with html.Div(classes="seurat-workspace-preview-media"):
                                        with vuetify.Template(v_if="tile.media_type === 'plot1d'"):
                                            html.Div(
                                                classes="seurat-plot1d",
                                                raw_attrs=[
                                                    ':data-plot="JSON.stringify(tile.plot || {})"',
                                                    ':data-plot-settings="JSON.stringify(tile.plot_settings || {})"',
                                                    ':data-plot-axis-key="tile.plot_axis_key || \'\'"',
                                                ],
                                            )
                                        with vuetify.Template(
                                            v_if="tile.media_type !== 'plot1d' && tile.src"
                                        ):
                                            with vuetify.Template(
                                                v_if="tile.media_type === 'image' || tile.media_type === 'image_sequence'"
                                            ):
                                                html.Img(
                                                    src=("tile.src",),
                                                    raw_attrs=[
                                                        ':class="[\'seurat-workspace-preview-image\', { \'seurat-grid-image-sequence\': tile.media_type === \'image_sequence\' }]"',
                                                        ':data-grid-image-sequence="tile.media_type === \'image_sequence\' ? \'1\' : null"',
                                                        ':data-fps="tile.fps || 2"',
                                                        ':data-frame-count="tile.frame_count || 0"',
                                                        ':data-frame-indices="(tile.frame_indices || []).join(\',\')"',
                                                        ':data-frame-sources="JSON.stringify(tile.frame_sources || [])"',
                                                        ':data-time-values="(tile.time_values || []).join(\',\')"',
                                                        ':data-time-mode="tile.time_mode || \'timestep\'"',
                                                        'data-current-frame="0"',
                                                        'draggable="false"',
                                                    ],
                                                )
                                            with vuetify.Template(
                                                v_if="tile.media_type !== 'image' && tile.media_type !== 'image_sequence'"
                                            ):
                                                html.Video(
                                                    src=("tile.src",),
                                                    class_="seurat-workspace-preview-image seurat-grid-video",
                                                    muted=True,
                                                    raw_attrs=[
                                                        'data-grid-video="1"',
                                                        ':data-fps="tile.fps || 2"',
                                                        ':data-frame-count="tile.frame_count || 0"',
                                                        ':data-frame-indices="(tile.frame_indices || []).join(\',\')"',
                                                        ':data-time-values="(tile.time_values || []).join(\',\')"',
                                                        ':data-time-mode="tile.time_mode || \'timestep\'"',
                                                        "playsinline",
                                                    ],
                                                )
                                with vuetify.Template(v_if="!(tile && tile.variable_name)"):
                                    with html.Div(classes="seurat-empty-cell"):
                                        html.Div("+", classes="seurat-empty-plus")


def _build_workspace_splitters():
    html.Div(
        classes="seurat-workspace-layout-surface",
        raw_attrs=[
            ':data-layout-tree="JSON.stringify((workspaceLayout || {}).root || {})"'
        ],
    )
    with vuetify.Template(v_for="pane in workspacePanes", key="'dock-' + pane.id"):
        with html.Div(
            classes="seurat-workspace-tab-dock-preview",
            raw_attrs=[
                ':data-tab-dock-pane-id="pane.id"',
                ':data-pane-frame-id="pane.id"',
                'aria-hidden="true"',
                ":style=\"{"
                " '--pane-left': Number(((workspacePaneFrames || {})[pane.id] || {}).left || 0) + '%',"
                " '--pane-top': Number(((workspacePaneFrames || {})[pane.id] || {}).top || 0) + '%',"
                " '--pane-width': Number(((workspacePaneFrames || {})[pane.id] || {}).width || 100) + '%',"
                " '--pane-height': Number(((workspacePaneFrames || {})[pane.id] || {}).height || 100) + '%'"
                "}\"",
            ],
        ):
            html.Div(
                classes=(
                    "seurat-workspace-tab-dock-target "
                    "is-tab-dock-right"
                ),
                raw_attrs=[
                    ':data-tab-dock-pane-id="pane.id"',
                    'data-tab-dock-direction="horizontal"',
                    'data-tab-dock-label="Split right"',
                    'aria-hidden="true"',
                ],
            )
            html.Div(
                classes=(
                    "seurat-workspace-tab-dock-target "
                    "is-tab-dock-bottom"
                ),
                raw_attrs=[
                    ':data-tab-dock-pane-id="pane.id"',
                    'data-tab-dock-direction="vertical"',
                    'data-tab-dock-label="Split down"',
                    'aria-hidden="true"',
                ],
            )
    with vuetify.Template(v_for="split in workspaceSplitters", key="split.id"):
        with html.Div(
            classes="seurat-workspace-splitter",
            raw_attrs=[
                ":class=\"split.direction === 'vertical' ? 'is-horizontal-divider' : 'is-vertical-divider'\"",
                ':data-split-frame-id="split.id"',
                ':data-split-id="split.id"',
                ':data-split-direction="split.direction"',
                ':data-split-ratio="split.ratio"',
                ':data-container-left="split.container_left"',
                ':data-container-top="split.container_top"',
                ':data-container-width="split.container_width"',
                ':data-container-height="split.container_height"',
                'role="separator"',
                ':aria-orientation="split.direction === \'vertical\' ? \'horizontal\' : \'vertical\'"',
                'aria-valuemin="15"',
                'aria-valuemax="85"',
                ':aria-valuenow="Math.round(Number(split.ratio || 0.5) * 100)"',
                'title="Drag to resize panes; double-click to reset"',
                ":style=\"{"
                " '--split-left': Number(split.left || 0) + '%',"
                " '--split-top': Number(split.top || 0) + '%',"
                " '--split-span': Number(split.span || 0) + '%'"
                "}\"",
            ],
        ):
            html.Span(
                classes="seurat-workspace-split-readout",
                raw_attrs=['aria-hidden="true"'],
            )


class GridWorkspace(TrameComponent):
    def __init__(self, server):
        super().__init__(server)
        self.runtime = None
        self.provenance_dialog = ProvenanceDialog(server)
        self.source_dialog = SourceDialog(server)
        self.scalar_plot_dialog = ScalarPlotDialog(server)
        self.plot_settings_panel = PlotSettingsPanel(server)
        self.plugin_options_panel = PluginOptionsPanel(server)
        self.scalar_field_settings_panel = ScalarFieldSettingsPanel(server)
        self.scalar_field_assistant_panel = ScalarFieldAssistantPanel(server)

    def build(self):
        ctrl = self.ctrl
        with vuetify.VCol(
            classes="seurat-content-column",
            style="display:flex; flex-direction:column; height:80vh;",
        ):
            with vuetify.VCard(
                variant="outlined",
                style="flex:1 1 auto; min-height:0; display:flex; flex-direction:column;",
            ):
                with vuetify.VCardText(
                    classes="seurat-workspace-card-content",
                    style=(
                        "height:100%;"
                        "min-height:0;"
                        "overflow:hidden;"
                    ),
                ):
                    self.runtime = GridRuntime()
                    html.Div(
                        "",
                        id="seurat-reset-view-request",
                        style="display:none;",
                        raw_attrs=[
                            ':data-reset-view-request="JSON.stringify(resetViewRequest || {})"'
                        ],
                    )
                    with html.Div(classes="seurat-vcr-bar seurat-grid-controls-header"):
                        with html.Div(classes="seurat-vcr-controls"):
                            html.Button(
                                "|<",
                                classes="seurat-vcr-btn",
                                raw_attrs=[
                                    'type="button"',
                                    'data-vcr-action="start"',
                                ],
                                title="Jump to start",
                            )
                            html.Button(
                                "<<",
                                classes="seurat-vcr-btn",
                                raw_attrs=[
                                    'type="button"',
                                    'data-vcr-action="back"',
                                ],
                                title="Back step",
                            )
                            html.Button(
                                "▶",
                                classes="seurat-vcr-btn",
                                raw_attrs=[
                                    'type="button"',
                                    'data-vcr-action="toggle"',
                                    'aria-label="Play all"',
                                ],
                                title="Play all",
                            )
                            html.Button(
                                ">>",
                                classes="seurat-vcr-btn",
                                raw_attrs=[
                                    'type="button"',
                                    'data-vcr-action="forward"',
                                ],
                                title="Forward step",
                            )
                            html.Button(
                                ">|",
                                classes="seurat-vcr-btn",
                                raw_attrs=[
                                    'type="button"',
                                    'data-vcr-action="end"',
                                ],
                                title="Jump to end",
                            )
                        with html.Div(classes="seurat-vcr-timeline"):
                            html.Span(
                                "Step = 0",
                                id="seurat-vcr-time-value",
                                class_="text-caption seurat-vcr-time",
                            )
                            html.Input(
                                type="range",
                                id="seurat-vcr-step-slider",
                                classes="seurat-vcr-slider",
                                change=(
                                    ctrl.set_active_axis_selection,
                                    "[$event.target.value]",
                                ),
                                raw_attrs=[
                                    'min="0"',
                                    'max="20"',
                                    'step="1"',
                                    'value="0"',
                                    'aria-label="Timestep"',
                                    'title="Timestep (frame index)"',
                                ],
                            )
                        _build_canvas_zoom_controls(ctrl)
                        _build_grid_layout_controls(ctrl)
                    with vuetify.Template(v_if="scalarPlotStatus"):
                        html.Div(
                            "{{ scalarPlotStatus }}",
                            class_="text-caption seurat-workspace-grid-status",
                            style="color:#8a4b00;",
                        )
                    _build_workspace_tab_bars(ctrl)
                    with html.Div(
                        classes="seurat-main-grid seurat-workspace-active-grid",
                        raw_attrs=[
                            ':key="workspaceActiveTabId"',
                            ":class=\"[workspacePanes.findIndex(pane => pane.id === workspaceActivePaneId) === 0 ? 'seurat-workspace-slot-first' : 'seurat-workspace-slot-second', { 'seurat-freeform-canvas': gridLayoutMode === 'freeform', 'show-grid': gridLayoutMode === 'freeform' && canvasShowGrid }]\"",
                            ':data-pane-frame-id="workspaceActivePaneId"',
                            ':data-pane-id="workspaceActivePaneId"',
                            ':data-tab-id="workspaceActiveTabId"',
                            ':data-layout-mode="gridLayoutMode"',
                            ':data-grid-sizing-mode="gridSizingMode"',
                            ':data-grid-cols="gridCols"',
                            ':data-grid-rows="gridRows"',
                            ':data-grid-column-sizes="(gridColumnSizes || []).join(\',\')"',
                            ':data-grid-row-sizes="(gridRowSizes || []).join(\',\')"',
                            ':data-grid-column-weights="(gridColumnWeights || []).join(\',\')"',
                            ':data-grid-row-weights="(gridRowWeights || []).join(\',\')"',
                            ':data-grid-min-column-size="gridMinCellSize"',
                            ':data-grid-max-column-size="gridMaxCellSize"',
                            ':data-grid-min-row-size="Number(gridMinCellSize || 80) + 32"',
                            ':data-grid-max-row-size="Number(gridMaxCellSize || 5000) + 32"',
                            ':data-grid-fit-min-column-size="gridFitMinCellSize"',
                            ':data-grid-fit-min-row-size="Number(gridFitMinCellSize || 180) + 32"',
                            ':data-grid-column-fallback="gridCellSize"',
                            ':data-grid-row-fallback="Number(gridCellSize || 300) + 32"',
                            ':data-canvas-cols="canvasCols"',
                            ':data-canvas-row-height="canvasRowHeight"',
                            ':data-canvas-snap="canvasSnapToGrid ? 1 : 0"',
                            ':data-canvas-nudge="canvasNudgeOthers ? 1 : 0"',
                            ':data-canvas-zoom="canvasZoom"',
                            ':data-canvas-fit="canvasFitToView ? 1 : 0"',
                            ':data-canvas-default-tile-width="canvasDefaultTileWidth || 2"',
                            ':data-canvas-dwell-ms="canvasDwellMs"',
                            ':data-canvas-dead-zone="canvasSnapDeadZone"',
                            ':data-canvas-transition-ms="canvasTransitionMs"',
                            ':data-canvas-revision="canvasLayoutRevision"',
                        ],
                        style=(
                            "('display:grid;'"
                            " + ((gridSizingMode === 'fit')"
                            " ? ('grid-template-columns:' + String(gridFitColumnTemplate || ('repeat(' + gridCols + ', minmax(' + Number(gridFitMinCellSize || 180) + 'px, 1fr))')) + ';'"
                            " + 'grid-template-rows:' + String(gridFitRowTemplate || ('repeat(' + gridRows + ', minmax(' + (Number(gridFitMinCellSize || 180) + 32) + 'px, 1fr))')) + ';'"
                            " + 'justify-content:stretch;'"
                            " + 'align-content:stretch;')"
                            " : ('grid-template-columns:' + String(gridColumnTemplate || ('repeat(' + gridCols + ', ' + Number(gridCellSize || 300) + 'px)')) + ';'"
                            " + 'grid-template-rows:' + String(gridRowTemplate || ('repeat(' + gridRows + ', ' + (Number(gridCellSize || 300) + 32) + 'px)')) + ';'"
                            " + 'justify-content:center;'"
                            " + 'align-content:start;'))"
                            " + '--pane-left:' + Number(((workspacePaneFrames || {})[workspaceActivePaneId] || {}).left || 0) + '%;'"
                            " + '--pane-top:' + Number(((workspacePaneFrames || {})[workspaceActivePaneId] || {}).top || 0) + '%;'"
                            " + '--pane-width:' + Number(((workspacePaneFrames || {})[workspaceActivePaneId] || {}).width || 100) + '%;'"
                            " + '--pane-height:' + Number(((workspacePaneFrames || {})[workspaceActivePaneId] || {}).height || 100) + '%;'"
                            " + 'flex:1 1 auto;'"
                            " + 'min-height:0;'"
                            " + 'overflow:auto;'"
                            " + 'width:100%;'"
                            " + 'box-sizing:border-box;'"
                            " + 'position:relative;'"
                            " + 'margin:4px 0 0 0;'"
                            " + 'border:1px solid #cfcfcf;')",
                        ),
                    ):
                        html.Div(
                            classes="seurat-canvas-extent",
                            v_if="gridLayoutMode === 'freeform'",
                            raw_attrs=[
                                ":style=\"{ top: ((Math.max(12, ...(gridCells || []).map(tile => Number((tile && tile.canvas_y) || 0) + Number((tile && tile.canvas_h) || 0))) * Number(canvasRowHeight || 24)) + 24) + 'px' }\"",
                            ],
                        )
                        with html.Div(
                            classes="seurat-canvas-grid-overlay",
                            v_if="gridLayoutMode === 'freeform' && canvasShowGrid",
                            raw_attrs=[
                                'aria-hidden="true"',
                                ':data-grid-columns="canvasCols"',
                                ":style=\"{ height: (((Math.max(12, Math.ceil(Math.max(0, ...(gridCells || []).map(tile => Number((tile && tile.canvas_y) || 0) + Number((tile && tile.canvas_h) || 0))))) * Number(canvasRowHeight || 24)) + Number(canvasRowHeight || 24)) + 'px') }\"",
                            ],
                        ):
                            with vuetify.Template(
                                v_for="line in Math.max(0, Number(canvasCols || 24) - 1)",
                                key="'vertical-' + line",
                            ):
                                html.Div(
                                    classes="seurat-canvas-grid-line is-vertical",
                                    raw_attrs=[
                                        ':class="{ \'is-major\': line % 4 === 0 }"',
                                        ':data-grid-line="line"',
                                        ":style=\"{ left: ((line * 100 / Number(canvasCols || 24)) + '%') }\"",
                                    ],
                                )
                            with vuetify.Template(
                                v_for="line in Math.max(12, Math.ceil(Math.max(0, ...(gridCells || []).map(tile => Number((tile && tile.canvas_y) || 0) + Number((tile && tile.canvas_h) || 0)))))",
                                key="'horizontal-' + line",
                            ):
                                html.Div(
                                    classes="seurat-canvas-grid-line is-horizontal",
                                    raw_attrs=[
                                        ':class="{ \'is-major\': line % 4 === 0 }"',
                                        ':data-grid-line="line"',
                                        ":style=\"{ top: ((line * Number(canvasRowHeight || 24)) + 'px') }\"",
                                    ],
                                )
                        with vuetify.Template(
                            v_if="gridLayoutMode === 'freeform' && !(gridCells || []).some(tile => tile && (tile.variable_name || tile.src || (tile.plot && Object.keys(tile.plot).length) || (tile.status && tile.status !== 'empty')))"
                        ):
                            with html.Div(classes="seurat-canvas-empty-state"):
                                html.Div("Drop a variable anywhere", classes="seurat-canvas-empty-title")
                                html.Div(
                                    "Tiles will snap to a {{ canvasCols }}-column canvas.",
                                    classes="seurat-canvas-empty-copy",
                                )
                        html.Div(
                            classes="seurat-canvas-placeholder",
                            v_if="gridLayoutMode === 'freeform'",
                            raw_attrs=['aria-hidden="true"'],
                        )
                        html.Div(
                            classes="seurat-canvas-insertion-caret",
                            v_if="gridLayoutMode === 'freeform'",
                            raw_attrs=['aria-hidden="true"'],
                        )
                        html.Div(
                            classes="seurat-canvas-guide seurat-canvas-guide-v guide-v-1",
                            v_if="gridLayoutMode === 'freeform'",
                            raw_attrs=['aria-hidden="true"'],
                        )
                        html.Div(
                            classes="seurat-canvas-guide seurat-canvas-guide-v guide-v-2",
                            v_if="gridLayoutMode === 'freeform'",
                            raw_attrs=['aria-hidden="true"'],
                        )
                        html.Div(
                            classes="seurat-canvas-guide seurat-canvas-guide-h guide-h-1",
                            v_if="gridLayoutMode === 'freeform'",
                            raw_attrs=['aria-hidden="true"'],
                        )
                        html.Div(
                            classes="seurat-canvas-guide seurat-canvas-guide-h guide-h-2",
                            v_if="gridLayoutMode === 'freeform'",
                            raw_attrs=['aria-hidden="true"'],
                        )
                        with vuetify.Template(v_for="(tile, i) in gridCells", key="i"):
                            with html.Div(
                                v_if="gridLayoutMode !== 'freeform' || (tile && (tile.variable_name || tile.src || (tile.plot && Object.keys(tile.plot).length) || (tile.status && tile.status !== 'empty')))",
                                click=(
                                    ctrl.set_active_grid_cell,
                                    "[i, (($event && $event.target && $event.target.closest && $event.target.closest('.seurat-cell-close, .seurat-timeline-driver-btn, .seurat-scalar-field-ai-btn, .seurat-grid-track-resize-handle')) ? 1 : 0), (($event && $event.shiftKey) ? 1 : 0)]",
                                ),
                                classes="seurat-dropcell",
                                raw_attrs=[
                                    ':data-cell-index="i"',
                                    ':data-pane-id="workspaceActivePaneId"',
                                    ':data-tab-id="workspaceActiveTabId"',
                                    ':data-cell-filled="((tile && tile.variable_name) ? 1 : 0)"',
                                    ':data-cell-active="(activeGridCell === i ? 1 : 0)"',
                                    ':data-timeline-driver="(timelineDriverCell === i ? 1 : 0)"',
                                    ':data-selection-axis="JSON.stringify((tile && tile.selection_axis) || {})"',
                                    ':data-axis-sync-status="(tile && tile.axis_sync_status) || \'\'"',
                                    ':data-tile-id="(tile && tile.tile_id) || (\'tile-\' + (i + 1))"',
                                    ':data-tile-type="(tile && tile.tile_type) || \'plot\'"',
                                    ':data-canvas-x="Number((tile && tile.canvas_x) || 0)"',
                                    ':data-canvas-y="Number((tile && tile.canvas_y) || 0)"',
                                    ':data-canvas-w="Number((tile && tile.canvas_w) || 4)"',
                                    ':data-canvas-h="Number((tile && tile.canvas_h) || 3)"',
                                    ':aria-selected="activeGridCell === i ? \'true\' : \'false\'"',
                                    ':draggable="gridLayoutMode !== \'freeform\' && !!(tile && tile.variable_name)"',
                                ],
                                style=(
                                    "((gridLayoutMode === 'freeform')"
                                    " ? ('position:absolute;left:calc(' + (Number((tile && tile.canvas_x) || 0) * 100 / Number(canvasCols || 24)) + '% + 2px);top:' + ((Number((tile && tile.canvas_y) || 0) * Number(canvasRowHeight || 24)) + 2) + 'px;width:calc(' + (Number((tile && tile.canvas_w) || 4) * 100 / Number(canvasCols || 24)) + '% - 4px);height:' + ((Number((tile && tile.canvas_h) || 3) * Number(canvasRowHeight || 24)) - 4) + 'px;')"
                                    " : ((gridLayoutMode === 'spanning')"
                                    " ? ('grid-row:' + Number((tile && tile.grid_row) || (Math.floor(i / gridCols) + 1)) + ' / span ' + Number((tile && tile.row_span) || 1) + ';grid-column:' + Number((tile && tile.grid_col) || ((i % gridCols) + 1)) + ' / span ' + Number((tile && tile.col_span) || 1) + ';')"
                                    " : ''))"
                                    " + ((gridLayoutMode === 'spanning')"
                                    " ? 'width:100%; height:100%; min-width:0; min-height:0;'"
                                    " : ((gridLayoutMode === 'freeform') ? 'min-width:0;min-height:0;' : ((gridSizingMode === 'fit')"
                                    " ? ('width:100%; height:100%; min-width:' + Number(gridFitMinCellSize || 180) + 'px; min-height:' + (Number(gridFitMinCellSize || 180) + 32) + 'px;')"
                                    " : 'width:100%; height:100%; min-width:0; min-height:0;')))"
                                    " + 'overflow:hidden; cursor:pointer; display:flex; flex-direction:column; box-sizing:border-box;'"
                                    " + ((gridLayoutMode === 'freeform') ? 'border:1px solid #b8c2cf;border-radius:7px;background:#fff;box-shadow:0 2px 8px rgba(18,32,50,.16);' : ((gridLayoutMode === 'spanning') ? 'position:relative;border:1px solid #cfcfcf;' : ('position:relative;border-left:1px solid #cfcfcf; border-top:1px solid #cfcfcf;'"
                                    " + (((i % gridCols) === (gridCols - 1)) ? 'border-right:1px solid #cfcfcf;' : '')"
                                    " + ((i >= ((gridRows - 1) * gridCols)) ? 'border-bottom:1px solid #cfcfcf;' : ''))))"
                                    " + ((activeGridCell === i) ? 'background:#e7f0ff; outline:3px solid #0d47a1; outline-offset:-3px; z-index:2;' : '')"
                                    " + ((gridLayoutMode === 'spanning' && tile && tile.grid_hidden) ? 'display:none;' : '')",
                                ),
                            ):
                                html.Div(
                                    classes="seurat-grid-track-resize-handle seurat-grid-col-resize-handle seurat-grid-left-resize-handle",
                                    v_if=(
                                        "gridLayoutMode !== 'freeform' && gridSizingMode !== 'fit'"
                                        " && !(gridLayoutMode === 'spanning' && tile && tile.grid_hidden)"
                                        " && ((gridLayoutMode === 'spanning'"
                                        " ? Number((tile && tile.grid_col) || ((i % gridCols) + 1))"
                                        " : ((i % gridCols) + 1)) === 1)"
                                    ),
                                    raw_attrs=[
                                        'role="separator"',
                                        'aria-orientation="vertical"',
                                        'title="Drag to resize column"',
                                        'data-resize-edge="left"',
                                        'data-col-index="0"',
                                    ],
                                )
                                html.Div(
                                    classes="seurat-grid-track-resize-handle seurat-grid-col-resize-handle",
                                    v_if=(
                                        "gridLayoutMode !== 'freeform'"
                                        " && !(gridLayoutMode === 'spanning' && tile && tile.grid_hidden)"
                                        " && (gridSizingMode !== 'fit' || ((gridLayoutMode === 'spanning'"
                                        " ? (Number((tile && tile.grid_col) || ((i % gridCols) + 1)) + Number((tile && tile.col_span) || 1) - 1)"
                                        " : ((i % gridCols) + 1)) < Number(gridCols || 0)))"
                                    ),
                                    raw_attrs=[
                                        'role="separator"',
                                        'aria-orientation="vertical"',
                                        'title="Drag to resize column"',
                                        'data-resize-edge="right"',
                                        ':data-col-index="gridLayoutMode === \'spanning\' ? (Number((tile && tile.grid_col) || ((i % gridCols) + 1)) + Number((tile && tile.col_span) || 1) - 2) : (i % gridCols)"',
                                    ],
                                )
                                html.Div(
                                    classes="seurat-grid-track-resize-handle seurat-grid-row-resize-handle seurat-grid-top-resize-handle",
                                    v_if=(
                                        "gridLayoutMode !== 'freeform' && gridSizingMode !== 'fit'"
                                        " && !(gridLayoutMode === 'spanning' && tile && tile.grid_hidden)"
                                        " && ((gridLayoutMode === 'spanning'"
                                        " ? Number((tile && tile.grid_row) || (Math.floor(i / gridCols) + 1))"
                                        " : (Math.floor(i / gridCols) + 1)) === 1)"
                                    ),
                                    raw_attrs=[
                                        'role="separator"',
                                        'aria-orientation="horizontal"',
                                        'title="Drag to resize row"',
                                        'data-resize-edge="top"',
                                        'data-row-index="0"',
                                    ],
                                )
                                html.Div(
                                    classes="seurat-grid-track-resize-handle seurat-grid-row-resize-handle",
                                    v_if=(
                                        "gridLayoutMode !== 'freeform'"
                                        " && !(gridLayoutMode === 'spanning' && tile && tile.grid_hidden)"
                                        " && (gridSizingMode !== 'fit' || ((gridLayoutMode === 'spanning'"
                                        " ? (Number((tile && tile.grid_row) || (Math.floor(i / gridCols) + 1)) + Number((tile && tile.row_span) || 1) - 1)"
                                        " : (Math.floor(i / gridCols) + 1)) < Number(gridRows || 0)))"
                                    ),
                                    raw_attrs=[
                                        'role="separator"',
                                        'aria-orientation="horizontal"',
                                        'title="Drag to resize row"',
                                        'data-resize-edge="bottom"',
                                        ':data-row-index="gridLayoutMode === \'spanning\' ? (Number((tile && tile.grid_row) || (Math.floor(i / gridCols) + 1)) + Number((tile && tile.row_span) || 1) - 2) : Math.floor(i / gridCols)"',
                                    ],
                                )
                                html.Div(
                                    classes="seurat-grid-track-resize-handle seurat-grid-corner-resize-handle seurat-grid-corner-bottom-left",
                                    v_if=(
                                        "gridLayoutMode !== 'freeform'"
                                        " && !(gridLayoutMode === 'spanning' && tile && tile.grid_hidden)"
                                        " && (gridSizingMode !== 'fit' || ("
                                        "((gridLayoutMode === 'spanning' ? Number((tile && tile.grid_col) || ((i % gridCols) + 1)) : ((i % gridCols) + 1)) > 1)"
                                        " && ((gridLayoutMode === 'spanning' ? (Number((tile && tile.grid_row) || (Math.floor(i / gridCols) + 1)) + Number((tile && tile.row_span) || 1) - 1) : (Math.floor(i / gridCols) + 1)) < Number(gridRows || 0))"
                                        "))"
                                    ),
                                    raw_attrs=[
                                        'role="separator"',
                                        'aria-orientation="vertical"',
                                        'title="Drag to resize row and column"',
                                        'data-col-edge="left"',
                                        'data-row-edge="bottom"',
                                        ':data-col-index="gridLayoutMode === \'spanning\' ? (Number((tile && tile.grid_col) || ((i % gridCols) + 1)) - 1) : (i % gridCols)"',
                                        ':data-row-index="gridLayoutMode === \'spanning\' ? (Number((tile && tile.grid_row) || (Math.floor(i / gridCols) + 1)) + Number((tile && tile.row_span) || 1) - 2) : Math.floor(i / gridCols)"',
                                    ],
                                )
                                html.Div(
                                    classes="seurat-grid-track-resize-handle seurat-grid-corner-resize-handle seurat-grid-corner-bottom-right",
                                    v_if=(
                                        "gridLayoutMode !== 'freeform'"
                                        " && !(gridLayoutMode === 'spanning' && tile && tile.grid_hidden)"
                                        " && (gridSizingMode !== 'fit' || ("
                                        "((gridLayoutMode === 'spanning' ? (Number((tile && tile.grid_col) || ((i % gridCols) + 1)) + Number((tile && tile.col_span) || 1) - 1) : ((i % gridCols) + 1)) < Number(gridCols || 0))"
                                        " && ((gridLayoutMode === 'spanning' ? (Number((tile && tile.grid_row) || (Math.floor(i / gridCols) + 1)) + Number((tile && tile.row_span) || 1) - 1) : (Math.floor(i / gridCols) + 1)) < Number(gridRows || 0))"
                                        "))"
                                    ),
                                    raw_attrs=[
                                        'role="separator"',
                                        'aria-orientation="vertical"',
                                        'title="Drag to resize row and column"',
                                        'data-col-edge="right"',
                                        'data-row-edge="bottom"',
                                        ':data-col-index="gridLayoutMode === \'spanning\' ? (Number((tile && tile.grid_col) || ((i % gridCols) + 1)) + Number((tile && tile.col_span) || 1) - 2) : (i % gridCols)"',
                                        ':data-row-index="gridLayoutMode === \'spanning\' ? (Number((tile && tile.grid_row) || (Math.floor(i / gridCols) + 1)) + Number((tile && tile.row_span) || 1) - 2) : Math.floor(i / gridCols)"',
                                    ],
                                )
                                with vuetify.Template(v_if="tile && tile.variable_name"):
                                    with html.Div(
                                        classes="seurat-tile-header",
                                        style=(
                                            "'display:flex;'"
                                            " + 'align-items:center;'"
                                            " + 'gap:8px;'"
                                            " + 'width:100%;'"
                                            " + 'height:32px;'"
                                            " + 'padding:4px 6px;'"
                                            " + (((selectedGridCellMap || {})[String(i)]) ? 'background:#ef6c00; color:#fff; border-bottom:1px solid #b53d00;' : ((activeGridCell === i) ? 'background:#1565c0; color:#fff; border-bottom:1px solid #0d47a1;' : 'background:#7bd0ef; color:#111; border-bottom:1px solid #3ca7c9;'))",
                                        ),
                                    ):
                                        html.Div(
                                            "{{ tile.display_title || tile.variable_name || 'variable' }}",
                                            style="flex:1 1 auto; min-width:0; font-size:0.9rem; font-weight:400; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;",
                                        )
                                        html.Button(
                                            "AI",
                                            v_if=(
                                                "scalarFieldAssistantAvailable"
                                                " && (tile.media_type === 'plot1d'"
                                                " || tile.variable_type === 'scalarField'"
                                                " || tile.payload_type === 'SCALAR_FIELD'"
                                                " || tile.visualization_item_type === 'SCALAR_FIELD')"
                                            ),
                                            classes="seurat-scalar-field-ai-btn",
                                            click=(
                                                ctrl.open_scalar_field_options_assistant,
                                                "[i]",
                                            ),
                                            raw_attrs=[
                                                'type="button"',
                                                'aria-label="Open plot options assistant"',
                                            ],
                                            style=(
                                                "flex:0 0 auto;"
                                                "height:20px;"
                                                "min-width:26px;"
                                                "padding:0 5px;"
                                                "font-size:11px;"
                                                "line-height:18px;"
                                                "border:1px solid currentColor;"
                                                "border-radius:3px;"
                                                "background:rgba(255,255,255,.9);"
                                                "color:#111;"
                                                "cursor:pointer;"
                                            ),
                                            title="Open plot options assistant",
                                        )
                                        with html.Button(
                                            v_if=(
                                                "(tile.selection_axis && tile.selection_axis.values"
                                                " && tile.selection_axis.values.length)"
                                                " || (tile.time_values && tile.time_values.length)"
                                                " || (tile.plot && tile.plot.series && tile.plot.series.length"
                                                " && (String(tile.plot.x_label || '').toLowerCase() === 'time'"
                                                " || String(tile.plot.x_label || '').toLowerCase() === 'physical time'))"
                                            ),
                                            classes="seurat-timeline-driver-btn",
                                            click=(ctrl.toggle_timeline_driver_cell, "[i]"),
                                            raw_attrs=[
                                                'type="button"',
                                                ':aria-pressed="timelineDriverCell === i ? \'true\' : \'false\'"',
                                            ],
                                            title="Use as timeline driver",
                                        ):
                                            html.Span(
                                                classes="seurat-timeline-clock-icon",
                                                raw_attrs=['aria-hidden="true"'],
                                            )
                                        html.Button(
                                            "x",
                                            classes="seurat-cell-close",
                                            click=(ctrl.clear_grid_cell, "[i]"),
                                            style=(
                                                "margin-left:auto;"
                                                "flex:0 0 auto;"
                                                "width:18px;"
                                                "height:18px;"
                                                "line-height:16px;"
                                                "padding:0;"
                                                "font-size:11px;"
                                                "border:1px solid #2c7c97;"
                                                "border-radius:2px;"
                                                "background:#fff;"
                                                "color:#222;"
                                                "cursor:pointer;"
                                            ),
                                            title="Remove",
                                        )

                                    with html.Div(
                                        style="width:100%; flex:1 1 auto; min-height:0; background:#111; position:relative; overflow:hidden;",
                                    ):
                                        with vuetify.Template(v_if="tile.media_type === 'plot1d'"):
                                            html.Div(
                                                classes="seurat-plot1d",
                                                raw_attrs=[
                                                    ':data-plot="JSON.stringify(tile.plot || {})"',
                                                    ':data-plot-settings="JSON.stringify(tile.plot_settings || {})"',
                                                    ':data-plot-axis-key="tile.plot_axis_key || \'\'"',
                                                ],
                                                style=(
                                                    "display:block;"
                                                    "width:100%;"
                                                    "height:100%;"
                                                    "background:#fff;"
                                                ),
                                            )
                                            with vuetify.Template(
                                                v_if=(
                                                    "tile.plot"
                                                    " && tile.plot.series"
                                                    " && tile.plot.series.length > 1"
                                                ),
                                            ):
                                                with html.Div(classes="seurat-plot-legend"):
                                                    with vuetify.Template(
                                                        v_for="(item, j) in ((tile.plot && tile.plot.series) || [])",
                                                        key="j",
                                                    ):
                                                        with html.Div(
                                                            classes="seurat-plot-legend-item",
                                                            raw_attrs=[
                                                                ':title="item.source_label || item.source_key || (\'Series \' + (j + 1))"',
                                                            ],
                                                        ):
                                                            html.Div(
                                                                classes="seurat-plot-legend-line",
                                                                raw_attrs=[
                                                                    ":data-line-style=\"(((tile.plot_settings && tile.plot_settings.series_styles && tile.plot_settings.series_styles[(item.source_key || item.source_label || ('series:' + j))] && tile.plot_settings.series_styles[(item.source_key || item.source_label || ('series:' + j))].line_style) || item.line_style || 'solid').toLowerCase().replace('_', '-'))\"",
                                                                    ":style=\"{'--seurat-legend-color': ((tile.plot_settings && tile.plot_settings.series_styles && tile.plot_settings.series_styles[(item.source_key || item.source_label || ('series:' + j))] && tile.plot_settings.series_styles[(item.source_key || item.source_label || ('series:' + j))].color) || (tile.plot_settings && tile.plot_settings.series_colors && tile.plot_settings.series_colors[(item.source_key || item.source_label || ('series:' + j))]) || item.color || '#1565c0')}\"",
                                                                ],
                                                            )
                                                            html.Span(
                                                                "{{ item.source_label || item.source_key || ('Series ' + (j + 1)) }}",
                                                                classes="seurat-plot-legend-label",
                                                            )
                                        with vuetify.Template(v_if="tile.media_type !== 'plot1d'"):
                                            with vuetify.Template(v_if="tile.src"):
                                                with vuetify.Template(
                                                    v_if=(
                                                        "(tile.media_type === 'image' || tile.media_type === 'image_sequence')"
                                                        " && (tile.variable_type === 'scalarField'"
                                                        " || tile.payload_type === 'SCALAR_FIELD'"
                                                        " || tile.visualization_item_type === 'SCALAR_FIELD')"
                                                    )
                                                ):
                                                    with html.Div(
                                                        classes="seurat-scalar-field-view",
                                                        raw_attrs=[
                                                            ":style=\"{"
                                                            " '--seurat-scalar-field-background': ((tile.scalar_field_settings && tile.scalar_field_settings.background_color) || '#000000'),"
                                                            " '--seurat-scalar-field-foreground': ((tile.scalar_field_settings && tile.scalar_field_settings.foreground_color) || '#ffffff')"
                                                            " }\"",
                                                        ],
                                                    ):
                                                        with html.Div(
                                                            classes="seurat-scalar-field-plot-frame seurat-panzoom-viewport",
                                                            raw_attrs=[
                                                                ":class=\"{ 'seurat-scalar-field-show-axes': tile.scalar_field_settings && tile.scalar_field_settings.show_axes }\"",
                                                            ],
                                                        ):
                                                            with html.Div(classes="seurat-panzoom-content"):
                                                                with vuetify.Template(v_if="tile.media_type === 'image_sequence'"):
                                                                    html.Img(
                                                                        src=("tile.src",),
                                                                        class_="seurat-grid-image-sequence",
                                                                        raw_attrs=[
                                                                            'data-grid-image-sequence="1"',
                                                                            ':data-fps="tile.fps || 2"',
                                                                            ':data-frame-count="tile.frame_count || 0"',
                                                                            ':data-frame-indices="(tile.frame_indices || []).join(\',\')"',
                                                                            ':data-frame-sources="JSON.stringify(tile.frame_sources || [])"',
                                                                            ':data-time-values="(tile.time_values || []).join(\',\')"',
                                                                            ':data-time-mode="tile.time_mode || \'timestep\'"',
                                                                            'data-current-frame="0"',
                                                                            'draggable="false"',
                                                                        ],
                                                                    )
                                                                with vuetify.Template(v_if="tile.media_type === 'image'"):
                                                                    html.Img(src=("tile.src",), raw_attrs=['draggable="false"'])
                                                            with vuetify.Template(
                                                                v_if=(
                                                                    "tile.scalar_field_settings"
                                                                    " && tile.scalar_field_settings.show_axes"
                                                                )
                                                            ):
                                                                with html.Div(
                                                                    classes="seurat-scalar-field-y-axis",
                                                                    raw_attrs=[
                                                                        'data-scalar-axis="y"',
                                                                        ":data-axis-start=\"tile.scalar_field_axes && tile.scalar_field_axes.y && tile.scalar_field_axes.y.start\"",
                                                                        ":data-axis-end=\"tile.scalar_field_axes && tile.scalar_field_axes.y && tile.scalar_field_axes.y.end\"",
                                                                    ],
                                                                ):
                                                                    with vuetify.Template(
                                                                        v_for="tick in ((tile.scalar_field_axes && tile.scalar_field_axes.y && tile.scalar_field_axes.y.ticks) || [])",
                                                                        key="'y:' + tick.position",
                                                                    ):
                                                                        with html.Div(
                                                                            classes="seurat-scalar-field-y-tick",
                                                                            raw_attrs=[
                                                                                ":class=\"{ 'is-start': tick.position === 0, 'is-end': tick.position === 100 }\"",
                                                                                ":style=\"{ bottom: tick.position + '%' }\"",
                                                                                ':data-axis-position="tick.position"',
                                                                                ':data-axis-value="tick.value"',
                                                                            ],
                                                                        ):
                                                                            html.Span(
                                                                                "{{ tick.label }}",
                                                                                classes="seurat-scalar-field-tick-label",
                                                                            )
                                                                    html.Div(
                                                                        "{{ (tile.scalar_field_axes && tile.scalar_field_axes.y && tile.scalar_field_axes.y.label) || 'row' }}",
                                                                        classes="seurat-scalar-field-y-label",
                                                                    )
                                                                with html.Div(
                                                                    classes="seurat-scalar-field-x-axis",
                                                                    raw_attrs=[
                                                                        'data-scalar-axis="x"',
                                                                        ":data-axis-start=\"tile.scalar_field_axes && tile.scalar_field_axes.x && tile.scalar_field_axes.x.start\"",
                                                                        ":data-axis-end=\"tile.scalar_field_axes && tile.scalar_field_axes.x && tile.scalar_field_axes.x.end\"",
                                                                    ],
                                                                ):
                                                                    with vuetify.Template(
                                                                        v_for="tick in ((tile.scalar_field_axes && tile.scalar_field_axes.x && tile.scalar_field_axes.x.ticks) || [])",
                                                                        key="'x:' + tick.position",
                                                                    ):
                                                                        with html.Div(
                                                                            classes="seurat-scalar-field-x-tick",
                                                                            raw_attrs=[
                                                                                ":class=\"{ 'is-start': tick.position === 0, 'is-end': tick.position === 100 }\"",
                                                                                ":style=\"{ left: tick.position + '%' }\"",
                                                                                ':data-axis-position="tick.position"',
                                                                                ':data-axis-value="tick.value"',
                                                                            ],
                                                                        ):
                                                                            html.Span(
                                                                                "{{ tick.label }}",
                                                                                classes="seurat-scalar-field-tick-label",
                                                                            )
                                                                    html.Div(
                                                                        "{{ (tile.scalar_field_axes && tile.scalar_field_axes.x && tile.scalar_field_axes.x.label) || 'column' }}",
                                                                        classes="seurat-scalar-field-x-label",
                                                                    )
                                                        with vuetify.Template(
                                                            v_if=(
                                                                "tile.scalar_field_settings"
                                                                " && tile.scalar_field_settings.show_colorbar"
                                                                " && tile.scalar_field_settings.render_mode !== 'contours'"
                                                            )
                                                        ):
                                                            with html.Div(classes="seurat-scalar-field-colorbar"):
                                                                html.Div(
                                                                    classes="seurat-scalar-field-colorbar-ramp",
                                                                    raw_attrs=[
                                                                        ":style=\"{ '--seurat-scalar-field-colorbar': ((tile.scalar_field_settings && tile.scalar_field_settings.colorbar_gradient) || 'linear-gradient(to top, #440154, #fde725)') }\"",
                                                                    ],
                                                                )
                                                                with html.Div(classes="seurat-scalar-field-colorbar-labels"):
                                                                    html.Div(
                                                                        "{{ tile.scalar_field_colorbar_max || tile.max || '' }}",
                                                                        classes="seurat-scalar-field-colorbar-label",
                                                                        raw_attrs=[
                                                                            ':title="String(tile.scalar_field_colorbar_max || tile.max || \'\')"',
                                                                        ],
                                                                    )
                                                                    html.Div(
                                                                        "{{ tile.scalar_field_colorbar_min || tile.min || '' }}",
                                                                        classes="seurat-scalar-field-colorbar-label",
                                                                        raw_attrs=[
                                                                            ':title="String(tile.scalar_field_colorbar_min || tile.min || \'\')"',
                                                                        ],
                                                                    )
                                                with vuetify.Template(
                                                    v_if=(
                                                        "tile.media_type === 'image_sequence'"
                                                        " && !(tile.variable_type === 'scalarField'"
                                                        " || tile.payload_type === 'SCALAR_FIELD'"
                                                        " || tile.visualization_item_type === 'SCALAR_FIELD')"
                                                    )
                                                ):
                                                    with html.Div(classes="seurat-panzoom-viewport"):
                                                        with html.Div(classes="seurat-panzoom-content"):
                                                            html.Img(
                                                                src=("tile.src",),
                                                                class_="seurat-grid-image-sequence",
                                                                raw_attrs=[
                                                                    'data-grid-image-sequence="1"',
                                                                    ':data-fps="tile.fps || 2"',
                                                                    ':data-frame-count="tile.frame_count || 0"',
                                                                    ':data-frame-indices="(tile.frame_indices || []).join(\',\')"',
                                                                    ':data-frame-sources="JSON.stringify(tile.frame_sources || [])"',
                                                                    ':data-time-values="(tile.time_values || []).join(\',\')"',
                                                                    ':data-time-mode="tile.time_mode || \'timestep\'"',
                                                                    'data-current-frame="0"',
                                                                    'draggable="false"',
                                                                ],
                                                                style=(
                                                                    "display:block;"
                                                                    "width:100%;"
                                                                    "height:100%;"
                                                                    "object-fit:contain;"
                                                                    "background:#111;"
                                                                ),
                                                            )
                                                with vuetify.Template(
                                                    v_if=(
                                                        "tile.media_type === 'image'"
                                                        " && !(tile.variable_type === 'scalarField'"
                                                        " || tile.payload_type === 'SCALAR_FIELD'"
                                                        " || tile.visualization_item_type === 'SCALAR_FIELD')"
                                                    )
                                                ):
                                                    with html.Div(classes="seurat-panzoom-viewport"):
                                                        with html.Div(classes="seurat-panzoom-content"):
                                                            html.Img(
                                                                src=("tile.src",),
                                                                raw_attrs=['draggable="false"'],
                                                                style=(
                                                                    "display:block;"
                                                                    "width:100%;"
                                                                    "height:100%;"
                                                                    "object-fit:contain;"
                                                                    "background:#111;"
                                                                ),
                                                            )
                                                with vuetify.Template(v_if="tile.media_type !== 'image' && tile.media_type !== 'image_sequence'"):
                                                    with html.Div(classes="seurat-panzoom-viewport"):
                                                        with html.Div(classes="seurat-panzoom-content"):
                                                            html.Video(
                                                                src=("tile.src",),
                                                                class_="seurat-grid-video",
                                                                controls=False,
                                                                autoplay=False,
                                                                loop=False,
                                                                muted=True,
                                                                raw_attrs=[
                                                                    'data-grid-video="1"',
                                                                    ':data-fps="tile.fps || 2"',
                                                                    ':data-frame-count="tile.frame_count || 0"',
                                                                    ':data-frame-indices="(tile.frame_indices || []).join(\',\')"',
                                                                    ':data-time-values="(tile.time_values || []).join(\',\')"',
                                                                    ':data-time-mode="tile.time_mode || \'timestep\'"',
                                                                    "playsinline",
                                                                    "webkit-playsinline",
                                                                ],
                                                                style=(
                                                                    "display:block;"
                                                                    "width:100%;"
                                                                    "height:100%;"
                                                                    "object-fit:contain;"
                                                                    "background:#111;"
                                                                ),
                                                            )
                                            with vuetify.Template(v_if="!tile.src"):
                                                html.Div(
                                                    "{{ tile.note ? tile.note : 'No movie src' }}",
                                                    class_="text-caption",
                                                    style=(
                                                        "display:flex;"
                                                        "height:100%;"
                                                        "align-items:center;"
                                                        "justify-content:center;"
                                                        "text-align:center;"
                                                        "padding:8px;"
                                                        "color:#ddd;"
                                                    ),
                                                )
                                for resize_edge in (
                                    "top",
                                    "right",
                                    "bottom",
                                    "left",
                                    "top-left",
                                    "top-right",
                                    "bottom-left",
                                    "bottom-right",
                                ):
                                    handle_classes = (
                                        "seurat-canvas-resize-zone "
                                        f"is-{resize_edge}"
                                    )
                                    if resize_edge == "bottom-right":
                                        handle_classes += (
                                            " seurat-canvas-resize-handle"
                                        )
                                    html.Div(
                                        classes=handle_classes,
                                        v_if="gridLayoutMode === 'freeform' && tile && tile.variable_name",
                                        raw_attrs=[
                                            'role="separator"',
                                            f'data-resize-edge="{resize_edge}"',
                                            f'aria-label="Resize tile from {resize_edge.replace("-", " ")}"',
                                            f'title="Resize from {resize_edge.replace("-", " ")}"',
                                        ],
                                    )
                                with vuetify.Template(v_if="!(tile && tile.variable_name)"):
                                    with html.Div(classes="seurat-empty-cell"):
                                        html.Div("+", classes="seurat-empty-plus")
                                        html.Div("Drop variable here", classes="seurat-empty-hover-label")
                    _build_inactive_workspace_grids(ctrl)
                    _build_workspace_splitters()

            html.Div(style="height: 8px; flex:0 0 auto;")

            with vuetify.VCard(variant="outlined", style="flex:0 0 auto;"):
                with vuetify.VCardText(class_="py-2"):
                    with vuetify.Template(v_if="detailsSelectedVar"):
                        with html.Div(
                            style=(
                                "display:flex; flex-direction:column; gap:6px; "
                                "width:100%;"
                            )
                        ):
                            with html.Div(
                                style=(
                                    "display:flex; align-items:center; gap:12px; "
                                    "width:100%; flex-wrap:wrap;"
                                ),
                            ):
                                html.Div("{{ 'Details: ' + detailsSelectedVar }}", class_="text-body-2")
                                vuetify.VBtn(
                                    "{{ 'SOURCES(' + detailsNumSources + ')' }}",
                                    variant="tonal",
                                    size="small",
                                    click=ctrl.toggle_sources,
                                )
                                with html.Div(
                                    class_="text-caption",
                                    style=(
                                        "display:flex; align-items:center; gap:12px; "
                                        "white-space:nowrap;"
                                    ),
                                ):
                                    html.Span("Min/Max")
                                    with html.Span():
                                        html.Strong("Global ")
                                        html.Span("{{ detailsGlobalMin + ' / ' + detailsGlobalMax }}")
                                    with html.Span():
                                        html.Strong("Median ")
                                        html.Span("{{ detailsMedianMin + ' / ' + detailsMedianMax }}")
                                    with html.Span():
                                        html.Strong("Mean ")
                                        html.Span("{{ detailsMeanMin + ' / ' + detailsMeanMax }}")
                                vuetify.VSpacer()
                                html.Div("{{ 'QueryView: ' + queryViewLabel }}", class_="text-caption")
                            with vuetify.Template(v_if="detailsProvenanceChain"):
                                with html.Div(
                                    classes="seurat-provenance-strip text-caption",
                                ):
                                    vuetify.VBtn(
                                        "Provenance",
                                        variant="tonal",
                                        size="small",
                                        click=ctrl.open_provenance_dialog,
                                    )
                                    html.Span(
                                        "{{ detailsProvenanceCompact || detailsProvenanceChain }}",
                                        classes="seurat-provenance-compact",
                                    )
                    with vuetify.Template(v_if="!detailsSelectedVar"):
                        html.Div("Select a variable", class_="text-caption")
            self.provenance_dialog.build()
            self.source_dialog.build()
            self.scalar_plot_dialog.build()
            self.plot_settings_panel.build()
            self.plugin_options_panel.build()
            self.scalar_field_settings_panel.build()
            self.scalar_field_assistant_panel.build()
