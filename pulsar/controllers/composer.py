"""Composition and Trame registration for Pulsar's domain controllers."""

import inspect
from functools import wraps
from typing import Optional

from pulsar.backends import LocalCampaignBackend, PulsarBackend
from pulsar.history import WorkspaceMutationCoordinator

from .base import ControllerBase
from .catalog import CatalogControllerMixin
from .context import ControllerContext
from .context_menu import ContextMenuControllerMixin
from .grid import GridControllerMixin
from .history import HistoryControllerMixin
from .lifecycle import LifecycleControllerMixin
from .query_assistant import QueryAssistantControllerMixin
from .sources import SourcesControllerMixin
from .visualization import VisualizationControllerMixin
from .workspace import WorkspaceControllerMixin


CONTROLLER_TYPES = (
    CatalogControllerMixin,
    QueryAssistantControllerMixin,
    SourcesControllerMixin,
    GridControllerMixin,
    VisualizationControllerMixin,
    ContextMenuControllerMixin,
    HistoryControllerMixin,
    WorkspaceControllerMixin,
    LifecycleControllerMixin,
)


class PulsarController(
    CatalogControllerMixin,
    QueryAssistantControllerMixin,
    SourcesControllerMixin,
    GridControllerMixin,
    VisualizationControllerMixin,
    ContextMenuControllerMixin,
    HistoryControllerMixin,
    WorkspaceControllerMixin,
    LifecycleControllerMixin,
    ControllerBase,
):
    def __init__(self, context):
        super().__init__(context)
        self.history = WorkspaceMutationCoordinator(
            self.state,
            self.capture_workspace_history,
            self.restore_workspace_history,
            validate=self.validate_workspace_history,
        )

    def _history_wrapped(self, method, label):
        if inspect.iscoroutinefunction(method):
            raise TypeError(
                f"Historical mutation {method.__qualname__} must be synchronous"
            )

        @wraps(method)
        def wrapped(*args, **kwargs):
            with self.history.transaction(label):
                return method(*args, **kwargs)

        return wrapped

    def register(self):
        for controller_type in CONTROLLER_TYPES:
            # Mutation boundary contract: every user-facing edit belongs in
            # one of these declarations so it cannot bypass transaction
            # framing when registered with Trame.
            history_actions = getattr(controller_type, "HISTORY_ACTIONS", {})
            history_triggers = getattr(controller_type, "HISTORY_TRIGGERS", {})
            for action_name, method_name in controller_type.ACTION_BINDINGS:
                method = getattr(self, method_name)
                if action_name in history_actions:
                    method = self._history_wrapped(
                        method, history_actions[action_name]
                    )
                if inspect.iscoroutinefunction(method):
                    self.ctrl.set(action_name, clear=True)(method)
                else:
                    self.ctrl.add(action_name)(method)
            for trigger_name, method_name in controller_type.TRIGGER_BINDINGS:
                method = getattr(self, method_name)
                if trigger_name in history_triggers:
                    method = self._history_wrapped(
                        method, history_triggers[trigger_name]
                    )
                self.ctrl.trigger(trigger_name)(method)
            for state_names, method_name in controller_type.STATE_CHANGE_BINDINGS:
                self.state.change(*state_names)(getattr(self, method_name))
        self.ctrl.on_server_ready.add(self.ingest_campaign_every_time)
        return self


def attach_controllers(
    server,
    db,
    collection,
    parse_campaign,
    campaign_path: str,
    image_association_schema_path: str = "",
    campaign_schema_path: str = "",
    backend: Optional[PulsarBackend] = None,
    query_translator=None,
    plot_options_translator=None,
    interaction_log=None,
):
    catalog_backend = backend if backend is not None else LocalCampaignBackend(db)
    context = ControllerContext(
        server=server,
        backend=catalog_backend,
        db=db,
        collection=collection,
        parse_campaign=parse_campaign,
        campaign_path=campaign_path,
        image_association_schema_path=image_association_schema_path,
        campaign_schema_path=campaign_schema_path,
        query_translator=query_translator,
        plot_options_translator=plot_options_translator,
        interaction_log=interaction_log,
    )
    controller = PulsarController(context).register()
    return controller.refresh_variable_list
