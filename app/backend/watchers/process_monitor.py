"""Bounded, local-only lifecycle monitoring for Roblox client processes.

The monitor observes only process metadata exposed by :mod:`psutil`.  It never
reads Roblox memory or logs, changes client binaries, parses command lines,
injects code, or opens a remote-control channel.  A ``roblox://`` launch is
registered as an *intent* and may be associated with one subsequently observed
process only when the association is unambiguous.  This deliberately favours an
honest ``orphaned`` state over attributing the wrong process to an account.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import Enum
import math
from threading import Event, RLock, Thread, current_thread
import time
from typing import Any
from uuid import uuid4

import psutil

from app.backend.core.errors import ValidationError
from app.backend.models.domain import InstanceInfo
from app.backend.roblox.errors import ProcessMonitorError


ProcessIterator = Callable[..., Iterable[object]]
ProcessFactory = Callable[[int], object]
Clock = Callable[[], float]
ScanCallback = Callable[["ProcessScan"], object]
IntervalProvider = Callable[[], float]
ErrorCallback = Callable[[], object]

DEFAULT_ROBLOX_PROCESS_NAMES = frozenset(
    {
        "robloxplayerbeta.exe",
        "robloxplayer.exe",
    }
)


class InstanceState(str, Enum):
    """States used by the local process lifecycle state machine.

    Only the first four values can appear in the current snapshot.  Terminal
    values appear in lifecycle events and scan deltas so the UI can distinguish
    a normal exit, a requested close and a short-lived crash.
    """

    RUNNING = "running"
    ORPHANED = "orphaned"
    TERMINATING = "terminating"
    UNKNOWN = "unknown"
    EXITED = "exited"
    CRASHED = "crashed"
    TERMINATED = "terminated"
    RELAUNCH_PENDING = "relaunch_pending"


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    """A PID plus creation time, which protects against PID reuse."""

    pid: int
    created_at: float | None


@dataclass(frozen=True, slots=True)
class RestartPolicy:
    """Explicit, bounded restart policy carried by one managed launch.

    ``enabled`` is false by default.  A policy is intentionally evaluated only
    for a process that was confidently matched to a registered local launch;
    externally discovered/orphaned processes can never be auto-relaunched.
    """

    enabled: bool = False
    delay_seconds: float = 15.0
    max_attempts: int = 2
    restart_on_crash: bool = True
    restart_on_exit: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValidationError("The relaunch rule must be boolean.")
        if (
            isinstance(self.delay_seconds, bool)
            or not isinstance(self.delay_seconds, (int, float))
            or not math.isfinite(float(self.delay_seconds))
            or not 1 <= float(self.delay_seconds) <= 3_600
        ):
            raise ValidationError("The relaunch delay must be between 1 and 3,600 seconds.")
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or not 0 <= self.max_attempts <= 20
        ):
            raise ValidationError("The maximum number of relaunches must be between 0 and 20.")
        if not isinstance(self.restart_on_crash, bool) or not isinstance(self.restart_on_exit, bool):
            raise ValidationError("Relaunch triggers must be boolean.")


@dataclass(frozen=True, slots=True)
class LaunchIntent:
    """Secret-free local launch metadata kept only in monitor memory."""

    request_id: str
    account_id: str
    account_username: str
    place_id: int
    job_id: str | None
    requested_at: float
    expires_at: float
    restart_policy: RestartPolicy
    restart_attempt: int = 0


@dataclass(frozen=True, slots=True)
class RestartRequest:
    """One due/queued local protocol relaunch request.

    The application service consumes this object and invokes its normal,
    validated Windows protocol launcher.  It does not include a session,
    browser cookie, executable path, or command-line argument.
    """

    request_id: str
    account_id: str
    account_username: str
    place_id: int
    job_id: str | None
    due_at: float
    restart_attempt: int
    restart_policy: RestartPolicy


@dataclass(frozen=True, slots=True)
class MonitorEvent:
    """A compact, non-sensitive lifecycle event retained in bounded history."""

    kind: str
    pid: int
    occurred_at: str
    state: str | None = None
    previous_state: str | None = None
    account_id: str | None = None
    reason: str | None = None
    restart_attempt: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return bridge-safe primitives suitable for diagnostics."""

        return {
            "kind": self.kind,
            "pid": self.pid,
            "occurred_at": self.occurred_at,
            "state": self.state,
            "previous_state": self.previous_state,
            "account_id": self.account_id,
            "reason": self.reason,
            "restart_attempt": self.restart_attempt,
        }


@dataclass(frozen=True, slots=True)
class ProcessScan:
    """One bounded snapshot and the lifecycle changes seen during that scan."""

    instances: tuple[InstanceInfo, ...]
    started: tuple[InstanceInfo, ...]
    exited: tuple[InstanceInfo, ...]
    events: tuple[MonitorEvent, ...]
    crashed: tuple[InstanceInfo, ...] = ()
    terminated: tuple[InstanceInfo, ...] = ()
    orphaned: tuple[InstanceInfo, ...] = ()
    pending_restarts: tuple[RestartRequest, ...] = ()
    complete: bool = True
    truncated: bool = False


class TerminationStatus(str, Enum):
    """Explicit outcomes for an opt-in, local process termination request."""

    TERMINATED = "terminated"
    TIMED_OUT = "timed_out"
    NOT_TRACKED = "not_tracked"
    NOT_FOUND = "not_found"
    IDENTITY_CHANGED = "identity_changed"
    DENIED = "denied"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TerminationResult:
    """A safe result that never includes command-line or exception text."""

    pid: int
    status: TerminationStatus
    message: str


