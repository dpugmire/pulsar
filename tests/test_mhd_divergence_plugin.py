import unittest
from unittest.mock import Mock

import numpy as np

from pulsar_plugins import mhd_divergence_heatmap


class MhdDivergenceHeatmapTests(unittest.TestCase):
    def test_supports_only_2d_div_b(self):
        meta = {"ndims": 2, "steps_count": 3, "variable_name": "div_b"}
        self.assertTrue(mhd_divergence_heatmap.supports(meta))
        self.assertFalse(mhd_divergence_heatmap.supports({**meta, "ndims": 0}))
        self.assertFalse(
            mhd_divergence_heatmap.supports({**meta, "variable_name": "pressure"})
        )

    def test_renders_png_data_url_and_statistics(self):
        helpers = Mock()
        helpers.read_variable.return_value = np.asarray([[[[-2.0, 0.0], [1.0, 3.0]]]])
        tile = mhd_divergence_heatmap.render(
            {
                "helpers": helpers,
                "variable_path": "run/output.bp/div_b",
                "steps_count": 4,
                "options": {"step": 2, "symmetric": True},
            }
        )
        self.assertEqual(tile["media_type"], "image")
        self.assertTrue(tile["src"].startswith("data:image/png;base64,"))
        self.assertIn("step=2", tile["note"])
        helpers.read_variable.assert_called_once_with(
            "run/output.bp/div_b", step_selection=(2, 3)
        )


if __name__ == "__main__":
    unittest.main()
