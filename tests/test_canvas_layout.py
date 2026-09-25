import unittest
import json
from pathlib import Path

from pulsar.models.canvas_layout import (
    apply_column_insertion,
    column_insertion_size,
    connected_column_move_set,
    fit_rectangle,
    geometry,
    horizontal_resize_push,
    insertion_zone,
    nearest_free,
    normalize_columns,
    normalize_drop_width,
    normalize_zoom,
    scale_layout_columns,
    sticky_snap,
    validate_layout,
    vertical_push,
)


def tile(tile_id, x, y, w, h, kind="plot"):
    return geometry(tile_id, kind, x, y, w, h)


class CanvasLayoutTests(unittest.TestCase):
    def test_shared_browser_conformance_fixtures_match_python(self):
        fixture_path = (
            Path(__file__).with_name("fixtures")
            / "canvas_layout_conformance.json"
        )
        cases = json.loads(fixture_path.read_text(encoding="utf-8"))["cases"]

        for case in cases:
            operation = case["operation"]
            arguments = case["arguments"]
            if operation == "horizontal_resize_push":
                result = horizontal_resize_push(
                    case["items"],
                    arguments["priority_id"],
                    original_right=arguments["original_right"],
                    columns=arguments["columns"],
                )
            elif operation == "insertion_zone":
                result = insertion_zone(
                    case["items"],
                    arguments["dragged_id"],
                    arguments["pointer_x"],
                    arguments["pointer_y"],
                    x_tolerance=arguments["x_tolerance"],
                    y_tolerance=arguments["y_tolerance"],
                )
            elif operation == "apply_column_insertion":
                result = apply_column_insertion(
                    case["items"],
                    dragged_id=arguments["dragged_id"],
                    seam=arguments["seam"],
                    anchor_y=arguments["anchor_y"],
                    move_ids=arguments["move_ids"],
                    width=arguments["width"],
                    height=arguments["height"],
                    mode=arguments["mode"],
                    columns=arguments["columns"],
                )
            else:
                self.fail(f"Unknown conformance operation: {operation}")
            self.assertEqual(result, case["expected"], case["name"])
    def test_geometry_clamps_to_canvas_and_minimum_size(self):
        item = geometry("plot-1", "plot", 23, -2, 1, 1)

        self.assertEqual(item, {
            "tile_id": "plot-1",
            "tile_type": "plot",
            "x": 22,
            "y": 0,
            "w": 2,
            "h": 3,
        })

    def test_fractional_geometry_is_preserved_when_snap_is_off(self):
        item = geometry("plot-1", "plot", 2.125, 3.75, 5.5, 4.25, snap=False)

        self.assertEqual(
            (item["x"], item["y"], item["w"], item["h"]),
            (2.125, 3.75, 5.5, 4.25),
        )

    def test_canvas_columns_are_restricted_to_supported_choices(self):
        self.assertEqual(normalize_columns("36"), 36)
        self.assertEqual(normalize_columns(30), 24)

    def test_canvas_zoom_is_clamped_to_manual_range(self):
        self.assertEqual(normalize_zoom("1.25"), 1.25)
        self.assertEqual(normalize_zoom(0.1), 0.25)
        self.assertEqual(normalize_zoom(4), 2.0)

    def test_default_drop_width_is_clamped_to_global_control_range(self):
        self.assertEqual(normalize_drop_width("5"), 5)
        self.assertEqual(normalize_drop_width(0), 2)
        self.assertEqual(normalize_drop_width(99), 12)

    def test_column_scaling_preserves_visual_horizontal_proportions(self):
        items = [
            tile("left", 0, 0, 8, 6),
            tile("right", 12, 0, 6, 6),
        ]

        result = scale_layout_columns(items, 24, 48)
        by_id = {item["tile_id"]: item for item in result}

        self.assertEqual((by_id["left"]["x"], by_id["left"]["w"]), (0, 16))
        self.assertEqual((by_id["right"]["x"], by_id["right"]["w"]), (24, 12))
        self.assertEqual(validate_layout(result, columns=48), (True, ""))

    def test_column_scaling_resolves_minimum_width_collisions_horizontally(self):
        items = [
            tile("left", 0, 0, 2, 3),
            tile("right", 2, 0, 2, 3),
        ]

        result = scale_layout_columns(items, 24, 12)
        by_id = {item["tile_id"]: item for item in result}

        self.assertEqual((by_id["left"]["x"], by_id["left"]["y"]), (0, 0))
        self.assertEqual((by_id["right"]["x"], by_id["right"]["y"]), (2, 0))
        self.assertEqual(validate_layout(result, columns=12), (True, ""))

    def test_column_scaling_moves_down_only_when_no_horizontal_room_remains(self):
        items = [
            tile("first", 0, 0, 8, 6, "stats"),
            tile("second", 8, 0, 8, 6, "stats"),
            tile("third", 16, 0, 8, 6, "stats"),
        ]

        result = scale_layout_columns(items, 24, 12)
        by_id = {item["tile_id"]: item for item in result}

        self.assertEqual(by_id["first"]["y"], 0)
        self.assertEqual(by_id["second"]["y"], 0)
        self.assertEqual(by_id["third"]["y"], 6)
        self.assertEqual(validate_layout(result, columns=12), (True, ""))

    def test_sticky_snap_keeps_current_line_inside_dead_zone(self):
        self.assertEqual(sticky_snap(5.54, 5), 5)
        self.assertEqual(sticky_snap(5.56, 5), 6)

    def test_vertical_shared_seam_wins_near_a_tile_corner(self):
        items = [
            tile("left", 0, 0, 10, 8),
            tile("right", 10, 0, 10, 8),
            tile("moving", 0, 10, 8, 6),
        ]

        zone = insertion_zone(
            items,
            "moving",
            9.8,
            0.1,
            x_tolerance=0.3,
            y_tolerance=0.3,
        )

        self.assertEqual(zone, {
            "orientation": "column",
            "seam": 10.0,
            "anchor_x": 10.0,
            "anchor_y": 0.0,
            "edge": "shared",
        })

    def test_horizontal_shared_seam_wins_near_a_tile_corner(self):
        items = [
            tile("top", 4, 0, 10, 8),
            tile("bottom", 4, 8, 10, 8),
            tile("moving", 16, 0, 8, 6),
        ]

        zone = insertion_zone(
            items,
            "moving",
            4.1,
            7.8,
            x_tolerance=0.3,
            y_tolerance=0.3,
        )

        self.assertEqual(zone, {
            "orientation": "row",
            "seam": 8.0,
            "anchor_x": 4.0,
            "anchor_y": 8.0,
            "edge": "shared",
        })

    def test_fit_rectangle_uses_largest_anchored_free_region(self):
        fitted = fit_rectangle(
            0,
            0,
            10,
            8,
            [tile("block", 6, 0, 6, 4), tile("floor", 0, 5, 12, 4)],
        )

        self.assertEqual(fitted, {"x": 0, "y": 0, "w": 6, "h": 5})

    def test_nearest_free_searches_by_manhattan_distance(self):
        target = tile("moving", 0, 0, 4, 3)
        result = nearest_free(target, [tile("occupied", 0, 0, 4, 3)])

        self.assertEqual((result["x"], result["y"]), (0, 3))

    def test_vertical_push_keeps_priority_tile_fixed(self):
        items = [
            tile("first", 0, 0, 8, 5),
            tile("moving", 0, 0, 8, 6),
            tile("last", 0, 4, 8, 3),
        ]
        result = vertical_push(items, "moving")
        by_id = {item["tile_id"]: item for item in result}

        self.assertEqual((by_id["moving"]["x"], by_id["moving"]["y"]), (0, 0))
        self.assertEqual(by_id["first"]["y"], 6)
        self.assertEqual(by_id["last"]["y"], 11)
        self.assertEqual(validate_layout(result), (True, ""))

    def test_horizontal_resize_pushes_side_neighbors_right(self):
        items = [
            tile("moving", 0, 0, 8, 6),
            tile("right", 4, 0, 4, 6),
            tile("far-right", 8, 0, 4, 6),
        ]

        result = horizontal_resize_push(
            items,
            "moving",
            original_right=4,
        )
        by_id = {item["tile_id"]: item for item in result}

        self.assertEqual(by_id["moving"]["w"], 8)
        self.assertEqual(by_id["right"]["x"], 8)
        self.assertEqual(by_id["far-right"]["x"], 12)
        self.assertEqual(by_id["right"]["y"], 0)
        self.assertEqual(validate_layout(result), (True, ""))

    def test_horizontal_resize_clamps_growth_at_canvas_boundary(self):
        items = [
            tile("moving", 0, 0, 8, 6),
            tile("right", 4, 0, 20, 6),
        ]

        result = horizontal_resize_push(
            items,
            "moving",
            original_right=4,
        )
        by_id = {item["tile_id"]: item for item in result}

        self.assertEqual(by_id["moving"]["w"], 4)
        self.assertEqual((by_id["right"]["x"], by_id["right"]["y"]), (4, 0))
        self.assertEqual(validate_layout(result), (True, ""))

    def test_column_insertion_pushes_connected_neighbors(self):
        items = [
            tile("moving", 0, 8, 4, 3),
            tile("a", 8, 0, 4, 5),
            tile("b", 12, 4, 4, 5),
        ]
        move_ids = connected_column_move_set(
            items,
            seam=8,
            anchor_y=2,
            dragged_height=4,
            excluded_id="moving",
        )
        size = column_insertion_size(items[0], items[1:], 8)
        result = apply_column_insertion(
            items,
            dragged_id="moving",
            seam=8,
            anchor_y=2,
            move_ids=move_ids,
            width=size["w"],
            height=size["h"],
            mode=size["mode"],
        )
        by_id = {item["tile_id"]: item for item in result}

        self.assertEqual(move_ids, ["a", "b"])
        self.assertEqual(size["mode"], "push")
        self.assertEqual(by_id["moving"]["x"], 8)
        self.assertEqual(by_id["a"]["x"], 12)
        self.assertEqual(by_id["b"]["x"], 16)
        self.assertEqual(validate_layout(result), (True, ""))

    def test_column_insertion_shrinks_neighbor_space_affinely(self):
        items = [
            tile("moving", 0, 8, 8, 6),
            tile("neighbor", 8, 0, 16, 8),
        ]
        size = column_insertion_size(items[0], items[1:], 8)
        result = apply_column_insertion(
            items,
            dragged_id="moving",
            seam=8,
            anchor_y=0,
            move_ids=["neighbor"],
            width=size["w"],
            height=size["h"],
            mode=size["mode"],
        )
        by_id = {item["tile_id"]: item for item in result}

        self.assertEqual(size["mode"], "shrink")
        self.assertEqual((by_id["moving"]["x"], by_id["moving"]["w"]), (8, 8))
        self.assertEqual((by_id["neighbor"]["x"], by_id["neighbor"]["w"]), (16, 8))
        self.assertEqual(validate_layout(result), (True, ""))


if __name__ == "__main__":
    unittest.main()
