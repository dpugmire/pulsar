import unittest

from seurat.models.grid import (
    assign_cell,
    empty_grid_cell,
    normalize_grid_cells,
    normalize_grid_selection,
    range_selection,
    source_dialog_targets,
)
from seurat.models.grid_layout import (
    grid_fit_template_from_weights,
    grid_template_from_sizes,
    normalize_size_list,
    normalize_weight_list,
)
from seurat.models.plot import (
    clean_plot_color,
    normalize_plot_settings,
    valid_extrema,
)
from seurat.models.plugin_options import plugin_option_rows, plugin_options_from_rows
from seurat.models.source_selection import (
    normalize_source_keys,
    select_single_source,
    select_visible_sources,
    selected_source_label,
    source_filter_from_row,
    source_key_for_fields,
    toggle_source_selection,
)
from seurat.models.timeline import (
    cell_has_timeline_samples,
    clear_timeline_driver,
    selection_axis_descriptor,
    selection_axis_index_for_value,
    selection_axis_key,
    selection_axis_values,
    toggle_timeline_driver,
)


def variable_cell(variable_id, **values):
    cell = empty_grid_cell()
    cell["variable_id"] = variable_id
    cell["variable_name"] = variable_id
    cell["status"] = "ready"
    cell.update(values)
    return cell


class GridModelTests(unittest.TestCase):
    def test_freeform_normalization_is_compact_and_assigns_stable_ids(self):
        cells = normalize_grid_cells(
            [
                empty_grid_cell(),
                variable_cell(
                    "density",
                    canvas_x=3,
                    canvas_y=4,
                    canvas_w=8,
                    canvas_h=6,
                ),
            ],
            rows=3,
            cols=3,
            layout_mode="freeform",
        )

        self.assertEqual(len(cells), 1)
        self.assertEqual(cells[0]["tile_id"], "tile-1")
        self.assertEqual(
            tuple(cells[0][key] for key in ("canvas_x", "canvas_y", "canvas_w", "canvas_h")),
            (3, 4, 8, 6),
        )

    def test_uniform_normalization_resets_geometry_and_pads_grid(self):
        cells = normalize_grid_cells(
            [variable_cell("density", grid_row=8, grid_col=8, row_span=4)],
            rows=2,
            cols=2,
            layout_mode="uniform",
        )

        self.assertEqual(len(cells), 4)
        self.assertEqual(
            {key: cells[0][key] for key in ("grid_row", "grid_col", "row_span")},
            {"grid_row": 1, "grid_col": 1, "row_span": 1},
        )
        self.assertEqual(cells[3]["status"], "empty")
        self.assertEqual((cells[3]["grid_row"], cells[3]["grid_col"]), (2, 2))

    def test_spanning_normalization_marks_covered_slots_hidden(self):
        cells = normalize_grid_cells(
            [variable_cell("density", row_span=2, col_span=2)],
            rows=2,
            cols=2,
            layout_mode="spanning",
        )

        self.assertEqual(cells[0]["variable_id"], "density")
        self.assertEqual((cells[0]["row_span"], cells[0]["col_span"]), (2, 2))
        self.assertEqual(
            [cell["grid_hidden"] for cell in cells],
            [False, True, True, True],
        )

    def test_assignment_preserves_layout_geometry(self):
        cells = normalize_grid_cells(
            [variable_cell("old", row_span=1, col_span=2)],
            rows=1,
            cols=2,
            layout_mode="spanning",
        )

        assign_cell(cells, 0, variable_cell("new"))

        self.assertEqual(cells[0]["variable_id"], "new")
        self.assertEqual(cells[0]["col_span"], 2)

    def test_selection_rules_ignore_empty_hidden_and_duplicate_cells(self):
        cells = [
            variable_cell("a"),
            empty_grid_cell(),
            variable_cell("covered", grid_hidden=True),
            variable_cell("d"),
        ]

        self.assertEqual(
            normalize_grid_selection([3, "0", 3, 1, 2, "bad"], cells),
            [3, 0],
        )
        self.assertEqual(range_selection(cells, [0], 0, 3), [0, 3])
        self.assertEqual(source_dialog_targets(cells, [0, 3], 3), [0, 3])
        self.assertEqual(source_dialog_targets(cells, [0, 3], 1), [])


