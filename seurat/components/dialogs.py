"""Dialog and floating-options components."""

from trame.app import TrameComponent
from trame.widgets import html
from trame.widgets import vuetify3 as vuetify

from seurat.constants import SCALAR_FIELD_COLORMAP_OPTIONS


def _build_provenance_node(node_expr: str, detail_toggle=None):
    with html.Div(
        classes="seurat-provenance-node",
        raw_attrs=[
            f":class=\"[{node_expr}.kind ? 'is-' + {node_expr}.kind : '', {node_expr}.shape ? 'shape-' + {node_expr}.shape : '', {node_expr}.expanded ? 'is-expanded' : '']\"",
            f":title=\"{node_expr}.label || ''\"",
        ],
    ):
        if detail_toggle is not None:
            with vuetify.Template(
                v_if=f"{node_expr}.details && {node_expr}.details.length"
            ):
                with html.Button(
                    classes="seurat-provenance-detail-btn",
                    click=(detail_toggle, f"[{node_expr}.id]"),
                    raw_attrs=[
                        'type="button"',
                        f":aria-expanded=\"{node_expr}.expanded ? 'true' : 'false'\"",
                        f":aria-label=\"({node_expr}.expanded ? 'Hide' : 'Show') + ' details for ' + ({node_expr}.label || 'provenance item')\"",
                        f":title=\"({node_expr}.expanded ? 'Hide' : 'Show') + ' details'\"",
                    ],
                ):
                    vuetify.VIcon("mdi-information-outline", size="x-small")
        html.Span(
            f"{{{{ {node_expr}.display_label || {node_expr}.label }}}}",
            classes="seurat-provenance-node-label",
        )
        with vuetify.Template(v_if=f"{node_expr}.secondary_label"):
            html.Span(
                f"{{{{ {node_expr}.secondary_label }}}}",
                classes="seurat-provenance-node-secondary",
            )
        if detail_toggle is not None:
            with vuetify.Template(
                v_if=(
                    f"{node_expr}.expanded && {node_expr}.details "
                    f"&& {node_expr}.details.length"
                )
            ):
                with html.Div(classes="seurat-provenance-node-details"):
                    with vuetify.Template(
                        v_for=f"detail in {node_expr}.details",
                        key="detail.label + '-' + (detail.kind || 'row')",
                    ):
                        with vuetify.Template(v_if="detail.kind === 'input_table'"):
                            with html.Div(
                                classes="seurat-provenance-detail-table-block"
                            ):
                                html.Div(
                                    "{{ detail.label }}",
                                    classes=(
                                        "seurat-provenance-detail-label "
                                        "seurat-provenance-detail-table-title"
                                    ),
                                )
                                with html.Div(classes="seurat-provenance-detail-table-wrap"):
                                    with html.Table(
                                        classes="seurat-provenance-input-table"
                                    ):
                                        with html.Thead():
                                            with html.Tr():
                                                html.Th("Variable")
                                                html.Th("Role")
                                        with html.Tbody():
                                            with vuetify.Template(
                                                v_for="input in detail.rows",
                                                key="input.variable + '-' + input.role",
                                            ):
                                                with html.Tr():
                                                    html.Td("{{ input.variable }}")
                                                    html.Td("{{ input.role }}")
                        with vuetify.Template(v_if="detail.kind !== 'input_table'"):
                            with html.Div(classes="seurat-provenance-detail-row"):
                                html.Span(
                                    "{{ detail.label }}",
                                    classes="seurat-provenance-detail-label",
                                )
                                html.Span(
                                    "{{ detail.value }}",
                                    classes="seurat-provenance-detail-value",
                                )


def _build_provenance_entity_source(
    entity_expr: str,
    source_expr: str,
    detail_toggle=None,
):
    with html.Div(classes="seurat-provenance-entity-source"):
        _build_provenance_node(entity_expr, detail_toggle)
        _build_provenance_node(source_expr, detail_toggle)


def _build_provenance_down_arrow(relation_expr: str = ""):
    with html.Div(
        classes="seurat-provenance-down-arrow",
        raw_attrs=['aria-hidden="true"'],
    ):
        if relation_expr:
            html.Span(
                f"{{{{ {relation_expr} }}}}",
                v_if=relation_expr,
                classes="seurat-provenance-down-arrow-label",
            )


def _branch_grid_style() -> str:
    return (
        ":style=\"{ gridTemplateColumns: 'repeat(' + segment.branches.length "
        "+ ', minmax(138px, 1fr))' }\""
    )


