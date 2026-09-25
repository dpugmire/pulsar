import asyncio
import unittest
from types import SimpleNamespace

import numpy as np

from pulsar.controllers.visualization import VisualizationControllerMixin
from pulsar.plot_options_assistant import (
    Plot1dOptionsPatch,
    Plot1dSeriesOptionsPatch,
    PlotOptionsTranslationResult,
    ScalarFieldContourOptionsPatch,
    ScalarFieldOptionsPatch,
    parse_plot1d_options_result,
    parse_scalar_field_options_result,
    plot1d_options_patch_to_dict,
    scalar_field_options_patch_to_dict,
)
from pulsar.query_assistant import QueryAssistantError


def empty_patch():
    return {
        "render_mode": None,
        "colormap": None,
        "background": None,
        "range_auto": None,
        "min": None,
        "max": None,
        "show_colorbar": None,
        "show_axes": None,
        "contours": {
            "level_mode": None,
            "values": None,
            "min": None,
            "max": None,
            "count": None,
            "color": None,
        },
    }


def empty_plot1d_patch():
    return {
        "x_auto": None,
        "x_min": None,
        "x_max": None,
        "x_scale": None,
        "y_auto": None,
        "y_min": None,
        "y_max": None,
        "y_scale": None,
        "line_width": None,
        "show_grid": None,
        "show_cursor": None,
        "background_color": None,
        "grid_color": None,
        "cursor_color": None,
        "series": [],
    }


class ScalarFieldOptionsParserTests(unittest.TestCase):
    def test_parse_colormap_patch(self):
        patch = empty_patch()
        patch["colormap"] = "plasma"

        result = parse_scalar_field_options_result(
            {
                "version": 1,
                "status": "proposal",
                "patch": patch,
                "summary": "Use plasma.",
                "clarification": "",
            }
        )

        self.assertEqual(result.status, "proposal")
        self.assertEqual(result.patch.colormap, "plasma")
        self.assertEqual(result.summary, "Use plasma.")

    def test_reject_unknown_colormap(self):
        patch = empty_patch()
        patch["colormap"] = "not-a-map"

        with self.assertRaisesRegex(QueryAssistantError, "Unsupported colormap"):
            parse_scalar_field_options_result(
                {
                    "version": 1,
                    "status": "proposal",
                    "patch": patch,
                    "summary": "Use it.",
                    "clarification": "",
                }
            )

    def test_clarification_requires_question(self):
        with self.assertRaisesRegex(QueryAssistantError, "clarification"):
            parse_scalar_field_options_result(
                {
                    "version": 1,
                    "status": "needs_clarification",
                    "patch": empty_patch(),
                    "summary": "",
                    "clarification": "",
                }
            )


class Plot1dOptionsParserTests(unittest.TestCase):
    def test_parse_y_log_scale_patch(self):
        patch = empty_plot1d_patch()
        patch["y_scale"] = "log"

        result = parse_plot1d_options_result(
            {
                "version": 1,
                "status": "proposal",
                "patch": patch,
                "summary": "Use log y scale.",
                "clarification": "",
            }
        )

        self.assertEqual(result.status, "proposal")
        self.assertEqual(result.patch.y_scale, "log")

    def test_parse_series_style_patch(self):
        patch = empty_plot1d_patch()
        patch["series"] = [
            {
                "series_key": "pressure",
                "color": "#ff0000",
                "line_style": "dash",
            }
        ]

        result = parse_plot1d_options_result(
            {
                "version": 1,
                "status": "proposal",
                "patch": patch,
                "summary": "Style pressure.",
                "clarification": "",
            }
        )

        self.assertEqual(result.patch.series[0].series_key, "pressure")
        self.assertEqual(result.patch.series[0].color, "#ff0000")
        self.assertEqual(result.patch.series[0].line_style, "dash")


class FakePlotOptionsTranslator:
    description = "fake plot options"
    timeout_seconds = 1.0

    def __init__(self, result):
        self.result = result
        self.requests = []

    def translate(self, request):
        self.requests.append(request)
        return self.result


def scalar_field_cell():
    return {
        "variable_type": "scalarField",
        "variable_id": "field",
        "variable_name": "field",
        "selected_visualization": "scalar_field",
        "visualization_name": "scalar_field",
        "scalar_field_settings": {},
        "scalar_field_colorbar_min": "-2",
        "scalar_field_colorbar_max": "2",
    }


def plot1d_cell(y_values=None):
    return {
        "media_type": "plot1d",
        "variable_id": "pressure",
        "variable_name": "pressure",
        "selected_visualization": "generated_timeseries",
        "visualization_name": "generated_timeseries",
        "plot_settings": {},
        "plot": {
            "x_label": "time",
            "y_label": "pressure",
            "series": [
                {
                    "x": [1.0, 2.0, 3.0],
                    "y": list(y_values if y_values is not None else [2.0, 4.0, 8.0]),
                    "source_key": "pressure",
                    "source_label": "pressure",
                    "color": "#1565c0",
                }
            ],
        },
    }


