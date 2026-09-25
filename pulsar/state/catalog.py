"""State owned by the variable catalog, query toolbar, and help dialog."""


def defaults():
    return {
        "variableNames": [],
        "variableGroups": [],
        "filteredVariableGroups": [],
        "variableLabelsById": {},
        "variableSearchText": "",
        "variablePaneView": "variables",
        "variableGroupCollapsed": {},
        "variableGroupCollapsedByView": {"variables": {}, "files": {}},
        "showOnlyVisualizedVars": False,
        "selectedVar": "",
        "queryText": "",
        "queryStatus": "",
        "queryError": "",
        "queryFilter": {},
        "querySourceFilters": [],
        "querySourceRestrictionFilter": {},
        "querySourceRestrictionCount": 0,
        "queryViewLabel": "ALL",
        "activeViewerActionPlan": {},
        "activeNaturalLanguageQuery": "",
        "showHelpModal": False,
        "helpModalTitle": "",
        "helpModalText": "",
        "draggedVar": "",
    }