def build_provenance_graph(detail_toggle=None):
    with html.Div(
        classes="seurat-provenance-graph is-expandable",
        raw_attrs=['role="list"'],
    ):
        with vuetify.Template(
            v_for="(segment, segmentIndex) in detailsProvenanceGraph",
            key="segment.id || segmentIndex",
        ):
            with vuetify.Template(v_if="segment.type === 'node'"):
                with html.Div(
                    classes="seurat-provenance-dag-row",
                    raw_attrs=['role="listitem"'],
                ):
                    _build_provenance_node("segment.node", detail_toggle)
            with vuetify.Template(v_if="segment.type === 'entity_source'"):
                with html.Div(raw_attrs=['role="listitem"']):
                    _build_provenance_entity_source(
                        "segment.entity",
                        "segment.source",
                        detail_toggle,
                    )
            with vuetify.Template(v_if="segment.type === 'activity_context'"):
                with html.Div(
                    classes="seurat-provenance-activity-context-row",
                    raw_attrs=['role="listitem"'],
                ):
                    with html.Div(
                        classes="seurat-provenance-activity-context-primary"
                    ):
                        _build_provenance_node("segment.node", detail_toggle)
                    with html.Div(
                        classes="seurat-provenance-activity-context-items"
                    ):
                        with vuetify.Template(
                            v_for="context in segment.contexts",
                            key="context.id",
                        ):
                            with html.Div(
                                classes="seurat-provenance-activity-context-item"
                            ):
                                html.Span(
                                    "{{ context.relation }}",
                                    classes="seurat-provenance-context-relation",
                                )
                                _build_provenance_node(
                                    "context.node",
                                    detail_toggle,
                                )
            with vuetify.Template(v_if="segment.type === 'plan_group'"):
                with html.Div(
                    classes="seurat-provenance-plan-group",
                    raw_attrs=[
                        'role="group"',
                        ':aria-label="\'Plan: \' + (segment.plan.label || \'workflow\')"',
                    ],
                ):
                    with html.Div(classes="seurat-provenance-plan-group-header"):
                        html.Span(
                            "WORKFLOW",
                            classes="seurat-provenance-plan-group-kicker",
                        )
                        _build_provenance_node("segment.plan", detail_toggle)
                    with html.Div(classes="seurat-provenance-plan-actions"):
                        with html.Div(
                            classes=(
                                "seurat-provenance-plan-action-row "
                                "is-selected"
                            )
                        ):
                            _build_provenance_node(
                                "segment.selected_action.node",
                                detail_toggle,
                            )
                            with vuetify.Template(
                                v_if="segment.selected_action.agent && segment.selected_action.agent.id"
                            ):
                                _build_provenance_node(
                                    "segment.selected_action.agent",
                                    detail_toggle,
                                )
            with vuetify.Template(v_if="segment.type === 'arrow'"):
                _build_provenance_down_arrow("segment.relation")
            with vuetify.Template(v_if="segment.type === 'branches'"):
                with html.Div(
                    classes="seurat-provenance-branch-section",
                    raw_attrs=['role="listitem"'],
                ):
                    with vuetify.Template(
                        v_if="segment.relation && segment.branches.length > 1"
                    ):
                        html.Span(
                            "{{ segment.relation }}",
                            classes="seurat-provenance-branch-relation",
                        )
                    with vuetify.Template(v_if="segment.branches.length > 1"):
                        with html.Div(
                            classes="seurat-provenance-fan",
                            raw_attrs=[_branch_grid_style(), 'aria-hidden="true"'],
                        ):
                            html.Span(classes="seurat-provenance-fan-spine")
                            html.Span(classes="seurat-provenance-fan-bar")
                            with vuetify.Template(
                                v_for="(_branch, branchIndex) in segment.branches",
                                key="'fan-' + branchIndex",
                            ):
                                html.Span(classes="seurat-provenance-fan-drop")
                    with vuetify.Template(v_if="segment.branches.length <= 1"):
                        _build_provenance_down_arrow("segment.relation")
                    with html.Div(
                        classes="seurat-provenance-branch-grid seurat-provenance-input-row",
                        raw_attrs=[_branch_grid_style()],
                    ):
                        with vuetify.Template(
                            v_for="branch in segment.branches",
                            key="branch.id",
                        ):
                            with html.Div(classes="seurat-provenance-branch-cell"):
                                with vuetify.Template(v_if="segment.shared_source"):
                                    _build_provenance_node(
                                        "branch.input",
                                        detail_toggle,
                                    )
                                with vuetify.Template(v_if="!segment.shared_source"):
                                    _build_provenance_entity_source(
                                        "branch.input",
                                        "branch.source",
                                        detail_toggle,
                                    )
                    with vuetify.Template(v_if="segment.shared_source"):
                        with vuetify.Template(v_if="segment.branches.length > 1"):
                            html.Span(
                                "stored in",
                                classes="seurat-provenance-branch-relation",
                            )
                            with html.Div(
                                classes="seurat-provenance-source-fan",
                                raw_attrs=[_branch_grid_style(), 'aria-hidden="true"'],
                            ):
                                html.Span(classes="seurat-provenance-source-fan-bar")
                                with vuetify.Template(
                                    v_for="(_branch, branchIndex) in segment.branches",
                                    key="'source-fan-' + branchIndex",
                                ):
                                    html.Span(
                                        classes="seurat-provenance-source-fan-drop"
                                    )
                                html.Span(
                                    classes="seurat-provenance-source-fan-spine"
                                )
                        with vuetify.Template(v_if="segment.branches.length <= 1"):
                            html.Div(
                                classes="seurat-provenance-down-arrow",
                                raw_attrs=['aria-hidden="true"'],
                            )
                        with html.Div(classes="seurat-provenance-shared-source-row"):
                            _build_provenance_node(
                                "segment.shared_source",
                                detail_toggle,
                            )


class HelpDialog(TrameComponent):
    def build(self):
        ctrl = self.ctrl
        with vuetify.VDialog(v_model=("showHelpModal",), max_width="520"):
            with vuetify.VCard():
                with vuetify.VCardTitle():
                    with html.Div(style="display:flex; align-items:center; gap:8px; width:100%;"):
                        html.Div("{{ helpModalTitle || 'Help' }}")
                        vuetify.VSpacer()
                        vuetify.VBtn("Close", variant="text", size="small", click=ctrl.close_help_modal)
                with vuetify.VCardText():
                    vuetify.VTextarea(
                        v_model=("helpModalText",),
                        readonly=True,
                        auto_grow=True,
                        rows=3,
                        variant="outlined",
                        hide_details=True,
                    )


class ProvenanceDialog(TrameComponent):
    def build(self):
        ctrl = self.ctrl
        with html.Div(
            id="seurat-provenance-panel",
            v_show=("showProvenanceModal",),
            classes="seurat-floating-options-panel seurat-provenance-panel",
            raw_attrs=[
                'role="dialog"',
                'aria-modal="false"',
                'aria-labelledby="seurat-provenance-title"',
            ],
        ):
            with vuetify.VCard(
                classes="seurat-floating-options-card seurat-provenance-dialog",
                elevation=6,
            ):
                with vuetify.VCardTitle(
                    classes=(
                        "seurat-floating-options-titlebar "
                        "seurat-provenance-titlebar"
                    )
                ):
                    with html.Div(
                        style="display:flex; align-items:center; gap:8px; width:100%;"
                    ):
                        with html.Div(
                            id="seurat-provenance-title",
                            classes="seurat-floating-panel-drag-handle",
                        ):
                            vuetify.VIcon("mdi-family-tree", size="small")
                            html.Span("Provenance Viewer")
                        vuetify.VSpacer()
                        vuetify.VBtn(
                            "Close",
                            classes="seurat-provenance-close-btn",
                            variant="text",
                            size="small",
                            click=ctrl.close_provenance_dialog,
                        )
                with vuetify.VCardText(
                    classes=(
                        "seurat-floating-options-content "
                        "seurat-provenance-dialog-content"
                    )
                ):
                    with vuetify.Template(
                        v_if="detailsProvenanceGraph && detailsProvenanceGraph.length"
                    ):
                        build_provenance_graph(
                            detail_toggle=ctrl.toggle_provenance_node_details,
                        )
                        with html.Div(classes="seurat-provenance-legend"):
                            with html.Div(classes="seurat-provenance-legend-item"):
                                html.Span(classes="seurat-provenance-legend-swatch is-visualization")
                                html.Span("Visualization")
                            with html.Div(classes="seurat-provenance-legend-item"):
                                html.Span(classes="seurat-provenance-legend-swatch is-variable")
                                html.Span("Variable")
                            with html.Div(classes="seurat-provenance-legend-item"):
                                html.Span(classes="seurat-provenance-legend-swatch is-activity")
                                html.Span("Action")
                            with html.Div(classes="seurat-provenance-legend-item"):
                                html.Span(classes="seurat-provenance-legend-swatch is-plan")
                                html.Span("Workflow Plan")
                            with html.Div(classes="seurat-provenance-legend-item"):
                                html.Span(classes="seurat-provenance-legend-swatch is-agent")
                                html.Span("Agent")
                            with html.Div(classes="seurat-provenance-legend-item"):
                                html.Span(classes="seurat-provenance-legend-swatch is-source")
                                html.Span("Data source")
                    with vuetify.Template(
                        v_if="!(detailsProvenanceGraph && detailsProvenanceGraph.length)"
                    ):
                        html.Div("No provenance available.", class_="text-caption")
            html.Div(
                classes="seurat-provenance-resize-handle",
                raw_attrs=[
                    'role="separator"',
                    'aria-label="Resize provenance viewer"',
                ],
            )


