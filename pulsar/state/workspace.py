"""State owned by workspace layout and JSON save/load controls."""

from pulsar.models.workspace_layout import (
    grid_snapshot,
    initial_workspace_layout,
    workspace_geometry,
)

from . import grid


def defaults():
    grid_defaults = grid.defaults()

    class _GridDefaults:
        pass

    state = _GridDefaults()
    for name, value in grid_defaults.items():
        setattr(state, name, value)
    layout = initial_workspace_layout(grid_snapshot(state))
    pane_frames, splitters = workspace_geometry(layout)
    return {
        "workspaceDrawerOpen": False,
        "workspaceStatePath": "",
        "workspaceStateStatus": "",
        "workspaceStateError": "",
        "workspaceLayout": layout,
        "workspacePanes": layout["panes"],
        "workspacePaneFrames": pane_frames,
        "workspaceSplitters": list(splitters),
        "workspaceSplitDirection": layout["split_direction"],
        "workspaceSplitRatio": layout["split_ratio"],
        "workspaceActivePaneId": layout["active_pane_id"],
        "workspaceActiveTabId": layout["active_tab_id"],
    }
