import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trame.app import TrameComponent, get_server

import app as compatibility_app
from pulsar import module as pulsar_module
from pulsar.app import PulsarApp, build_parser, main
from pulsar.backends import LocalCampaignBackend
from pulsar.components import PulsarUI
from pulsar.components.query_assistant import QueryAssistantDialog
from pulsar.widgets import CanvasRuntime, GridRuntime, InteractionRuntime, ResizeRuntime
from ui import build_ui


class PulsarAppTests(unittest.TestCase):
    def test_browser_assets_use_current_cache_namespace(self):
        self.assertEqual(pulsar_module.BASE_URL, "pulsar_0_1_11")
        self.assertEqual(
            pulsar_module.styles,
            ["pulsar_0_1_11/pulsar.css"],
        )

    def test_provenance_panel_styles_enable_bounded_two_axis_resize(self):
        css = (
            Path(pulsar_module.__file__).parent
            / "serve"
            / "pulsar.css"
        ).read_text(encoding="utf-8")

        provenance_rule = css.split(
            ".pulsar-floating-options-panel.pulsar-provenance-panel {",
            1,
        )[1].split("}", 1)[0]
        self.assertIn("resize: both", provenance_rule)
        self.assertIn("overflow: hidden", provenance_rule)
        self.assertIn("min-width:", provenance_rule)
        self.assertIn("min-height:", provenance_rule)
        self.assertIn("max-width:", provenance_rule)
        self.assertIn("max-height:", provenance_rule)
        self.assertIn("border:", provenance_rule)
        self.assertIn("box-shadow:", provenance_rule)

    def test_composition_root_connects_application_dependencies(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            campaign_path = Path(temp_dir) / "sample.aca"
            collection = SimpleNamespace(path=Path(temp_dir) / "sample.sqlite")
            db = SimpleNamespace(ok=True, last_error="")
            controller_calls = []
            ui_calls = []
            refresh_variable_list = object()
            built_ui = object()
            interaction_log = SimpleNamespace(enabled=False)

            def attach(**kwargs):
                controller_calls.append(kwargs)
                return refresh_variable_list

            def build(server, refresh, campaign_name):
                ui_calls.append((server, refresh, campaign_name))
                return built_ui

            server = get_server(
                f"pulsar-composition-{id(self)}",
                client_type="vue3",
            )
            app = PulsarApp(
                campaign_path,
                image_association_schema_path="~/images.yaml",
                campaign_schema_path="~/campaign.yaml",
                server=server,
                collection=collection,
                db=db,
                interaction_log=interaction_log,
                controller_attacher=attach,
                ui_builder=build,
            )

        self.assertIs(app.server, server)
        self.assertIs(app.collection, collection)
        self.assertIs(app.db, db)
        self.assertIs(app.interaction_log, interaction_log)
        self.assertIsInstance(app.backend, LocalCampaignBackend)
        self.assertIs(app.refresh_variable_list, refresh_variable_list)
        self.assertIs(app.ui, built_ui)
        self.assertEqual(
            server.state.trame__scripts,
            [
                f"{pulsar_module.BASE_URL}/pulsar.js",
                f"{pulsar_module.BASE_URL}/pulsar-media-runtime.js",
                f"{pulsar_module.BASE_URL}/pulsar-plot-runtime.js",
                f"{pulsar_module.BASE_URL}/pulsar-timeline-runtime.js",
                f"{pulsar_module.BASE_URL}/pulsar-grid-runtime.js",
                f"{pulsar_module.BASE_URL}/pulsar-canvas-layout.js",
                f"{pulsar_module.BASE_URL}/pulsar-canvas-runtime.js",
                f"{pulsar_module.BASE_URL}/pulsar-interaction-runtime.js",
                f"{pulsar_module.BASE_URL}/pulsar-resize-runtime.js",
                f"{pulsar_module.BASE_URL}/pulsar-history-runtime.js",
            ],
        )
        self.assertEqual(
            server.state.trame__vue_use,
            [
                "pulsarGridRuntime",
                "pulsarCanvasRuntime",
                "pulsarInteractionRuntime",
                "pulsarResizeRuntime",
                "pulsarHistoryRuntime",
            ],
        )
        self.assertEqual(
            server.state.trame__styles,
            [f"{pulsar_module.BASE_URL}/pulsar.css"],
        )
        self.assertEqual(
            server.serve[pulsar_module.BASE_URL],
            pulsar_module.serve[pulsar_module.BASE_URL],
        )
        self.assertEqual(app.campaign_path, str(campaign_path))
        self.assertEqual(
            app.image_association_schema_path,
            str(Path("~/images.yaml").expanduser()),
        )
        self.assertEqual(
            app.campaign_schema_path,
            str(Path("~/campaign.yaml").expanduser()),
        )
        self.assertIs(controller_calls[0]["server"], server)
        self.assertIs(controller_calls[0]["backend"], app.backend)
        self.assertIs(controller_calls[0]["db"], db)
        self.assertIs(controller_calls[0]["collection"], collection)
        self.assertIs(controller_calls[0]["interaction_log"], interaction_log)
        self.assertEqual(controller_calls[0]["campaign_path"], str(campaign_path))
        self.assertEqual(
            ui_calls,
            [(server, refresh_variable_list, "sample.aca")],
        )

    def test_top_level_app_preserves_public_entry_points(self):
        self.assertIs(compatibility_app.PulsarApp, PulsarApp)
        self.assertIs(compatibility_app.build_parser, build_parser)

        args = build_parser().parse_args(
            [
                "campaign.aca",
                "--image-association-schema",
                "images.yaml",
                "--campaign-schema",
                "campaign.yaml",
            ]
        )
        self.assertEqual(args.campaign_path, "campaign.aca")
        self.assertEqual(args.image_association_schema, "images.yaml")
        self.assertEqual(args.campaign_schema, "campaign.yaml")
        self.assertFalse(args.demo)

        demo_args = build_parser().parse_args(["--demo"])
        self.assertEqual(demo_args.demo, 5)
        self.assertIsNone(demo_args.campaign_path)

        counted_demo_args = build_parser().parse_args(["--demo", "12"])
        self.assertEqual(counted_demo_args.demo, 12)
        self.assertIsNone(counted_demo_args.campaign_path)

        for invalid_count in ("0", "50"):
            with self.subTest(invalid_count=invalid_count), self.assertRaises(
                SystemExit
            ):
                build_parser().parse_args(["--demo", invalid_count])

    def test_demo_cli_launches_generated_campaign_and_closes_sidecar(self):
        generated = SimpleNamespace(
            campaign_path=Path("/tmp/pulsar-demo/synthetic-demo.aca"),
            sidecar_path=Path("/tmp/pulsar-demo/synthetic-demo.sqlite"),
        )

        @contextmanager
        def demo_context(*, config):
            self.assertEqual(config.source_count, 5)
            yield generated

        collection = MagicMock()
        application = MagicMock()
        with patch("pulsar.app.temporary_demo_campaign", side_effect=demo_context), patch(
            "pulsar.app.open_sqlite_collection",
            return_value=collection,
        ) as open_collection, patch(
            "pulsar.app.PulsarApp",
            return_value=application,
        ) as app_class:
            main(["--demo"])

        open_collection.assert_called_once_with(
            str(generated.campaign_path),
            db_path=str(generated.sidecar_path),
        )
        app_class.assert_called_once_with(
            campaign_path=str(generated.campaign_path),
            collection=collection,
        )
        application.server.start.assert_called_once_with()
        collection.close.assert_called_once_with()

    def test_cli_requires_exactly_one_input_mode(self):
        for argv in ([], ["campaign.aca", "--demo"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                main(argv)

        with self.assertRaises(SystemExit):
            main(["--demo", "--campaign-schema", "schema.yaml"])

    def test_ui_is_composed_from_trame_components(self):
        server = get_server(
            f"pulsar-ui-components-{id(self)}",
            client_type="vue3",
        )

        ui = build_ui(server, campaign_name="sample.aca")

        self.assertIsInstance(ui, PulsarUI)
        for component in (
            ui.query_toolbar,
            ui.query_assistant,
            ui.help_dialog,
            ui.workspace_menu,
            ui.variable_panel,
            ui.grid_workspace,
            ui.context_menu,
            ui.grid_workspace.source_dialog,
            ui.grid_workspace.provenance_dialog,
            ui.grid_workspace.scalar_plot_dialog,
            ui.grid_workspace.plot_settings_panel,
            ui.grid_workspace.plugin_options_panel,
            ui.grid_workspace.scalar_field_settings_panel,
            ui.grid_workspace.scalar_field_assistant_panel,
        ):
            self.assertIsInstance(component, TrameComponent)
            self.assertIs(component.server, server)

        self.assertIn("sample.aca", ui.layout.html)
        self.assertNotIn("Campaign loaded:", ui.layout.html)
        self.assertIn("Save As…", ui.layout.html)
        self.assertIn("Current state file", ui.layout.html)
        self.assertIn("New tab", ui.layout.html)
        self.assertNotIn("Pane and tab actions", ui.layout.html)
        self.assertNotIn("pulsar-workspace-pane-menu-button", ui.layout.html)
        self.assertIn("Split right", ui.layout.html)
        self.assertIn("Split down", ui.layout.html)
        self.assertIn("pulsar-workspace-tab-bar", ui.layout.html)
        self.assertIn("pulsar-workspace-tab-dock-preview", ui.layout.html)
        self.assertIn("pulsar-workspace-grid-preview", ui.layout.html)
        self.assertNotIn('id="pulsar-workspace-state-file"', ui.layout.html)
        self.assertIn('id="pulsar-variable-column"', ui.layout.html)
        self.assertIn("Search variables", ui.layout.html)
        self.assertIn("variableSearchText", ui.layout.html)
        self.assertIsInstance(ui.query_assistant, QueryAssistantDialog)
        self.assertIn('id="pulsar-query-assistant-panel"', ui.layout.html)
        self.assertIn("pulsar-query-assistant-panel", ui.layout.html)
        self.assertIn("pulsar-ai-assistant-panel", ui.layout.html)
        self.assertIn("pulsar-floating-panel-drag-handle", ui.layout.html)
        self.assertIn("Query Assistant", ui.layout.html)
        self.assertIn("Source Filter Assistant", ui.layout.html)
        self.assertIn("Visualization Assistant", ui.layout.html)
        self.assertIn("Natural language + Ask", ui.layout.html)
        self.assertIn("Apply to Source Filter", ui.layout.html)
        self.assertIn("Add to Grid", ui.layout.html)
        self.assertIn("queryAssistantRequestText", ui.layout.html)
        self.assertIn("queryAssistantProposalText", ui.layout.html)
        self.assertIn("queryAssistantProposalSummary", ui.layout.html)
        self.assertIn("Resolved Advanced Query", ui.layout.html)
        self.assertIn("Translate natural language into a query", ui.layout.html)
        self.assertIn("Add a variable to the active grid cell", ui.layout.html)
        self.assertIn('id="pulsar-context-menu"', ui.layout.html)
        self.assertIn("scalarFieldSettingsBackground", ui.layout.html)
        self.assertIn("scalarFieldSettingsShowHeatmap", ui.layout.html)
        self.assertIn("scalarFieldSettingsShowContours", ui.layout.html)
        self.assertIn("scalarFieldSettingsContourLevelMode", ui.layout.html)
        self.assertIn("scalarFieldSettingsContourValues", ui.layout.html)
        self.assertIn("scalarFieldSettingsContourCount", ui.layout.html)
        self.assertIn("scalarFieldSettingsContourColor", ui.layout.html)
        self.assertIn("scalarFieldAssistantRequestText", ui.layout.html)
        self.assertIn("pulsar-scalar-field-ai-btn", ui.layout.html)
        self.assertIn("tile.media_type === 'plot1d'", ui.layout.html)
        self.assertIn('id="pulsar-plot-options-assistant-panel"', ui.layout.html)
        self.assertIn("pulsar-plot-options-assistant-panel", ui.layout.html)
        self.assertIn("Plot Options Assistant", ui.layout.html)
        self.assertIn("Min/Max", ui.layout.html)
        self.assertIn("Provenance", ui.layout.html)
        self.assertIn("detailsProvenanceChain", ui.layout.html)
        self.assertIn("detailsProvenanceCompact", ui.layout.html)
        self.assertIn("detailsProvenanceGraph", ui.layout.html)
        self.assertIn("pulsar-provenance-detail-btn", ui.layout.html)
        self.assertIn("pulsar-provenance-detail-table-block", ui.layout.html)
        self.assertIn("pulsar-provenance-input-table", ui.layout.html)
        self.assertIn("input.variable", ui.layout.html)
        self.assertIn("input.role", ui.layout.html)
        self.assertIn("pulsar-provenance-branch-section", ui.layout.html)
        self.assertIn("segment.type === 'activity_context'", ui.layout.html)
        self.assertIn("pulsar-provenance-activity-context-row", ui.layout.html)
        self.assertIn("context.relation", ui.layout.html)
        self.assertIn("segment.type === 'plan_group'", ui.layout.html)
        self.assertIn("pulsar-provenance-plan-group", ui.layout.html)
        self.assertIn("segment.selected_action.node", ui.layout.html)
        self.assertNotIn("Other actions in this plan", ui.layout.html)
        self.assertIn("pulsar-provenance-resize-handle", ui.layout.html)
        self.assertIn("Resize provenance viewer", ui.layout.html)
        self.assertIn("Workflow Plan", ui.layout.html)
        self.assertIn("Agent", ui.layout.html)
        self.assertIn("Provenance Viewer", ui.layout.html)
        self.assertIn("showProvenanceModal", ui.layout.html)
        self.assertIn("pulsar-provenance-graph", ui.layout.html)
        self.assertIn('id="pulsar-provenance-panel"', ui.layout.html)
        self.assertIn("pulsar-provenance-dialog-content", ui.layout.html)
        self.assertIn("pulsar-provenance-dialog", ui.layout.html)
        self.assertNotIn("detailsProvenanceRows", ui.layout.html)
        self.assertIn("detailsGlobalMin", ui.layout.html)
        self.assertNotIn('id="pulsar-representation-details"', ui.layout.html)
        self.assertNotIn("detailsDerivedRepresentations", ui.layout.html)
        self.assertIsInstance(ui.grid_workspace.runtime, GridRuntime)
        self.assertIn("pulsar-grid-runtime", ui.layout.html)
        self.assertIsInstance(ui.interaction_runtime, InteractionRuntime)
        self.assertIsInstance(ui.canvas_runtime, CanvasRuntime)
        self.assertIn("pulsar-canvas-runtime", ui.layout.html)
        self.assertIn("pulsar-interaction-runtime", ui.layout.html)
        self.assertIsInstance(ui.resize_runtime, ResizeRuntime)
        self.assertIn("pulsar-resize-runtime", ui.layout.html)


if __name__ == "__main__":
    unittest.main()