class SourceDialog(TrameComponent):
    def build(self):
        ctrl = self.ctrl
        with vuetify.VDialog(v_model=("showSourcesModal",), max_width="1200"):
            with vuetify.VCard():
                with vuetify.VCardTitle():
                    with html.Div(style="display:flex; align-items:center; gap:8px; width:100%;"):
                        html.Div("{{ sourceDialogTitle || 'Sources' }}")
                        vuetify.VSpacer()
                        vuetify.VBtn("Close", variant="text", size="small", click=ctrl.cancel_source_dialog)

                with vuetify.VCardText():
                    with vuetify.Template(v_if="detailsSelectedVar"):
                        with html.Div(
                            style=(
                                "display:flex;"
                                "align-items:center;"
                                "gap:8px;"
                                "margin-bottom:8px;"
                            )
                        ):
                            html.Span(
                                "Filter Sources:",
                                class_="text-caption",
                                style="white-space:nowrap;",
                            )
                            vuetify.VBtn(
                                "?",
                                variant="tonal",
                                size="small",
                                min_width=32,
                                title="Source filter help",
                                click=ctrl.show_source_filter_help,
                            )
                            vuetify.VTextField(
                                v_model=("sourceFilterDraftText",),
                                placeholder=(
                                    "Natural language + Ask, or Advanced Query + Filter"
                                ),
                                density="compact",
                                hide_details=True,
                                variant="outlined",
                                style="max-width:620px; min-width:360px;",
                            )
                            with vuetify.Template(v_if="queryAssistantAvailable"):
                                vuetify.VBtn(
                                    "Ask",
                                    color="primary",
                                    variant="tonal",
                                    size="small",
                                    title="Interpret as natural language",
                                    click=ctrl.open_source_query_assistant,
                                )
                            vuetify.VBtn(
                                "Filter",
                                variant="tonal",
                                size="small",
                                click=ctrl.apply_source_dialog_filter,
                            )
                            with vuetify.Template(v_if="sourceDialogMode === 'add'"):
                                vuetify.VBtn(
                                    "Select All",
                                    variant="tonal",
                                    size="small",
                                    click=ctrl.select_all_sources,
                                )
                                vuetify.VBtn(
                                    "Clear All",
                                    variant="text",
                                    size="small",
                                    click=ctrl.clear_all_sources,
                                )
                        with vuetify.Template(v_if="sourceFilterError"):
                            html.Div("{{ sourceFilterError }}", class_="text-caption mb-2", style="color:#b00020;")
                        with vuetify.Template(v_if="sourceDialogStatus && sourceDialogStatusIsError"):
                            html.Div("{{ sourceDialogStatus }}", class_="text-caption mb-2", style="color:#b00020;")
                        with vuetify.Template(v_if="sourceDialogStatus && !sourceDialogStatusIsError"):
                            html.Div("{{ sourceDialogStatus }}", class_="text-caption mb-2", style="color:#2e7d32;")
                        html.Div(
                            "{{ ((sourceDialogMode === 'add') ? 'Selected sources: ' : 'Selected source: ') + selectedSourceLabel }}",
                            class_="text-caption mb-2",
                        )
                        with html.Div(
                            style=(
                                "max-height:60vh;"
                                "overflow-y:auto;"
                                "overflow-x:scroll;"
                                "white-space:nowrap;"
                                "scrollbar-gutter:stable;"
                            )
                        ):
                            with vuetify.VTable(density="compact"):
                                with html.Thead():
                                    with html.Tr():
                                        with html.Th(
                                            style="cursor:pointer; user-select:none; white-space:nowrap; width:72px;",
                                            click=(ctrl.sort_sources, "['show']"),
                                        ):
                                            html.Span("Selected")
                                            with vuetify.Template(v_if="sourceSortField === 'show'"):
                                                vuetify.VIcon(
                                                    ("sourceSortAsc ? 'mdi-arrow-up' : 'mdi-arrow-down'",),
                                                    size="x-small",
                                                    class_="ml-1",
                                                )
                                            with vuetify.Template(v_if="sourceSortField !== 'show'"):
                                                vuetify.VIcon("mdi-sort", size="x-small", class_="ml-1")
                                        with html.Th(
                                            style="cursor:pointer; user-select:none; white-space:nowrap;",
                                            click=(ctrl.sort_sources, "['source_dataset']"),
                                        ):
                                            html.Span("source dataset")
                                            with vuetify.Template(v_if="sourceSortField === 'source_dataset'"):
                                                vuetify.VIcon(
                                                    ("sourceSortAsc ? 'mdi-arrow-up' : 'mdi-arrow-down'",),
                                                    size="x-small",
                                                    class_="ml-1",
                                                )
                                            with vuetify.Template(v_if="sourceSortField !== 'source_dataset'"):
                                                vuetify.VIcon("mdi-sort", size="x-small", class_="ml-1")

                                        with html.Th(
                                            style="cursor:pointer; user-select:none; white-space:nowrap;",
                                            click=(ctrl.sort_sources, "['min']"),
                                        ):
                                            html.Span("min")
                                            with vuetify.Template(v_if="sourceSortField === 'min'"):
                                                vuetify.VIcon(
                                                    ("sourceSortAsc ? 'mdi-arrow-up' : 'mdi-arrow-down'",),
                                                    size="x-small",
                                                    class_="ml-1",
                                                )
                                            with vuetify.Template(v_if="sourceSortField !== 'min'"):
                                                vuetify.VIcon("mdi-sort", size="x-small", class_="ml-1")

                                        with html.Th(
                                            style="cursor:pointer; user-select:none; white-space:nowrap;",
                                            click=(ctrl.sort_sources, "['max']"),
                                        ):
                                            html.Span("max")
                                            with vuetify.Template(v_if="sourceSortField === 'max'"):
                                                vuetify.VIcon(
                                                    ("sourceSortAsc ? 'mdi-arrow-up' : 'mdi-arrow-down'",),
                                                    size="x-small",
                                                    class_="ml-1",
                                                )
                                            with vuetify.Template(v_if="sourceSortField !== 'max'"):
                                                vuetify.VIcon("mdi-sort", size="x-small", class_="ml-1")
                                with html.Tbody():
                                    with vuetify.Template(v_for="(r, i) in sourceRows", key="i"):
                                        with html.Tr(
                                            style=(
                                                "((selectedSourceKeys || []).includes(r._key)) ? "
                                                "'background-color:#f5f5f5; cursor:pointer;' : "
                                                "'cursor:pointer;'",
                                            ),
                                            click=(ctrl.source_dialog_select, "[r._key]"),
                                        ):
                                            with html.Td(style="text-align:center; white-space:nowrap;"):
                                                with vuetify.Template(v_if="sourceDialogMode === 'add'"):
                                                    html.Input(
                                                        type="checkbox",
                                                        checked=("((selectedSourceKeys || []).includes(r._key))",),
                                                    )
                                                with vuetify.Template(v_if="sourceDialogMode !== 'add'"):
                                                    html.Input(
                                                        type="radio",
                                                        name="selected-source",
                                                        checked=("((selectedSourceKeys || []).includes(r._key))",),
                                                    )
                                            html.Td(
                                                "{{ r.sourceName || r.source_label || r.source_dataset || [r.producer, r.casename, r.file].filter(Boolean).join('/') }}",
                                                style="white-space:nowrap;",
                                            )
                                            html.Td("{{ r.min }}", style="white-space:nowrap;")
                                            html.Td("{{ r.max }}", style="white-space:nowrap;")
                        with vuetify.Template(v_if="!detailsSelectedVar"):
                            html.Div("Select a variable first.", class_="text-caption")
                with vuetify.VCardActions():
                    vuetify.VSpacer()
                    vuetify.VBtn("Cancel", variant="text", click=ctrl.cancel_source_dialog)
                    vuetify.VBtn("Apply", variant="tonal", click=ctrl.apply_source_dialog)