class ScalarFieldAssistantController(VisualizationControllerMixin):
    def __init__(self, translator, cell=None):
        self.plot_options_translator = translator
        self.state = SimpleNamespace(
            gridCells=[dict(cell or scalar_field_cell())],
            activeGridCell=-1,
            scalarFieldAssistantCellIndex=-1,
            scalarFieldAssistantTitle="",
            scalarFieldAssistantRequestText="",
            scalarFieldAssistantBusy=False,
            scalarFieldAssistantStatus="",
            scalarFieldAssistantError="",
            scalarFieldAssistantProposalSummary="",
            scalarFieldAssistantClarification="",
            scalarFieldAssistantPatch={},
            showScalarFieldAssistantModal=False,
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
        cell = dict(existing_cell or {})
        cell["rebuilt_with"] = preferred_vis
        return cell


class ScalarFieldAssistantControllerTests(unittest.TestCase):
    def test_translate_and_apply_colormap_patch(self):
        translator = FakePlotOptionsTranslator(
            PlotOptionsTranslationResult(
                status="proposal",
                patch=ScalarFieldOptionsPatch(colormap="plasma"),
                summary="Set colormap to plasma.",
            )
        )
        controller = ScalarFieldAssistantController(translator)

        self.assertTrue(controller.open_scalar_field_options_assistant(0))
        controller.state.scalarFieldAssistantRequestText = "use plasma colormap"
        self.assertTrue(
            asyncio.run(controller.translate_scalar_field_options_request())
        )
        self.assertEqual(len(translator.requests), 1)
        self.assertEqual(translator.requests[0].variable_id, "field")

        self.assertTrue(controller.apply_scalar_field_options_patch())
        settings = controller.state.gridCells[0]["scalar_field_settings"]
        self.assertEqual(settings["colormap"], "plasma")
        self.assertEqual(settings["render_mode"], "colormap")
        self.assertEqual(controller.state.gridCells[0]["rebuilt_with"], "scalar_field")
        self.assertEqual(controller.state.scalarFieldAssistantStatus, "Applied.")

    def test_apply_manual_range_patch_validates_range(self):
        patch = ScalarFieldOptionsPatch(range_auto=False, min=2.0, max=-2.0)
        controller = ScalarFieldAssistantController(
            FakePlotOptionsTranslator(
                PlotOptionsTranslationResult(
                    status="proposal",
                    patch=patch,
                    summary="Set range.",
                )
            )
        )
        controller.open_scalar_field_options_assistant(0)
        controller.state.scalarFieldAssistantPatch = scalar_field_options_patch_to_dict(
            patch
        )

        self.assertFalse(controller.apply_scalar_field_options_patch())
        self.assertIn("Manual range must have min < max", controller.state.scalarFieldAssistantError)

    def test_contour_values_patch_sets_both_mode(self):
        patch = ScalarFieldOptionsPatch(
            render_mode="both",
            contours=ScalarFieldContourOptionsPatch(
                level_mode="values",
                values=(-1.0, 0.0, 1.0),
            ),
        )
        controller = ScalarFieldAssistantController(
            FakePlotOptionsTranslator(
                PlotOptionsTranslationResult(
                    status="proposal",
                    patch=patch,
                    summary="Show contours.",
                )
            )
        )
        controller.open_scalar_field_options_assistant(0)
        controller.state.scalarFieldAssistantPatch = scalar_field_options_patch_to_dict(
            patch
        )

        self.assertTrue(controller.apply_scalar_field_options_patch())
        settings = controller.state.gridCells[0]["scalar_field_settings"]
        self.assertEqual(settings["render_mode"], "both")
        self.assertEqual(settings["contours"]["level_mode"], "values")
        np.testing.assert_allclose(settings["contours"]["values"], [-1.0, 0.0, 1.0])


class Plot1dAssistantControllerTests(unittest.TestCase):
    def test_translate_and_apply_log_y_scale(self):
        translator = FakePlotOptionsTranslator(
            PlotOptionsTranslationResult(
                status="proposal",
                patch=Plot1dOptionsPatch(y_scale="log"),
                summary="Use log y scale.",
            )
        )
        controller = ScalarFieldAssistantController(translator, plot1d_cell())

        self.assertTrue(controller.open_scalar_field_options_assistant(0))
        controller.state.scalarFieldAssistantRequestText = "use log y scale"
        self.assertTrue(
            asyncio.run(controller.translate_scalar_field_options_request())
        )
        self.assertEqual(translator.requests[0].plot_type, "plot1d")
        self.assertEqual(translator.requests[0].series[0]["key"], "pressure")

        self.assertTrue(controller.apply_scalar_field_options_patch())
        settings = controller.state.gridCells[0]["plot_settings"]
        self.assertEqual(settings["y_scale"], "log")

    def test_log_y_scale_requires_positive_y_values(self):
        patch = Plot1dOptionsPatch(y_scale="log")
        controller = ScalarFieldAssistantController(
            FakePlotOptionsTranslator(
                PlotOptionsTranslationResult(
                    status="proposal",
                    patch=patch,
                    summary="Use log y scale.",
                )
            ),
            plot1d_cell(y_values=[-3.0, 0.0, -1.0]),
        )
        controller.open_scalar_field_options_assistant(0)
        controller.state.scalarFieldAssistantPatch = plot1d_options_patch_to_dict(
            patch
        )

        self.assertFalse(controller.apply_scalar_field_options_patch())
        self.assertIn(
            "Y log scale requires positive Y values",
            controller.state.scalarFieldAssistantError,
        )

    def test_series_style_patch_updates_matching_series(self):
        patch = Plot1dOptionsPatch(
            series=(
                Plot1dSeriesOptionsPatch(
                    series_key="pressure",
                    color="#ff0000",
                    line_style="dash",
                ),
            )
        )
        controller = ScalarFieldAssistantController(
            FakePlotOptionsTranslator(
                PlotOptionsTranslationResult(
                    status="proposal",
                    patch=patch,
                    summary="Style pressure.",
                )
            ),
            plot1d_cell(),
        )
        controller.open_scalar_field_options_assistant(0)
        controller.state.scalarFieldAssistantPatch = plot1d_options_patch_to_dict(
            patch
        )

        self.assertTrue(controller.apply_scalar_field_options_patch())
        settings = controller.state.gridCells[0]["plot_settings"]
        self.assertEqual(
            settings["series_styles"]["pressure"],
            {"color": "#ff0000", "line_style": "dash"},
        )


if __name__ == "__main__":
    unittest.main()
