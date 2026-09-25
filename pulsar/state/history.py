"""State owned by session-only workspace undo/redo history."""


def defaults():
    return {
        "workspaceCanUndo": False,
        "workspaceCanRedo": False,
        "workspaceUndoLabel": "",
        "workspaceRedoLabel": "",
        "workspaceHistoryError": "",
    }