class ScalarPlotDialog(TrameComponent):
    def build(self):
        ctrl = self.ctrl
        with vuetify.VDialog(v_model=("showScalarPlotDialog",), max_width="560"):
            with vuetify.VCard():
                vuetify.VCardTitle("Generate Scalar Plot")
                with vuetify.VCardText():
                    html.Div("{{ scalarPlotDialogMessage }}", class_="text-body-2")
                    vuetify.VCheckbox(
                        v_model=("scalarPlotAlwaysForSession",),
                        label="Always generate scalar plots for this session",
                        density="compact",
                        hide_details=True,
                        class_="mt-3",
                    )
                with vuetify.VCardActions():
                    vuetify.VSpacer()
                    vuetify.VBtn(
                        "Cancel",
                        variant="text",
                        click=ctrl.cancel_scalar_plot_generation,
                    )
                    vuetify.VBtn(
                        "Generate",
                        variant="tonal",
                        click=ctrl.confirm_scalar_plot_generation,
                    )


class PlotSettingsPanel(TrameComponent):
    def build(self):
        ctrl = self.ctrl
        with html.Div(
            id="seurat-plot-settings-panel",
            v_show=("showPlotSettingsModal",),
            classes="seurat-floating-options-panel seurat-plot-settings-panel",
        ):
            with vuetify.VCard(classes="seurat-floating-options-card", elevation=6):
                with vuetify.VCardTitle(classes="seurat-floating-options-titlebar"):
                    with html.Div(style="display:flex; align-items:center; gap:8px; width:100%;"):
                        html.Div(
                            "{{ 'Plot Settings: ' + (plotSettingsTitle || '') }}",
                            classes="seurat-floating-panel-drag-handle",
                        )
                        vuetify.VSpacer()
                        vuetify.VBtn("Close", variant="text", size="small", click=ctrl.cancel_plot_settings)

                with vuetify.VCardText(classes="seurat-floating-options-content"):
                    with vuetify.Template(v_if="plotSettingsStatus"):
                        html.Div("{{ plotSettingsStatus }}", class_="text-caption mb-2", style="color:#b00020;")

                    html.Div("Grid", classes="seurat-plot-settings-section-title")
                    with html.Div(classes="seurat-plot-settings-section"):
                        with html.Div(classes="seurat-plot-settings-grid-controls"):
                            with html.Div(classes="seurat-plot-settings-background-control"):
                                html.Span("Background", class_="text-caption")
                                with html.Div(classes="seurat-plot-settings-color-menu"):
                                    html.Button(
                                        "",
                                        classes="seurat-plot-settings-current-color",
                                        raw_attrs=[
                                            'type="button"',
                                            ':title="\'Background: \' + (plotSettingsBackgroundColor || \'\')"',
                                            ':style="{ backgroundColor: plotSettingsBackgroundColor || \'#ffffff\' }"',
                                        ],
                                    )
                                    with vuetify.VMenu(
                                        activator="parent",
                                        location="bottom end",
                                        close_on_content_click=False,
                                    ):
                                        with vuetify.VCard(classes="seurat-plot-settings-color-popup", elevation=4):
                                            with vuetify.VCardText(class_="pa-2"):
                                                html.Div("Standard Colors", classes="text-caption seurat-plot-settings-popup-title")
                                                with html.Div(classes="seurat-plot-settings-standard-colors"):
                                                    with vuetify.Template(
                                                        v_for="color in plotSettingsStandardColors",
                                                        key="'background:' + color",
                                                    ):
                                                        html.Button(
                                                            "",
                                                            classes="seurat-plot-settings-color-swatch",
                                                            raw_attrs=[
                                                                'type="button"',
                                                                ':title="color"',
                                                                ':style="{ backgroundColor: color, boxShadow: ((plotSettingsBackgroundColor || \'\').toLowerCase() === color.toLowerCase()) ? \'0 0 0 2px #111\' : \'none\' }"',
                                                            ],
                                                            click=(ctrl.update_plot_background_color, "[color]"),
                                                        )
                                                html.Div("More colors...", classes="text-caption seurat-plot-settings-more-colors")
                                                vuetify.VColorPicker(
                                                    hide_header=True,
                                                    hide_inputs=False,
                                                    show_swatches=False,
                                                    width=220,
                                                    raw_attrs=[
                                                        ':model-value="plotSettingsBackgroundColor"',
                                                        ':modes="[\'hex\', \'rgb\', \'hsl\']"',
                                                    ],
                                                    update_modelValue=(ctrl.update_plot_background_color, "[$event]"),
                                                )
                            with html.Div(
                                classes="seurat-plot-settings-background-control",
                                raw_attrs=[':style="{ opacity: plotSettingsShowGrid ? 1 : 0.45 }"'],
                            ):
                                vuetify.VCheckbox(
                                    v_model=("plotSettingsShowGrid",),
                                    density="compact",
                                    hide_details=True,
                                    classes="seurat-plot-settings-toggle",
                                )
                                html.Span("Grid lines", class_="text-caption")
                                with html.Div(classes="seurat-plot-settings-color-menu"):
                                    html.Button(
                                        "",
                                        classes="seurat-plot-settings-current-color",
                                        raw_attrs=[
                                            'type="button"',
                                            ':disabled="!plotSettingsShowGrid"',
                                            ':title="\'Grid lines: \' + (plotSettingsGridColor || \'\')"',
                                            ':style="{ backgroundColor: plotSettingsGridColor || \'#e8e8e8\', cursor: plotSettingsShowGrid ? \'pointer\' : \'not-allowed\' }"',
                                        ],
                                    )
                                    with vuetify.VMenu(
                                        activator="parent",
                                        location="bottom end",
                                        close_on_content_click=False,
                                        raw_attrs=[':disabled="!plotSettingsShowGrid"'],
                                    ):
                                        with vuetify.VCard(classes="seurat-plot-settings-color-popup", elevation=4):
                                            with vuetify.VCardText(class_="pa-2"):
                                                html.Div("Standard Colors", classes="text-caption seurat-plot-settings-popup-title")
                                                with html.Div(classes="seurat-plot-settings-standard-colors"):
                                                    with vuetify.Template(
                                                        v_for="color in plotSettingsStandardColors",
                                                        key="'grid:' + color",
                                                    ):
                                                        html.Button(
                                                            "",
                                                            classes="seurat-plot-settings-color-swatch",
                                                            raw_attrs=[
                                                                'type="button"',
                                                                ':disabled="!plotSettingsShowGrid"',
                                                                ':title="color"',
                                                                ':style="{ backgroundColor: color, boxShadow: ((plotSettingsGridColor || \'\').toLowerCase() === color.toLowerCase()) ? \'0 0 0 2px #111\' : \'none\' }"',
                                                            ],
                                                            click=(ctrl.update_plot_grid_color, "[color]"),
                                                        )
                                                html.Div("More colors...", classes="text-caption seurat-plot-settings-more-colors")
                                                vuetify.VColorPicker(
                                                    hide_header=True,
                                                    hide_inputs=False,
                                                    show_swatches=False,
                                                    width=220,
                                                    raw_attrs=[
                                                        ':model-value="plotSettingsGridColor"',
                                                        ':modes="[\'hex\', \'rgb\', \'hsl\']"',
                                                        ':disabled="!plotSettingsShowGrid"',
                                                    ],
                                                    update_modelValue=(ctrl.update_plot_grid_color, "[$event]"),
                                                )
                            with html.Div(
                                classes="seurat-plot-settings-background-control",
                                raw_attrs=[':style="{ opacity: plotSettingsShowCursor ? 1 : 0.45 }"'],
                            ):
                                vuetify.VCheckbox(
                                    v_model=("plotSettingsShowCursor",),
                                    density="compact",
                                    hide_details=True,
                                    classes="seurat-plot-settings-toggle",
                                )
                                html.Span("Cursor", class_="text-caption")
                                with html.Div(classes="seurat-plot-settings-color-menu"):
                                    html.Button(
                                        "",
                                        classes="seurat-plot-settings-current-color",
                                        raw_attrs=[
                                            'type="button"',
                                            ':disabled="!plotSettingsShowCursor"',
                                            ':title="\'Cursor: \' + (plotSettingsCursorColor || \'\')"',
                                            ':style="{ backgroundColor: plotSettingsCursorColor || \'#111111\', cursor: plotSettingsShowCursor ? \'pointer\' : \'not-allowed\' }"',
                                        ],
                                    )
                                    with vuetify.VMenu(
                                        activator="parent",
                                        location="bottom end",
                                        close_on_content_click=False,
                                        raw_attrs=[':disabled="!plotSettingsShowCursor"'],
                                    ):
                                        with vuetify.VCard(classes="seurat-plot-settings-color-popup", elevation=4):
                                            with vuetify.VCardText(class_="pa-2"):
                                                html.Div("Standard Colors", classes="text-caption seurat-plot-settings-popup-title")
                                                with html.Div(classes="seurat-plot-settings-standard-colors"):
                                                    with vuetify.Template(
                                                        v_for="color in plotSettingsStandardColors",
                                                        key="'cursor:' + color",
                                                    ):
                                                        html.Button(
                                                            "",
                                                            classes="seurat-plot-settings-color-swatch",
                                                            raw_attrs=[
                                                                'type="button"',
                                                                ':disabled="!plotSettingsShowCursor"',
                                                                ':title="color"',
                                                                ':style="{ backgroundColor: color, boxShadow: ((plotSettingsCursorColor || \'\').toLowerCase() === color.toLowerCase()) ? \'0 0 0 2px #111\' : \'none\' }"',
                                                            ],
                                                            click=(ctrl.update_plot_cursor_color, "[color]"),
                                                        )
                                                html.Div("More colors...", classes="text-caption seurat-plot-settings-more-colors")
                                                vuetify.VColorPicker(
                                                    hide_header=True,
                                                    hide_inputs=False,
                                                    show_swatches=False,
                                                    width=220,
                                                    raw_attrs=[
                                                        ':model-value="plotSettingsCursorColor"',
                                                        ':modes="[\'hex\', \'rgb\', \'hsl\']"',
                                                        ':disabled="!plotSettingsShowCursor"',
                                                    ],
                                                    update_modelValue=(ctrl.update_plot_cursor_color, "[$event]"),
                                                )

                    html.Div("Axes", classes="seurat-plot-settings-section-title mt-3")
                    with html.Div(classes="seurat-plot-settings-section"):
                        with html.Div(classes="seurat-plot-settings-axis-list"):
                            with html.Div(classes="seurat-plot-settings-axis-row"):
                                html.Span("X:", classes="seurat-plot-settings-axis-label")
                                vuetify.VCheckbox(
                                    v_model=("plotSettingsXAuto",),
                                    label="Auto range",
                                    density="compact",
                                    hide_details=True,
                                )
                                vuetify.VTextField(
                                    v_model=("plotSettingsXMin",),
                                    label="Min",
                                    density="compact",
                                    hide_details=True,
                                    raw_attrs=[':disabled="plotSettingsXAuto"'],
                                )
                                vuetify.VTextField(
                                    v_model=("plotSettingsXMax",),
                                    label="Max",
                                    density="compact",
                                    hide_details=True,
                                    raw_attrs=[':disabled="plotSettingsXAuto"'],
                                )
                                html.Span("Scale", class_="text-caption")
                                with html.Select(
                                    v_model=("plotSettingsXScale",),
                                    classes="seurat-scalar-plot-policy",
                                ):
                                    html.Option("Linear", value="linear")
                                    html.Option("Log", value="log")

                            with html.Div(classes="seurat-plot-settings-axis-row"):
                                html.Span("Y:", classes="seurat-plot-settings-axis-label")
                                vuetify.VCheckbox(
                                    v_model=("plotSettingsYAuto",),
                                    label="Auto range",
                                    density="compact",
                                    hide_details=True,
                                )
                                vuetify.VTextField(
                                    v_model=("plotSettingsYMin",),
                                    label="Min",
                                    density="compact",
                                    hide_details=True,
                                    raw_attrs=[':disabled="plotSettingsYAuto"'],
                                )
                                vuetify.VTextField(
                                    v_model=("plotSettingsYMax",),
                                    label="Max",
                                    density="compact",
                                    hide_details=True,
                                    raw_attrs=[':disabled="plotSettingsYAuto"'],
                                )
                                html.Span("Scale", class_="text-caption")
                                with html.Select(
                                    v_model=("plotSettingsYScale",),
                                    classes="seurat-scalar-plot-policy",
                                ):
                                    html.Option("Linear", value="linear")
                                    html.Option("Log", value="log")

                    html.Div("Curves", classes="seurat-plot-settings-section-title mt-3")
                    with html.Div(classes="seurat-plot-settings-section"):
                        with html.Div(classes="seurat-plot-settings-curves-layout"):
                            with html.Div(classes="seurat-plot-settings-curve-controls"):
                                vuetify.VTextField(
                                    v_model=("plotSettingsLineWidth",),
                                    label="Line width",
                                    density="compact",
                                    hide_details=True,
                                    raw_attrs=['type="number"', 'min="0.5"', 'max="8"', 'step="0.5"'],
                                    style="max-width:160px;",
                                )
                            with html.Div(classes="seurat-plot-settings-color-list"):
                                with html.Div(v_if="!(plotSettingsSeriesRows || []).length", class_="text-caption"):
                                    html.Span("No series")
                                with vuetify.Template(v_for="row in plotSettingsSeriesRows", key="row.key"):
                                    with html.Div(classes="seurat-plot-settings-series-row"):
                                        with html.Div(classes="seurat-plot-settings-color-menu"):
                                            html.Button(
                                                "",
                                                classes="seurat-plot-settings-current-color",
                                                raw_attrs=[
                                                    'type="button"',
                                                    ':title="\'Color: \' + (row.color || \'\')"',
                                                    ':style="{ backgroundColor: row.color || \'#1565c0\' }"',
                                                ],
                                            )
                                            with vuetify.VMenu(
                                                activator="parent",
                                                location="bottom end",
                                                close_on_content_click=False,
                                            ):
                                                with vuetify.VCard(classes="seurat-plot-settings-color-popup", elevation=4):
                                                    with vuetify.VCardText(class_="pa-2"):
                                                        html.Div("Standard Colors", classes="text-caption seurat-plot-settings-popup-title")
                                                        with html.Div(classes="seurat-plot-settings-standard-colors"):
                                                            with vuetify.Template(
                                                                v_for="color in plotSettingsStandardColors",
                                                                key="row.key + ':' + color",
                                                            ):
                                                                html.Button(
                                                                    "",
                                                                    classes="seurat-plot-settings-color-swatch",
                                                                    raw_attrs=[
                                                                        'type="button"',
                                                                        ':title="color"',
                                                                        ':style="{ backgroundColor: color, boxShadow: ((row.color || \'\').toLowerCase() === color.toLowerCase()) ? \'0 0 0 2px #111\' : \'none\' }"',
                                                                    ],
                                                                    click=(ctrl.update_plot_series_color, "[row.key, color]"),
                                                                )
                                                        html.Div("More colors...", classes="text-caption seurat-plot-settings-more-colors")
                                                        vuetify.VColorPicker(
                                                            hide_header=True,
                                                            hide_inputs=False,
                                                            show_swatches=False,
                                                            width=220,
                                                            raw_attrs=[
                                                                ':model-value="row.color"',
                                                                ':modes="[\'hex\', \'rgb\', \'hsl\']"',
                                                            ],
                                                            update_modelValue=(ctrl.update_plot_series_color, "[row.key, $event]"),
                                                        )
                                        html.Div(
                                            "{{ row.label }}",
                                            class_="text-caption seurat-plot-settings-series-label",
                                        )
                                        with html.Select(
                                            classes="seurat-plot-settings-line-style",
                                            raw_attrs=[':value="row.line_style || \'solid\'"'],
                                            change=(ctrl.update_plot_series_line_style, "[row.key, $event.target.value]"),
                                        ):
                                            html.Option("Solid", value="solid")
                                            html.Option("Dash", value="dash")
                                            html.Option("Dot", value="dot")
                                            html.Option("Dash-dot", value="dash-dot")

                with vuetify.VCardActions():
                    with vuetify.Template(v_if="plotSettingsCanPluginOptions"):
                        vuetify.VBtn("Plugin options...", variant="text", click=ctrl.open_plot_settings_plugin_options)
                    vuetify.VSpacer()
                    vuetify.VBtn("Reset", variant="text", click=ctrl.reset_plot_settings)
                    vuetify.VBtn("Cancel", variant="text", click=ctrl.cancel_plot_settings)
                    vuetify.VBtn("Apply", variant="tonal", click=ctrl.apply_plot_settings)


