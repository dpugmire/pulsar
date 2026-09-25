"""State owned by source selection, details, and rendered media."""

from config import SOURCE_FIELDS


def details_defaults():
    return {
        "detailsSelectedVar": "",
        "detailsSelectedVarId": "",
        "detailsNumSources": 0,
        "detailsGlobalMin": "",
        "detailsGlobalMax": "",
        "detailsMeanMin": "",
        "detailsMeanMax": "",
        "detailsMedianMin": "",
        "detailsMedianMax": "",
        "detailsSourceRepresentation": {},
        "detailsDerivedRepresentations": [],
        "detailsProvenanceKind": "",
        "detailsProvenanceChain": "",
        "detailsProvenanceCompact": "",
        "detailsProvenanceNodes": [],
        "detailsProvenanceExpanded": {},
        "detailsProvenanceGraph": [],
        "detailsProvenanceContext": "variable",
        "showProvenanceModal": False,
        "showSourcesModal": False,
        "sourceDialogMode": "single",
        "sourceDialogCellIndex": -1,
        "sourceDialogTargetCellIndices": [],
        "sourceDialogTitle": "Sources",
        "sourceDialogStatus": "",
        "sourceDialogStatusIsError": False,
        "sourceRowsAll": [],
        "sourceRows": [],
        "sourceFilterDraftText": "",
        "sourceFilterText": "",
        "sourceFilterError": "",
        "sourceSortField": SOURCE_FIELDS[0],
        "sourceSortAsc": True,
        "selectedSourceKeys": [],
        "sourceDialogInitialSelectedSourceKeys": [],
        "selectedSourceLabel": "All sources",
    }


def media_defaults():
    return {
        "movieTiles": [],
        "movieStatus": "",
        "movieDetailsOpen": {},
        "tileVisualizationBySource": {},
    }


def defaults():
    return {**details_defaults(), **media_defaults()}