@dataclass(frozen=True, slots=True)
class _ObservedProcess:
    identity: ProcessIdentity
    name: str
    memory_bytes: int | None
    raw_status: str


@dataclass(frozen=True, slots=True)
class _TrackedProcess:
    identity: ProcessIdentity
    name: str
    memory_bytes: int | None
    raw_status: str
    state: InstanceState
    first_seen_at: float
    last_seen_at: float
    account_id: str | None = None
    account_username: str | None = None
    place_id: int | None = None
    job_id: str | None = None
    launch_intent: LaunchIntent | None = None

    def as_instance(self) -> InstanceInfo:
        return InstanceInfo(
            pid=self.identity.pid,
            name=self.name,
            started_at=_timestamp(self.identity.created_at) if self.identity.created_at is not None else None,
            memory_bytes=self.memory_bytes,
            account_id=self.account_id,
            account_username=self.account_username,
            place_id=self.place_id,
            job_id=self.job_id,
            status=self.state.value,
        )


class RobloxProcessMonitor:
    """A resilient local state machine for known Roblox client executables.

    Call :meth:`scan` from a scheduler or :class:`MonitorPollingLoop`.  There
    is no hidden worker in this class, which makes process ownership clear and
    allows the desktop application to stop its worker deterministically.

    A failed or incomplete psutil scan never emits mass ``exited`` events.  The
    previous snapshot is instead retained as ``unknown`` until a complete scan
    can confirm the transition.  This prevents the common ghost/false-crash
    issue caused by transient access-denied or iterator failures.
    """

    def __init__(
        self,
        *,
        process_iter: ProcessIterator = psutil.process_iter,
        process_factory: ProcessFactory = psutil.Process,
        process_names: Iterable[str] = DEFAULT_ROBLOX_PROCESS_NAMES,
        max_history: int = 200,
        max_tracked: int = 256,
        max_pending: int = 256,
        termination_enabled: bool = False,
        launch_match_timeout_seconds: float = 45.0,
        crash_window_seconds: float = 120.0,
        clock: Clock = time.time,
    ) -> None:
        _validate_bounded_int(max_history, "Process history size is invalid.")
        _validate_bounded_int(max_tracked, "Tracked process limit is invalid.")
        _validate_bounded_int(max_pending, "Pending launches limit is invalid.")
        if not isinstance(termination_enabled, bool):
            raise ValidationError("Process termination option must be boolean.")
        _validate_duration(
            launch_match_timeout_seconds,
            "Launch association timeout must be between 5 and 300 seconds.",
            minimum=5,
            maximum=300,
        )
        _validate_duration(
            crash_window_seconds,
            "Crash detection window must be between 5 and 3,600 seconds.",
            minimum=5,
            maximum=3_600,
        )
        if isinstance(process_names, str):
            raise ValidationError("Roblox process names must be a collection.")
        normalized_names = {
            name.strip().casefold()
            for name in process_names
            if isinstance(name, str) and name.strip()
        }
        if not normalized_names:
            raise ValidationError("At least one Roblox process name is required.")

        self._process_iter = process_iter
        self._process_factory = process_factory
        self._process_names = frozenset(normalized_names)
        self._max_tracked = max_tracked
        self._max_pending = max_pending
        self._termination_enabled = termination_enabled
        self._launch_match_timeout_seconds = float(launch_match_timeout_seconds)
        self._crash_window_seconds = float(crash_window_seconds)
        self._clock = clock
        self._tracked: dict[ProcessIdentity, _TrackedProcess] = {}
        self._history: deque[MonitorEvent] = deque(maxlen=max_history)
        self._pending_launches: deque[LaunchIntent] = deque(maxlen=max_pending)
        self._pending_restarts: dict[str, RestartRequest] = {}
        self._termination_requested: set[ProcessIdentity] = set()
        self._last_scan_complete = True
        self._lock = RLock()
        self._scan_lock = RLock()

    @property
    def termination_enabled(self) -> bool:
        """Whether explicit local termination has been configured as opt-in."""

        with self._lock:
            return self._termination_enabled

    @property
    def last_scan_complete(self) -> bool:
        """Whether the most recent process snapshot was complete."""

        with self._lock:
            return self._last_scan_complete

    def configure(
        self,
        *,
        termination_enabled: bool | None = None,
        launch_match_timeout_seconds: float | None = None,
        crash_window_seconds: float | None = None,
    ) -> None:
        """Apply validated local runtime options without restarting the monitor."""

        if termination_enabled is not None and not isinstance(termination_enabled, bool):
            raise ValidationError("Process termination option must be boolean.")
        if launch_match_timeout_seconds is not None:
            _validate_duration(
                launch_match_timeout_seconds,
                "Launch association timeout must be between 5 and 300 seconds.",
                minimum=5,
                maximum=300,
            )
        if crash_window_seconds is not None:
            _validate_duration(
                crash_window_seconds,
                "Crash detection window must be between 5 and 3,600 seconds.",
                minimum=5,
                maximum=3_600,
            )
        with self._lock:
            if termination_enabled is not None:
                self._termination_enabled = termination_enabled
            if launch_match_timeout_seconds is not None:
                self._launch_match_timeout_seconds = float(launch_match_timeout_seconds)
            if crash_window_seconds is not None:
                self._crash_window_seconds = float(crash_window_seconds)

    def register_launch_intent(
        self,
        *,
        account_id: str,
        account_username: str,
        place_id: int,
        job_id: str | None = None,
        restart_policy: RestartPolicy | None = None,
        restart_attempt: int = 0,
    ) -> str:
        """Register a successful local protocol hand-off for later matching.

        The caller should invoke this immediately after its normal launcher
        accepts a validated target.  An intent expires harmlessly when no
        matching client process appears; it never creates a fake instance.
        """

        account_id = _opaque_text(account_id, "Account ID is invalid.")
        account_username = _opaque_text(account_username, "Account username is invalid.")
        _validate_positive_int(place_id, "Place ID is invalid.")
        if job_id is not None and (not isinstance(job_id, str) or len(job_id.strip()) > 128):
            raise ValidationError("Job ID is invalid.")
        if isinstance(restart_attempt, bool) or not isinstance(restart_attempt, int) or not 0 <= restart_attempt <= 20:
            raise ValidationError("Relaunch attempt count is invalid.")
        policy = restart_policy or RestartPolicy()
        if not isinstance(policy, RestartPolicy):
            raise ValidationError("Relaunch rule is invalid.")

        now = self._clock()
        intent = LaunchIntent(
            request_id=str(uuid4()),
            account_id=account_id,
            account_username=account_username,
            place_id=place_id,
            job_id=job_id.strip() if isinstance(job_id, str) and job_id.strip() else None,
            requested_at=now,
            expires_at=now + self._launch_match_timeout_seconds,
            restart_policy=policy,
            restart_attempt=restart_attempt,
        )
        with self._lock:
            # deque(maxlen=...) silently drops data, which would hide the
            # reason a launch was not matched.  Emit an explicit bounded event.
            if len(self._pending_launches) >= self._max_pending:
                dropped = self._pending_launches.popleft()
                self._history.append(
                    self._event(
                        "launch_discarded",
                        0,
                        now,
                        account_id=dropped.account_id,
                        reason="pending_limit",
                    )
                )
            self._pending_launches.append(intent)
            self._history.append(self._event("launch_registered", 0, now, account_id=account_id))
        return intent.request_id

    def cancel_launch_intent(self, request_id: str) -> bool:
        """Cancel an unobserved launch intent after a caller-side failure."""

        token = _opaque_text(request_id, "Launch ID is invalid.")
        with self._lock:
            matches = [item for item in self._pending_launches if item.request_id == token]
            if not matches:
                return False
            self._pending_launches = deque(
                (item for item in self._pending_launches if item.request_id != token),
                maxlen=self._max_pending,
            )
            self._history.append(
                self._event("launch_cancelled", 0, self._clock(), account_id=matches[0].account_id)
            )
            return True

    def forget_account(self, account_id: str) -> dict[str, int]:
        """Detach one deleted local account from pending watcher work.

        The client process is left entirely untouched.  A live, previously
        associated process becomes an honest ``orphaned`` instance, while any
        pending launch/restart request for that account is discarded so a
        deleted account can never be launched later by an opt-in rule.
        """

        account_id = _opaque_text(account_id, "Account ID is invalid.")
        now = self._clock()
        with self._lock:
            old_launches = len(self._pending_launches)
            self._pending_launches = deque(
                (item for item in self._pending_launches if item.account_id != account_id),
                maxlen=self._max_pending,
            )
            removed_launches = old_launches - len(self._pending_launches)
            restart_ids = [
                request_id
                for request_id, request in self._pending_restarts.items()
                if request.account_id == account_id
            ]
            for request_id in restart_ids:
                del self._pending_restarts[request_id]

            detached = 0
            for identity, tracked in tuple(self._tracked.items()):
                if tracked.account_id != account_id:
                    continue
                detached += 1
                self._tracked[identity] = replace(
                    tracked,
                    state=InstanceState.ORPHANED,
                    account_id=None,
                    account_username=None,
                    place_id=None,
                    job_id=None,
                    launch_intent=None,
                )
                self._history.append(
                    self._event(
                        "account_detached",
                        identity.pid,
                        now,
                        previous_state=tracked.state.value,
                        state=InstanceState.ORPHANED.value,
                        account_id=account_id,
                        reason="account_deleted",
                    )
                )
            if removed_launches or restart_ids:
                self._history.append(
                    self._event(
                        "account_watch_work_cancelled",
                        0,
                        now,
                        account_id=account_id,
                        reason="account_deleted",
                    )
                )
            return {
                "launches_cancelled": removed_launches,
                "restarts_cancelled": len(restart_ids),
                "instances_detached": detached,
            }

    def scan(self) -> ProcessScan:
        """Take one resilient, serialised snapshot of local Roblox processes."""

        with self._scan_lock:
            observed, complete = self._observe_processes()
            now = self._clock()
            truncated = len(observed) > self._max_tracked
            if truncated:
                # Keep the newest processes but never infer exits from a
                # deliberately truncated observation.
                ordered = sorted(
                    observed.values(),
                    key=lambda item: (
                        item.identity.created_at if item.identity.created_at is not None else -1.0,
                        item.identity.pid,
                    ),
                    reverse=True,
                )
                observed = {item.identity: item for item in ordered[: self._max_tracked]}
                complete = False

            with self._lock:
                events: list[MonitorEvent] = []
                events.extend(self._expire_pending_launches(now))
                if not complete:
                    events.append(
                        self._event(
                            "scan_incomplete",
                            0,
                            now,
                            reason="truncated" if truncated else "process_enumeration",
                        )
                    )

                previous = self._tracked
                next_tracked: dict[ProcessIdentity, _TrackedProcess] = {}
                started: list[InstanceInfo] = []
                orphaned: list[InstanceInfo] = []
                crashed: list[InstanceInfo] = []
                terminated: list[InstanceInfo] = []
                exited: list[InstanceInfo] = []

                for identity in sorted(observed, key=_identity_sort_key):
                    record = observed[identity]
                    old = previous.get(identity)
                    if old is None:
                        tracked, start_events = self._start_tracking(record, now)
                        next_tracked[identity] = tracked
                        instance = tracked.as_instance()
                        started.append(instance)
                        events.extend(start_events)
                        if tracked.state is InstanceState.ORPHANED:
                            orphaned.append(instance)
                        continue

                    tracked, state_event = self._refresh_tracked(old, record, now)
                    next_tracked[identity] = tracked
                    if state_event is not None:
                        events.append(state_event)

                missing = previous.keys() - observed.keys()
                if complete:
                    for identity in sorted(missing, key=_identity_sort_key):
                        former = previous[identity]
                        terminal_state = self._terminal_state(former, now)
                        instance = replace(former, state=terminal_state).as_instance()
                        event = self._event(
                            terminal_state.value,
                            identity.pid,
                            now,
                            previous_state=former.state.value,
                            state=terminal_state.value,
                            account_id=former.account_id,
                            reason=self._terminal_reason(former, terminal_state),
                        )
                        events.append(event)
                        exited.append(instance)
                        if terminal_state is InstanceState.CRASHED:
                            crashed.append(instance)
                        elif terminal_state is InstanceState.TERMINATED:
                            terminated.append(instance)
                        events.extend(self._schedule_restart_if_eligible(former, terminal_state, now))
                        self._termination_requested.discard(identity)
                else:
                    # A partial scan cannot safely prove that a PID vanished.
                    # Preserve the record but surface uncertainty instead of a
                    # stale optimistic "running" state.
                    for identity in sorted(missing, key=_identity_sort_key):
                        former = previous[identity]
                        if former.state is InstanceState.TERMINATING:
                            next_tracked[identity] = former
                            continue
                        uncertain = replace(former, state=InstanceState.UNKNOWN)
                        next_tracked[identity] = uncertain
                        if former.state is not InstanceState.UNKNOWN:
                            events.append(
                                self._event(
                                    "state_changed",
                                    identity.pid,
                                    now,
                                    previous_state=former.state.value,
                                    state=InstanceState.UNKNOWN.value,
                                    account_id=former.account_id,
                                    reason="incomplete_scan",
                                )
                            )

                self._tracked = next_tracked
                self._last_scan_complete = complete
                self._history.extend(events)
                instances = tuple(
                    tracked.as_instance()
                    for tracked in sorted(next_tracked.values(), key=lambda tracked: tracked.identity.pid)
                )
                pending_restarts = tuple(
                    sorted(self._pending_restarts.values(), key=lambda item: (item.due_at, item.request_id))
                )

            return ProcessScan(
                instances=instances,
                started=tuple(started),
                exited=tuple(exited),
                events=tuple(events),
                crashed=tuple(crashed),
                terminated=tuple(terminated),
                orphaned=tuple(orphaned),
                pending_restarts=pending_restarts,
                complete=complete,
                truncated=truncated,
            )

    def current_instances(self) -> tuple[InstanceInfo, ...]:
        """Return the last bounded snapshot without resampling."""

        with self._lock:
            return tuple(
                tracked.as_instance()
                for tracked in sorted(self._tracked.values(), key=lambda tracked: tracked.identity.pid)
            )

    def history(self) -> tuple[MonitorEvent, ...]:
        """Return a bounded copy of lifecycle events for diagnostics."""

        with self._lock:
            return tuple(self._history)

    def pending_restarts(self) -> tuple[RestartRequest, ...]:
        """Return queued bounded relaunches without claiming them."""

        with self._lock:
            return tuple(
                sorted(self._pending_restarts.values(), key=lambda item: (item.due_at, item.request_id))
            )

    def claim_due_restarts(self) -> tuple[RestartRequest, ...]:
        """Atomically claim due restart requests exactly once.

        The monitor cannot launch processes itself.  A higher layer must call
        this method and decide whether the normal Windows protocol launcher is
        still available.  Claimed requests are removed even if that launcher
        later fails, preventing an unbounded launch loop.
        """

        now = self._clock()
        with self._lock:
            due = [item for item in self._pending_restarts.values() if item.due_at <= now]
            for item in due:
                self._pending_restarts.pop(item.request_id, None)
                self._history.append(
                    self._event(
                        "restart_claimed",
                        0,
                        now,
                        account_id=item.account_id,
                        restart_attempt=item.restart_attempt,
                    )
                )
            return tuple(sorted(due, key=lambda item: (item.due_at, item.request_id)))

    def record_restart_result(self, request: RestartRequest, *, launched: bool) -> None:
        """Record the service's non-sensitive outcome after claiming a restart."""

        if not isinstance(request, RestartRequest):
            raise ValidationError("Relaunch request is invalid.")
        if not isinstance(launched, bool):
            raise ValidationError("Relaunch result is invalid.")
        with self._lock:
            self._history.append(
                self._event(
                    "restart_requested" if launched else "restart_failed",
                    0,
                    self._clock(),
                    account_id=request.account_id,
                    restart_attempt=request.restart_attempt,
                )
            )

    def bind_orphan(
        self,
        pid: int,
        *,
        account_id: str,
        account_username: str,
        place_id: int,
        job_id: str | None = None,
        restart_policy: RestartPolicy | None = None,
        confirm: bool = False,
    ) -> InstanceInfo:
        """Explicitly associate one observed orphan to a local account record.

        Matching two simultaneous protocol launches is inherently ambiguous.
        This is the deliberate, user-confirmed repair path; it edits only
        Astro Account Manager's local metadata and never touches the Roblox process.
        """

        _validate_positive_int(pid, "PID is invalid.")
        if not isinstance(confirm, bool) or not confirm:
            raise ProcessMonitorError(
                "Instance binding requires explicit confirmation.",
                code="instance_binding_confirmation_required",
            )
        account_id = _opaque_text(account_id, "Account ID is invalid.")
        account_username = _opaque_text(account_username, "Account username is invalid.")
        _validate_positive_int(place_id, "Place ID is invalid.")
        if job_id is not None and (not isinstance(job_id, str) or len(job_id.strip()) > 128):
            raise ValidationError("Job ID is invalid.")
        policy = restart_policy or RestartPolicy()
        if not isinstance(policy, RestartPolicy):
            raise ValidationError("Relaunch rule is invalid.")

        with self._lock:
            candidates = [item for item in self._tracked.values() if item.identity.pid == pid]
            if len(candidates) != 1:
                raise ProcessMonitorError(
                    "This Roblox instance is not available for binding.",
                    code="instance_not_available",
                )
            current = candidates[0]
            if current.account_id is not None:
                raise ProcessMonitorError(
                    "This instance is already bound to an account.", code="instance_already_bound"
                )
            now = self._clock()
            intent = LaunchIntent(
                request_id=str(uuid4()),
                account_id=account_id,
                account_username=account_username,
                place_id=place_id,
                job_id=job_id.strip() if isinstance(job_id, str) and job_id.strip() else None,
                requested_at=now,
                expires_at=now,
                restart_policy=policy,
            )
            bound = replace(
                current,
                state=InstanceState.RUNNING,
                account_id=account_id,
                account_username=account_username,
                place_id=place_id,
                job_id=intent.job_id,
                launch_intent=intent,
            )
            self._tracked[current.identity] = bound
            self._history.append(
                self._event(
                    "orphan_bound",
                    pid,
                    now,
                    previous_state=current.state.value,
                    state=bound.state.value,
                    account_id=account_id,
                )
            )
            return bound.as_instance()

    def terminate_known_process(
        self, pid: int, *, confirm: bool = False, wait_timeout_seconds: float = 3.0
    ) -> TerminationResult:
        """Request a graceful close of one verified, tracked local client.

        This is never called automatically.  It sends only ``terminate()`` and
        never escalates to a forced ``kill()`` after a timeout.
        """

        _validate_positive_int(pid, "PID must be a positive integer.")
        if not isinstance(confirm, bool) or not confirm:
            raise ProcessMonitorError(
                "Closing a Roblox instance requires explicit confirmation.",
                code="termination_confirmation_required",
            )
        if not self.termination_enabled:
            raise ProcessMonitorError(
                "Roblox instance closing is not enabled.",
                code="termination_not_enabled",
            )
        _validate_duration(
            wait_timeout_seconds,
            "Termination delay must be between 0 and 10 seconds.",
            minimum=0.001,
            maximum=10,
        )

        tracked = self._tracked_for_pid(pid)
        if tracked is None:
            return TerminationResult(pid, TerminationStatus.NOT_TRACKED, "This Roblox instance is not tracked.")
        if tracked.identity.created_at is None:
            return TerminationResult(
                pid,
                TerminationStatus.IDENTITY_CHANGED,
                "Instance identity could not be verified.",
            )

        try:
            process = self._process_factory(pid)
        except (psutil.NoSuchProcess, ProcessLookupError):
            return TerminationResult(pid, TerminationStatus.NOT_FOUND, "This instance is already closed.")
        except (psutil.AccessDenied, PermissionError):
            return TerminationResult(pid, TerminationStatus.DENIED, "Windows denied closing this instance.")
        except Exception:
            return TerminationResult(pid, TerminationStatus.FAILED, "Closing this instance failed.")

        if not self._matches_tracked_identity(process, tracked):
            return TerminationResult(
                pid,
                TerminationStatus.IDENTITY_CHANGED,
                "Instance changed since last scan; no termination was performed.",
            )

        with self._lock:
            self._termination_requested.add(tracked.identity)
            self._tracked[tracked.identity] = replace(tracked, state=InstanceState.TERMINATING)
            self._history.append(
                self._event(
                    "termination_requested",
                    pid,
                    self._clock(),
                    previous_state=tracked.state.value,
                    state=InstanceState.TERMINATING.value,
                    account_id=tracked.account_id,
                )
            )

        try:
            terminate = getattr(process, "terminate")
            terminate()
            waiter = getattr(process, "wait")
            waiter(timeout=float(wait_timeout_seconds))
        except psutil.TimeoutExpired:
            return TerminationResult(
                pid,
                TerminationStatus.TIMED_OUT,
                "Instance did not close in time; no force kill was performed.",
            )
        except (psutil.NoSuchProcess, ProcessLookupError):
            # It vanished between verification and termination, which is the
            # desired end state and does not need escalation.
            self._remove_tracked(tracked.identity, state=InstanceState.TERMINATED)
            return TerminationResult(pid, TerminationStatus.TERMINATED, "Roblox instance closed.")
        except (psutil.AccessDenied, PermissionError):
            self._clear_termination_request(tracked.identity)
            return TerminationResult(pid, TerminationStatus.DENIED, "Windows denied closing this instance.")
        except Exception:
            self._clear_termination_request(tracked.identity)
            return TerminationResult(pid, TerminationStatus.FAILED, "Closing this instance failed.")

        self._remove_tracked(tracked.identity, state=InstanceState.TERMINATED)
        return TerminationResult(pid, TerminationStatus.TERMINATED, "Roblox instance closed.")

    def _observe_processes(self) -> tuple[dict[ProcessIdentity, _ObservedProcess], bool]:
        attributes = ["pid", "name", "create_time", "status", "memory_info"]
        try:
            iterator = self._process_iter(attrs=attributes)
        except TypeError:
            # Allows simple deterministic test doubles and older adapters.
            try:
                iterator = self._process_iter()
            except (psutil.Error, OSError):
                return {}, False
            except Exception:
                return {}, False
        except (psutil.Error, OSError):
            return {}, False
        except Exception:
            return {}, False

        observed: dict[ProcessIdentity, _ObservedProcess] = {}
        complete = True
        try:
            for process in iterator:
                record, item_complete = self._to_observed(process)
                complete = complete and item_complete
                if record is not None:
                    observed[record.identity] = record
        except (psutil.Error, OSError):
            complete = False
        except Exception:
            # Do not expose arbitrary adapter errors or abandon records seen
            # earlier.  Missing processes simply remain uncertain this cycle.
            complete = False
        return observed, complete

    def _to_observed(self, process: object) -> tuple[_ObservedProcess | None, bool]:
        try:
            info = _process_info(process)
            pid = info.get("pid")
            name = info.get("name")
            if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
                return None, True
            if not isinstance(name, str) or name.strip().casefold() not in self._process_names:
                return None, True
            created_at = _as_timestamp(info.get("create_time"))
            identity = ProcessIdentity(pid=pid, created_at=created_at)
            memory_bytes = _memory_bytes(info.get("memory_info"))
            raw_status = info.get("status") if isinstance(info.get("status"), str) else "running"
            return (
                _ObservedProcess(
                    identity=identity,
                    name=name.strip(),
                    memory_bytes=memory_bytes,
                    raw_status=raw_status.strip().casefold() or "running",
                ),
                True,
            )
        except (psutil.Error, OSError):
            # Access can disappear between two psutil field reads.  The whole
            # snapshot becomes uncertain rather than making an unrelated
            # previously tracked Roblox PID look as if it exited.
            return None, False
        except (AttributeError, TypeError, ValueError):
            return None, True

    def _start_tracking(
        self, record: _ObservedProcess, now: float
    ) -> tuple[_TrackedProcess, tuple[MonitorEvent, ...]]:
        intent = self._match_pending_intent(record, now)
        if intent is not None:
            state = InstanceState.RUNNING
            tracked = _TrackedProcess(
                identity=record.identity,
                name=record.name,
                memory_bytes=record.memory_bytes,
                raw_status=record.raw_status,
                state=state,
                first_seen_at=now,
                last_seen_at=now,
                account_id=intent.account_id,
                account_username=intent.account_username,
                place_id=intent.place_id,
                job_id=intent.job_id,
                launch_intent=intent,
            )
            return tracked, (
                self._event("started", record.identity.pid, now, state=state.value, account_id=intent.account_id),
                self._event("launch_matched", record.identity.pid, now, state=state.value, account_id=intent.account_id),
            )

        state = InstanceState.ORPHANED
        tracked = _TrackedProcess(
            identity=record.identity,
            name=record.name,
            memory_bytes=record.memory_bytes,
            raw_status=record.raw_status,
            state=state,
            first_seen_at=now,
            last_seen_at=now,
        )
        return tracked, (
            self._event("started", record.identity.pid, now, state=state.value),
            self._event("orphaned", record.identity.pid, now, state=state.value, reason="no_unambiguous_launch"),
        )

    def _refresh_tracked(
        self, previous: _TrackedProcess, record: _ObservedProcess, now: float
    ) -> tuple[_TrackedProcess, MonitorEvent | None]:
        state = previous.state
        state_event: MonitorEvent | None = None
        if state is InstanceState.UNKNOWN:
            state = InstanceState.RUNNING if previous.account_id else InstanceState.ORPHANED
            state_event = self._event(
                "state_changed",
                record.identity.pid,
                now,
                previous_state=previous.state.value,
                state=state.value,
                account_id=previous.account_id,
                reason="scan_recovered",
            )
        elif state is InstanceState.TERMINATING and record.raw_status not in {"zombie", "dead"}:
            # A graceful close timed out and the process is still observable.
            # Keep it visibly terminating until a later complete scan confirms
            # exit, avoiding a premature restart/close classification.
            state = InstanceState.TERMINATING

        return (
            replace(
                previous,
                name=record.name,
                memory_bytes=record.memory_bytes,
                raw_status=record.raw_status,
                state=state,
                last_seen_at=now,
            ),
            state_event,
        )

    def _match_pending_intent(self, record: _ObservedProcess, now: float) -> LaunchIntent | None:
        """Consume one intent only if it is the sole plausible candidate."""

        if record.identity.created_at is None:
            # A PID without a creation timestamp cannot be defended against
            # reuse, so it must remain an explicit orphan until manually bound.
            return None
        candidates = [
            intent
            for intent in self._pending_launches
            if intent.expires_at >= now
            and (
                record.identity.created_at is None
                or record.identity.created_at >= intent.requested_at - 5.0
            )
        ]
        if len(candidates) != 1:
            return None
        intent = candidates[0]
        self._pending_launches = deque(
            (item for item in self._pending_launches if item.request_id != intent.request_id),
            maxlen=self._max_pending,
        )
        return intent

    def _expire_pending_launches(self, now: float) -> tuple[MonitorEvent, ...]:
        expired = [intent for intent in self._pending_launches if intent.expires_at < now]
        if not expired:
            return ()
        self._pending_launches = deque(
            (intent for intent in self._pending_launches if intent.expires_at >= now),
            maxlen=self._max_pending,
        )
        return tuple(
            self._event(
                "launch_expired",
                0,
                now,
                account_id=intent.account_id,
                reason="no_process_observed",
                restart_attempt=intent.restart_attempt,
            )
            for intent in expired
        )

    def _terminal_state(self, tracked: _TrackedProcess, now: float) -> InstanceState:
        if tracked.identity in self._termination_requested or tracked.state is InstanceState.TERMINATING:
            return InstanceState.TERMINATED
        created = tracked.identity.created_at if tracked.identity.created_at is not None else tracked.first_seen_at
        age = max(0.0, now - created)
        return InstanceState.CRASHED if age <= self._crash_window_seconds else InstanceState.EXITED

    @staticmethod
    def _terminal_reason(tracked: _TrackedProcess, state: InstanceState) -> str:
        if state is InstanceState.TERMINATED:
            return "requested_close"
        if state is InstanceState.CRASHED:
            return "short_lived_process"
        if tracked.state is InstanceState.UNKNOWN:
            return "confirmed_after_incomplete_scan"
        return "process_disappeared"

    def _schedule_restart_if_eligible(
        self, tracked: _TrackedProcess, state: InstanceState, now: float
    ) -> tuple[MonitorEvent, ...]:
        intent = tracked.launch_intent
        if intent is None or tracked.account_id is None:
            return ()
        policy = intent.restart_policy
        should_restart = (
            policy.enabled
            and (
                (state is InstanceState.CRASHED and policy.restart_on_crash)
                or (state is InstanceState.EXITED and policy.restart_on_exit)
            )
        )
        if not should_restart:
            return ()
        next_attempt = intent.restart_attempt + 1
        if next_attempt > policy.max_attempts:
            return (
                self._event(
                    "restart_exhausted",
                    tracked.identity.pid,
                    now,
                    account_id=intent.account_id,
                    reason="attempt_limit",
                    restart_attempt=intent.restart_attempt,
                ),
            )
        request = RestartRequest(
            request_id=str(uuid4()),
            account_id=intent.account_id,
            account_username=intent.account_username,
            place_id=intent.place_id,
            job_id=intent.job_id,
            due_at=now + float(policy.delay_seconds),
            restart_attempt=next_attempt,
            restart_policy=policy,
        )
        if len(self._pending_restarts) >= self._max_pending:
            # Drop the farthest/oldest queued request deterministically.  This
            # remains safe because relaunch is opt-in and never unbounded.
            oldest_id = min(
                self._pending_restarts,
                key=lambda key: (self._pending_restarts[key].due_at, key),
            )
            dropped = self._pending_restarts.pop(oldest_id)
            dropped_event = self._event(
                "restart_discarded",
                0,
                now,
                account_id=dropped.account_id,
                reason="pending_limit",
                restart_attempt=dropped.restart_attempt,
            )
        else:
            dropped_event = None
        self._pending_restarts[request.request_id] = request
        events: list[MonitorEvent] = []
        if dropped_event is not None:
            events.append(dropped_event)
        events.append(
            self._event(
                "restart_scheduled",
                tracked.identity.pid,
                now,
                state=InstanceState.RELAUNCH_PENDING.value,
                previous_state=state.value,
                account_id=intent.account_id,
                restart_attempt=next_attempt,
            )
        )
        return tuple(events)

    def _tracked_for_pid(self, pid: int) -> _TrackedProcess | None:
        with self._lock:
            matches = [tracked for identity, tracked in self._tracked.items() if identity.pid == pid]
        # More than one entry for a PID would imply a race or unreliable process
        # metadata.  Refuse to act rather than guessing which identity is live.
        return matches[0] if len(matches) == 1 else None

    def _matches_tracked_identity(self, process: object, tracked: _TrackedProcess) -> bool:
        try:
            name_method = getattr(process, "name")
            created_method = getattr(process, "create_time")
            name = name_method()
            created_at = _as_timestamp(created_method())
        except (psutil.Error, OSError, AttributeError, TypeError, ValueError):
            return False
        if not isinstance(name, str) or name.strip().casefold() not in self._process_names:
            return False
        expected = tracked.identity.created_at
        return created_at is not None and expected is not None and math.isclose(
            created_at, expected, rel_tol=0.0, abs_tol=0.05
        )

    def _remove_tracked(self, identity: ProcessIdentity, *, state: InstanceState) -> None:
        with self._lock:
            tracked = self._tracked.pop(identity, None)
            self._termination_requested.discard(identity)
            if tracked is not None:
                self._history.append(
                    self._event(
                        state.value,
                        identity.pid,
                        self._clock(),
                        previous_state=tracked.state.value,
                        state=state.value,
                        account_id=tracked.account_id,
                        reason="requested_close",
                    )
                )

    def _clear_termination_request(self, identity: ProcessIdentity) -> None:
        with self._lock:
            self._termination_requested.discard(identity)
            tracked = self._tracked.get(identity)
            if tracked is not None and tracked.state is InstanceState.TERMINATING:
                self._tracked[identity] = replace(
                    tracked,
                    state=InstanceState.RUNNING if tracked.account_id else InstanceState.ORPHANED,
                )

    @staticmethod
    def _event(
        kind: str,
        pid: int,
        occurred_at: float,
        *,
        state: str | None = None,
        previous_state: str | None = None,
        account_id: str | None = None,
        reason: str | None = None,
        restart_attempt: int | None = None,
    ) -> MonitorEvent:
        return MonitorEvent(
            kind=kind,
            pid=pid,
            occurred_at=_timestamp(occurred_at),
            state=state,
            previous_state=previous_state,
            account_id=account_id,
            reason=reason,
            restart_attempt=restart_attempt,
        )


