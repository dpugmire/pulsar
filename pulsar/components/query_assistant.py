"""Review-before-apply natural-language Query Assistant dialog."""

from trame.app import TrameComponent
from trame.widgets import html
from trame.widgets import vuetify3 as vuetify


class QueryAssistantDialog(TrameComponent):
    def build(self):
        ctrl = self.ctrl
        with html.Div(
            id="pulsar-query-assistant-panel",
            v_show=("showQueryAssistant",),
            classes=(
                "pulsar-floating-options-panel "
                "pulsar-ai-assistant-panel "
                "pulsar-query-assistant-panel"
            ),
        ):
            with vuetify.VCard(classes="pulsar-floating-options-card", elevation=6):
                with vuetify.VCardTitle(classes="pulsar-floating-options-titlebar"):
                    with html.Div(
                        style=(
                            "display:flex; align-items:center; gap:8px; width:100%;"
                        )
                    ):
                        html.Div(
                            "{{ queryAssistantTarget === 'source_filter' "
                            "? 'Source Filter Assistant' "
                            ": (queryAssistantTarget === 'visualization' "
                            "? 'Visualization Assistant' : 'Query Assistant') }}",
                            classes="pulsar-floating-panel-drag-handle",
                        )
                        vuetify.VSpacer()
                        vuetify.VBtn(
                            "Close",
                            variant="text",
                            size="small",
                            click=ctrl.close_query_assistant,
                        )

                with vuetify.VCardText(classes="pulsar-floating-options-content"):
                    with vuetify.Template(
                        v_if="queryAssistantTarget === 'source_filter'"
                    ):
                        html.Div(
                            "Describe which source rows should remain visible for "
                            "the selected variable. The global catalog query will "
                            "not be changed.",
                            class_="text-body-2 mb-2",
                        )
                    with vuetify.Template(
                        v_if="queryAssistantTarget === 'catalog'"
                    ):
                        html.Div(
                            "Describe the variables or sources you want. The "
                            "assistant will propose a structured viewer action, "
                            "resolve campaign metadata locally, and preview the "
                            "result. It will not apply anything until you choose "
                            "Apply.",
                            class_="text-body-2 mb-2",
                        )
                    with vuetify.Template(
                        v_if="queryAssistantTarget === 'visualization'"
                    ):
                        html.Div(
                            "Describe the variable to add to the active grid cell. "
                            "The viewer will use the active query, current source "
                            "selection, and its default visualization. The grid will "
                            "not change until you choose Add to Grid.",
                            class_="text-body-2 mb-2",
                        )
                    html.Div(
                        "{{ 'Provider: ' + queryAssistantProvider }}",
                        class_="text-caption mb-1",
                    )
                    html.Div(
                        "Variable names, labels, paths, and source datasets from "
                        "this campaign may be sent to the configured provider. "
                        "Array values and media are not sent.",
                        class_="text-caption mb-4",
                        style="color:#555;",
                    )
                    vuetify.VTextarea(
                        v_model=("queryAssistantRequestText",),
                        label="Request",
                        placeholder=(
                            "queryAssistantTarget === 'source_filter' "
                            "? 'e.g. max > 5 and dataset contains 128' "
                            ": (queryAssistantTarget === 'visualization' "
                            "? 'e.g. Add pressure to the selected cell' "
                            ": 'e.g. Show temperature from runs where valid equals 1')",
                        ),
                        rows=3,
                        auto_grow=True,
                        counter=2000,
                        maxlength=2000,
                        variant="outlined",
                        disabled=("queryAssistantBusy",),
                    )
                    with html.Div(
                        style=(
                            "display:flex; align-items:center; gap:8px; "
                            "margin-bottom:12px;"
                        )
                    ):
                        vuetify.VBtn(
                            "Translate",
                            color="primary",
                            variant="tonal",
                            loading=("queryAssistantBusy",),
                            disabled=(
                                "queryAssistantBusy || "
                                "!(queryAssistantRequestText || '').trim()",
                            ),
                            click=ctrl.translate_query_request,
                        )
                        with vuetify.Template(v_if="queryAssistantStatus"):
                            html.Span(
                                "{{ queryAssistantStatus }}",
                                class_="text-caption",
                                style="color:#2e7d32;",
                            )

                    with vuetify.Template(v_if="queryAssistantError"):
                        html.Div(
                            "{{ queryAssistantError }}",
                            class_="text-caption mb-3",
                            style="color:#b00020;",
                        )

                    with vuetify.Template(v_if="queryAssistantClarification"):
                        with vuetify.VAlert(
                            type="info",
                            variant="tonal",
                            density="compact",
                            class_="mb-3",
                        ):
                            html.Div("{{ queryAssistantClarification }}")

                    with vuetify.Template(v_if="queryAssistantProposalSummary"):
                        with vuetify.VAlert(
                            type="info",
                            variant="tonal",
                            density="compact",
                            class_="mb-3",
                        ):
                            html.Div("{{ queryAssistantProposalSummary }}")

                    with vuetify.Template(v_if="queryAssistantProposalText"):
                        vuetify.VTextarea(
                            v_model=("queryAssistantProposalText",),
                            label="Resolved Advanced Query",
                            rows=2,
                            auto_grow=True,
                            variant="outlined",
                            readonly=True,
                        )
                        with html.Div(
                            style=(
                                "display:flex; align-items:center; gap:8px; "
                                "margin-top:-8px; margin-bottom:12px;"
                            )
                        ):
                            vuetify.VBtn(
                                "Validate",
                                variant="text",
                                size="small",
                                disabled=("queryAssistantBusy",),
                                click=ctrl.validate_query_proposal,
                            )
                            html.Span(
                                "Compatibility representation used by the current "
                                "local query backend.",
                                class_="text-caption",
                            )

                    with vuetify.Template(v_if="queryAssistantExplanation"):
                        html.Div(
                            "{{ queryAssistantExplanation }}",
                            class_="text-body-2 mb-2",
                        )
                    with vuetify.Template(
                        v_if="(queryAssistantAssumptions || []).length"
                    ):
                        html.Div("Assumptions:", class_="text-caption font-weight-bold")
                        with html.Ul(class_="text-caption mb-2"):
                            with vuetify.Template(
                                v_for="item in queryAssistantAssumptions",
                                key="item",
                            ):
                                html.Li("{{ item }}")

                with vuetify.VCardActions():
                    vuetify.VSpacer()
                    vuetify.VBtn(
                        "Cancel",
                        variant="text",
                        click=ctrl.close_query_assistant,
                    )
                    with vuetify.VBtn(
                        color="primary",
                        variant="outlined",
                        disabled=(
                            "queryAssistantBusy || "
                            "!(queryAssistantProposalSummary || '').trim()",
                        ),
                        click=ctrl.apply_query_proposal,
                    ):
                        html.Span(
                            "{{ queryAssistantTarget === 'source_filter' "
                            "? 'Apply to Source Filter' "
                            ": (queryAssistantTarget === 'visualization' "
                            "? 'Add to Grid' : 'Apply') }}"
                        )
