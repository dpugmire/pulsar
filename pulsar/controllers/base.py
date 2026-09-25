"""Base state and dependencies for domain controller mixins."""

import time
from typing import Any, Dict, Optional

from application import PulsarApplication
from pulsar.learning.context import (
    sanitized_query_context,
    sanitized_workspace_snapshot,
    stable_fingerprint,
    workspace_location,
)
from pulsar.learning.events import new_identifier
from pulsar.models import grid_layout

from .context import ControllerContext


class ControllerBase:
    GRID_MIN_ROWS = grid_layout.GRID_MIN_ROWS
    GRID_MIN_COLS = grid_layout.GRID_MIN_COLS
    GRID_MAX_ROWS = grid_layout.GRID_MAX_ROWS
    GRID_MAX_COLS = grid_layout.GRID_MAX_COLS
    GRID_HEADER_HEIGHT = grid_layout.GRID_HEADER_HEIGHT
    GRID_MIN_TRACK_WEIGHT = grid_layout.GRID_MIN_TRACK_WEIGHT
    GRID_MAX_TRACK_WEIGHT = grid_layout.GRID_MAX_TRACK_WEIGHT

    def __init__(self, context: ControllerContext):
        self.context = context
        self.server = context.server
        self.state = context.server.state
        self.ctrl = context.server.controller
        self.backend = context.backend
        self.db = context.db
        self.collection = context.collection
        self.parse_campaign = context.parse_campaign
        self.campaign_path = context.campaign_path
        self.image_association_schema_path = context.image_association_schema_path
        self.campaign_schema_path = context.campaign_schema_path
        self.query_translator = context.query_translator
        self.plot_options_translator = context.plot_options_translator
        self.interaction_log = context.interaction_log
        self._interaction_query_id = ""
        self._interaction_assignment_source = ""
        self._interaction_assignments: Dict[str, Dict[str, Any]] = {}
        self.state.queryAssistantAvailable = self.query_translator is not None
        self.state.queryAssistantProvider = (
            self.query_translator.description if self.query_translator else ""
        )
        self.state.scalarFieldAssistantAvailable = (
            self.plot_options_translator is not None
        )
        self.state.scalarFieldAssistantProvider = (
            self.plot_options_translator.description
            if self.plot_options_translator
            else ""
        )
        self.application = PulsarApplication(backend=context.backend)
        self.plugin_source_variables_cache = {}

    def record_interaction(
        self,
        event_type: str,
        *,
        source: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> str:
        recorder = self.interaction_log
        if recorder is None or not bool(getattr(recorder, "enabled", False)):
            return ""
        try:
            return str(
                recorder.record(
                    event_type,
                    source=source,
                    payload=dict(payload or {}),
                )
                or ""
            )
        except Exception:
            return ""

    def record_query_applied(
        self,
        *,
        origin: str,
        target: str = "catalog",
        action_plan: Optional[Dict[str, Any]] = None,
    ) -> str:
        query_id = new_identifier("query")
        payload = sanitized_query_context(
            self.state,
            query_id=query_id,
            origin=origin,
            target=target,
            action_plan=action_plan,
        )
        event_id = self.record_interaction(
            "query.applied",
            source=origin,
            payload=payload,
        )
        if event_id:
            self._interaction_query_id = query_id
        return query_id if event_id else ""

    def interaction_workspace_location(
        self, cell_index: Optional[int] = None
    ) -> Dict[str, Any]:
        try:
            return workspace_location(self.state, cell_index)
        except Exception:
            return {}

    def interaction_workspace_snapshot(self) -> Dict[str, Any]:
        try:
            return sanitized_workspace_snapshot(self.state)
        except Exception:
            return {}

    def record_visualization_assignment(
        self,
        cell_index: int,
        cell: Dict[str, Any],
        *,
        source: str,
        selection_origin: str = "default",
    ) -> str:
        item = dict(cell or {})
        variable_id = str(
            item.get("variable_id", "") or item.get("variable_name", "") or ""
        )
        if not variable_id or str(item.get("status", "") or "") == "error":
            return ""
        visualization = str(
            item.get("selected_visualization", "")
            or item.get("visualization_name", "")
            or ""
        )
        candidates = [
            str(value or "")
            for value in list(item.get("visualization_options", []) or [])
            if str(value or "")
        ]
        if visualization and visualization not in candidates:
            candidates.append(visualization)
        payload = {
            "variable_id": variable_id,
            "candidate_visualizations": candidates,
            "selected_visualization": visualization,
            "selection_origin": str(selection_origin or "default"),
            "selection_policy": "heatmap_else_first",
            "query_id": self._interaction_query_id,
            "workspace": self.interaction_workspace_location(cell_index),
        }
        source_identity = str(
            item.get("source_id", "") or item.get("_source_key", "") or ""
        )
        if source_identity:
            payload["source_id"] = stable_fingerprint(source_identity, "source")
        event_id = self.record_interaction(
            "visualization.assigned",
            source=source,
            payload=payload,
        )
        if event_id:
            self._interaction_assignments[self._interaction_cell_key(cell_index)] = {
                "event_id": event_id,
                "started": time.monotonic(),
            }
        return event_id

    def _interaction_cell_key(self, cell_index: int) -> str:
        location = self.interaction_workspace_location(cell_index)
        return "|".join(
            (
                str(location.get("pane_id", "") or ""),
                str(location.get("tab_id", "") or ""),
                str(location.get("cell_index", -1)),
            )
        )

    def interaction_assignment_reference(self, cell_index: int) -> Dict[str, Any]:
        item = dict(
            self._interaction_assignments.get(
                self._interaction_cell_key(cell_index), {}
            )
            or {}
        )
        if not item:
            return {}
        return {
            "assignment_event_id": str(item.get("event_id", "") or ""),
            "elapsed_since_assignment_ms": max(
                0, int((time.monotonic() - float(item.get("started", 0.0))) * 1000)
            ),
        }

    def clear_interaction_assignment(self, cell_index: Optional[int] = None) -> None:
        if cell_index is None:
            self._interaction_assignments.clear()
            return
        self._interaction_assignments.pop(
            self._interaction_cell_key(cell_index), None
        )
