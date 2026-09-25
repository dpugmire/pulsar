import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pulsar.native_file_dialog import (
    choose_workspace_load_path,
    choose_workspace_save_path,
)


class NativeFileDialogTests(unittest.TestCase):
    def test_macos_save_dialog_adds_json_extension_and_returns_absolute_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            selected = Path(temp_dir) / "chosen-name"
            with patch(
                "pulsar.native_file_dialog.platform.system",
                return_value="Darwin",
            ), patch(
                "pulsar.native_file_dialog._macos_save_path",
                return_value=str(selected),
            ) as dialog:
                result = choose_workspace_save_path(
                    "campaign.json",
                    campaign_path=str(Path(temp_dir) / "campaign.aca"),
                )

        self.assertEqual(result, f"{selected.resolve()}.json")
        dialog.assert_called_once_with("campaign.json", Path(temp_dir).resolve())

    def test_macos_load_dialog_returns_selected_absolute_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            selected = Path(temp_dir) / "chosen.json"
            selected.write_text("{}", encoding="utf-8")
            with patch(
                "pulsar.native_file_dialog.platform.system",
                return_value="Darwin",
            ), patch(
                "pulsar.native_file_dialog._macos_load_path",
                return_value=str(selected),
            ) as dialog:
                result = choose_workspace_load_path(
                    campaign_path=str(Path(temp_dir) / "campaign.aca"),
                )

        self.assertEqual(result, str(selected.resolve()))
        dialog.assert_called_once_with(Path(temp_dir).resolve())

    def test_canceled_dialog_returns_empty_path(self):
        with patch(
            "pulsar.native_file_dialog.platform.system",
            return_value="Darwin",
        ), patch(
            "pulsar.native_file_dialog._macos_save_path",
            return_value="",
        ):
            self.assertEqual(
                choose_workspace_save_path("campaign.json"),
                "",
            )


if __name__ == "__main__":
    unittest.main()