class PluginOptionsPanel(TrameComponent):
    def build(self):
        ctrl = self.ctrl
        with html.Div(
            id="seurat-plugin-options-panel",
            v_show=("showPluginOptionsModal",),
            classes="seurat-floating-options-panel",
        ):
            with vuetify.VCard(classes="seurat-floating-options-card", elevation=6):
                with vuetify.VCardTitle(classes="seurat-floating-options-titlebar"):
                    with html.Div(style="display:flex; align-items:center; gap:8px; width:100%;"):
                        html.Div(
                            "{{ 'Plugin Options: ' + (pluginOptionsTitle || '') }}",
                            classes="seurat-floating-panel-drag-handle",
                        )
                        vuetify.VSpacer()
                        vuetify.VBtn("Close", variant="text", size="small", click=ctrl.cancel_plugin_options)

                with vuetify.VCardText(classes="seurat-floating-options-content"):
                    with vuetify.Template(v_if="pluginOptionsStatus"):
                        html.Div("{{ pluginOptionsStatus }}", class_="text-caption mb-2", style="color:#b00020;")
                    with vuetify.Template(v_if="!(pluginOptionsRows || []).length"):
                        html.Div("No plugin-specific options.", class_="text-caption")
                    with html.Div(classes="seurat-plugin-options-list"):
                        with vuetify.Template(v_for="row in pluginOptionsRows", key="row.key"):
                            with html.Div(classes="seurat-plugin-option-row"):
                                html.Span("{{ row.label }}", classes="seurat-plugin-option-label")
                                with html.Div(classes="seurat-plugin-option-control"):
                                    with vuetify.Template(v_if="row.type === 'bool'"):
                                        html.Input(
                                            classes="seurat-plugin-option-checkbox",
                                            raw_attrs=[
                                                'type="checkbox"',
                                                ':checked="!!row.value"',
                                            ],
                                            change=(ctrl.update_plugin_option_value, "[row.key, $event.target.checked]"),
                                        )
                                    with vuetify.Template(v_if="row.type === 'select'"):
                                        with html.Select(
                                            classes="seurat-scalar-plot-policy seurat-plugin-option-select",
                                            raw_attrs=[':value="row.value"'],
                                            change=(ctrl.update_plugin_option_value, "[row.key, $event.target.value]"),
                                        ):
                                            with vuetify.Template(v_for="choice in row.choices", key="choice"):
                                                html.Option("{{ choice }}", raw_attrs=[':value="choice"'])
                                    with vuetify.Template(v_if="row.type !== 'bool' && row.type !== 'select'"):
                                        html.Input(
                                            classes="seurat-plugin-option-input",
                                            raw_attrs=[
                                                ':type="row.type === \'number\' ? \'number\' : \'text\'"',
                                                ':value="row.value"',
                                            ],
                                            change=(ctrl.update_plugin_option_value, "[row.key, $event.target.value]"),
                                        )

                with vuetify.VCardActions():
                    vuetify.VSpacer()
                    vuetify.VBtn("Reset", variant="text", click=ctrl.reset_plugin_options)
                    vuetify.VBtn("Cancel", variant="text", click=ctrl.cancel_plugin_options)
                    vuetify.VBtn("Apply", variant="tonal", click=ctrl.apply_plugin_options)


