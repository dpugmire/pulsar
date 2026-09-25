"""Native local file dialogs for workspace JSON files."""

import platform
import subprocess
from pathlib import Path


_JSON_FILE_TYPES = [("JSON files", "*.json")]


def _initial_directory(preferred_path: str, fallback_path: str) -> Path:
    candidates = []
    if preferred_path:
        preferred = Path(preferred_path).expanduser()
        candidates.append(preferred if preferred.is_dir() else preferred.parent)
    if fallback_path:
        fallback = Path(fallback_path).expanduser()
        candidates.append(fallback if fallback.is_dir() else fallback.parent)
    candidates.append(Path.home())
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    return Path.cwd().resolve()


def _run_macos_dialog(script: str, *arguments: str) -> str:
    result = subprocess.run(
        ["osascript", "-e", script, *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _macos_save_path(initial_name: str, initial_directory: Path) -> str:
    return _run_macos_dialog(
        """
on run argv
  set initialName to item 1 of argv
  set initialDirectory to POSIX file (item 2 of argv)
  try
    set selectedFile to choose file name with prompt "Save Pulsar State" default name initialName default location initialDirectory
    return POSIX path of selectedFile
  on error errorMessage number errorNumber
    if errorNumber is -128 then return ""
    error errorMessage number errorNumber
  end try
end run
""",
        initial_name,
        str(initial_directory),
    )


def _macos_load_path(initial_directory: Path) -> str:
    return _run_macos_dialog(
        """
on run argv
  set initialDirectory to POSIX file (item 1 of argv)
  try
    set selectedFile to choose file with prompt "Load Pulsar State" of type {"public.json"} default location initialDirectory
    return POSIX path of selectedFile
  on error errorMessage number errorNumber
    if errorNumber is -128 then return ""
    error errorMessage number errorNumber
  end try
end run
""",
        str(initial_directory),
    )


def _tk_root():
    try:
        from tkinter import Tk
    except (ImportError, OSError) as e:
        raise RuntimeError(f"Native file dialog is unavailable: {e}") from e

    root = Tk()
    root.withdraw()
    try:
        root.wm_attributes("-topmost", 1)
    except Exception:
        pass
    return root


def _tk_save_path(initial_name: str, initial_directory: Path) -> str:
    from tkinter import filedialog

    root = _tk_root()
    try:
        return str(
            filedialog.asksaveasfilename(
                parent=root,
                title="Save Pulsar State",
                initialdir=str(initial_directory),
                initialfile=initial_name,
                defaultextension=".json",
                filetypes=_JSON_FILE_TYPES,
            )
            or ""
        )
    finally:
        root.destroy()


def _tk_load_path(initial_directory: Path) -> str:
    from tkinter import filedialog

    root = _tk_root()
    try:
        return str(
            filedialog.askopenfilename(
                parent=root,
                title="Load Pulsar State",
                initialdir=str(initial_directory),
                filetypes=_JSON_FILE_TYPES,
            )
            or ""
        )
    finally:
        root.destroy()


def choose_workspace_save_path(
    initial_name: str,
    current_path: str = "",
    campaign_path: str = "",
) -> str:
    initial_directory = _initial_directory(current_path, campaign_path)
    if platform.system() == "Darwin":
        selected = _macos_save_path(initial_name, initial_directory)
    else:
        selected = _tk_save_path(initial_name, initial_directory)
    if not selected:
        return ""
    path = Path(selected).expanduser()
    if path.suffix.lower() != ".json":
        path = Path(f"{path}.json")
    return str(path.resolve())


def choose_workspace_load_path(
    current_path: str = "",
    campaign_path: str = "",
) -> str:
    initial_directory = _initial_directory(current_path, campaign_path)
    if platform.system() == "Darwin":
        selected = _macos_load_path(initial_directory)
    else:
        selected = _tk_load_path(initial_directory)
    if not selected:
        return ""
    return str(Path(selected).expanduser().resolve())
