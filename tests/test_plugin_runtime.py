import json
import os
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

try:
    __import__("adios2")
except ModuleNotFoundError:
    adios2 = types.ModuleType("adios2")
    adios2.FileReader = object
    sys.modules["adios2"] = adios2


import plugin_runtime


class PersonalPluginDiscoveryTests(unittest.TestCase):
    def write_plugin(self, plugin_dir, plugin_id):
        plugin_dir.mkdir(parents=True, exist_ok=True)
        (plugin_dir / f"{plugin_id}.py").write_text(
            textwrap.dedent(
                f"""
                PLUGIN_ID = '{plugin_id}'
                LABEL = '{plugin_id}'

                def supports(meta):
                    return meta.get('ndims') == 0
                """
            ),
            encoding="utf-8",
        )

    def test_external_plugin_can_use_relative_helper_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = Path(tmp)
            (plugin_dir / "_helper.py").write_text(
                textwrap.dedent(
                    """
                    CHOICES = ['from-helper']

                    def supports_scalar(meta):
                        return meta.get('ndims') == 0
                    """
                ),
                encoding="utf-8",
            )
            (plugin_dir / "relative_plugin.py").write_text(
                textwrap.dedent(
                    """
                    from ._helper import CHOICES, supports_scalar

                    PLUGIN_ID = 'external_relative_import_test'
                    LABEL = 'External relative import test'

                    def supports(meta):
                        return supports_scalar(meta)

                    def options_schema(meta):
                        return [
                            {
                                'key': 'mode',
                                'type': 'select',
                                'label': 'Mode',
                                'choices': CHOICES,
                                'default': CHOICES[0],
                            }
                        ]
                    """
                ),
                encoding="utf-8",
            )

            missing_default_dir = plugin_dir / "missing-default"
            with patch.object(
                plugin_runtime,
                "DEFAULT_PERSONAL_PLUGIN_DIR",
                missing_default_dir,
            ), patch.dict(os.environ, {"SEURAT_PLUGIN_PATH": str(plugin_dir)}):
                discovered = {
                    info.plugin_id: info
                    for info in plugin_runtime.discover_plugins()
                }
                self.assertIn("external_relative_import_test", discovered)

                names = plugin_runtime.supported_plugin_visualizations({"ndims": 0})
                self.assertIn("plugin:external_relative_import_test", names)

                schema = plugin_runtime.plugin_options_schema(
                    "external_relative_import_test",
                    {"ndims": 0},
                )
                self.assertEqual(schema[0]["choices"], ["from-helper"])

    def test_profile_plugin_paths_are_discovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "profile-plugins"
            profile_path = root / "profile.json"
            self.write_plugin(plugin_dir, "profile_plugin_path_test")
            profile_path.write_text(
                json.dumps({"plugin_paths": [str(plugin_dir)]}),
                encoding="utf-8",
            )

            with patch.object(
                plugin_runtime,
                "DEFAULT_PERSONAL_PLUGIN_DIR",
                root / "missing-default",
            ), patch.object(
                plugin_runtime,
                "DEFAULT_PROFILE_PATH",
                profile_path,
            ), patch.dict(os.environ, {"SEURAT_PLUGIN_PATH": ""}):
                discovered = {
                    info.plugin_id: info
                    for info in plugin_runtime.discover_plugins()
                }
                self.assertIn("profile_plugin_path_test", discovered)

    def test_plugin_dirs_merge_profile_env_and_deduplicate_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            default_dir = root / "default"
            profile_dir = root / "profile"
            env_dir = root / "env"
            profile_path = root / "profile.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "plugin_paths": [
                            "$SEURAT_PROFILE_PLUGIN_DIR",
                            str(profile_dir),
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(
                plugin_runtime,
                "DEFAULT_PERSONAL_PLUGIN_DIR",
                default_dir,
            ), patch.object(
                plugin_runtime,
                "DEFAULT_PROFILE_PATH",
                profile_path,
            ), patch.dict(
                os.environ,
                {
                    "SEURAT_PROFILE_PLUGIN_DIR": str(profile_dir),
                    "SEURAT_PLUGIN_PATH": os.pathsep.join(
                        [str(profile_dir), str(env_dir)]
                    ),
                },
            ):
                self.assertEqual(
                    plugin_runtime._personal_plugin_dirs(),
                    [default_dir, profile_dir, env_dir],
                )

    def test_malformed_profile_does_not_block_env_plugin_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "env-plugins"
            profile_path = root / "profile.json"
            self.write_plugin(plugin_dir, "env_plugin_with_bad_profile_test")
            profile_path.write_text("{bad json", encoding="utf-8")

            with patch.object(
                plugin_runtime,
                "DEFAULT_PERSONAL_PLUGIN_DIR",
                root / "missing-default",
            ), patch.object(
                plugin_runtime,
                "DEFAULT_PROFILE_PATH",
                profile_path,
            ), patch.dict(os.environ, {"SEURAT_PLUGIN_PATH": str(plugin_dir)}):
                discovered = {
                    info.plugin_id: info
                    for info in plugin_runtime.discover_plugins()
                }
                self.assertIn("env_plugin_with_bad_profile_test", discovered)


