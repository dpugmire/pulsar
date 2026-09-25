import unittest
from copy import deepcopy
import math
from types import SimpleNamespace

from pulsar.history import WorkspaceMutationCoordinator


class WorkspaceMutationCoordinatorTests(unittest.TestCase):
    def make_history(self, value=0, **kwargs):
        state = SimpleNamespace(value=value)

        def capture():
            return {
                "workspace": {
                    "active_pane_id": "pane-1",
                    "active_tab_id": "tab-1",
                    "value": state.value,
                }
            }

        def restore(snapshot):
            state.value = deepcopy(snapshot)["workspace"]["value"]

        return state, WorkspaceMutationCoordinator(
            state, capture, restore, **kwargs
        )

    def test_transaction_undo_redo_and_labels(self):
        state, history = self.make_history()

        with history.transaction("Move plot"):
            state.value = 7

        self.assertEqual(state.value, 7)
        self.assertTrue(state.workspaceCanUndo)
        self.assertEqual(state.workspaceUndoLabel, "Move plot")
        self.assertTrue(history.undo())
        self.assertEqual(state.value, 0)
        self.assertTrue(state.workspaceCanRedo)
        self.assertEqual(state.workspaceRedoLabel, "Move plot")
        self.assertTrue(history.redo())
        self.assertEqual(state.value, 7)

    def test_nested_transactions_coalesce_and_no_op_is_ignored(self):
        state, history = self.make_history()

        with history.transaction("Outer edit"):
            state.value = 1
            with history.transaction("Inner edit"):
                state.value = 2
        with history.transaction("No change"):
            state.value = 2

        self.assertEqual(len(history.undo_entries), 1)
        self.assertEqual(history.undo_entries[0].label, "Outer edit")
        history.undo()
        self.assertEqual(state.value, 0)

    def test_new_edit_invalidates_redo(self):
        state, history = self.make_history()
        with history.transaction("First"):
            state.value = 1
        history.undo()
        self.assertTrue(state.workspaceCanRedo)

        with history.transaction("Replacement"):
            state.value = 3

        self.assertFalse(state.workspaceCanRedo)
        self.assertEqual(history.undo_entries[-1].label, "Replacement")

    def test_non_finite_snapshot_values_do_not_break_history(self):
        state = SimpleNamespace(value=0, imported_limit=float("nan"))

        def capture():
            return {
                "workspace": {
                    "value": state.value,
                    "imported_limit": state.imported_limit,
                }
            }

        def restore(snapshot):
            state.value = snapshot["workspace"]["value"]
            state.imported_limit = snapshot["workspace"]["imported_limit"]

        history = WorkspaceMutationCoordinator(state, capture, restore)
        with history.transaction("Edit imported plot"):
            state.value = 1

        self.assertEqual(len(history.undo_entries), 1)
        self.assertTrue(history.undo())
        self.assertEqual(state.value, 0)
        self.assertTrue(math.isnan(state.imported_limit))

    def test_exception_rolls_back_without_recording(self):
        state, history = self.make_history()

        with self.assertRaisesRegex(RuntimeError, "broken"):
            with history.transaction("Broken edit"):
                state.value = 9
                raise RuntimeError("broken")

        self.assertEqual(state.value, 0)
        self.assertFalse(state.workspaceCanUndo)
        self.assertIn("rolled back", state.workspaceHistoryError)

    def test_validation_failure_rolls_back_without_recording(self):
        state = SimpleNamespace(value=0)

        def capture():
            return {"workspace": {"value": state.value}}

        def restore(snapshot):
            state.value = snapshot["workspace"]["value"]

        def validate():
            if state.value == 9:
                raise ValueError("invalid state")

        history = WorkspaceMutationCoordinator(
            state, capture, restore, validate=validate
        )
        with self.assertRaisesRegex(ValueError, "invalid state"):
            with history.transaction("Invalid edit"):
                state.value = 9

        self.assertEqual(state.value, 0)
        self.assertFalse(state.workspaceCanUndo)
        self.assertIn("rolled back", state.workspaceHistoryError)

    def test_depth_and_memory_limits_evict_oldest_entries(self):
        state, history = self.make_history(max_entries=2, max_bytes=100_000)
        for value in (1, 2, 3):
            with history.transaction(f"Set {value}"):
                state.value = value

        self.assertEqual(
            [entry.label for entry in history.undo_entries],
            ["Set 2", "Set 3"],
        )
        history.undo()
        history.undo()
        self.assertEqual(state.value, 1)
        self.assertFalse(history.undo())

    def test_failed_undo_preserves_state_and_stacks(self):
        state = SimpleNamespace(value=0)
        fail_restore = {"enabled": False}

        def capture():
            return {"workspace": {"value": state.value}}

        def restore(snapshot):
            value = snapshot["workspace"]["value"]
            if fail_restore["enabled"] and value == 0:
                raise ValueError("invalid snapshot")
            state.value = value

        history = WorkspaceMutationCoordinator(state, capture, restore)
        with history.transaction("Edit"):
            state.value = 1
        fail_restore["enabled"] = True

        self.assertFalse(history.undo())
        self.assertEqual(state.value, 1)
        self.assertEqual(len(history.undo_entries), 1)
        self.assertEqual(len(history.redo_entries), 0)
        self.assertIn("Undo failed", state.workspaceHistoryError)


if __name__ == "__main__":
    unittest.main()