class MonitorPollingLoop:
    """Small stoppable worker that owns periodic local process scans.

    It has no knowledge of Roblox, credentials or launch mechanics.  The
    callback receives the fully processed scan and can persist redacted
    activity or consume due opt-in restart requests.  The worker is daemonised
    as a final safety net, but :meth:`stop` is still required during normal
    application shutdown.
    """

    def __init__(
        self,
        scan: Callable[[], ProcessScan],
        *,
        interval_seconds: IntervalProvider,
        on_scan: ScanCallback | None = None,
        on_error: ErrorCallback | None = None,
        name: str = "astro-roblox-watcher",
    ) -> None:
        if not callable(scan) or not callable(interval_seconds):
            raise ValidationError("Watcher loop parameters are invalid.")
        self._scan = scan
        self._interval_seconds = interval_seconds
        self._on_scan = on_scan
        self._on_error = on_error
        self._name = name
        self._stop = Event()
        self._lock = RLock()
        self._thread: Thread | None = None

    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """Start a single background worker; return false when already running."""

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            # Each generation owns a distinct stop event.  If a slow scan
            # survives a bounded join during reconfiguration, clearing a new
            # worker's event must never revive that old generation.
            stop_event = Event()
            self._stop = stop_event
            self._thread = Thread(target=self._run, args=(stop_event,), name=self._name, daemon=True)
            self._thread.start()
            return True

    def stop(self, *, timeout_seconds: float = 3.0) -> None:
        """Signal the worker and wait briefly without blocking shutdown forever."""

        _validate_duration(
            timeout_seconds,
            "Watcher stop timeout must be between 0 and 10 seconds.",
            minimum=0.001,
            maximum=10,
        )
        with self._lock:
            thread = self._thread
            self._thread = None
            self._stop.set()
        if thread is not None and thread is not current_thread():
            thread.join(timeout=float(timeout_seconds))

    def tick_once(self) -> ProcessScan:
        """Run one scan synchronously; useful for deterministic callers/tests."""

        scan = self._scan()
        if self._on_scan is not None:
            self._on_scan(scan)
        return scan

    def _run(self, stop_event: Event) -> None:
        while not stop_event.is_set():
            try:
                self.tick_once()
            except Exception:
                # The service logger deliberately receives no exception object
                # here: a third-party process adapter could include sensitive
                # command-line text in it.  It can log a fixed local message.
                if self._on_error is not None:
                    try:
                        self._on_error()
                    except Exception:
                        pass
            try:
                interval = float(self._interval_seconds())
            except (TypeError, ValueError):
                interval = 6.0
            # Never allow an invalid runtime setting to turn into a busy loop.
            interval = min(max(interval, 1.0), 300.0)
            stop_event.wait(interval)


