import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from seurat.controllers.base import ControllerBase
from seurat.controllers.context import ControllerContext
from seurat.controllers.visualization import VisualizationControllerMixin
from seurat.learning.audit import audit_logs, format_audit
from seurat.learning.context import sanitized_workspace_snapshot
from seurat.learning.events import validate_event
from seurat.learning.log import InteractionLog
from seurat.state import grid as grid_state
from seurat.state import workspace as workspace_state


class MemoryInteractionLog:
    enabled = True

    def __init__(self):
        self.events = []

    def record(self, event_type, *, source, payload):
        event_id = f"event:{len(self.events) + 1}"
        self.events.append(
            {
                "event_id": event_id,
                "event_type": event_type,
                "source": source,
                "payload": payload,
            }
        )
        return event_id


class InteractionLogTests(unittest.TestCase):
    def test_empty_directory_disables_logging_without_writing(self):
        recorder = InteractionLog("", campaign_path="/campaign/private.aca")

        self.assertFalse(recorder.enabled)
        self.assertEqual(
            recorder.record("query.applied", source="test", payload={}),
            "",
        )
        self.assertIsNone(recorder.path)

    def test_enabled_log_writes_valid_ordered_events_without_campaign_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir) / "logs"
            recorder = InteractionLog(
                str(log_dir), campaign_path="/campaign/private/example.aca"
            )
            profile_id = recorder.user_profile_id
            recorder.record(
                "query.applied",
                source="query_toolbar",
                payload={"query_id": "query:1", "result_variable_count": 2},
            )
            recorder.close()

            lines = [
                json.loads(line)
                for path in log_dir.glob("*.jsonl")
                for line in path.read_text(encoding="utf-8").splitlines()
            ]

            self.assertEqual(
                [event["event_type"] for event in lines],
                ["session.started", "query.applied", "session.ended"],
            )
            self.assertEqual([event["event_sequence"] for event in lines], [1, 2, 3])
            self.assertTrue(all(not validate_event(event) for event in lines))
            self.assertTrue(all(event["user_profile_id"] == profile_id for event in lines))
            self.assertNotIn(
                "/campaign/private/example.aca",
                json.dumps(lines),
            )

            next_session = InteractionLog(
                str(log_dir), campaign_path="/campaign/private/example.aca"
            )
            self.assertEqual(next_session.user_profile_id, profile_id)
            next_session.close()

    def test_non_json_payload_is_failure_isolated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = InteractionLog(temp_dir, campaign_path="campaign.aca")

            self.assertEqual(
                recorder.record(
                    "query.applied",
                    source="test",
                    payload={"bad": object()},
                ),
                "",
            )
            self.assertTrue(recorder.enabled)
            self.assertTrue(recorder.last_error)
            self.assertTrue(
                recorder.record(
                    "query.cleared",
                    source="test",
                    payload={"query_id": "query:1"},
                )
            )
            recorder.close()

    def test_workspace_snapshot_keeps_semantics_and_excludes_sensitive_fields(self):
        values = grid_state.defaults()
        values.update(workspace_state.defaults())
        state = SimpleNamespace(**values)
        state.queryText = "pressure > secret-threshold"
        state.workspaceStatePath = "/private/workspace.json"
        state.workspaceLayout["panes"][0]["tabs"][0]["title"] = "Secret Project"
        state.gridCells[0].update(
            {
                "variable_id": "pressure",
                "visualization_name": "heatmap",
                "selected_visualization": "heatmap",
                "source_dataset": "/private/run/output.bp",
                "src": "data:image/png;base64,secret-pixels",
                "metadata": {"secret": "payload"},
                "plugin_options": {"private_path": "/private/plugin"},
            }
        )
        state.activeGridCell = 0

        snapshot = sanitized_workspace_snapshot(state)
        encoded = json.dumps(snapshot)
        active_grid = snapshot["panes"][0]["tabs"][0]["grid"]

        self.assertEqual(active_grid["active_cell"], 0)
        self.assertEqual(active_grid["cells"][0]["variable_id"], "pressure")
        self.assertEqual(active_grid["cells"][0]["visualization_id"], "heatmap")
        for sensitive in (
            "Secret Project",
            "secret-threshold",
            "/private/workspace.json",
            "/private/run/output.bp",
            "secret-pixels",
            "payload",
            "/private/plugin",
        ):
            self.assertNotIn(sensitive, encoded)

    def test_audit_ignores_truncated_tail_and_reports_learning_signals(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = InteractionLog(temp_dir, campaign_path="campaign.aca")
            recorder.record(
                "visualization.assigned",
                source="variable_add",
                payload={
                    "variable_id": "pressure",
                    "candidate_visualizations": ["heatmap", "contour"],
                    "selected_visualization": "heatmap",
                },
            )
            recorder.record(
                "visualization.changed",
                source="grid_menu",
                payload={
                    "variable_id": "pressure",
                    "previous_visualization": "heatmap",
                    "selected_visualization": "contour",
                },
            )
            recorder.record(
                "plugin.executed",
                source="plugin_runtime",
                payload={
                    "plugin_id": "density-heatmap",
                    "status": "success",
                    "normalized_options": {"colormap": "plasma"},
                },
            )
            recorder.record(
                "workspace.saved",
                source="workspace_menu",
                payload={
                    "workspace": {
                        "panes": [
                            {
                                "tabs": [
                                    {
                                        "grid": {
                                            "cells": [
                                                {"variable_id": "pressure"},
                                                {"variable_id": "temperature"},
                                            ]
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                },
            )
            recorder.close()
            path = next(Path(temp_dir).glob("*.jsonl"))
            with path.open("ab") as stream:
                stream.write(b'{"truncated"')

            summary = audit_logs([temp_dir])
            report = format_audit(summary)

            self.assertEqual(summary["invalid_events"], 0)
            self.assertEqual(summary["truncated_final_lines"], 1)
            self.assertEqual(
                summary["default_changes"][0],
                {"from": "heatmap", "to": "contour", "count": 1},
            )
            self.assertEqual(
                summary["saved_colocations"][0],
                {"variables": ["pressure", "temperature"], "count": 1},
            )
            self.assertIn("heatmap -> contour: 1", report)
            self.assertIn("pressure + temperature: 1", report)
            self.assertIn("Plugin executions: 1", report)


class ControllerLearningContextTests(unittest.TestCase):
    def test_plugin_execution_records_success_with_reproducible_context(self):
        events = []
        controller = SimpleNamespace(
            _interaction_query_id="query:plugin",
            record_interaction=lambda event_type, **kwargs: events.append(
                {
                    "event_type": event_type,
                    **kwargs,
                }
            ),
        )
        tile = {
            "plugin_execution_provenance": {
                "plugin_id": "density-heatmap",
                "plugin_label": "Density heatmap",
                "plugin_module": "plugins.density",
                "plugin_version": "2.1",
                "plugin_scope": "variable",
                "status": "success",
                "normalized_options": {"colormap": "plasma"},
                "input_variables": ["rho"],
                "source_datasets": ["private/run/output.bp"],
                "output": {"media_type": "image", "status": "ok"},
                "scientific_context": {"outcome": "supported"},
            }
        }

        result = VisualizationControllerMixin.execute_plugin_render(
            controller,
            plugin_id="density-heatmap",
            plugin_scope_name="variable",
            variable_id="rho",
            source_dataset="private/run/output.bp",
            options={"colormap": "plasma"},
            renderer=lambda: tile,
        )

        self.assertIs(result, tile)
        self.assertEqual(events[0]["event_type"], "plugin.executed")
        payload = events[0]["payload"]
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["normalized_options"], {"colormap": "plasma"})
        self.assertEqual(payload["input_variables"], ["rho"])
        self.assertEqual(payload["query_id"], "query:plugin")
        self.assertTrue(payload["source_ids"][0].startswith("source:sha256:"))
        self.assertNotIn("private/run/output.bp", json.dumps(payload))

    def test_plugin_execution_records_failed_attempt(self):
        events = []
        controller = SimpleNamespace(
            _interaction_query_id="",
            record_interaction=lambda event_type, **kwargs: events.append(
                {
                    "event_type": event_type,
                    **kwargs,
                }
            ),
        )

        def fail_render():
            raise ValueError("bad input")

        with self.assertRaisesRegex(ValueError, "bad input"):
            VisualizationControllerMixin.execute_plugin_render(
                controller,
                plugin_id="density-heatmap",
                plugin_scope_name="variable",
                variable_id="rho",
                source_dataset="run/output.bp",
                options={"colormap": "plasma"},
                renderer=fail_render,
            )

        payload = events[0]["payload"]
        self.assertEqual(payload["status"], "failure")
        self.assertEqual(payload["error_type"], "ValueError")
        self.assertEqual(payload["plugin_id"], "density-heatmap")

    def test_assignment_records_candidates_query_and_workspace_location(self):
        state_values = grid_state.defaults()
        state_values.update(workspace_state.defaults())
        state = SimpleNamespace(
            **state_values,
            queryAssistantAvailable=False,
            queryAssistantProvider="",
        )
        recorder = MemoryInteractionLog()
        context = ControllerContext(
            server=SimpleNamespace(state=state, controller=SimpleNamespace()),
            backend=SimpleNamespace(),
            db=SimpleNamespace(),
            collection=SimpleNamespace(),
            parse_campaign=lambda *_args, **_kwargs: None,
            campaign_path="/campaign/private.aca",
            interaction_log=recorder,
        )
        controller = ControllerBase(context)
        controller._interaction_query_id = "query:1"

        event_id = controller.record_visualization_assignment(
            0,
            {
                "variable_id": "pressure",
                "visualization_options": ["heatmap", "contour"],
                "selected_visualization": "heatmap",
                "source_id": "private/source/path",
                "status": "ready",
            },
            source="variable_add",
        )

        self.assertEqual(event_id, "event:1")
        payload = recorder.events[0]["payload"]
        self.assertEqual(payload["candidate_visualizations"], ["heatmap", "contour"])
        self.assertEqual(payload["selected_visualization"], "heatmap")
        self.assertEqual(payload["query_id"], "query:1")
        self.assertEqual(payload["workspace"]["cell_index"], 0)
        self.assertTrue(payload["source_id"].startswith("source:sha256:"))
        self.assertNotIn("private/source/path", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
