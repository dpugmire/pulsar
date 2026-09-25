"""Grid and variable context-menu component."""

from trame.app import TrameComponent
from trame.widgets import html
from trame.widgets import vuetify3 as vuetify


class ContextMenu(TrameComponent):
    def build(self):
        ctrl = self.ctrl
        with html.Div(
            id="pulsar-context-menu",
            v_show=("contextMenuVisible",),
            raw_attrs=[
                ':style="{ position: \'fixed\', zIndex: 9999, left: (contextMenuX || 0) + \'px\', top: (contextMenuY || 0) + \'px\' }"'
            ],
        ):
            html.Div("{{ contextMenuItemLabel || contextMenuItem || 'Menu' }}", classes="menu-label")

            with html.Div(v_if="contextMenuKind === 'item'"):
                html.Div("Add To Grid", classes="menu-item", click=ctrl.context_menu_item_add)
                html.Div("Select Variable", classes="menu-item", click=ctrl.context_menu_item_select)

            with html.Div(v_if="contextMenuKind === 'tab'"):
                with html.Div(
                    classes="menu-item menu-item-with-icon",
                    click=(
                        ctrl.context_menu_tab_rename,
                        "[window.prompt('Tab name', contextMenuItemLabel || 'View')]",
                    ),
                ):
                    vuetify.VIcon(
                        "mdi-pencil-outline",
                        size="small",
                        classes="menu-item-icon",
                    )
                    html.Span("Rename…")
                with html.Div(
                    classes="menu-item menu-item-with-icon danger",
                    click=(
                        ctrl.context_menu_tab_close,
                        "[window.confirm('Close this tab and remove its visualizations?')]",
                    ),
                    raw_attrs=[
                        ":class=\"{ 'is-disabled': !contextMenuTabCanClose }\"",
                        ":aria-disabled=\"!contextMenuTabCanClose ? 'true' : 'false'\"",
                    ],
                ):
                    vuetify.VIcon(
                        "mdi-close",
                        size="small",
                        classes="menu-item-icon",
                    )
                    html.Span("Close")

            with html.Div(v_if="contextMenuKind === 'cell'"):
                html.Div("Select Cell", classes="menu-item", click=ctrl.context_menu_cell_select)
                with vuetify.Template(v_if="contextMenuCellCanResetView"):
                    html.Div("Reset View", classes="menu-item", click=ctrl.context_menu_cell_reset_view)
                html.Div("Clear Cell", classes="menu-item danger", click=ctrl.context_menu_cell_clear)
                with vuetify.Template(v_if="gridLayoutMode === 'spanning'"):
                    with html.Div(classes="menu-submenu"):
                        with html.Div(classes="menu-item menu-submenu-trigger"):
                            html.Span("Span")
                            html.Span("›", classes="menu-submenu-arrow")
                        with html.Div(classes="menu-submenu-panel"):
                            html.Div("Span right", classes="menu-item", click=ctrl.context_menu_cell_span_right)
                            html.Div("Span down", classes="menu-item", click=ctrl.context_menu_cell_span_down)
                            html.Div("Shrink width", classes="menu-item", click=ctrl.context_menu_cell_shrink_width)
                            html.Div("Shrink height", classes="menu-item", click=ctrl.context_menu_cell_shrink_height)
                            html.Div("Reset span", classes="menu-item", click=ctrl.context_menu_cell_reset_span)
                with vuetify.Template(v_if="contextMenuCellHasVariable"):
                    html.Div("Sources...", classes="menu-item", click=ctrl.context_menu_cell_sources)
                with vuetify.Template(v_if="contextMenuCellCanPlotSettings"):
                    html.Div("Plot settings...", classes="menu-item", click=ctrl.context_menu_cell_plot_settings)
                with vuetify.Template(v_if="contextMenuCellCanScalarFieldSettings"):
                    html.Div("Plot options...", classes="menu-item", click=ctrl.context_menu_cell_scalar_field_settings)
                with vuetify.Template(v_if="(contextMenuCellSourcePlugins || []).length"):
                    html.Div("Run Plugin", classes="menu-section")
                    with vuetify.Template(v_for="plugin in contextMenuCellSourcePlugins", key="plugin.plugin_id"):
                        html.Div(
                            "{{ plugin.label }}",
                            classes="menu-item",
                            click=(ctrl.context_menu_cell_run_source_plugin, "[plugin.plugin_id]"),
                        )
                with vuetify.Template(v_if="(contextMenuCellVisualizationOptions || []).length"):
                    html.Div("Visualization Type", classes="menu-section")
                    with vuetify.Template(v_for="vis in contextMenuCellVisualizationOptions", key="vis"):
                        html.Div(
                            "{{ ((vis === contextMenuCellSelectedVisualization) ? '✓ ' : '') + vis }}",
                            classes="menu-item",
                            click=(ctrl.context_menu_cell_pick_visualization, "[vis]"),
                        )
