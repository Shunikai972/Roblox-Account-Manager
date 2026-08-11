"""Bounded, incremental parsing of local Roblox client log files.

The historical ``RobloxProcess`` object tailed a client log to infer a small
set of lifecycle transitions.  This module ports that observation layer as a
poll-driven component: it does not inspect process memory, invoke helper
binaries, alter a client, or expose raw log lines.  Callers decide whether and
how typed events should affect a process monitor or UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
import os
from pathlib import Path
import re
from threading import RLock
import time
from typing import Any, Callable

from app.backend.core.errors import ValidationError


Clock = Callable[[], float]

_DEFAULT_MAX_READ_BYTES = 256 * 1024
_DEFAULT_MAX_LINE_BYTES = 16 * 1024
_DEFAULT_MAX_EVENTS = 256
_MAX_READ_BYTES = 4 * 1024 * 1024
_MAX_LINE_BYTES = 256 * 1024
_MAX_EVENTS = 2_048

# Patterns are deliberately local and versioned with this module.  Unlike the
# historical watcher, no remote regular-expression file is fetched at runtime.
_JOINED_GAME = re.compile(
    r"\[FLog::Output\]\s*!\s*Joining game\s+'(?P<job_id>[A-Za-z0-9-]{1,128})'\s+place\s+(?P<place_id>\d+)",
    re.IGNORECASE,
)
_DISCONNECTED = re.compile(r"\[FLog::Network\]\s*Sending disconnect with reason:\s*(?P<code>\d+)", re.IGNORECASE)
_DATA_MODEL_STARTED = (
    re.compile(r"\[FLog::UGCGameController\].*?initialized DataModel\((?P<id>[A-Fa-f0-9]+)\)", re.IGNORECASE),
    re.compile(r"\[FLog::SurfaceController\].*?::start dataModel\((?P<id>[A-Fa-f0-9]+)\)", re.IGNORECASE),
)
_DATA_MODEL_STOPPED = re.compile(
    r"\[FLog::UGCGameController\].*?::leave\s+\(blocking:\d+\)\s+dataModel\((?P<id>[A-Fa-f0-9]+)\)",
    re.IGNORECASE,
)
_DATA_MODEL_PAUSED = re.compile(
    r"\[FLog::SurfaceController\].*?::pause dataModel\((?P<id>[A-Fa-f0-9]+)\)",
    re.IGNORECASE,
)
_DATA_MODEL_STOPPED_AFTER_PAUSE = re.compile(r"\[FLog::SurfaceController\].*?::stop", re.IGNORECASE)
_RETURNED_TO_APP = re.compile(
    r"\[FLog::SingleSurfaceApp\]\s*returnToLuaApp:.*?returning from game\.",
    re.IGNORECASE,
)


class RobloxLogEventKind(str, Enum):
    """Typed lifecycle and parser events produced by :class:`RobloxLogTailer`."""

    GAME_JOINED = "game_joined"
    DISCONNECTED = "disconnected"
    DATA_MODEL_STARTED = "data_model_started"
    DATA_MODEL_PAUSED = "data_model_paused"
    DATA_MODEL_STOPPED = "data_model_stopped"
    RETURNED_TO_APP = "returned_to_app"
    LOG_ROTATED = "log_rotated"
    LOG_TRUNCATED = "log_truncated"
    LOG_UNAVAILABLE = "log_unavailable"
    LINE_DROPPED = "line_dropped"
    EVENTS_DROPPED = "events_dropped"


@dataclass(frozen=True, slots=True)
class RobloxLogEvent:
    """A bridge-safe event without its source line or local file path."""

    kind: RobloxLogEventKind
    occurred_at: str
    place_id: int | None = None
    job_id: str | None = None
    disconnect_code: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "occurred_at": self.occurred_at,
            "place_id": self.place_id,
            "job_id": self.job_id,
            "disconnect_code": self.disconnect_code,
        }


@dataclass(frozen=True, slots=True)
class RobloxLogSnapshot:
    """One poll result and the non-sensitive lifecycle state inferred so far."""

    available: bool
    offset: int
    connected: bool
    in_game: bool
    place_id: int | None
    job_id: str | None
    events: tuple[RobloxLogEvent, ...]


class RobloxLogTailer:
    """Incrementally parse one Roblox Player log, including rotation/truncation.

    ``poll`` is intentionally synchronous and performs at most
    ``max_read_bytes`` of local I/O.  It is safe to call from an existing
    watcher scheduler.  Missing/unreadable files become typed availability
    events instead of raising process-wide errors, while malformed or unknown
    log content is simply ignored.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        verify_data_model: bool = True,
        max_read_bytes: int = _DEFAULT_MAX_READ_BYTES,
        max_line_bytes: int = _DEFAULT_MAX_LINE_BYTES,
        max_events_per_poll: int = _DEFAULT_MAX_EVENTS,
        clock: Clock = time.time,
    ) -> None:
        self._path = Path(path)
        if not isinstance(verify_data_model, bool):
            raise ValidationError("DataModel verification must be boolean.")
        self._verify_data_model = verify_data_model
        self._max_read_bytes = _bounded_int(
            max_read_bytes,
            minimum=1,
            maximum=_MAX_READ_BYTES,
            message="Roblox log read size is invalid.",
        )
        self._max_line_bytes = _bounded_int(
            max_line_bytes,
            minimum=128,
            maximum=_MAX_LINE_BYTES,
            message="Roblox log max line size is invalid.",
        )
        self._max_events_per_poll = _bounded_int(
            max_events_per_poll,
            minimum=1,
            maximum=_MAX_EVENTS,
            message="Roblox log event limit is invalid.",
        )
        self._clock = clock
        self._lock = RLock()
        self._offset = 0
        self._fingerprint: tuple[int, int] | None = None
        self._partial = b""
        self._connected = False
        self._in_game = False
        self._place_id: int | None = None
        self._job_id: str | None = None
        self._data_model_id: str | None = None
        self._data_model_paused = False
        self._data_model_stopped = False
        self._available: bool | None = None

    @property
    def path(self) -> Path:
        """The local log source, retained for the owning backend only."""

        return self._path

    def poll(self) -> RobloxLogSnapshot:
        """Read newly appended bytes and return only typed lifecycle events."""

        with self._lock:
            events: list[RobloxLogEvent] = []
            try:
                metadata = self._path.stat()
            except (FileNotFoundError, PermissionError, OSError):
                self._emit_availability_change(events, available=False)
                return self._snapshot(events)

            self._emit_availability_change(events, available=True)
            fingerprint = _fingerprint(metadata)
            if self._fingerprint is not None and fingerprint is not None and fingerprint != self._fingerprint:
                self._reset_file_position()
                self._append(events, RobloxLogEventKind.LOG_ROTATED)
            elif metadata.st_size < self._offset:
                self._reset_file_position()
                self._append(events, RobloxLogEventKind.LOG_TRUNCATED)
            self._fingerprint = fingerprint

            if metadata.st_size <= self._offset:
                return self._snapshot(events)

            read_length = min(metadata.st_size - self._offset, self._max_read_bytes)
            try:
                with self._path.open("rb") as log_file:
                    log_file.seek(self._offset)
                    content = log_file.read(read_length)
            except (FileNotFoundError, PermissionError, OSError):
                self._emit_availability_change(events, available=False)
                return self._snapshot(events)

            self._offset += len(content)
            self._consume_bytes(content, events)
            return self._snapshot(events)

    def _consume_bytes(self, content: bytes, events: list[RobloxLogEvent]) -> None:
        buffer = self._partial + content
        lines = buffer.split(b"\n")
        self._partial = lines.pop()
        for raw_line in lines:
            if len(raw_line) > self._max_line_bytes:
                self._append(events, RobloxLogEventKind.LINE_DROPPED)
                continue
            # Logs are only decoded after they are bounded and are never
            # returned or logged.  Replacement protects the parser from a
            # partial/malformed byte sequence.
            self._consume_line(raw_line.decode("utf-8", errors="replace"), events)

        if len(self._partial) > self._max_line_bytes:
            self._partial = b""
            self._append(events, RobloxLogEventKind.LINE_DROPPED)

    def _consume_line(self, line: str, events: list[RobloxLogEvent]) -> None:
        joined = _JOINED_GAME.search(line)
        if joined is not None:
            place_id = _positive_int_or_none(joined.group("place_id"))
            job_id = joined.group("job_id")
            if place_id is not None:
                self._connected = True
                self._in_game = True
                self._place_id = place_id
                self._job_id = job_id
                self._append(events, RobloxLogEventKind.GAME_JOINED, place_id=place_id, job_id=job_id)
                return

        disconnected = _DISCONNECTED.search(line)
        if disconnected is not None:
            self._connected = False
            self._in_game = False
            self._append(
                events,
                RobloxLogEventKind.DISCONNECTED,
                disconnect_code=_positive_int_or_none(disconnected.group("code")),
            )
            return

        for pattern in _DATA_MODEL_STARTED:
            started = pattern.search(line)
            if started is not None:
                self._data_model_id = started.group("id").casefold()
                self._data_model_paused = False
                self._data_model_stopped = False
                self._in_game = True
                self._append(events, RobloxLogEventKind.DATA_MODEL_STARTED)
                return

        paused = _DATA_MODEL_PAUSED.search(line)
        if paused is not None and self._is_current_data_model(paused.group("id")):
            self._data_model_paused = True
            self._append(events, RobloxLogEventKind.DATA_MODEL_PAUSED)
            return

        stopped = _DATA_MODEL_STOPPED.search(line)
        if stopped is not None and self._is_current_data_model(stopped.group("id")):
            self._data_model_stopped = True
            self._in_game = False
            self._append(events, RobloxLogEventKind.DATA_MODEL_STOPPED)
            return

        if _DATA_MODEL_STOPPED_AFTER_PAUSE.search(line) is not None and self._data_model_paused:
            self._data_model_stopped = True
            self._in_game = False
            self._append(events, RobloxLogEventKind.DATA_MODEL_STOPPED)
            return

        if _RETURNED_TO_APP.search(line) is not None:
            if not self._verify_data_model or self._data_model_paused or self._data_model_stopped:
                self._in_game = False
                self._data_model_id = None
                self._data_model_paused = False
                self._data_model_stopped = False
                self._append(events, RobloxLogEventKind.RETURNED_TO_APP)

    def _is_current_data_model(self, value: str) -> bool:
        return self._data_model_id is not None and value.casefold() == self._data_model_id

    def _reset_file_position(self) -> None:
        self._offset = 0
        self._partial = b""
        # A replacement/truncation can belong to a newly launched client.  Do
        # not carry an inferred in-game state into the next physical file.
        self._connected = False
        self._in_game = False
        self._place_id = None
        self._job_id = None
        self._data_model_id = None
        self._data_model_paused = False
        self._data_model_stopped = False

    def _emit_availability_change(self, events: list[RobloxLogEvent], *, available: bool) -> None:
        if self._available is not available:
            self._available = available
            if not available:
                self._append(events, RobloxLogEventKind.LOG_UNAVAILABLE)

    def _append(
        self,
        events: list[RobloxLogEvent],
        kind: RobloxLogEventKind,
        *,
        place_id: int | None = None,
        job_id: str | None = None,
        disconnect_code: int | None = None,
    ) -> None:
        if len(events) >= self._max_events_per_poll:
            if not any(event.kind is RobloxLogEventKind.EVENTS_DROPPED for event in events):
                events[-1] = RobloxLogEvent(
                    kind=RobloxLogEventKind.EVENTS_DROPPED,
                    occurred_at=_timestamp(self._clock()),
                )
            return
        events.append(
            RobloxLogEvent(
                kind=kind,
                occurred_at=_timestamp(self._clock()),
                place_id=place_id,
                job_id=job_id,
                disconnect_code=disconnect_code,
            )
        )

    def _snapshot(self, events: list[RobloxLogEvent]) -> RobloxLogSnapshot:
        return RobloxLogSnapshot(
            available=bool(self._available),
            offset=self._offset,
            connected=self._connected,
            in_game=self._in_game,
            place_id=self._place_id,
            job_id=self._job_id,
            events=tuple(events),
        )


def _fingerprint(metadata: os.stat_result) -> tuple[int, int] | None:
    device = getattr(metadata, "st_dev", 0)
    inode = getattr(metadata, "st_ino", 0)
    if isinstance(device, int) and isinstance(inode, int) and (device or inode):
        return (device, inode)
    return None


def _bounded_int(value: object, *, minimum: int, maximum: int, message: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValidationError(message)
    return value


def _positive_int_or_none(value: str) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if 0 < parsed <= 2**63 - 1 else None


def _timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=UTC).isoformat()


__all__ = [
    "RobloxLogEvent",
    "RobloxLogEventKind",
    "RobloxLogSnapshot",
    "RobloxLogTailer",
]
