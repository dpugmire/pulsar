import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

from db import (
    CampaignDb,
    scalar_field_axis_spec,
    scalar_field_contour_levels,
    scalar_field_to_png_bytes,
)
from pulsar.controllers.sources import SourcesControllerMixin
from pulsar.controllers.visualization import VisualizationControllerMixin
from sqlite_store import SQLiteCampaignCollection


class ScalarFieldTitleController(
    SourcesControllerMixin,
    VisualizationControllerMixin,
):
    def __init__(self, summary):
        self.application = SimpleNamespace(
            get_source_summary=lambda _request: summary
        )

    @staticmethod
    def active_query_filter():
        return None


class ScalarFieldAxisTests(unittest.TestCase):
    def test_grid_metadata_produces_physical_axes(self):
        axes = scalar_field_axis_spec(
            {
                "shape": [256, 256],
                "grid": {
                    "axes": ["R", "Z"],
                    "bounds": {
                        "R": [0.2, 4.6],
                        "Z": [-2.5, 2.5],
                    },
                    "column_axis": "R",
                    "column_order": "ascending",
                    "row_axis": "Z",
                    "row_order": "descending",
                    "shape": [256, 256],
                },
            }
        )

        self.assertEqual(axes["x"]["label"], "R")
        self.assertEqual(axes["y"]["label"], "Z")
        self.assertEqual((axes["x"]["start"], axes["x"]["end"]), (0.2, 4.6))
        self.assertEqual((axes["y"]["start"], axes["y"]["end"]), (-2.5, 2.5))
        self.assertEqual(
            [tick["position"] for tick in axes["x"]["ticks"]],
            [0, 50, 100],
        )
        self.assertEqual(
            [tick["value"] for tick in axes["x"]["ticks"]],
            [0.2, 2.4, 4.6],
        )
        self.assertEqual(
            [tick["value"] for tick in axes["y"]["ticks"]],
            [-2.5, 0.0, 2.5],
        )

    def test_shape_only_metadata_uses_array_indices(self):
        axes = scalar_field_axis_spec({"shape": [3, 5]})

        self.assertEqual(axes["x"]["label"], "column")
        self.assertEqual(axes["y"]["label"], "row")
        self.assertEqual(
            [tick["value"] for tick in axes["x"]["ticks"]],
            [0.0, 2.0, 4.0],
        )
        self.assertEqual(
            [tick["value"] for tick in axes["y"]["ticks"]],
            [2.0, 1.0, 0.0],
        )

    def test_axes_are_attached_to_scalar_field_tiles(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            collection = SQLiteCampaignCollection(
                Path(temp_dir) / "campaign.sqlite",
                "/campaign/example.aca",
            )
            collection.insert_one(
                {
                    "campaign_path": "/campaign/example.aca",
                    "variable_id": "fields/P",
                    "variable_name": "P",
                    "variable_type": "scalarField",
                    "payload_type": "SCALAR_FIELD",
                    "visualization_item_type": "SCALAR_FIELD",
                    "visualization_name": "scalar_field",
                    "source_dataset": "run/output.bp",
                    "frame_index": 0,
                    "visualization_activity_provenance": {
                        "activity_operation": "scalar_field",
                        "workflow_plan": {
                            "label": "MHD scalar-field visualization workflow"
                        },
                    },
                    "scalar_field_metadata": {
                        "shape": [4, 6],
                        "grid": {
                            "column_axis": "R",
                            "row_axis": "Z",
                            "bounds": {
                                "R": [1.0, 3.0],
                                "Z": [-1.0, 1.0],
                            },
                            "row_order": "descending",
                        },
                    },
                }
            )
            campaign_db = CampaignDb(collection)

            with patch.object(
                campaign_db,
                "get_movie_frames_for_stream",
                return_value=([b"png"], 1, [0], [0], "timestep"),
            ):
                tiles = campaign_db.get_first_movie_tiles_for_variable(
                    "fields/P"
                )
            collection._con.close()

        self.assertEqual(len(tiles), 1)
        self.assertEqual(tiles[0]["scalar_field_axes"]["x"]["label"], "R")
        self.assertEqual(tiles[0]["scalar_field_axes"]["y"]["label"], "Z")
        self.assertEqual(
            tiles[0]["visualization_activity_provenance"],
            {
                "activity_operation": "scalar_field",
                "workflow_plan": {
                    "label": "MHD scalar-field visualization workflow"
                },
            },
        )


class ScalarFieldRepresentationSummaryTests(unittest.TestCase):
    def test_source_and_derived_statistics_are_reported_separately(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            collection = SQLiteCampaignCollection(
                Path(temp_dir) / "campaign.sqlite",
                "/campaign/example.aca",
            )
            collection.insert_one(
                {
                    "campaign_path": "/campaign/example.aca",
                    "variable_id": "fields/P",
                    "variable_name": "P",
                    "variable_type": "variable",
                    "source_dataset": "run/output.bp",
                    "data_model": "m3dc1_element_basis_coefficients",
                    "metadata": {
                        "Shape": "27894,20",
                        "AvailableStepsCount": "51",
                    },
                    "min": -5.6e9,
                    "max": 1.3e10,
                }
            )
            for frame_index, minimum, maximum in (
                (0, 0.1, 3.5),
                (1, -0.2, 2.5),
            ):
                collection.insert_one(
                    {
                        "campaign_path": "/campaign/example.aca",
                        "variable_id": "fields/P",
                        "variable_name": "P",
                        "variable_type": "scalarField",
                        "source_dataset": "run/output.bp",
                        "visualization_name": "scalar_field",
                        "frame_index": frame_index,
                        "min": minimum,
                        "max": maximum,
                        "scalar_field_metadata": {
                            "data_model": "m3dc1_regular_rz_grid",
                            "source_data_model": (
                                "m3dc1_element_basis_coefficients"
                            ),
                            "shape": [256, 256],
                            "grid": {
                                "axes": ["R", "Z"],
                                "shape": [256, 256],
                            },
                        },
                    }
                )

            summary = CampaignDb(collection).variable_min_max_summary(
                "fields/P"
            )
            collection._con.close()

        source = summary["source_representation"]
        self.assertEqual(source["label"], "Source coefficients")
        self.assertEqual(
            source["data_model"],
            "m3dc1_element_basis_coefficients",
        )
        self.assertEqual(source["shape"], "27894 × 20")
        self.assertEqual(source["num_frames"], 51)
        self.assertEqual(source["global_min"], -5.6e9)
        self.assertEqual(source["global_max"], 1.3e10)

        self.assertEqual(len(summary["derived_representations"]), 1)
        derived = summary["derived_representations"][0]
        self.assertEqual(derived["label"], "Derived scalar field")
        self.assertEqual(derived["data_model"], "m3dc1_regular_rz_grid")
        self.assertEqual(
            derived["source_data_model"],
            "m3dc1_element_basis_coefficients",
        )
        self.assertEqual(derived["shape"], "256 × 256")
        self.assertEqual(derived["axes"], "R × Z")
        self.assertEqual(derived["num_frames"], 2)
        self.assertEqual(derived["num_sources"], 1)
        self.assertEqual(derived["global_min"], -0.2)
        self.assertEqual(derived["global_max"], 3.5)
        self.assertAlmostEqual(derived["mean_min"], -0.05)
        self.assertEqual(derived["mean_max"], 3.0)


class ScalarFieldTitleRangeTests(unittest.TestCase):
    @staticmethod
    def scalar_field_cell():
        return {
            "media_type": "image_sequence",
            "variable_type": "scalarField",
            "variable_id": "fields/P",
            "source_dataset": "run/output.bp",
            "visualization_name": "fields/P/scalar_field",
            "selected_visualization": "fields/P/scalar_field",
            "min": 0.1,
            "max": 3.5,
            "scalar_field_settings": {},
        }

    def test_scalar_field_title_and_colorbar_use_derived_global_range(self):
        controller = ScalarFieldTitleController(
            {
                "global_min": -5.6e9,
                "global_max": 1.3e10,
                "derived_representations": [
                    {
                        "id": "fields/P/scalar_field",
                        "global_min": -0.2,
                        "global_max": 3.5,
                    }
                ],
            }
        )
        cell = self.scalar_field_cell()

        controller.update_2d_display_title(cell, "fields/P", "P")

        self.assertEqual(cell["display_title"], "P [-0.2, 3.5]")
        self.assertEqual(cell["scalar_field_colorbar_min"], "-0.2")
        self.assertEqual(cell["scalar_field_colorbar_max"], "3.5")

    def test_scalar_field_without_derived_summary_uses_payload_range(self):
        controller = ScalarFieldTitleController(
            {
                "global_min": -5.6e9,
                "global_max": 1.3e10,
                "derived_representations": [],
            }
        )
        cell = self.scalar_field_cell()

        controller.update_2d_display_title(cell, "fields/P", "P")

        self.assertEqual(cell["display_title"], "P [0.1, 3.5]")
        self.assertEqual(cell["scalar_field_colorbar_min"], "0.1")
        self.assertEqual(cell["scalar_field_colorbar_max"], "3.5")


class ScalarFieldBackgroundTests(unittest.TestCase):
    @staticmethod
    def render(background=None):
        values = np.array(
            [
                [np.nan, 0.0],
                [1.0, np.nan],
            ],
            dtype=np.float32,
        )
        metadata = {
            "kind": "scalarField",
            "encoding": "raw",
            "compression": "none",
            "layout": "row-major",
            "value_encoding": "direct",
            "dtype": "float32",
            "byte_order": "little",
            "shape": [2, 2],
            "min": 0.0,
            "max": 1.0,
        }
        png = scalar_field_to_png_bytes(
            values.tobytes(),
            metadata,
            {"background": background} if background else {},
        )
        return Image.open(io.BytesIO(png)).convert("RGB")

    def test_non_finite_pixels_use_black_background_by_default(self):
        image = self.render()

        self.assertEqual(image.getpixel((0, 0)), (0, 0, 0))
        self.assertEqual(image.getpixel((1, 1)), (0, 0, 0))

    def test_non_finite_pixels_use_white_background_when_selected(self):
        image = self.render("white")

        self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(image.getpixel((1, 1)), (255, 255, 255))

    def test_background_setting_derives_contrasting_display_colors(self):
        controller = object.__new__(VisualizationControllerMixin)

        black = controller.normalize_scalar_field_settings(
            {"background": "black"}
        )
        white = controller.normalize_scalar_field_settings(
            {"background": "white"}
        )

        self.assertEqual(black["background_color"], "#000000")
        self.assertEqual(black["foreground_color"], "#ffffff")
        self.assertEqual(white["background_color"], "#ffffff")
        self.assertEqual(white["foreground_color"], "#111111")


class ScalarFieldContourLevelTests(unittest.TestCase):
    def test_range_levels_include_min_and_max(self):
        levels = scalar_field_contour_levels(
            {
                "contours": {
                    "level_mode": "range",
                    "min": -1.0,
                    "max": 1.0,
                    "count": 5,
                }
            },
            -4.0,
            4.0,
        )

        self.assertEqual(levels, [-1.0, -0.5, 0.0, 0.5, 1.0])

    def test_range_levels_fall_back_to_render_range(self):
        levels = scalar_field_contour_levels(
            {"contours": {"level_mode": "range", "count": 3}},
            2.0,
            8.0,
        )

        self.assertEqual(levels, [2.0, 5.0, 8.0])

    def test_explicit_levels_are_finite_sorted_and_unique(self):
        levels = scalar_field_contour_levels(
            {
                "contours": {
                    "level_mode": "values",
                    "values": [1.0, -2.0, 1.0, float("nan"), 0.25],
                }
            },
            -4.0,
            4.0,
        )

        self.assertEqual(levels, [-2.0, 0.25, 1.0])


class ScalarFieldContourRenderingTests(unittest.TestCase):
    @staticmethod
    def render(render_mode, background="black", contour_color="#ffffff"):
        values = np.tile(
            np.linspace(0.0, 1.0, 9, dtype=np.float32),
            (9, 1),
        )
        metadata = {
            "kind": "scalarField",
            "encoding": "raw",
            "compression": "none",
            "layout": "row-major",
            "value_encoding": "direct",
            "dtype": "float32",
            "byte_order": "little",
            "shape": [9, 9],
            "min": 0.0,
            "max": 1.0,
        }
        png = scalar_field_to_png_bytes(
            values.tobytes(),
            metadata,
            {
                "render_mode": render_mode,
                "background": background,
                "contours": {
                    "level_mode": "values",
                    "values": [0.5],
                    "color": contour_color,
                },
            },
        )
        return Image.open(io.BytesIO(png)).convert("RGB")

    def test_contour_only_uses_background_and_contrasting_line(self):
        black = self.render("contours", "black")
        white = self.render("contours", "white", "#111111")

        self.assertEqual(black.getpixel((0, 4)), (0, 0, 0))
        self.assertEqual(black.getpixel((4, 4)), (255, 255, 255))
        self.assertEqual(white.getpixel((0, 4)), (255, 255, 255))
        self.assertEqual(white.getpixel((4, 4)), (17, 17, 17))

    def test_both_preserves_colormap_and_overlays_contour(self):
        colormap = self.render("colormap")
        both = self.render("both")

        self.assertEqual(both.getpixel((0, 4)), colormap.getpixel((0, 4)))
        self.assertEqual(both.getpixel((3, 4)), colormap.getpixel((3, 4)))
        self.assertNotEqual(colormap.getpixel((4, 4)), (255, 255, 255))
        self.assertEqual(both.getpixel((4, 4)), (255, 255, 255))


class ScalarFieldContourSettingsTests(unittest.TestCase):
    def setUp(self):
        self.controller = object.__new__(VisualizationControllerMixin)

    def test_normalization_preserves_contour_settings(self):
        settings = self.controller.normalize_scalar_field_settings(
            {
                "render_mode": "both",
                "contours": {
                    "level_mode": "values",
                    "values": [1, -1, 1],
                    "min": -2,
                    "max": 2,
                    "count": 7,
                    "color": "#ff0000",
                },
            }
        )

        self.assertEqual(settings["render_mode"], "both")
        self.assertEqual(
            settings["contours"],
            {
                "level_mode": "values",
                "values": [-1.0, 1.0],
                "min": -2.0,
                "max": 2.0,
                "count": 7,
                "color": "#ff0000",
            },
        )

    def test_explicit_value_parser_accepts_commas_spaces_and_semicolons(self):
        self.assertEqual(
            self.controller.parse_scalar_field_contour_values(
                "1, -0.5; 0 1"
            ),
            [-0.5, 0.0, 1.0],
        )

    def test_explicit_value_parser_rejects_invalid_values(self):
        with self.assertRaisesRegex(ValueError, "Invalid contour value"):
            self.controller.parse_scalar_field_contour_values("0, nope, 1")


class ScalarFieldSettingsApplyController(VisualizationControllerMixin):
    def __init__(self):
        self.state = SimpleNamespace(
            gridCells=[
                {
                    "variable_type": "scalarField",
                    "variable_id": "field",
                    "variable_name": "field",
                    "selected_visualization": "scalar_field",
                    "visualization_name": "scalar_field",
                    "scalar_field_settings": {},
                }
            ],
            scalarFieldSettingsCellIndex=0,
            scalarFieldSettingsColormap="viridis",
            scalarFieldSettingsShowHeatmap=True,
            scalarFieldSettingsShowContours=True,
            scalarFieldSettingsBackground="black",
            scalarFieldSettingsRangeAuto=True,
            scalarFieldSettingsMin="",
            scalarFieldSettingsMax="",
            scalarFieldSettingsShowColorbar=True,
            scalarFieldSettingsShowAxes=True,
            scalarFieldSettingsContourLevelMode="values",
            scalarFieldSettingsContourValues="-1, 0, 1",
            scalarFieldSettingsContourMin="-2",
            scalarFieldSettingsContourMax="2",
            scalarFieldSettingsContourCount=5,
            scalarFieldSettingsContourColor="#ffffff",
            scalarFieldSettingsStatus="",
            scalarFieldSettingsStatusIsError=False,
            activeGridCell=-1,
        )

    def normalize_grid_cells(self, cells):
        return [dict(cell) for cell in cells]

    def is_valid_grid_index(self, index):
        return 0 <= int(index) < len(self.state.gridCells)

    def build_grid_cell_for_variable(
        self,
        _variable_id,
        preferred_vis="",
        existing_cell=None,
        **_kwargs,
    ):
        return dict(existing_cell or {})


class ScalarFieldContourApplyTests(unittest.TestCase):
    def test_background_toggle_switches_between_black_and_white(self):
        controller = ScalarFieldSettingsApplyController()

        controller.toggle_scalar_field_background()
        self.assertEqual(
            controller.state.scalarFieldSettingsBackground,
            "white",
        )

        controller.toggle_scalar_field_background()
        self.assertEqual(
            controller.state.scalarFieldSettingsBackground,
            "black",
        )

    def test_apply_persists_explicit_contours(self):
        controller = ScalarFieldSettingsApplyController()

        controller.apply_scalar_field_settings()

        self.assertFalse(controller.state.scalarFieldSettingsStatusIsError)
        settings = controller.state.gridCells[0]["scalar_field_settings"]
        self.assertEqual(settings["render_mode"], "both")
        self.assertEqual(settings["contours"]["level_mode"], "values")
        self.assertEqual(settings["contours"]["values"], [-1.0, 0.0, 1.0])
        self.assertEqual(settings["contours"]["color"], "#ffffff")

    def test_inactive_heatmap_range_does_not_block_contour_apply(self):
        controller = ScalarFieldSettingsApplyController()
        controller.state.scalarFieldSettingsShowHeatmap = False
        controller.state.scalarFieldSettingsRangeAuto = False
        controller.state.scalarFieldSettingsMin = ""
        controller.state.scalarFieldSettingsMax = ""

        controller.apply_scalar_field_settings()

        self.assertFalse(controller.state.scalarFieldSettingsStatusIsError)
        self.assertEqual(
            controller.state.gridCells[0]["scalar_field_settings"][
                "render_mode"
            ],
            "contours",
        )

    def test_contour_color_update_uses_plot_color_validation(self):
        controller = ScalarFieldSettingsApplyController()

        controller.update_scalar_field_contour_color("#ff0000")
        self.assertEqual(
            controller.state.scalarFieldSettingsContourColor,
            "#ff0000",
        )
        controller.update_scalar_field_contour_color("not-a-color")
        self.assertEqual(
            controller.state.scalarFieldSettingsContourColor,
            "#ff0000",
        )

    def test_apply_rejects_invalid_explicit_contours(self):
        controller = ScalarFieldSettingsApplyController()
        controller.state.scalarFieldSettingsContourValues = "-1, invalid, 1"

        controller.apply_scalar_field_settings()

        self.assertTrue(controller.state.scalarFieldSettingsStatusIsError)
        self.assertIn(
            "Invalid contour value",
            controller.state.scalarFieldSettingsStatus,
        )

    def test_apply_rejects_invalid_generated_range(self):
        controller = ScalarFieldSettingsApplyController()
        controller.state.scalarFieldSettingsContourLevelMode = "range"
        controller.state.scalarFieldSettingsContourMin = "2"
        controller.state.scalarFieldSettingsContourMax = "-2"

        controller.apply_scalar_field_settings()

        self.assertTrue(controller.state.scalarFieldSettingsStatusIsError)
        self.assertEqual(
            controller.state.scalarFieldSettingsStatus,
            "Contour range must have min < max.",
        )

    def test_apply_rejects_empty_rendering_selection(self):
        controller = ScalarFieldSettingsApplyController()
        controller.state.scalarFieldSettingsShowHeatmap = False
        controller.state.scalarFieldSettingsShowContours = False

        controller.apply_scalar_field_settings()

        self.assertTrue(controller.state.scalarFieldSettingsStatusIsError)
        self.assertEqual(
            controller.state.scalarFieldSettingsStatus,
            "Select Heatmap, Contour, or both.",
        )


if __name__ == "__main__":
    unittest.main()
