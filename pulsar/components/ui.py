"""Top-level Pulsar UI composition."""

from trame.app import TrameComponent
from trame.ui.vuetify3 import SinglePageLayout
from trame.widgets import vuetify3 as vuetify
from trame.widgets import html

from pulsar import module as pulsar_module
from pulsar.widgets import (
    CanvasRuntime,
    HistoryRuntime,
    InteractionRuntime,
    ResizeRuntime,
)

from .context_menu import ContextMenu
from .campaigns import CampaignOverview
from .dialogs import HelpDialog
from .grid import GridWorkspace
from .query_assistant import QueryAssistantDialog
from .toolbar import QueryToolbar
from .variables import VariablePanel
from .workspace import WorkspaceMenu


class PulsarUI(TrameComponent):
    def __init__(self, server, campaign_name=""):
        super().__init__(server)
        self.server.state.trame__title = "Pulsar"
        self.server.state.trame__favicon = (
            f"{pulsar_module.BASE_URL}/pulsar-mark.svg"
        )
        self.query_toolbar = QueryToolbar(server)
        self.query_assistant = QueryAssistantDialog(server)
        self.help_dialog = HelpDialog(server)
        self.workspace_menu = WorkspaceMenu(server)
        self.variable_panel = VariablePanel(server)
        self.grid_workspace = GridWorkspace(server)
        self.context_menu = ContextMenu(server)
        self.campaign_overview = CampaignOverview(server)
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
                with vuetify.Template(v_if="campaignDisplay === 'workspace'"):
                    self.query_toolbar.build()

            with layout.content:
                self.interaction_runtime = InteractionRuntime()
                self.canvas_runtime = CanvasRuntime()
                self.resize_runtime = ResizeRuntime()
                self.history_runtime = HistoryRuntime()
                self.help_dialog.build()
                self.query_assistant.build()
                with html.Div(classes="d-flex align-center px-4 pt-2", style="gap:16px;"):
                    with vuetify.VBtnToggle(v_model=("campaignDisplay",), mandatory=True, density="compact", variant="outlined"):
                        vuetify.VBtn("Campaigns", value="overview", size="small")
                        vuetify.VBtn("Workspace", value="workspace", size="small")
                    with html.Div(v_if="campaignDisplay === 'workspace' && campaignDatasetPath", classes="text-caption"):
                        html.Span("Dataset: {{ campaignDatasetPath }}")
                        vuetify.VBtn("All data", size="x-small", variant="text", click=(self.ctrl.select_campaign, "[selectedCampaignPath]"))
                with html.Div(v_show="campaignDisplay === 'overview'"):
                    self.campaign_overview.build()
                with vuetify.VContainer(fluid=True, class_="pa-2"):
                    with vuetify.VRow(v_show="campaignDisplay === 'workspace'", classes="pulsar-main-row", no_gutters=True):
                        self.variable_panel.build()
                        self.grid_workspace.build()
                self.context_menu.build()

        return layout
