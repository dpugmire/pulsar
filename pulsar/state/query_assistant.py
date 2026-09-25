"""State owned by the natural-language Query Assistant."""


def defaults():
    return {
        "showQueryAssistant": False,
        "queryAssistantAvailable": False,
        "queryAssistantProvider": "",
        "queryAssistantTarget": "catalog",
        "queryAssistantRequestText": "",
        "queryAssistantProposalText": "",
        "queryAssistantProposalSummary": "",
        "queryAssistantActionPlan": {},
        "queryAssistantExplanation": "",
        "queryAssistantAssumptions": [],
        "queryAssistantClarification": "",
        "queryAssistantStatus": "",
        "queryAssistantError": "",
        "queryAssistantBusy": False,
        "queryAssistantVariableCount": 0,
        "queryAssistantSourceCount": 0,
        "queryAssistantRankValue": None,
        "queryAssistantTieCount": 0,
        "queryAssistantValidatedText": "",
        "queryAssistantTargetCellIndex": -1,
        "queryAssistantVisualizationName": "",
    }