class TimelineModelTests(unittest.TestCase):
    def test_explicit_selection_axis_drives_timeline_semantics(self):
        cell = variable_cell(
            "waveform",
            axes={
                "shot": {
                    "id": "shot",
                    "key": "lasernet:laser_runs:shot",
                    "label": "Shot number",
                    "values": [15, 16, 17],
                }
            },
            selection_axis="shot",
            plot={"x_label": "Time within shot", "series": [{"x": [0, 1]}]},
        )

        self.assertEqual(selection_axis_descriptor(cell)["label"], "Shot number")
        self.assertEqual(selection_axis_values(cell), [15.0, 16.0, 17.0])
        self.assertEqual(selection_axis_key(cell), "lasernet:laser_runs:shot")
        self.assertEqual(selection_axis_index_for_value(cell, 16.0), 1)
        self.assertIsNone(selection_axis_index_for_value(cell, 18.0))
        self.assertTrue(cell_has_timeline_samples(cell))

    def test_timeline_samples_accept_explicit_or_time_axis_values(self):
        explicit = variable_cell("a", time_values=[None, "1.5", "nan"])
        plotted = variable_cell(
            "b",
            plot={"x_label": "Physical Time", "series": [{"x": [0.0, 1.0]}]},
        )
        index_plot = variable_cell(
            "c",
            plot={"x_label": "Index", "series": [{"x": [0.0, 1.0]}]},
        )

        self.assertTrue(cell_has_timeline_samples(explicit))
        self.assertTrue(cell_has_timeline_samples(plotted))
        self.assertFalse(cell_has_timeline_samples(index_plot))

    def test_timeline_driver_toggle_and_clear_are_deterministic(self):
        cells = [
            variable_cell("timed", time_values=[0, 1]),
            variable_cell("static"),
        ]

        self.assertEqual(toggle_timeline_driver(cells, -1, 0), 0)
        self.assertEqual(toggle_timeline_driver(cells, 0, 0), -1)
        self.assertEqual(toggle_timeline_driver(cells, 0, 1), 0)
        self.assertEqual(toggle_timeline_driver(cells, 0, 5), 0)
        self.assertEqual(clear_timeline_driver(0, [0, 2]), -1)
        self.assertEqual(clear_timeline_driver(1, [0, 2]), 1)


class PlotModelTests(unittest.TestCase):
    def test_color_and_axis_settings_are_normalized(self):
        tile = {
            "plot": {
                "series": [
                    {
                        "source_key": "run-a",
                        "source_label": "Run A",
                        "color": "#123456",
                        "x": [0, 1],
                        "y": [2, 3],
                    }
                ]
            }
        }

        settings = normalize_plot_settings(
            tile,
            {
                "line_width": 99,
                "x_scale": "log",
                "series_styles": {
                    "run-a": {"color": "rgb(1, 2, 3)", "line_style": "dash_dot"}
                },
            },
        )

        self.assertEqual(settings["line_width"], 8.0)
        self.assertEqual(settings["x_scale"], "log")
        self.assertEqual(
            settings["series_styles"]["run-a"],
            {"color": "rgb(1, 2, 3)", "line_style": "dash-dot"},
        )
        self.assertEqual(clean_plot_color({"r": 1, "g": 2, "b": 3, "a": 0.5}, "fallback"), "fallback")
        self.assertEqual(valid_extrema("2", "1"), (None, None))


class GridLayoutModelTests(unittest.TestCase):
    def test_track_values_and_templates_are_normalized(self):
        self.assertEqual(normalize_size_list("100;bad", 3, 50, 40, 200), [100, 50, 50])
        self.assertEqual(normalize_weight_list([0, 2, 1000], 3), [1.0, 2.0, 100.0])
        self.assertEqual(grid_template_from_sizes([100, 200]), "100px 200px")
        self.assertEqual(
            grid_fit_template_from_weights([1, 2], 80),
            "minmax(80px, 1fr) minmax(80px, 2fr)",
        )


class PluginOptionsModelTests(unittest.TestCase):
    def test_option_rows_round_trip_typed_values(self):
        schema = [
            {"key": "enabled", "label": "Enabled", "type": "bool", "default": True},
            {"key": "mode", "label": "Mode", "type": "select", "default": "a", "choices": ["a", "b"]},
        ]

        rows = plugin_option_rows(schema, {"enabled": False, "mode": " b "})

        self.assertEqual(
            plugin_options_from_rows(rows),
            {"enabled": False, "mode": "b"},
        )


class SourceSelectionModelTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{"_key": "a"}, {"_key": "b"}, {"_key": "c"}]

    def test_normalization_and_single_selection(self):
        self.assertEqual(normalize_source_keys([" b ", "a", "b", ""]), ["b", "a"])
        self.assertEqual(select_single_source("b", ["a", "b"]), ["b"])
        self.assertEqual(select_single_source("missing", ["a", "b"]), [])

    def test_multi_selection_preserves_catalog_order(self):
        self.assertEqual(toggle_source_selection(["c"], "a", ["a", "b", "c"]), ["a", "c"])
        self.assertEqual(toggle_source_selection(["a", "c"], "a", ["a", "b", "c"]), ["c"])
        self.assertEqual(
            select_visible_sources(["c"], ["b"], ["a", "b", "c"]),
            ["b", "c"],
        )

    def test_selection_label_reports_total_and_filtered_counts(self):
        self.assertEqual(selected_source_label([], [], []), "No sources")
        self.assertEqual(
            selected_source_label(self.rows, self.rows[:2], ["a"]),
            "1 of 3 selected · 2 shown",
        )

    def test_source_identity_prefers_schema_groups_then_datasets(self):
        schema_row = {
            "variable_id": "density",
            "schema_file_group": "xgc_3d",
            "schema_mode": "file_per_timestep",
            "source_dataset": "xgc.3d.00010.bp",
        }
        dataset_row = {
            "variable_id": "temperature",
            "source_dataset": "scalars.bp",
        }

        self.assertEqual(source_key_for_fields(schema_row), "schema|density|xgc_3d")
        self.assertEqual(
            source_filter_from_row(schema_row),
            {
                "variable_id": "density",
                "schema_file_group": "xgc_3d",
                "schema_mode": "file_per_timestep",
            },
        )
        self.assertEqual(
            source_filter_from_row(dataset_row),
            {"variable_id": "temperature", "source_dataset": "scalars.bp"},
        )


if __name__ == "__main__":
    unittest.main()