class ScalarFieldSettingsPanel(TrameComponent):
    def build(self):
        ctrl = self.ctrl
        with html.Div(
            id="seurat-scalar-field-settings-panel",
            v_show=("showScalarFieldSettingsModal",),
            classes="seurat-floating-options-panel",
        ):
            with vuetify.VCard(classes="seurat-floating-options-card", elevation=6):
                with vuetify.VCardTitle(classes="seurat-floating-options-titlebar"):
                    with html.Div(style="display:flex; align-items:center; gap:8px; width:100%;"):
                        html.Div(
                            "{{ 'Plot Options: ' + (scalarFieldSettingsTitle || '') }}",
                            classes="seurat-floating-panel-drag-handle",
                        )
                        vuetify.VSpacer()
                        vuetify.VBtn(
                            "Close",
                            variant="text",
                            size="small",
                            click=ctrl.cancel_scalar_field_settings,
                        )

                with vuetify.VCardText(classes="seurat-floating-options-content"):
                    with vuetify.Template(v_if="scalarFieldSettingsStatus"):
                        html.Div(
                            "{{ scalarFieldSettingsStatus }}",
                            class_="text-caption mb-2",
                            raw_attrs=[
                                ':style="{ color: scalarFieldSettingsStatusIsError ? \'#b00020\' : \'#1b5e20\' }"'
                            ],
                        )

                    html.Div("Display", classes="seurat-plot-settings-section-title")
                    with html.Div(classes="seurat-plot-settings-section"):
                        with html.Div(classes="seurat-scalar-field-compact-row"):
                            with html.Div(classes="seurat-scalar-field-auto-control"):
                                html.Span("Background")
                                html.Button(
                                    classes="seurat-scalar-field-background-toggle",
                                    click=ctrl.toggle_scalar_field_background,
                                    raw_attrs=[
                                        'type="button"',
                                        ':style="{ backgroundColor: scalarFieldSettingsBackground === \'white\' ? \'#ffffff\' : \'#000000\' }"',
                                        ':title="\'Background: \' + (scalarFieldSettingsBackground === \'white\' ? \'White\' : \'Black\') + \'. Click to toggle.\'"',
                                        ':aria-label="\'Background: \' + (scalarFieldSettingsBackground === \'white\' ? \'White\' : \'Black\') + \'. Click to toggle.\'"',
                                    ],
                                )
                            with html.Div(classes="seurat-scalar-field-auto-control"):
                                html.Input(
                                    v_model=("scalarFieldSettingsShowAxes",),
                                    classes="seurat-scalar-field-auto-checkbox",
                                    raw_attrs=['type="checkbox"'],
                                )
                                html.Span("Show axes")

                    with html.Div(
                        classes="seurat-scalar-field-section-title mt-3"
                    ):
                        html.Input(
                            v_model=("scalarFieldSettingsShowHeatmap",),
                            classes="seurat-scalar-field-auto-checkbox",
                            raw_attrs=['type="checkbox"'],
                        )
                        html.Span("Heatmap")
                    with html.Div(
                        classes="seurat-plot-settings-section seurat-scalar-field-layer-section",
                        raw_attrs=[
                            ':class="{ \'is-disabled\': !scalarFieldSettingsShowHeatmap }"'
                        ],
                    ):
                        with html.Div(classes="seurat-scalar-field-compact-row"):
                            html.Span("Colormap", class_="text-caption")
                            with html.Select(
                                v_model=("scalarFieldSettingsColormap",),
                                classes="seurat-scalar-plot-policy seurat-scalar-field-colormap",
                                raw_attrs=[
                                    ':disabled="!scalarFieldSettingsShowHeatmap"'
                                ],
                            ):
                                for label, value in SCALAR_FIELD_COLORMAP_OPTIONS:
                                    html.Option(label, value=value)
                            with html.Div(classes="seurat-scalar-field-auto-control"):
                                html.Input(
                                    v_model=("scalarFieldSettingsShowColorbar",),
                                    classes="seurat-scalar-field-auto-checkbox",
                                    raw_attrs=[
                                        'type="checkbox"',
                                        ':disabled="!scalarFieldSettingsShowHeatmap"',
                                    ],
                                )
                                html.Span("Show colorbar")
                        with html.Div(classes="seurat-scalar-field-compact-row"):
                            html.Span("Range", class_="text-caption")
                            with html.Div(classes="seurat-scalar-field-auto-control"):
                                html.Input(
                                    v_model=("scalarFieldSettingsRangeAuto",),
                                    classes="seurat-scalar-field-auto-checkbox",
                                    raw_attrs=[
                                        'type="checkbox"',
                                        ':disabled="!scalarFieldSettingsShowHeatmap"',
                                    ],
                                )
                                html.Span("Auto")
                            vuetify.VTextField(
                                v_model=("scalarFieldSettingsMin",),
                                label="Min",
                                density="compact",
                                hide_details=True,
                                classes="seurat-scalar-field-compact-input",
                                raw_attrs=[
                                    ':disabled="scalarFieldSettingsRangeAuto || !scalarFieldSettingsShowHeatmap"'
                                ],
                            )
                            vuetify.VTextField(
                                v_model=("scalarFieldSettingsMax",),
                                label="Max",
                                density="compact",
                                hide_details=True,
                                classes="seurat-scalar-field-compact-input",
                                raw_attrs=[
                                    ':disabled="scalarFieldSettingsRangeAuto || !scalarFieldSettingsShowHeatmap"'
                                ],
                            )

                    with html.Div(
                        classes="seurat-scalar-field-section-title mt-3"
                    ):
                        html.Input(
                            v_model=("scalarFieldSettingsShowContours",),
                            classes="seurat-scalar-field-auto-checkbox",
                            raw_attrs=['type="checkbox"'],
                        )
                        html.Span("Contour")
                    with html.Div(
                        classes="seurat-plot-settings-section seurat-scalar-field-layer-section seurat-scalar-field-contour-section",
                        raw_attrs=[
                            ':class="{ \'is-disabled\': !scalarFieldSettingsShowContours }"'
                        ],
                    ):
                        with html.Div(classes="seurat-scalar-field-compact-row"):
                            html.Span("Color", class_="text-caption")
                            with html.Div(classes="seurat-plot-settings-color-menu"):
                                html.Button(
                                    "",
                                    classes="seurat-plot-settings-current-color seurat-scalar-field-contour-color",
                                    raw_attrs=[
                                        'type="button"',
                                        ':disabled="!scalarFieldSettingsShowContours"',
                                        ':title="\'Contour color: \' + (scalarFieldSettingsContourColor || \'#ffffff\')"',
                                        ':style="{ backgroundColor: scalarFieldSettingsContourColor || \'#ffffff\', cursor: scalarFieldSettingsShowContours ? \'pointer\' : \'not-allowed\' }"',
                                    ],
                                )
                                with vuetify.VMenu(
                                    activator="parent",
                                    location="bottom end",
                                    close_on_content_click=False,
                                    raw_attrs=[
                                        ':disabled="!scalarFieldSettingsShowContours"'
                                    ],
                                ):
                                    with vuetify.VCard(
                                        classes="seurat-plot-settings-color-popup",
                                        elevation=4,
                                    ):
                                        with vuetify.VCardText(class_="pa-2"):
                                            html.Div(
                                                "Standard Colors",
                                                classes="text-caption seurat-plot-settings-popup-title",
                                            )
                                            with html.Div(
                                                classes="seurat-plot-settings-standard-colors"
                                            ):
                                                with vuetify.Template(
                                                    v_for="color in plotSettingsStandardColors",
                                                    key="'contour:' + color",
                                                ):
                                                    html.Button(
                                                        "",
                                                        classes="seurat-plot-settings-color-swatch",
                                                        raw_attrs=[
                                                            'type="button"',
                                                            ':disabled="!scalarFieldSettingsShowContours"',
                                                            ':title="color"',
                                                            ':style="{ backgroundColor: color, boxShadow: ((scalarFieldSettingsContourColor || \'\').toLowerCase() === color.toLowerCase()) ? \'0 0 0 2px #111\' : \'none\' }"',
                                                        ],
                                                        click=(
                                                            ctrl.update_scalar_field_contour_color,
                                                            "[color]",
                                                        ),
                                                    )
                                            html.Div(
                                                "More colors...",
                                                classes="text-caption seurat-plot-settings-more-colors",
                                            )
                                            vuetify.VColorPicker(
                                                hide_header=True,
                                                hide_inputs=False,
                                                show_swatches=False,
                                                width=220,
                                                raw_attrs=[
                                                    ':model-value="scalarFieldSettingsContourColor"',
                                                    ':modes="[\'hex\', \'rgb\', \'hsl\']"',
                                                    ':disabled="!scalarFieldSettingsShowContours"',
                                                ],
                                                update_modelValue=(
                                                    ctrl.update_scalar_field_contour_color,
                                                    "[$event]",
                                                ),
                                            )

                        with html.Div(classes="seurat-scalar-field-compact-row"):
                            html.Span("Definition", class_="text-caption")
                            with vuetify.VRadioGroup(
                                v_model=(
                                    "scalarFieldSettingsContourLevelMode",
                                ),
                                inline=True,
                                density="compact",
                                hide_details=True,
                                classes="seurat-scalar-field-contour-level-mode",
                                raw_attrs=[
                                    ':disabled="!scalarFieldSettingsShowContours"'
                                ],
                            ):
                                vuetify.VRadio(label="Range", value="range")
                                vuetify.VRadio(label="Values", value="values")

                        with vuetify.Template(
                            v_if="scalarFieldSettingsContourLevelMode === 'range'"
                        ):
                            with html.Div(classes="seurat-scalar-field-compact-row"):
                                html.Span("Range", class_="text-caption")
                                vuetify.VTextField(
                                    v_model=("scalarFieldSettingsContourMin",),
                                    label="Min",
                                    density="compact",
                                    hide_details=True,
                                    classes="seurat-scalar-field-compact-input",
                                    raw_attrs=[
                                        ':disabled="!scalarFieldSettingsShowContours"'
                                    ],
                                )
                                vuetify.VTextField(
                                    v_model=("scalarFieldSettingsContourMax",),
                                    label="Max",
                                    density="compact",
                                    hide_details=True,
                                    classes="seurat-scalar-field-compact-input",
                                    raw_attrs=[
                                        ':disabled="!scalarFieldSettingsShowContours"'
                                    ],
                                )
                                vuetify.VTextField(
                                    v_model=("scalarFieldSettingsContourCount",),
                                    label="Number",
                                    density="compact",
                                    hide_details=True,
                                    classes="seurat-scalar-field-compact-input",
                                    raw_attrs=[
                                        'type="number"',
                                        'min="2"',
                                        'max="100"',
                                        'step="1"',
                                        ':disabled="!scalarFieldSettingsShowContours"',
                                    ],
                                )
                        with vuetify.Template(
                            v_if="scalarFieldSettingsContourLevelMode === 'values'"
                        ):
                            with html.Div(classes="seurat-scalar-field-compact-row"):
                                html.Span("Values", class_="text-caption")
                                vuetify.VTextField(
                                    v_model=("scalarFieldSettingsContourValues",),
                                    placeholder="-1, -0.5, 0, 0.5, 1",
                                    density="compact",
                                    hide_details=True,
                                    classes="seurat-scalar-field-contour-values",
                                    raw_attrs=[
                                        ':disabled="!scalarFieldSettingsShowContours"'
                                    ],
                                )

                with vuetify.VCardActions():
                    vuetify.VSpacer()
                    vuetify.VBtn("Reset", variant="text", click=ctrl.reset_scalar_field_settings)
                    vuetify.VBtn("Close", variant="text", click=ctrl.cancel_scalar_field_settings)
                    vuetify.VBtn("Apply", variant="tonal", click=ctrl.apply_scalar_field_settings)


