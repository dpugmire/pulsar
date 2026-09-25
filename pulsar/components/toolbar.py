"""Query toolbar component."""

from trame.app import TrameComponent
from trame.widgets import html
from trame.widgets import vuetify3 as vuetify


class QueryToolbar(TrameComponent):
    def build(self):
        ctrl = self.ctrl
        with html.Div(
            classes="pulsar-history-controls",
            raw_attrs=['aria-label="Workspace history"'],
        ):
            html.Button(
                "↶",
                classes="pulsar-history-button",
                click=ctrl.undo_workspace,
                raw_attrs=[
                    'type="button"',
                    ':disabled="!workspaceCanUndo"',
                    ':aria-label="workspaceCanUndo ? (\'Undo \' + workspaceUndoLabel) : \'Nothing to undo\'"',
                    ':title="workspaceCanUndo ? (\'Undo \' + workspaceUndoLabel + \' (Ctrl/Cmd+Z)\') : \'Nothing to undo\'"',
                ],
            )
            html.Button(
                "↷",
                classes="pulsar-history-button",
                click=ctrl.redo_workspace,
                raw_attrs=[
                    'type="button"',
                    ':disabled="!workspaceCanRedo"',
                    ':aria-label="workspaceCanRedo ? (\'Redo \' + workspaceRedoLabel) : \'Nothing to redo\'"',
                    ':title="workspaceCanRedo ? (\'Redo \' + workspaceRedoLabel + \' (Ctrl/Cmd+Shift+Z)\') : \'Nothing to redo\'"',
                ],
            )
        with vuetify.Template(v_if="workspaceHistoryError"):
            html.Span(
                "{{ workspaceHistoryError }}",
                classes="pulsar-history-error",
                title=("workspaceHistoryError",),
            )
        html.Span("Advanced Query:", class_="text-caption ml-4")
        vuetify.VBtn(
            "?",
            click=ctrl.show_query_help,
            variant="tonal",
            size="small",
            min_width=32,
            title="Query help",
        )
        vuetify.VTextField(
            v_model=("queryText",),
            placeholder="e.g. var == 'rho' and source_dataset == 'hll_128/output.bp'",
            density="compact",
            hide_details=True,
            variant="outlined",
            style="max-width: 420px;",
            class_="mx-2",
        )
        vuetify.VBtn("Query", click=ctrl.run_query, variant="outlined", size="small")
        with vuetify.Template(v_if="queryAssistantAvailable"):
            vuetify.VBtn(
                "Ask",
                click=ctrl.open_query_assistant,
                variant="tonal",
                size="small",
                class_="ml-1",
                title="Translate natural language into a query",
            )
            vuetify.VBtn(
                "Visualize",
                click=ctrl.open_visualization_assistant,
                variant="tonal",
                size="small",
                class_="ml-1",
                title="Add a variable to the active grid cell using natural language",
            )
        vuetify.VBtn(
            "Clear",
            click=ctrl.clear_query,
            variant="text",
            size="small",
            class_="ml-1",
        )
        with vuetify.Template(v_if="queryError"):
            html.Span(
                "{{ queryError }}",
                class_="text-caption ml-2",
                style="color:#b00020;",
            )
