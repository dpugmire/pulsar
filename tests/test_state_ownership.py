import unittest
from types import SimpleNamespace

import state_init as compatibility_state
from seurat.state import STATE_SECTIONS, clear_right_panes, init_state


class StateOwnershipTests(unittest.TestCase):
    def test_sections_have_explicit_non_overlapping_ownership(self):
        owner_by_key = {}
        for section_name, defaults in STATE_SECTIONS:
            for key in defaults():
                self.assertNotIn(
                    key,
                    owner_by_key,
                    f"{key} is owned by both {owner_by_key.get(key)} and {section_name}",
                )
                owner_by_key[key] = section_name

        state = SimpleNamespace()
        init_state(state, SimpleNamespace(ok=True, last_error=""))

        self.assertEqual(len(vars(state)), 230)
        self.assertEqual(state.gridLayoutMode, "uniform")
        self.assertEqual(set(vars(state)) - {"dbOk", "dbStatus"}, set(owner_by_key))

    def test_each_initialization_gets_fresh_mutable_values(self):
        first = SimpleNamespace()
        second = SimpleNamespace()
        db = SimpleNamespace(ok=True, last_error="")
        init_state(first, db)
        init_state(second, db)

        first.variableGroups.append({"name": "changed"})
        first.gridCells[0]["variable_id"] = "changed"
        first.plotSettingsStandardColors.append("#123456")
        first.detailsProvenanceExpanded["variable"] = True
        first.detailsProvenanceGraph.append({"type": "changed"})

        self.assertEqual(second.variableGroups, [])
        self.assertEqual(second.gridCells[0]["variable_id"], "")
        self.assertNotIn("#123456", second.plotSettingsStandardColors)
        self.assertEqual(second.detailsProvenanceExpanded, {})
        self.assertEqual(second.detailsProvenanceGraph, [])

    def test_compatibility_module_exports_package_state_api(self):
        self.assertIs(compatibility_state.init_state, init_state)
        self.assertIs(compatibility_state.clear_right_panes, clear_right_panes)

    def test_right_pane_reset_preserves_grid_and_session_preferences(self):
        state = SimpleNamespace()
        init_state(state, SimpleNamespace(ok=True, last_error=""))
        state.gridCells[0]["variable_id"] = "density"
        state.scalarPlotPolicy = "never"
        state.showSourcesModal = True
        state.showPlotSettingsModal = True
        state.contextMenuVisible = True

        clear_right_panes(state)

        self.assertEqual(state.gridCells[0]["variable_id"], "density")
        self.assertEqual(state.scalarPlotPolicy, "never")
        self.assertFalse(state.showSourcesModal)
        self.assertFalse(state.showPlotSettingsModal)
        self.assertFalse(state.contextMenuVisible)


if __name__ == "__main__":
    unittest.main()