class ScalarFieldAssistantPanel(TrameComponent):
    def build(self):
        ctrl = self.ctrl
        with html.Div(
            id="seurat-plot-options-assistant-panel",
            v_show=("showScalarFieldAssistantModal",),
            classes=(
                "seurat-floating-options-panel "
                "seurat-ai-assistant-panel "
                "seurat-plot-options-assistant-panel"
            ),
        ):
            with vuetify.VCard(classes="seurat-floating-options-card", elevation=6):
                with vuetify.VCardTitle(classes="seurat-floating-options-titlebar"):
                    with html.Div(
                        style="display:flex; align-items:center; gap:8px; width:100%;"
                    ):
                        html.Div(
                            "{{ 'Plot Options Assistant: ' + (scalarFieldAssistantTitle || '') }}",
                            classes="seurat-floating-panel-drag-handle",
                        )
                        vuetify.VSpacer()
                        vuetify.VBtn(
                            "Close",
                            variant="text",
                            size="small",
                            click=ctrl.cancel_scalar_field_options_assistant,
                        )
                with vuetify.VCardText(classes="seurat-floating-options-content"):
                    html.Div(
                        "{{ scalarFieldAssistantProvider ? ('Provider: ' + scalarFieldAssistantProvider) : '' }}",
                        class_="text-caption mb-2",
                    )
                    vuetify.VTextarea(
                        v_model=("scalarFieldAssistantRequestText",),
                        placeholder="use plasma colormap",
                        auto_grow=True,
                        rows=3,
                        variant="outlined",
                        hide_details=True,
                    )
                    with vuetify.Template(v_if="scalarFieldAssistantStatus"):
                        html.Div(
                            "{{ scalarFieldAssistantStatus }}",
                            class_="text-caption mt-2",
                            style="color:#1b5e20;",
                        )
                    with vuetify.Template(v_if="scalarFieldAssistantError"):
                        html.Div(
                            "{{ scalarFieldAssistantError }}",
                            class_="text-caption mt-2",
                            style="color:#b00020;",
                        )
                    with vuetify.Template(v_if="scalarFieldAssistantClarification"):
                        html.Div(
                            "{{ scalarFieldAssistantClarification }}",
                            class_="text-caption mt-2",
                        )
                    with vuetify.Template(v_if="scalarFieldAssistantProposalSummary"):
                        html.Div(
                            "{{ scalarFieldAssistantProposalSummary }}",
                            class_="text-caption mt-2",
                        )
                with vuetify.VCardActions():
                    vuetify.VSpacer()
                    vuetify.VBtn(
                        "Cancel",
                        variant="text",
                        click=ctrl.cancel_scalar_field_options_assistant,
                    )
                    vuetify.VBtn(
                        "Ask",
                        color="primary",
                        variant="tonal",
                        click=ctrl.translate_scalar_field_options_request,
                        raw_attrs=[
                            ':loading="scalarFieldAssistantBusy"',
                            ':disabled="scalarFieldAssistantBusy"',
                        ],
                    )
                    vuetify.VBtn(
                        "Apply",
                        variant="tonal",
                        click=ctrl.apply_scalar_field_options_patch,
                        raw_attrs=[
                            ':disabled="scalarFieldAssistantBusy || !(scalarFieldAssistantPatch && Object.keys(scalarFieldAssistantPatch).length)"'
                        ],
                    )
