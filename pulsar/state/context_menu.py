"""State owned by the grid and variable context menu."""


def defaults():
    return {
        "contextMenuVisible": False,
        "contextMenuX": 0,
        "contextMenuY": 0,
        "contextMenuKind": "",
        "contextMenuItem": "",
        "contextMenuItemLabel": "",
        "contextMenuTabPaneId": "",
        "contextMenuTabId": "",
        "contextMenuTabCanClose": False,
        "contextMenuCellIndex": -1,
        "contextMenuCellHasVariable": False,
        "contextMenuCellCanAddSource": False,
        "contextMenuCellCanPlotSettings": False,
        "contextMenuCellCanScalarFieldSettings": False,
        "contextMenuCellCanResetView": False,
        "contextMenuCellVisualizationOptions": [],
        "contextMenuCellSelectedVisualization": "",
        "contextMenuCellSourcePlugins": [],
    }


def right_pane_reset_defaults():
    return {
        "contextMenuVisible": False,
        "contextMenuCellVisualizationOptions": [],
        "contextMenuCellSelectedVisualization": "",
        "contextMenuCellSourcePlugins": [],
        "contextMenuItemLabel": "",
        "contextMenuTabPaneId": "",
        "contextMenuTabId": "",
        "contextMenuTabCanClose": False,
        "contextMenuCellHasVariable": False,
        "contextMenuCellCanAddSource": False,
        "contextMenuCellCanScalarFieldSettings": False,
        "contextMenuCellCanResetView": False,
    }
