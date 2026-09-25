import inspect
import unittest

import controllers as compatibility_controllers
from seurat.controllers import ControllerContext, SeuratController, attach_controllers
from seurat.controllers.composer import CONTROLLER_TYPES


NON_HISTORICAL_ACTIONS = {
    "activate_workspace_tab",
    "adjust_canvas_default_tile_width",
    "adjust_canvas_zoom",
    "apply_source_dialog_filter",
    "cancel_plot_settings",
    "cancel_plugin_options",
    "cancel_scalar_field_settings",
    "cancel_scalar_field_options_assistant",
    "cancel_scalar_plot_generation",
    "cancel_source_dialog",
    "clear_all_sources",
    "clear_query",
    "clear_source_filter",
    "close_help_modal",
    "close_provenance_dialog",
    "close_query_assistant",
    "context_menu_cell_add_source",
    "context_menu_cell_plot_settings",
    "context_menu_cell_reset_view",
    "context_menu_cell_scalar_field_settings",
    "context_menu_cell_sources",
    "context_menu_item_select",
    "hide_context_menu",
    "load_workspace_state",
    "open_plot_settings_plugin_options",
    "open_provenance_dialog",
    "open_query_assistant",
    "open_scalar_field_options_assistant",
    "open_source_query_assistant",
    "open_visualization_assistant",
    "pick_tile_visualization",
    "pick_var",
    "redo_workspace",
    "reset_plot_settings",
    "reset_plugin_options",
    "reset_scalar_field_settings",
    "run_query",
    "save_workspace_state",
    "save_workspace_state_as",
    "select_all_sources",
    "select_var",
    "set_active_axis_selection",
    "set_canvas_fit_to_view",
    "set_canvas_nudge_others",
    "set_canvas_show_grid",
    "set_canvas_snap_to_grid",
    "set_dragged_var",
    "show_query_help",
    "show_source_filter_help",
    "sort_sources",
    "source_dialog_select",
    "toggle_add_source",
    "toggle_movie_details",
    "toggle_provenance_node_details",
    "toggle_scalar_field_background",
    "toggle_sources",
    "toggle_variable_group",
    "translate_query_request",
    "translate_scalar_field_options_request",
    "undo_workspace",
    "update_plot_background_color",
    "update_plot_cursor_color",
    "update_plot_grid_color",
    "update_plot_series_color",
    "update_plot_series_line_style",
    "update_plugin_option_value",
    "update_scalar_field_contour_color",
    "validate_query_proposal",
}

NON_HISTORICAL_TRIGGERS = {
    "hide_context_menu_trigger",
    "redo_workspace_trigger",
    "show_cell_context_menu",
    "show_item_context_menu",
    "show_tab_context_menu",
    "sync_canvas_fit_zoom_trigger",
    "undo_workspace_trigger",
}


class ControllerOwnershipTests(unittest.TestCase):
    def test_domain_bindings_are_unique_and_owned_by_the_declaring_controller(self):
        expected_counts = {
            "ACTION_BINDINGS": 118,
            "TRIGGER_BINDINGS": 20,
            "STATE_CHANGE_BINDINGS": 4,
        }

        for attribute, expected_count in expected_counts.items():
            names = []
            for controller_type in CONTROLLER_TYPES:
                for binding_name, method_name in getattr(controller_type, attribute):
                    names.append(binding_name)
                    self.assertIn(method_name, controller_type.__dict__)
                    self.assertTrue(callable(getattr(SeuratController, method_name)))

            self.assertEqual(len(names), expected_count)
            self.assertEqual(len(names), len(set(names)))

    def test_history_declarations_reference_registered_mutations(self):
        for controller_type in CONTROLLER_TYPES:
            action_names = {
                name for name, _method in controller_type.ACTION_BINDINGS
            }
            trigger_names = {
                name for name, _method in controller_type.TRIGGER_BINDINGS
            }
            history_actions = getattr(controller_type, "HISTORY_ACTIONS", {})
            history_triggers = getattr(controller_type, "HISTORY_TRIGGERS", {})

            self.assertTrue(set(history_actions).issubset(action_names))
            self.assertTrue(set(history_triggers).issubset(trigger_names))
            self.assertTrue(all(str(label).strip() for label in history_actions.values()))
            self.assertTrue(all(str(label).strip() for label in history_triggers.values()))
            for name in (*history_actions, *history_triggers):
                method_name = dict(
                    (*controller_type.ACTION_BINDINGS, *controller_type.TRIGGER_BINDINGS)
                )[name]
                self.assertFalse(
                    inspect.iscoroutinefunction(getattr(SeuratController, method_name)),
                    name,
                )

    def test_every_controller_binding_has_an_explicit_history_classification(self):
        actions = {
            name
            for controller_type in CONTROLLER_TYPES
            for name, _method in controller_type.ACTION_BINDINGS
        }
        triggers = {
            name
            for controller_type in CONTROLLER_TYPES
            for name, _method in controller_type.TRIGGER_BINDINGS
        }
        historical_actions = {
            name
            for controller_type in CONTROLLER_TYPES
            for name in getattr(controller_type, "HISTORY_ACTIONS", {})
        }
        historical_triggers = {
            name
            for controller_type in CONTROLLER_TYPES
            for name in getattr(controller_type, "HISTORY_TRIGGERS", {})
        }

        self.assertFalse(historical_actions & NON_HISTORICAL_ACTIONS)
        self.assertFalse(historical_triggers & NON_HISTORICAL_TRIGGERS)
        self.assertEqual(actions, historical_actions | NON_HISTORICAL_ACTIONS)
        self.assertEqual(triggers, historical_triggers | NON_HISTORICAL_TRIGGERS)

    def test_top_level_controller_module_is_a_compatibility_facade(self):
        self.assertIs(compatibility_controllers.ControllerContext, ControllerContext)
        self.assertIs(compatibility_controllers.SeuratController, SeuratController)
        self.assertIs(compatibility_controllers.attach_controllers, attach_controllers)


if __name__ == "__main__":
    unittest.main()