class AxisPluginRuntimeTests(unittest.TestCase):
    def test_plugin_render_adds_execution_and_scientific_provenance(self):
        candidate = {
            "variable_id": "rho",
            "variable_name": "Density",
            "variable_path": "run.bp/rho",
            "metadata": {"Shape": "4,4"},
            "source_fields": {"source_dataset": "run/output.bp"},
        }
        plugin = types.SimpleNamespace(
            __name__="example_plugins.density",
            PLUGIN_ID="density-heatmap",
            LABEL="Density heatmap",
            PLUGIN_VERSION="2.1",
            options_schema=lambda _meta: [
                {
                    "key": "colormap",
                    "type": "select",
                    "label": "Colormap",
                    "choices": ["viridis", "plasma"],
                    "default": "viridis",
                }
            ],
            render=lambda _ctx: {
                "media_type": "image",
                "status": "ok",
                "visualization_activity_provenance": {
                    "workflow_plan": {"label": "Custom density workflow"}
                },
            },
            provenance=lambda _ctx, _tile: {
                "intent": "Inspect density structure.",
                "hypothesis": "A sharp interface is present.",
                "observations": ["The interface is displaced."],
                "conclusion": "The interface moved.",
                "outcome": "supported",
            },
        )

        with patch("plugin_runtime.load_plugin", return_value=plugin):
            tile = plugin_runtime.render_plugin_tile(
                "/campaign/example.aca",
                "density-heatmap",
                candidate,
                options={"colormap": "plasma"},
            )

        execution = tile["plugin_execution_provenance"]
        provenance = tile["visualization_activity_provenance"]
        self.assertEqual(execution["plugin_id"], "density-heatmap")
        self.assertEqual(execution["plugin_module"], "example_plugins.density")
        self.assertEqual(execution["plugin_version"], "2.1")
        self.assertEqual(execution["normalized_options"], {"colormap": "plasma"})
        self.assertEqual(execution["input_variables"], ["rho"])
        self.assertEqual(execution["source_datasets"], ["run/output.bp"])
        self.assertEqual(execution["status"], "success")
        self.assertEqual(
            execution["scientific_context"]["outcome"],
            "supported",
        )
        self.assertEqual(
            provenance["workflow_plan"]["label"],
            "Custom density workflow",
        )
        self.assertEqual(
            provenance["activity_agent"],
            {
                "label": "Density heatmap",
                "type": "SoftwareAgent",
                "version": "2.1",
            },
        )
        self.assertEqual(
            provenance["activity_metadata"]["scientific_context"]["conclusion"],
            "The interface moved.",
        )
        self.assertEqual(
            tile["visualization_variables"],
            [
                {
                    "name": "Density",
                    "roles": ["source"],
                    "source_dataset": "run/output.bp",
                    "variable_id": "rho",
                }
            ],
        )

    def test_plugin_provenance_hook_failure_does_not_discard_plot(self):
        candidate = {
            "variable_id": "rho",
            "variable_name": "Density",
            "source_fields": {"source_dataset": "run/output.bp"},
        }

        def fail_provenance(_ctx, _tile):
            raise RuntimeError("annotation failed")

        plugin = types.SimpleNamespace(
            PLUGIN_ID="density-test",
            LABEL="Density test",
            render=lambda _ctx: {"media_type": "plot1d", "status": "ok"},
            provenance=fail_provenance,
        )

        with patch("plugin_runtime.load_plugin", return_value=plugin):
            tile = plugin_runtime.render_plugin_tile(
                "/campaign/example.aca",
                "density-test",
                candidate,
            )

        self.assertEqual(tile["status"], "ok")
        self.assertEqual(
            tile["plugin_execution_provenance"]["annotation_error_type"],
            "RuntimeError",
        )

    def test_plugin_meta_and_tile_preserve_axis_semantics(self):
        shot_key = "lasernet:laser_runs:shot"
        axes = {
            "shot": {
                "id": "shot",
                "key": shot_key,
                "label": "Shot number",
                "values": [15.0, 16.0],
            }
        }
        candidate = {
            "variable_id": "energy",
            "variable_name": "Energy",
            "variable_path": "run.bp/energy",
            "metadata": {"Shape": "2", "AvailableStepsCount": "1"},
            "source_fields": {"source_dataset": "run.bp"},
            "axes": axes,
            "dimension_axes": ["shot"],
            "plot_x_axis": "shot",
            "selection_axis": "shot",
            "schema_default_axis": "shot",
        }
        plugin = types.SimpleNamespace(
            PLUGIN_ID="axis-test",
            LABEL="Axis test",
            supports=lambda meta: meta["selection_axis"] == "shot",
            render=lambda ctx: {
                "media_type": "plot1d",
                "plot": {
                    "x_label": "Shot number",
                    "series": [{"x": [15.0, 16.0], "y": [1.0, 2.0]}],
                },
                "status": "ok",
            },
        )

        with patch("plugin_runtime.load_plugin", return_value=plugin):
            tile = plugin_runtime.render_plugin_tile(
                "/campaign/example.aca",
                "axis-test",
                candidate,
            )

        self.assertEqual(tile["axes"], axes)
        self.assertEqual(tile["dimension_axes"], ["shot"])
        self.assertEqual(tile["plot_axis_key"], shot_key)
        self.assertEqual(tile["selection_axis"]["key"], shot_key)
        self.assertEqual(tile["selection_axis"]["index"], 0)
        self.assertEqual(tile["selection_axis"]["value"], 15.0)
        self.assertTrue(tile["selection_axis"]["default"])

    def test_plugin_helper_reads_selected_coordinate_row(self):
        helper = plugin_runtime.PluginHelpers(
            "/campaign/example.aca",
            "run.bp",
        )
        coordinate = np.asarray([[0.0, 0.5, 1.0], [0.1, 0.6, 1.1]])
        with patch.object(
            helper,
            "read_variable",
            return_value=coordinate[1:2],
        ) as read_variable:
            values = helper.read_axis_values(
                {
                    "variable_path": "run.bp/trace/time",
                    "shape": [2, 3],
                },
                selection_index=1,
            )

        np.testing.assert_allclose(values, coordinate[1])
        read_variable.assert_called_once_with(
            "run.bp/trace/time",
            start=[1, 0],
            count=[1, 3],
        )


if __name__ == "__main__":
    unittest.main()
