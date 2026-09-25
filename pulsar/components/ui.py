"""Top-level Pulsar UI composition."""

from trame.app import TrameComponent
from trame.ui.vuetify3 import SinglePageLayout
from trame.widgets import vuetify3 as vuetify

from pulsar.widgets import (
    CanvasRuntime,
    HistoryRuntime,
    InteractionRuntime,
    ResizeRuntime,
)

from .context_menu import ContextMenu
from .dialogs import HelpDialog
from .grid import GridWorkspace
from .query_assistant import QueryAssistantDialog
from .toolbar import QueryToolbar
from .variables import VariablePanel
from .workspace import WorkspaceMenu


class PulsarUI(TrameComponent):
    def __init__(self, server, campaign_name=""):
        super().__init__(server)
        self.query_toolbar = QueryToolbar(server)
        self.query_assistant = QueryAssistantDialog(server)
        self.help_dialog = HelpDialog(server)
        self.workspace_menu = WorkspaceMenu(server)
        self.variable_panel = VariablePanel(server)
        self.grid_workspace = GridWorkspace(server)
        self.context_menu = ContextMenu(server)
        self.interaction_runtime = None
        self.canvas_runtime = None
        self.resize_runtime = None
        self.history_runtime = None
        self.layout = self.build(campaign_name)

    def build(self, campaign_name=""):
        with SinglePageLayout(self.server) as layout:
            layout.title.set_text(campaign_name or "Pulsar")
            layout.icon.click = (
                "workspaceDrawerOpen = !workspaceDrawerOpen"
            )
            with vuetify.VNavigationDrawer(
                v_model=("workspaceDrawerOpen",),
                v_if=("workspaceDrawerOpen",),
                location="left",
                temporary=True,
                width=320,
            ) as drawer:
                self.workspace_menu.build()
            layout.drawer = drawer

            with layout.toolbar:
                self.query_toolbar.build()

            with layout.content:
                self.interaction_runtime = InteractionRuntime()
                self.canvas_runtime = CanvasRuntime()
                self.resize_runtime = ResizeRuntime()
                self.history_runtime = HistoryRuntime()
                self.help_dialog.build()
                self.query_assistant.build()
                with vuetify.VContainer(fluid=True, class_="pa-2"):
                    with vuetify.VRow(classes="pulsar-main-row", no_gutters=True):
                        self.variable_panel.build()
                        self.grid_workspace.build()
                self.context_menu.build()

        return layout
