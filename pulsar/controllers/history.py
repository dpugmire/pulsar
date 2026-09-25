"""Workspace undo/redo controller actions."""


class HistoryControllerMixin:
    ACTION_BINDINGS = (
        ("undo_workspace", "undo_workspace"),
        ("redo_workspace", "redo_workspace"),
    )
    TRIGGER_BINDINGS = (
        ("undo_workspace_trigger", "undo_workspace"),
        ("redo_workspace_trigger", "redo_workspace"),
    )
    STATE_CHANGE_BINDINGS = ()
    HISTORY_ACTIONS = {}
    HISTORY_TRIGGERS = {}

    def undo_workspace(self, **_):
        return self.history.undo()

    def redo_workspace(self, **_):
        return self.history.redo()
