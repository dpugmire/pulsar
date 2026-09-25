"""Append-only JSONL storage for Pulsar interaction events."""

import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from .events import EVENT_SCHEMA_VERSION, EVENT_TYPES, new_identifier


_PROFILE_ID_RE = re.compile(
    r"^profile:[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    flags=re.IGNORECASE,
)


def _utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _campaign_version_id(campaign_path: str) -> str:
    path = Path(str(campaign_path or "")).expanduser()
    identity: Dict[str, Any] = {"path": str(path.resolve(strict=False))}
    try:
        stat = path.stat()
        identity.update(
            {
                "size_bytes": int(stat.st_size),
                "mtime_ns": int(stat.st_mtime_ns),
            }
        )
    except OSError:
        identity["unavailable"] = True
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return "campaign:sha256:" + hashlib.sha256(encoded).hexdigest()


def _profile_id(directory: Path) -> str:
    profile_path = directory / ".pulsar-profile-id"
    try:
        existing = profile_path.read_text(encoding="utf-8").strip()
    except OSError:
        existing = ""
    if _PROFILE_ID_RE.fullmatch(existing):
        return existing
    if existing:
        digest = hashlib.sha256(existing.encode("utf-8", errors="replace")).hexdigest()
        return f"profile:sha256:{digest}"

    generated = f"profile:{uuid4()}"
    try:
        descriptor = os.open(
            str(profile_path),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError:
        try:
            raced = profile_path.read_text(encoding="utf-8").strip()
        except OSError:
            raced = ""
        return raced if _PROFILE_ID_RE.fullmatch(raced) else generated
    except OSError:
        return generated

    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(generated + "\n")
    return generated


class InteractionLog:
    """A failure-isolated, append-only interaction event writer."""

    def __init__(
        self,
        directory: str = "",
        *,
        campaign_path: str = "",
        max_megabytes: int = 64,
        model_version: str = "capture-v1",
    ):
        self.directory = Path(str(directory or "")).expanduser() if directory else None
        self.campaign_version_id = _campaign_version_id(campaign_path)
        self.model_version = str(model_version or "capture-v1")
        self.max_bytes = max(1, int(max_megabytes or 64)) * 1024 * 1024
        self.session_id = new_identifier("session")
        self.user_profile_id = ""
        self.path: Optional[Path] = None
        self.last_error = ""
        self._sequence = 0
        self._segment = 0
        self._stream = None
        self._bytes_written = 0
        self._lock = threading.Lock()
        self._started_monotonic = time.monotonic()
        self._closed = False

        if self.directory is None:
            return
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.user_profile_id = _profile_id(self.directory)
            self._open_segment()
            self.record(
                "session.started",
                source="application",
                payload={"logging_version": EVENT_SCHEMA_VERSION},
            )
        except Exception as error:
            self.last_error = f"{type(error).__name__}: {error}"
            self._close_stream()
            self.directory = None

    @property
    def enabled(self) -> bool:
        return self.directory is not None and self._stream is not None and not self._closed

    def _open_segment(self) -> None:
        if self.directory is None:
            return
        self._segment += 1
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        session_token = self.session_id.split(":", 1)[-1]
        name = (
            f"pulsar-interactions-{stamp}-{session_token}-{self._segment:04d}.jsonl"
        )
        self.path = self.directory / name
        descriptor = os.open(
            str(self.path),
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        self._stream = os.fdopen(descriptor, "a", encoding="utf-8", buffering=1)
        try:
            self._bytes_written = self.path.stat().st_size
        except OSError:
            self._bytes_written = 0

    def _close_stream(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        try:
            stream.flush()
            os.fsync(stream.fileno())
        except OSError:
            pass
        try:
            stream.close()
        except OSError:
            pass

    def _rotate_if_needed(self, encoded_size: int) -> None:
        if self._bytes_written <= 0 or self._bytes_written + encoded_size <= self.max_bytes:
            return
        self._close_stream()
        self._open_segment()

    def record(
        self,
        event_type: str,
        *,
        source: str,
        payload: Optional[Dict[str, Any]] = None,
        model_version: str = "",
    ) -> str:
        """Append one event and return its ID, or return empty text on failure."""

        event_name = str(event_type or "")
        if event_name not in EVENT_TYPES or not self.enabled:
            return ""
        raw_payload = dict(payload or {})

        try:
            with self._lock:
                if not self.enabled:
                    return ""
                self._sequence += 1
                event_id = new_identifier("event")
                event = {
                    "schema_version": EVENT_SCHEMA_VERSION,
                    "event_id": event_id,
                    "event_sequence": self._sequence,
                    "timestamp_utc": _utc_timestamp(),
                    "elapsed_session_ms": max(
                        0,
                        int((time.monotonic() - self._started_monotonic) * 1000),
                    ),
                    "user_profile_id": self.user_profile_id,
                    "session_id": self.session_id,
                    "campaign_version_id": self.campaign_version_id,
                    "event_type": event_name,
                    "source": str(source or "application"),
                    "model_version": str(model_version or self.model_version),
                    "payload": raw_payload,
                }
                encoded = json.dumps(
                    event,
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ) + "\n"
                encoded_size = len(encoded.encode("utf-8"))
                self._rotate_if_needed(encoded_size)
                if self._stream is None:
                    return ""
                self._stream.write(encoded)
                self._bytes_written += encoded_size
                self.last_error = ""
                return event_id
        except Exception as error:
            self.last_error = f"{type(error).__name__}: {error}"
            return ""

    def checkpoint(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            if self._stream is None:
                return
            try:
                self._stream.flush()
                os.fsync(self._stream.fileno())
                self.last_error = ""
            except OSError as error:
                self.last_error = f"{type(error).__name__}: {error}"

    def close(self) -> None:
        if not self.enabled:
            return
        self.record("session.ended", source="application", payload={})
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._close_stream()