def _process_info(process: object) -> Mapping[str, Any]:
    info = getattr(process, "info", None)
    if isinstance(info, Mapping):
        return info

    pid = getattr(process, "pid")
    name = getattr(process, "name")()
    create_time = getattr(process, "create_time")()
    status = getattr(process, "status")()
    memory = getattr(process, "memory_info")()
    return {
        "pid": pid,
        "name": name,
        "create_time": create_time,
        "status": status,
        "memory_info": memory,
    }


def _memory_bytes(value: object) -> int | None:
    raw: object
    if isinstance(value, Mapping):
        raw = value.get("rss")
    else:
        raw = getattr(value, "rss", None)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        return None
    return raw


def _as_timestamp(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def _timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=UTC).isoformat()


def _identity_sort_key(identity: ProcessIdentity) -> tuple[int, float]:
    return (identity.pid, identity.created_at if identity.created_at is not None else -1.0)


def _validate_bounded_int(value: object, message: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10_000:
        raise ValidationError(message)


def _validate_duration(value: object, message: str, *, minimum: float, maximum: float) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not minimum <= float(value) <= maximum
    ):
        raise ValidationError(message)


def _validate_positive_int(value: object, message: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError(message)


def _opaque_text(value: object, message: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 160:
        raise ValidationError(message)
    return value.strip()


__all__ = [
    "DEFAULT_ROBLOX_PROCESS_NAMES",
    "InstanceState",
    "LaunchIntent",
    "MonitorEvent",
    "MonitorPollingLoop",
    "ProcessIdentity",
    "ProcessScan",
    "RestartPolicy",
    "RestartRequest",
    "RobloxProcessMonitor",
    "TerminationResult",
    "TerminationStatus",
]
