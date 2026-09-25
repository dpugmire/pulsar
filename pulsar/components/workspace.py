"""Hamburger-drawer workspace file commands."""

from trame.app import TrameComponent
from trame.widgets import html
from trame.widgets import vuetify3 as vuetify


_LIVE_GRID_SIZING_ARGUMENTS = """
[(() => {
  const grid = $event.target.ownerDocument.querySelector('.pulsar-workspace-active-grid');
  if (!grid) return null;
  return {
    mode: grid.getAttribute('data-grid-sizing-mode') || '',
    column_sizes: grid.getAttribute('data-grid-column-sizes') || '',
    row_sizes: grid.getAttribute('data-grid-row-sizes') || '',
    column_weights: grid.getAttribute('data-grid-column-weights') || '',
    row_weights: grid.getAttribute('data-grid-row-weights') || '',
  };
})()]
"""


class WorkspaceMenu(TrameComponent):
    def build(self):
        ctrl = self.ctrl
        with vuetify.VList(density="compact", nav=True):
            vuetify.VListSubheader("State")
            vuetify.VListItem(
                title="Save",
                prepend_icon="mdi-content-save",
                click=(
                    ctrl.save_workspace_state,
                    _LIVE_GRID_SIZING_ARGUMENTS,
                ),
            )
            vuetify.VListItem(
                title="Save As…",
                prepend_icon="mdi-content-save-edit",
                click=(
                    ctrl.save_workspace_state_as,
                    _LIVE_GRID_SIZING_ARGUMENTS,
                ),
            )
            vuetify.VListItem(
                title="Load…",
                prepend_icon="mdi-folder-open",
                click=ctrl.load_workspace_state,
            )

        vuetify.VDivider()
        with html.Div(class_="pa-4"):
            html.Div("Current state file", class_="text-caption font-weight-bold")
            with vuetify.Template(v_if="workspaceStatePath"):
                html.Div(
                    "{{ workspaceStatePath }}",
                    class_="text-caption mt-1",
                    style="overflow-wrap:anywhere;",
                )
            with vuetify.Template(v_if="!workspaceStatePath"):
                html.Div(
                    "No state file selected",
                    class_="text-caption mt-1 text-medium-emphasis",
                )
            with vuetify.Template(v_if="workspaceStateStatus"):
                html.Div(
                    "{{ workspaceStateStatus }}",
                    class_="text-caption mt-3",
                    style="color:#2e7d32; overflow-wrap:anywhere;",
                )
            with vuetify.Template(v_if="workspaceStateError"):
                html.Div(
                    "{{ workspaceStateError }}",
                    class_="text-caption mt-3",
                    style="color:#b00020; overflow-wrap:anywhere;",
                )
