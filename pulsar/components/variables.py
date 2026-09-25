"""Variable catalog component."""

from trame.app import TrameComponent
from trame.widgets import html
from trame.widgets import vuetify3 as vuetify


class VariablePanel(TrameComponent):
    def build(self):
        ctrl = self.ctrl
        with vuetify.VCol(
            id="pulsar-variable-column",
            classes="pulsar-variable-column",
            style="display:flex; flex-direction:column; height:80vh;",
        ):
            with vuetify.VCard(
                variant="outlined",
                style="flex:1 1 auto; min-height:0; display:flex; flex-direction:column;",
            ):
                with vuetify.VCardTitle(
                    classes="pulsar-variable-card-title"
                ):
                    html.Div("Variables", classes="pulsar-variable-title-text")
                    vuetify.VTextField(
                        v_model=("variableSearchText",),
                        placeholder="Search",
                        density="compact",
                        hide_details=True,
                        clearable=True,
                        classes="pulsar-variable-search",
                        raw_attrs=[
                            'aria-label="Search variables"',
                            'autocomplete="off"',
                        ],
                    )
                with vuetify.VCardText(style="flex:1 1 auto; min-height:0; overflow-y:auto;"):
                    with html.Div(
                        style="display:flex; align-items:center; gap:8px; padding:0 4px 8px 4px;",
                    ):
                        html.Span("Group by:", class_="text-caption")
                        with vuetify.VBtnToggle(
                            v_model=("variablePaneView",),
                            mandatory=True,
                            density="compact",
                            divided=True,
                            variant="outlined",
                        ):
                            vuetify.VBtn("Variable", value="variables", size="small")
                            vuetify.VBtn("File", value="files", size="small")
                    with html.Div(style="padding:0 4px 8px 4px;"):
                        vuetify.VCheckbox(
                            v_model=("showOnlyVisualizedVars",),
                            label="Only with visualizations",
                            density="compact",
                            hide_details=True,
                        )
                    with vuetify.VList(density="compact", class_="pulsar-var-list"):
                        html.Div(
                            "No variables",
                            v_if="!(variableGroups || []).length",
                            class_="text-caption",
                            style="padding:8px 10px; color:#777;",
                        )
                        html.Div(
                            "No matching variables",
                            v_if="(variableSearchText || '').trim() && (variableGroups || []).length && !(filteredVariableGroups || []).length",
                            class_="text-caption",
                            style="padding:8px 10px; color:#777;",
                        )
                        with vuetify.Template(
                            v_for="group in ((variableSearchText || '').trim() ? filteredVariableGroups : variableGroups)",
                            key="group.name",
                        ):
                            with html.Div(
                                class_="pulsar-var-group",
                                style=(
                                    "border:1px solid #b8c4d1;"
                                    "background:#f4f7fa;"
                                    "box-shadow: inset 0 0 0 1px #e2e8ef;"
                                ),
                            ):
                                with html.Button(
                                    class_="pulsar-var-group-title",
                                    click=(ctrl.toggle_variable_group, "[group.name]"),
                                    style="font-weight:800;",
                                    raw_attrs=[
                                        'type="button"',
                                        ':aria-expanded="Boolean((variableSearchText || \'\').trim()) || !(variableGroupCollapsed && variableGroupCollapsed[group.name])"',
                                    ],
                                ):
                                    html.Span(
                                        "{{ (!(variableSearchText || '').trim() && variableGroupCollapsed && variableGroupCollapsed[group.name]) ? '▸' : '▾' }}",
                                        class_="pulsar-var-group-chevron",
                                    )
                                    html.Span(
                                        "{{ group.name + (((group.file_count || 0) > 1) ? (' (' + group.file_count + ')') : '') }}",
                                        raw_attrs=[':title="group.name"'],
                                        style="flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;",
                                    )
                                with html.Div(v_if="(variableSearchText || '').trim() || !(variableGroupCollapsed && variableGroupCollapsed[group.name])"):
                                    with vuetify.Template(v_for="v in group.variables", key="group.name + '::' + v.id"):
                                        with html.Div(
                                            click=(ctrl.pick_var, "[v.id]"),
                                            draggable="true",
                                            classes="pulsar-draggable-var pulsar-var-item",
                                            raw_attrs=[':data-item="v.id"', ':title="v.path || v.id"'],
                                            style=(
                                                "((v.id === selectedVar) ? 'background:#dfe7ef; box-shadow: inset 0 0 0 1px #b9c8d7;' : '')",
                                            ),
                                        ):
                                            html.Span("{{ v.label || v.name || v.id }}")

        html.Div(
            classes="pulsar-variable-resizer",
            raw_attrs=[
                "data-variable-panel-resizer",
                'role="separator"',
                'aria-label="Resize variable list"',
                'aria-orientation="vertical"',
                'aria-valuemin="180"',
                'tabindex="0"',
            ],
            title="Drag to resize the variable list",
        )
