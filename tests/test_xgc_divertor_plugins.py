import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


try:
    import adios2  # noqa: F401
except ModuleNotFoundError:
    adios2 = types.ModuleType("adios2")
    adios2.FileReader = object
    sys.modules["adios2"] = adios2

try:
    import numpy  # noqa: F401
except ModuleNotFoundError:
    sys.modules["numpy"] = types.ModuleType("numpy")

try:
    import matplotlib.pyplot  # noqa: F401
except ModuleNotFoundError:
    matplotlib = types.ModuleType("matplotlib")
    pyplot = types.ModuleType("matplotlib.pyplot")
    pyplot.close = lambda _figure: None
    matplotlib.pyplot = pyplot
    sys.modules["matplotlib"] = matplotlib
    sys.modules["matplotlib.pyplot"] = pyplot


from plugin_runtime import discover_plugins, plugin_options_schema
from pulsar_plugins import divertor_lambda_q_timeseries as lambda_q
from pulsar_plugins import divertor_load_map as load_map
from pulsar_plugins import divertor_target_totals_timeseries as target_totals


class XgcDivertorPluginTests(unittest.TestCase):
    def setUp(self):
        self.heatdiag_meta = {
            "variable_name": "e_number",
            "source_dataset": "run/xgc.heatdiag2.bp",
            "source_fields": {"source_dataset": "run/xgc.heatdiag2.bp"},
            "source_variables": [],
        }
        self.non_heatdiag_meta = {
            "variable_name": "density",
            "source_dataset": "run/xgc.3d.bp",
            "source_fields": {"source_dataset": "run/xgc.3d.bp"},
            "source_variables": [],
        }
        self.data_dir = Path("/tmp/xgc-run")
        self.figure = object()

    def test_plugins_are_registered_as_source_plugins(self):
        discovered = {info.plugin_id: info.scope for info in discover_plugins()}

        self.assertEqual(discovered[lambda_q.PLUGIN_ID], "source")
        self.assertEqual(discovered[load_map.PLUGIN_ID], "source")
        self.assertEqual(discovered[target_totals.PLUGIN_ID], "source")

    def test_plugins_only_support_heatdiag_sources(self):
        for plugin in (lambda_q, load_map, target_totals):
            with self.subTest(plugin=plugin.PLUGIN_ID):
                self.assertTrue(plugin.supports_context(self.heatdiag_meta))
                self.assertFalse(plugin.supports_context(self.non_heatdiag_meta))

    def test_load_map_uses_selects_for_exclusive_options(self):
        schema = plugin_options_schema(load_map.PLUGIN_ID, self.heatdiag_meta)
        by_key = {item["key"]: item for item in schema}

        self.assertEqual(by_key["view"]["choices"], ["time", "toroidal"])
        self.assertEqual(by_key["channel"]["choices"], ["energy", "particle"])
        self.assertEqual(by_key["target"]["choices"], ["outer", "inner"])
        self.assertEqual(by_key["component"]["choices"], ["total", "ion", "electron"])

    def test_lambda_q_render_forwards_ranges_and_returns_image_tile(self):
        compute_call = {}
        plot_call = {}

        def compute(data_dir, **kwargs):
            compute_call["data_dir"] = data_dir
            compute_call.update(kwargs)
            return ["point"]

        def plot(points, **kwargs):
            plot_call["points"] = points
            plot_call.update(kwargs)
            return self.figure

        ctx = {
            "options": {
                "step_range": "2,4",
                "time_range_ms": "1,3",
                "frame_index": "7",
                "show_outer": True,
                "show_inner": False,
                "show_lines": False,
                "show_symbols": True,
            }
        }
        with patch.object(lambda_q, "_resolve_data_dir", return_value=self.data_dir), patch.object(
            lambda_q, "_import_divertor_helpers", return_value=(compute, plot)
        ), patch.object(lambda_q, "_figure_data_url", return_value="data:image/png;base64,test"), patch.object(
            lambda_q.plt, "close"
        ) as close:
            tile = lambda_q.render(ctx)

        self.assertEqual(compute_call["data_dir"], self.data_dir)
        self.assertEqual(compute_call["step_range"], (2.0, 4.0))
        self.assertEqual(compute_call["time_window"], (0.001, 0.003))
        self.assertEqual(compute_call["selected_frame_index"], 7)
        self.assertFalse(compute_call["show_inner"])
        self.assertEqual(plot_call["points"], ["point"])
        self.assertFalse(plot_call["show_lines"])
        self.assertTrue(plot_call["show_symbols"])
        self.assertEqual(tile["media_type"], "image")
        self.assertEqual(tile["src"], "data:image/png;base64,test")
        close.assert_called_once_with(self.figure)

    def test_load_map_render_forwards_exclusive_selections(self):
        compute_call = {}
        plot_call = {}

        def compute(data_dir, **kwargs):
            compute_call["data_dir"] = data_dir
            compute_call.update(kwargs)
            return "map"

        def plot(values, **kwargs):
            plot_call["values"] = values
            plot_call.update(kwargs)
            return self.figure

        ctx = {
            "options": {
                "view": "toroidal",
                "channel": "particle",
                "target": "inner",
                "component": "electron",
                "toroidal_range": "10,90",
                "contour_count": "32",
                "include_sheath": True,
            }
        }
        with patch.object(load_map, "_resolve_data_dir", return_value=self.data_dir), patch.object(
            load_map, "_import_divertor_helpers", return_value=(compute, plot)
        ), patch.object(load_map, "_figure_data_url", return_value="data:image/png;base64,test"), patch.object(
            load_map.plt, "close"
        ):
            tile = load_map.render(ctx)

        self.assertEqual(compute_call["view"], "toroidal")
        self.assertEqual(compute_call["channel"], "particle")
        self.assertEqual(compute_call["target"], "inner")
        self.assertEqual(compute_call["component"], "electron")
        self.assertTrue(compute_call["include_sheath"])
        self.assertEqual(plot_call["values"], "map")
        self.assertEqual(plot_call["ylim"], (10.0, 90.0))
        self.assertEqual(plot_call["contour_count"], 32)
        self.assertEqual(tile["media_type"], "image")

    def test_target_totals_render_maps_control_to_wall(self):
        compute_call = {}
        plot_call = {}

        def compute(data_dir, **kwargs):
            compute_call["data_dir"] = data_dir
            compute_call.update(kwargs)
            return ["total"]

        def plot(points, **kwargs):
            plot_call["points"] = points
            plot_call.update(kwargs)
            return self.figure

        ctx = {
            "options": {
                "show_particle": False,
                "show_power": True,
                "show_outer": False,
                "show_inner": True,
                "show_total": False,
                "show_control": True,
                "show_ions": False,
                "show_electrons": True,
                "show_target_total": False,
            }
        }
        with patch.object(target_totals, "_resolve_data_dir", return_value=self.data_dir), patch.object(
            target_totals, "_import_divertor_helpers", return_value=(compute, plot)
        ), patch.object(
            target_totals, "_figure_data_url", return_value="data:image/png;base64,test"
        ), patch.object(target_totals.plt, "close"):
            tile = target_totals.render(ctx)

        self.assertFalse(compute_call["show_outer"])
        self.assertTrue(compute_call["show_inner"])
        self.assertFalse(compute_call["show_total"])
        self.assertTrue(compute_call["show_wall"])
        self.assertFalse(plot_call["show_particle"])
        self.assertTrue(plot_call["show_power"])
        self.assertTrue(plot_call["show_control"])
        self.assertEqual(tile["media_type"], "image")


if __name__ == "__main__":
    unittest.main()
