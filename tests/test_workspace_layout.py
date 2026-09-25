import unittest
from types import SimpleNamespace

from pulsar.models.workspace_layout import (
    MAX_SPLIT_RATIO,
    MAX_WORKSPACE_PANES,
    MIN_SPLIT_RATIO,
    active_pane_and_tab,
    add_workspace_tab,
    apply_grid_snapshot,
    close_workspace_pane,
    close_workspace_tab,
    grid_snapshot,
    initial_workspace_layout,
    move_workspace_grid_cell,
    move_workspace_tab,
    move_workspace_tab_to_pane,
    reorder_workspace_tab,
    resize_workspace_split,
    split_workspace,
    split_workspace_tab,
    workspace_geometry,
    workspace_pane_ids,
)
from pulsar.models.grid import empty_grid_cell
from pulsar.state import init_state


class WorkspaceLayoutTests(unittest.TestCase):
    def make_state(self):
        state = SimpleNamespace()
        init_state(state, SimpleNamespace(ok=True, last_error=""))
        return state

    def test_grid_snapshot_round_trip_copies_mutable_values(self):
        state = self.make_state()
        state.gridCells[0]["variable_id"] = "density"

        snapshot = grid_snapshot(state)
        state.gridCells[0]["variable_id"] = "temperature"
        apply_grid_snapshot(state, snapshot)

        self.assertEqual(state.gridCells[0]["variable_id"], "density")
        self.assertIsNot(state.gridCells, snapshot["cells"])

    def test_new_tabs_start_empty_in_default_uniform_mode(self):
        state = self.make_state()
        state.gridRows = 2
        state.gridCols = 2
        state.gridCells = state.gridCells[:4]
        state.gridCells[0]["variable_id"] = "density"
        layout = initial_workspace_layout(grid_snapshot(state))

        layout, tab_id = add_workspace_tab(layout, "pane-1", grid_snapshot(state))
        pane, tab = active_pane_and_tab(layout)

        self.assertEqual(tab_id, "tab-2")
        self.assertEqual(pane["active_tab_id"], tab_id)
        self.assertEqual((tab["grid"]["rows"], tab["grid"]["columns"]), (2, 2))
        self.assertEqual(tab["grid"]["layout_mode"], "uniform")
        self.assertEqual(len(tab["grid"]["cells"]), 4)
        self.assertTrue(
            all(cell["status"] == "empty" for cell in tab["grid"]["cells"])
        )

    def test_workspace_splits_active_panes_into_at_most_four_leaves(self):
        state = self.make_state()
        snapshot = grid_snapshot(state)
        layout = initial_workspace_layout(snapshot)

        layout, pane_id = split_workspace(layout, "vertical", snapshot)
        layout, third_pane_id = split_workspace(layout, "horizontal", snapshot)
        layout, fourth_pane_id = split_workspace(layout, "vertical", snapshot)
        layout, extra_pane_id = split_workspace(layout, "horizontal", snapshot)

        self.assertEqual(pane_id, "pane-2")
        self.assertEqual(third_pane_id, "pane-3")
        self.assertEqual(fourth_pane_id, "pane-4")
        self.assertIsNone(extra_pane_id)
        self.assertEqual(len(layout["panes"]), MAX_WORKSPACE_PANES)
        self.assertEqual(workspace_pane_ids(layout), tuple(
            f"pane-{index}" for index in range(1, 5)
        ))
        self.assertEqual(layout["split_direction"], "vertical")

    def test_workspace_can_split_a_specific_existing_pane(self):
        state = self.make_state()
        snapshot = grid_snapshot(state)
        layout = initial_workspace_layout(snapshot)
        layout, _ = split_workspace(layout, "horizontal", snapshot)

        layout, new_pane_id = split_workspace(
            layout, "vertical", snapshot, pane_id="pane-1"
        )

        self.assertEqual(new_pane_id, "pane-3")
        self.assertEqual(
            workspace_pane_ids(layout), ("pane-1", "pane-3", "pane-2")
        )
        frames, splitters = workspace_geometry(layout)
        self.assertEqual(set(frames), {"pane-1", "pane-2", "pane-3"})
        self.assertEqual(len(splitters), 2)
        self.assertAlmostEqual(frames["pane-1"]["height"], 50.0)
        self.assertAlmostEqual(frames["pane-3"]["top"], 50.0)

    def test_workspace_tab_can_split_right_without_losing_its_grid(self):
        state = self.make_state()
        snapshot = grid_snapshot(state)
        layout = initial_workspace_layout(snapshot)
        layout, second_tab_id = add_workspace_tab(layout, "pane-1", snapshot)
        _pane, second_tab = active_pane_and_tab(layout)
        second_tab["grid"]["cells"] = [{"variable_id": "pressure"}]

        layout, new_pane_id = split_workspace_tab(
            layout,
            "horizontal",
            snapshot,
            "pane-1",
            second_tab_id,
            "pane-1",
        )

        self.assertEqual(new_pane_id, "pane-2")
        self.assertEqual(workspace_pane_ids(layout), ("pane-1", "pane-2"))
        self.assertEqual(
            [tab["id"] for tab in layout["panes"][0]["tabs"]], ["tab-1"]
        )
        self.assertEqual(layout["panes"][1]["tabs"][0]["id"], second_tab_id)
        self.assertEqual(
            layout["panes"][1]["tabs"][0]["grid"]["cells"][0]["variable_id"],
            "pressure",
        )
        self.assertEqual(layout["root"]["direction"], "horizontal")
        self.assertEqual(layout["active_pane_id"], "pane-2")
        self.assertEqual(layout["active_tab_id"], second_tab_id)

    def test_splitting_a_panes_only_tab_leaves_an_empty_tab_behind(self):
        state = self.make_state()
        state.gridCells[0]["variable_id"] = "density"
        snapshot = grid_snapshot(state)
        layout = initial_workspace_layout(snapshot)

        layout, new_pane_id = split_workspace_tab(
            layout,
            "vertical",
            snapshot,
            "pane-1",
            "tab-1",
            "pane-1",
        )

        self.assertEqual(new_pane_id, "pane-2")
        self.assertEqual(layout["root"]["direction"], "vertical")
        self.assertEqual(layout["panes"][0]["tabs"][0]["id"], "tab-2")
        replacement_grid = layout["panes"][0]["tabs"][0]["grid"]
        self.assertEqual(replacement_grid["layout_mode"], "uniform")
        self.assertEqual(len(replacement_grid["cells"]), 9)
        self.assertTrue(
            all(cell["status"] == "empty" for cell in replacement_grid["cells"])
        )
        self.assertEqual(layout["panes"][1]["tabs"][0]["id"], "tab-1")
        self.assertEqual(
            layout["panes"][1]["tabs"][0]["grid"]["cells"][0]["variable_id"],
            "density",
        )

    def test_workspace_tab_split_targets_a_nested_pane_and_obeys_limit(self):
        state = self.make_state()
        snapshot = grid_snapshot(state)
        layout = initial_workspace_layout(snapshot)
        layout, moved_tab_id = add_workspace_tab(layout, "pane-1", snapshot)
        layout, _ = split_workspace(layout, "horizontal", snapshot, "pane-1")

        layout, new_pane_id = split_workspace_tab(
            layout,
            "vertical",
            snapshot,
            "pane-1",
            moved_tab_id,
            "pane-2",
        )

        self.assertEqual(new_pane_id, "pane-3")
        self.assertEqual(workspace_pane_ids(layout), ("pane-1", "pane-2", "pane-3"))
        self.assertEqual(layout["root"]["second"]["direction"], "vertical")

        layout, _ = split_workspace(layout, "horizontal", snapshot, "pane-1")
        unchanged, extra_pane_id = split_workspace_tab(
            layout,
            "horizontal",
            snapshot,
            "pane-1",
            "tab-1",
            "pane-1",
        )
        self.assertIsNone(extra_pane_id)
        self.assertEqual(unchanged, layout)

    def test_split_ratios_are_resized_and_clamped(self):
        state = self.make_state()
        snapshot = grid_snapshot(state)
        layout = initial_workspace_layout(snapshot)
        layout, _ = split_workspace(layout, "horizontal", snapshot)

        layout = resize_workspace_split(layout, "split-1", 0.7)
        frames, splitters = workspace_geometry(layout)

        self.assertAlmostEqual(layout["root"]["ratio"], 0.7)
        self.assertAlmostEqual(frames["pane-1"]["width"], 70.0)
        self.assertAlmostEqual(splitters[0]["left"], 70.0)
        self.assertEqual(
            resize_workspace_split(layout, "split-1", 0)["root"]["ratio"],
            MIN_SPLIT_RATIO,
        )
        self.assertEqual(
            resize_workspace_split(layout, "split-1", 1)["root"]["ratio"],
            MAX_SPLIT_RATIO,
        )

    def test_tabs_move_between_panes_without_losing_their_grid(self):
        state = self.make_state()
        snapshot = grid_snapshot(state)
        layout = initial_workspace_layout(snapshot)
        layout, moved_tab_id = add_workspace_tab(layout, "pane-1", snapshot)
        _, moved_tab = active_pane_and_tab(layout)
        moved_tab["grid"]["cells"] = [{"variable_id": "pressure"}]
        layout, _ = split_workspace(layout, "horizontal", snapshot)

        layout = move_workspace_tab(layout, "pane-1", moved_tab_id)
        pane, tab = active_pane_and_tab(layout)

        self.assertEqual(pane["id"], "pane-2")
        self.assertEqual(tab["id"], moved_tab_id)
        self.assertEqual(tab["grid"]["cells"][0]["variable_id"], "pressure")

    def test_tabs_move_to_a_specific_pane_insertion_slot(self):
        state = self.make_state()
        snapshot = grid_snapshot(state)
        layout = initial_workspace_layout(snapshot)
        layout, moved_tab_id = add_workspace_tab(layout, "pane-1", snapshot)
        _, moved_tab = active_pane_and_tab(layout)
        moved_tab["grid"]["cells"] = [{"variable_id": "pressure"}]
        layout, _ = split_workspace(layout, "horizontal", snapshot)

        layout = move_workspace_tab_to_pane(
            layout, "pane-1", moved_tab_id, "pane-2", 0
        )

        first_pane = next(
            pane for pane in layout["panes"] if pane["id"] == "pane-1"
        )
        second_pane = next(
            pane for pane in layout["panes"] if pane["id"] == "pane-2"
        )
        self.assertEqual([tab["id"] for tab in first_pane["tabs"]], ["tab-1"])
        self.assertEqual(
            [tab["id"] for tab in second_pane["tabs"]],
            [moved_tab_id, "tab-3"],
        )
        self.assertEqual(
            second_pane["tabs"][0]["grid"]["cells"][0]["variable_id"],
            "pressure",
        )
        self.assertEqual(layout["active_pane_id"], "pane-2")
        self.assertEqual(layout["active_tab_id"], moved_tab_id)

    def test_moving_a_panes_last_tab_collapses_the_empty_pane(self):
        state = self.make_state()
        snapshot = grid_snapshot(state)
        layout = initial_workspace_layout(snapshot)
        layout, _ = split_workspace(layout, "horizontal", snapshot)

        layout = move_workspace_tab_to_pane(
            layout, "pane-1", "tab-1", "pane-2", 1
        )

        self.assertEqual(workspace_pane_ids(layout), ("pane-2",))
        self.assertEqual(layout["root"], {"kind": "pane", "pane_id": "pane-2"})
        self.assertEqual(
            [tab["id"] for tab in layout["panes"][0]["tabs"]],
            ["tab-2", "tab-1"],
        )
        self.assertEqual(layout["active_pane_id"], "pane-2")
        self.assertEqual(layout["active_tab_id"], "tab-1")

    def test_visualizations_move_between_tab_grids_and_update_ownership(self):
        state = self.make_state()
        state.gridLayoutMode = "uniform"
        state.gridCells[0].update(
            {
                "variable_id": "pressure",
                "variable_name": "pressure",
                "status": "ready",
            }
        )
        state.activeGridCell = 0
        state.selectedGridCellIndices = [0, 1]
        state.selectedGridCellMap = {"0": True, "1": True}
        state.timelineDriverCell = 0
        snapshot = grid_snapshot(state)
        layout = initial_workspace_layout(snapshot)
        layout, _ = split_workspace(layout, "horizontal", snapshot)
        destination_grid = layout["panes"][1]["tabs"][0]["grid"]
        destination_grid["layout_mode"] = "uniform"
        destination_grid["cells"] = [empty_grid_cell() for _ in range(9)]
        destination_grid["cells"][4].update(
            {
                "variable_id": "temperature",
                "variable_name": "temperature",
                "status": "ready",
            }
        )
        destination_grid["timeline_driver_cell"] = 4

        layout = move_workspace_grid_cell(
            layout,
            "pane-1",
            "tab-1",
            0,
            "pane-2",
            "tab-2",
            4,
        )

        source_grid = layout["panes"][0]["tabs"][0]["grid"]
        destination_grid = layout["panes"][1]["tabs"][0]["grid"]
        self.assertEqual(source_grid["cells"][0]["variable_id"], "")
        self.assertEqual(source_grid["active_cell"], -1)
        self.assertEqual(source_grid["selected_cells"], [1])
        self.assertEqual(source_grid["selected_cell_map"], {"1": True})
        self.assertEqual(source_grid["timeline_driver_cell"], -1)
        self.assertEqual(
            destination_grid["cells"][4]["variable_id"], "pressure"
        )
        self.assertEqual(destination_grid["active_cell"], 4)
        self.assertEqual(destination_grid["selected_cells"], [4])
        self.assertEqual(destination_grid["selected_cell_map"], {"4": True})
        self.assertEqual(destination_grid["timeline_driver_cell"], -1)
        self.assertEqual(layout["active_pane_id"], "pane-2")
        self.assertEqual(layout["active_tab_id"], "tab-2")

    def test_tabs_reorder_within_a_pane_without_losing_state(self):
        state = self.make_state()
        snapshot = grid_snapshot(state)
        layout = initial_workspace_layout(snapshot)
        layout, _ = add_workspace_tab(layout, "pane-1", snapshot)
        layout, active_tab_id = add_workspace_tab(layout, "pane-1", snapshot)
        for index, tab in enumerate(layout["panes"][0]["tabs"]):
            tab["grid"]["cells"] = [
                {"variable_id": f"variable-{index + 1}"}
            ]

        layout = reorder_workspace_tab(layout, "pane-1", "tab-1", 3)

        tabs = layout["panes"][0]["tabs"]
        self.assertEqual([tab["id"] for tab in tabs], ["tab-2", "tab-3", "tab-1"])
        self.assertEqual(
            [tab["grid"]["cells"][0]["variable_id"] for tab in tabs],
            ["variable-2", "variable-3", "variable-1"],
        )
        self.assertEqual(layout["active_tab_id"], active_tab_id)
        self.assertEqual(layout["panes"][0]["active_tab_id"], active_tab_id)

    def test_closing_a_pane_merges_its_tabs_into_the_remaining_pane(self):
        state = self.make_state()
        snapshot = grid_snapshot(state)
        layout = initial_workspace_layout(snapshot)
        layout, _ = split_workspace(layout, "horizontal", snapshot)

        layout = close_workspace_pane(layout, "pane-2")

        self.assertEqual(len(layout["panes"]), 1)
        self.assertEqual(len(layout["panes"][0]["tabs"]), 2)
        self.assertEqual(layout["split_direction"], "none")

    def test_closing_nested_pane_promotes_its_sibling_subtree(self):
        state = self.make_state()
        snapshot = grid_snapshot(state)
        layout = initial_workspace_layout(snapshot)
        layout, _ = split_workspace(layout, "horizontal", snapshot)
        layout, _ = split_workspace(
            layout, "vertical", snapshot, pane_id="pane-1"
        )

        layout = close_workspace_pane(layout, "pane-1")

        self.assertEqual(workspace_pane_ids(layout), ("pane-3", "pane-2"))
        self.assertEqual(len(layout["panes"]), 2)
        self.assertEqual(layout["root"]["direction"], "horizontal")
        pane_three = next(
            pane for pane in layout["panes"] if pane["id"] == "pane-3"
        )
        self.assertEqual(len(pane_three["tabs"]), 2)

    def test_at_least_one_tab_is_always_retained(self):
        state = self.make_state()
        snapshot = grid_snapshot(state)
        layout = initial_workspace_layout(snapshot)

        unchanged = close_workspace_tab(layout, "pane-1", "tab-1")

        self.assertEqual(unchanged, layout)


if __name__ == "__main__":
    unittest.main()
