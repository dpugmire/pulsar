"""Transaction-framed, snapshot-backed workspace edit history."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import json
from typing import Any, Callable, Dict, Iterator, List, Mapping, Tuple


DEFAULT_HISTORY_DEPTH = 50
DEFAULT_HISTORY_BYTES = 32 * 1024 * 1024


def _canonical_bytes(snapshot: Mapping[str, Any]) -> bytes:
    return json.dumps(
        snapshot,
        # History is session-only. Preserve non-finite values from imported
        # metadata/settings without weakening durable workspace JSON.
        allow_nan=True,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


@dataclass(frozen=True)
class HistoryEntry:
    """One committed user edit and the semantic states on either side."""

    label: str
    before: Dict[str, Any]
    after: Dict[str, Any]
    size_bytes: int


class WorkspaceMutationCoordinator:
    """Own undo/redo framing for all history-relevant workspace mutations."""

    def __init__(
        self,
        state: Any,
        capture: Callable[[], Dict[str, Any]],
        restore: Callable[[Mapping[str, Any]], None],
        *,
        validate: Callable[[], None] | None = None,
        max_entries: int = DEFAULT_HISTORY_DEPTH,
        max_bytes: int = DEFAULT_HISTORY_BYTES,
    ):
        self.state = state
        self._capture = capture
        self._restore = restore
        self._validate = validate
        self.max_entries = max(1, int(max_entries))
        self.max_bytes = max(1, int(max_bytes))
        self._undo: List[HistoryEntry] = []
        self._redo: List[HistoryEntry] = []
        self._depth = 0
        self._suspend_depth = 0
        self._publish()

    @property
    def undo_entries(self) -> Tuple[HistoryEntry, ...]:
        return tuple(self._undo)

    @property
    def redo_entries(self) -> Tuple[HistoryEntry, ...]:
        return tuple(self._redo)

    @property
    def is_restoring(self) -> bool:
        return self._suspend_depth > 0

    def _publish(self, error: str = "") -> None:
        self.state.workspaceCanUndo = bool(self._undo)
        self.state.workspaceCanRedo = bool(self._redo)
        self.state.workspaceUndoLabel = (
            self._undo[-1].label if self._undo else ""
        )
        self.state.workspaceRedoLabel = (
            self._redo[-1].label if self._redo else ""
        )
        self.state.workspaceHistoryError = str(error or "")

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
        self._publish()

    @contextmanager
    def suspended(self) -> Iterator[None]:
        self._suspend_depth += 1
        try:
            yield
        finally:
            self._suspend_depth -= 1

    def _restore_safely(self, snapshot: Mapping[str, Any]) -> None:
        with self.suspended():
            self._restore(deepcopy(dict(snapshot)))

    def _trim(self) -> None:
        while len(self._undo) > self.max_entries:
            self._undo.pop(0)
        while (
            self._undo
            and sum(item.size_bytes for item in self._undo) > self.max_bytes
        ):
            self._undo.pop(0)

    @contextmanager
    def transaction(self, label: str) -> Iterator[None]:
        """Frame one committed edit; nested frames coalesce into the outer one."""

        if self.is_restoring:
            yield
            return

        if self._depth:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return

        before = self._capture()
        before_bytes = _canonical_bytes(before)
        self._depth = 1
        try:
            yield
            after = self._capture()
            after_bytes = _canonical_bytes(after)
        except Exception as error:
            try:
                self._restore_safely(before)
            finally:
                self._publish(f"Edit rolled back: {error}")
            raise
        finally:
            self._depth = 0

        if before_bytes == after_bytes:
            self._publish()
            return

        if self._validate is not None:
            try:
                self._validate()
            except Exception as error:
                try:
                    self._restore_safely(before)
                finally:
                    self._publish(f"Edit rolled back: {error}")
                raise

        entry = HistoryEntry(
            label=str(label or "Edit workspace"),
            before=deepcopy(before),
            after=deepcopy(after),
            size_bytes=len(before_bytes) + len(after_bytes),
        )
        self._redo.clear()
        if entry.size_bytes <= self.max_bytes:
            self._undo.append(entry)
            self._trim()
            self._publish()
        else:
            self._publish(
                f'“{entry.label}” is too large to retain in undo history.'
            )

    def _apply_entry(self, entry: HistoryEntry, *, redo: bool) -> bool:
        current = self._capture()
        target = entry.after if redo else entry.before
        try:
            self._restore_safely(target)
            if self._validate is not None:
                self._validate()
            self._capture()
        except Exception as error:
            try:
                self._restore_safely(current)
            finally:
                operation = "Redo" if redo else "Undo"
                self._publish(f"{operation} failed: {error}")
            return False
        return True

    def undo(self) -> bool:
        if not self._undo:
            self._publish()
            return False
        entry = self._undo[-1]
        if not self._apply_entry(entry, redo=False):
            return False
        self._undo.pop()
        self._redo.append(entry)
        self._publish()
        return True

    def redo(self) -> bool:
        if not self._redo:
            self._publish()
            return False
        entry = self._redo[-1]
        if not self._apply_entry(entry, redo=True):
            return False
        self._redo.pop()
        self._undo.append(entry)
        self._trim()
        self._publish()
        return True
