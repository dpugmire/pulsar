"""Discovery helpers for local multi-campaign browsing."""

from pathlib import Path


def discover_campaign_archives(directory):
    """Return readable candidate paths in a directory, sorted by name."""
    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    return sorted(
        (str(path.resolve()) for path in root.iterdir()
         if path.is_file() and path.suffix.lower() == ".aca"),
        key=lambda value: (Path(value).name.casefold(), value),
    )
