"""Conservative runtime wiring for local Roblox Player log observation.

The historical watcher used an external handle-inspection utility to associate
one process with one open Player log.  Astro deliberately does not use a
helper executable, process-handle inspection, or command-line scraping.  It
therefore makes an association only in the narrow case where the current
Windows user has exactly one observed Roblox process and exactly one bounded,
eligible Player log.  Any other case remains explicitly unassociated.

This module only turns the already-redacted events from
``RobloxLogTailer`` into PID-scoped observations.  It never asks the process
monitor to close, relaunch, bind, or otherwise alter a Roblox client.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
import os
import re
from threading import RLock
from typing import Any

from app.backend.core.errors import ValidationError

from .roblox_log_watcher import RobloxLogEvent, RobloxLogEventKind, RobloxLogTailer


_DEFAULT_MAX_DIRECTORY_ENTRIES = 256
_DEFAULT_MAX_CANDIDATES = 32
_DEFAULT_MAX_FILE_BYTES = 64 * 1024 * 1024
_DEFAULT_MAX_HISTORY = 256
_MAX_DIRECTORY_ENTRIES = 4_096
_MAX_CANDIDATES = 256
_MAX_FILE_BYTES = 512 * 1024 * 1024
_MAX_HISTORY = 2_048

# Player logs historically followed ``*_Player_*_last.log``.  Restricting the
# filename keeps this observer out of arbitrary application logs while still
# accepting the timestamp/version separators used by Roblox releases.
_PLAYER_LOG_NAME = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,255}_Player_[A-Za-z0-9_.-]{1,256}_last\.log$",
    re.IGNORECASE,
)

TailerFactory = Callable[[Path], RobloxLogTailer]


@dataclass(frozen=True, slots=True)
class RobloxPlayerLogCandidate:
    """An internal, bounded local candidate.

    ``path`` intentionally stays inside the backend/runtime layer.  No bridge
    payload is ever formed from this type.
    """

    path: Path
    modified_at: float
    size_bytes: int


@dataclass(frozen=True, slots=True)
class RobloxPlayerLogDiscoverySnapshot:
    """Result of a bounded local directory inspection."""

    directory_available: bool
    complete: bool
    candidates: tuple[RobloxPlayerLogCandidate, ...]


class RobloxPlayerLogDiscovery:
    """Discover only current-user Roblox Player logs using bounded I/O.

    The default source is ``%LOCALAPPDATA%\\Roblox\\logs``.  If the current
    environment does not provide ``LOCALAPPDATA`` (for example a non-Windows
    test host), discovery is simply unavailable; it never falls back to a
    broad home-directory search.
    """

    def __init__(
        self,
        directory: Path | str | None = None,
        *,
        max_directory_entries: int = _DEFAULT_MAX_DIRECTORY_ENTRIES,
        max_candidates: int = _DEFAULT_MAX_CANDIDATES,
        max_file_bytes: int = _DEFAULT_MAX_FILE_BYTES,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._directory = Path(directory) if directory is not None else _current_user_logs_directory(environ)
        self._max_directory_entries = _bounded_int(
            max_directory_entries,
            minimum=1,
            maximum=_MAX_DIRECTORY_ENTRIES,
            message="Roblox log file limit is invalid.",
        )
        self._max_candidates = _bounded_int(
            max_candidates,
            minimum=1,
            maximum=_MAX_CANDIDATES,
            message="Roblox log candidate limit is invalid.",
        )
        self._max_file_bytes = _bounded_int(
            max_file_bytes,
            minimum=1,
            maximum=_MAX_FILE_BYTES,
            message="Roblox log max file size is invalid.",
        )

    @property
    def directory(self) -> Path | None:
        """Internal source directory; it is not bridge data."""

        return self._directory

    def discover(self) -> RobloxPlayerLogDiscoverySnapshot:
        """Inspect at most the configured number of current-user entries."""

        directory = self._directory
        if directory is None:
            return RobloxPlayerLogDiscoverySnapshot(False, True, ())
        try:
            if not directory.is_dir():
                return RobloxPlayerLogDiscoverySnapshot(False, True, ())
        except OSError:
            return RobloxPlayerLogDiscoverySnapshot(False, True, ())

        candidates: list[RobloxPlayerLogCandidate] = []
        complete = True
        try:
            with os.scandir(directory) as entries:
                # Do not consume a look-ahead entry merely to learn whether a
                # directory is larger.  At the configured cap the result is
                # conservatively marked incomplete instead.
                for _ in range(self._max_directory_entries):
                    try:
                        entry = next(entries)
                    except StopIteration:
                        break
                    if not _PLAYER_LOG_NAME.fullmatch(entry.name):
                        continue
                    # A symlink/reparse point is deliberately not followed:
                    # discovery should never become a generic local-file reader.
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    metadata = entry.stat(follow_symlinks=False)
                    if metadata.st_size < 0 or metadata.st_size > self._max_file_bytes:
                        continue
                    candidates.append(
                        RobloxPlayerLogCandidate(
                            path=Path(entry.path),
                            modified_at=float(metadata.st_mtime),
                            size_bytes=int(metadata.st_size),
                        )
                    )
                    if len(candidates) >= self._max_candidates:
                        complete = False
                        break
                else:
                    complete = False
        except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
            return RobloxPlayerLogDiscoverySnapshot(False, True, ())

        candidates.sort(key=lambda candidate: (candidate.modified_at, candidate.path.name.casefold()), reverse=True)
        return RobloxPlayerLogDiscoverySnapshot(True, complete, tuple(candidates))


@dataclass(frozen=True, slots=True)
class RobloxInstanceLogEvent:
    """A PID-scoped, bridge-safe lifecycle observation.

    The event has no raw source text, file path, executable path, command line,
    cookie, or other credential-bearing data.
    """

    kind: RobloxLogEventKind
    occurred_at: str
    pid: int
    place_id: int | None = None
    job_id: str | None = None
    disconnect_code: int | None = None

    @classmethod
    def from_log_event(cls, event: RobloxLogEvent, *, pid: int) -> "RobloxInstanceLogEvent":
        return cls(
            kind=event.kind,
            occurred_at=event.occurred_at,
            pid=pid,
            place_id=event.place_id,
            job_id=event.job_id,
            disconnect_code=event.disconnect_code,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "occurred_at": self.occurred_at,
            "pid": self.pid,
            "place_id": self.place_id,
            "job_id": self.job_id,
            "disconnect_code": self.disconnect_code,
        }


@dataclass(frozen=True, slots=True)
class RobloxLogRuntimeSnapshot:
    """Redacted state of the conservative local log observer."""

    directory_available: bool
    discovery_complete: bool
    candidate_count: int
    observed_instance_count: int
    association_state: str
    associated_pid: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "directory_available": self.directory_available,
            "discovery_complete": self.discovery_complete,
            "candidate_count": self.candidate_count,
            "observed_instance_count": self.observed_instance_count,
            "association_state": self.association_state,
            "associated_pid": self.associated_pid,
        }


class RobloxPlayerLogRuntime:
    """Poll a Player log only while the PID-to-log association is unique.

    The public runtime state intentionally exposes counts and association status
    rather than local filenames.  ``poll`` has no callback into the process
    monitor, which makes log events observational only by construction.
    """

    def __init__(
        self,
        *,
        discovery: RobloxPlayerLogDiscovery | None = None,
        tailer_factory: TailerFactory = RobloxLogTailer,
        max_history: int = _DEFAULT_MAX_HISTORY,
    ) -> None:
        if not callable(tailer_factory):
            raise ValidationError("Roblox log tailer factory is invalid.")
        self._discovery = discovery or RobloxPlayerLogDiscovery()
        self._tailer_factory = tailer_factory
        self._max_history = _bounded_int(
            max_history,
            minimum=1,
            maximum=_MAX_HISTORY,
            message="Roblox log history limit is invalid.",
        )
        self._lock = RLock()
        self._tailer: RobloxLogTailer | None = None
        self._association: tuple[int, Path] | None = None
        self._history: deque[RobloxInstanceLogEvent] = deque(maxlen=self._max_history)
        self._snapshot = RobloxLogRuntimeSnapshot(
            directory_available=False,
            discovery_complete=True,
            candidate_count=0,
            observed_instance_count=0,
            association_state="directory_unavailable",
            associated_pid=None,
        )

    def poll(
        self, instances: Iterable[object], *, process_scan_complete: bool = True
    ) -> RobloxLogRuntimeSnapshot:
        """Poll once without associating ambiguous processes or logs.

        A fresh scan with two current processes, two eligible logs, or an
        incomplete bounded discovery clears any previous association.  That
        conservative choice avoids assigning an observation to the wrong
        client after a concurrent launch.
        """

        if not isinstance(process_scan_complete, bool):
            raise ValidationError("Roblox process scan state is invalid.")
        discovery = self._discovery.discover()
        process_ids = _observed_process_ids(instances)
        with self._lock:
            state = _association_state(discovery, process_ids, process_scan_complete=process_scan_complete)
            if state != "associated":
                self._tailer = None
                self._association = None
                self._snapshot = RobloxLogRuntimeSnapshot(
                    directory_available=discovery.directory_available,
                    discovery_complete=discovery.complete,
                    candidate_count=len(discovery.candidates),
                    observed_instance_count=len(process_ids),
                    association_state=state,
                    associated_pid=None,
                )
                return self._snapshot

            pid = process_ids[0]
            candidate = discovery.candidates[0]
            association = (pid, candidate.path)
            if self._association != association or self._tailer is None:
                self._tailer = self._tailer_factory(candidate.path)
                self._association = association

            events = self._tailer.poll()
            for event in events.events:
                self._history.append(RobloxInstanceLogEvent.from_log_event(event, pid=pid))
            self._snapshot = RobloxLogRuntimeSnapshot(
                directory_available=discovery.directory_available,
                discovery_complete=discovery.complete,
                candidate_count=len(discovery.candidates),
                observed_instance_count=len(process_ids),
                association_state="associated",
                associated_pid=pid,
            )
            return self._snapshot

    def snapshot(self) -> RobloxLogRuntimeSnapshot:
        """Return the last redacted runtime state without touching disk."""

        with self._lock:
            return self._snapshot

    def history(self) -> tuple[RobloxInstanceLogEvent, ...]:
        """Return bounded PID-scoped observations without source text or paths."""

        with self._lock:
            return tuple(self._history)


def _current_user_logs_directory(environ: Mapping[str, str] | None) -> Path | None:
    values = os.environ if environ is None else environ
    local_app_data = values.get("LOCALAPPDATA")
    if not isinstance(local_app_data, str) or not local_app_data.strip():
        return None
    return Path(local_app_data) / "Roblox" / "logs"


def _bounded_int(value: object, *, minimum: int, maximum: int, message: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValidationError(message)
    return value


def _observed_process_ids(instances: Iterable[object]) -> tuple[int, ...]:
    pids: set[int] = set()
    for instance in instances:
        pid = getattr(instance, "pid", None)
        if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
            pids.add(pid)
    return tuple(sorted(pids))


def _association_state(
    discovery: RobloxPlayerLogDiscoverySnapshot,
    process_ids: tuple[int, ...],
    *,
    process_scan_complete: bool,
) -> str:
    if not discovery.directory_available:
        return "directory_unavailable"
    if not process_scan_complete:
        return "process_scan_incomplete"
    if not discovery.complete:
        return "discovery_truncated"
    if not process_ids:
        return "no_instance"
    if not discovery.candidates:
        return "no_log"
    if len(process_ids) != 1 or len(discovery.candidates) != 1:
        return "ambiguous"
    return "associated"


__all__ = [
    "RobloxInstanceLogEvent",
    "RobloxLogRuntimeSnapshot",
    "RobloxPlayerLogCandidate",
    "RobloxPlayerLogDiscovery",
    "RobloxPlayerLogDiscoverySnapshot",
    "RobloxPlayerLogRuntime",
]
