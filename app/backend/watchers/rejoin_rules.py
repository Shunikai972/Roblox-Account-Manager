"""Explicit, bounded rejoin decisions for interrupted Roblox sessions.

The process watcher already owns *process* lifetime: it notices that a client
died and can consume a bounded relaunch rule.  What it cannot do is explain
*why* a session ended, because a Roblox client happily stays alive while it
shows its own disconnect dialog.  The Player-log observer knows the disconnect
code but is deliberately kept away from control decisions, so a transient
file-system failure can never close or relaunch a process.

This module is the missing middle.  It contains pure, side-effect-free rules
that turn "the session ended with code N, this was attempt K" into a single
auditable decision: rejoin or not, after how long, and on the same server or a
fresh one.  It performs no I/O, owns no process, imports nothing from Windows,
and keeps no state, so the watcher, the service and the UI can all rely on the
same answers.

The disconnect catalog is best-effort: Roblox does not publish a stable machine
readable list, so unknown codes stay retryable instead of pretending to be
understood, and labels are display text only -- never a control signal on
their own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.backend.core.errors import ValidationError

# Bounds ---------------------------------------------------------------------
# Every knob is bounded here rather than at the call site so that a settings
# payload, a stored account rule and a UI form cannot disagree about limits.

MIN_REJOIN_DELAY_SECONDS = 1.0
MAX_REJOIN_DELAY_SECONDS = 3_600.0
MAX_REJOIN_ATTEMPTS = 20
MIN_BACKOFF_FACTOR = 1.0
MAX_BACKOFF_FACTOR = 10.0
MAX_CHANGE_SERVER_AFTER = MAX_REJOIN_ATTEMPTS
MAX_JOB_ID_CHARS = 128
MAX_DISCONNECT_CODE = 100_000

UNKNOWN_CODE_LABEL = "The session ended without a disconnect code"

# code -> (label, category, retryable, prefer_new_server)
#
# ``retryable`` is False whenever retrying would deterministically reproduce
# the same outcome (a moderation kick, a security policy, a duplicate login).
# ``prefer_new_server`` is True when the *server* is the thing that failed, so
# reusing its job identifier would simply fail again.
_CATALOG: dict[int, tuple[str, str, bool, bool]] = {
    256: ("The game server is shutting down", "shutdown", True, True),
    260: ("Lost connection to the game server", "network", True, True),
    264: ("This account joined from another device", "duplicate", False, False),
    266: ("Lost connection after a network timeout", "network", True, True),
    267: ("Kicked by the game", "kicked", False, False),
    268: ("The client was asked to rejoin", "rejoin", True, True),
    269: ("Disconnected by the client", "client", True, False),
    270: ("Disconnected by the security policy", "security", False, False),
    271: ("The server shut down after every player left", "shutdown", True, True),
    272: ("The client could not finish loading the place", "client", True, False),
    273: ("This account joined from another device", "duplicate", False, False),
    274: ("The game server shut down", "shutdown", True, True),
    275: ("Lost connection to the game server", "network", True, True),
    276: ("Lost connection to the game server", "network", True, True),
    277: ("Lost connection to the game server", "network", True, True),
    278: ("Disconnected for being idle too long", "idle", True, False),
    279: ("The connection attempt failed", "join", True, True),
    280: ("The place could not be joined", "join", True, True),
    281: ("Lost connection to the game server", "network", True, True),
    282: ("Lost connection to the game server", "network", True, True),
    284: ("The teleport failed", "teleport", True, True),
    285: ("The teleport target could not be reached", "teleport", True, True),
    286: ("This place is restricted for this account", "restricted", False, False),
}


@dataclass(frozen=True, slots=True)
class DisconnectReason:
    """A classified session ending, safe to hand to the bridge and the UI."""

    code: int | None
    label: str
    category: str
    retryable: bool
    prefer_new_server: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "label": self.label,
            "category": self.category,
            "retryable": self.retryable,
            "prefer_new_server": self.prefer_new_server,
        }


@dataclass(frozen=True, slots=True)
class RejoinPlan:
    """One decision about one interrupted session.

    ``attempt`` is the attempt this plan *would* perform, so it is always one
    more than the number of attempts already spent.  ``explanation`` exists so
    a refusal is never silent: the UI can always say which rule stopped it.
    """

    should_rejoin: bool
    attempt: int
    delay_seconds: float
    place_id: int | None
    job_id: str | None
    change_server: bool
    reason: DisconnectReason
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_rejoin": self.should_rejoin,
            "attempt": self.attempt,
            "delay_seconds": self.delay_seconds,
            "place_id": self.place_id,
            "job_id": self.job_id,
            "change_server": self.change_server,
            "reason": self.reason.to_dict(),
            "explanation": self.explanation,
        }


def classify_disconnect(code: Any = None) -> DisconnectReason:
    """Classify a disconnect code without trusting its source.

    Anything that is not a plausible integer code -- ``None``, a boolean, a
    string, a negative number -- is reported as unknown rather than coerced.
    """

    normalized = _optional_code(code)
    if normalized is None:
        return DisconnectReason(None, UNKNOWN_CODE_LABEL, "unknown", True, False)
    entry = _CATALOG.get(normalized)
    if entry is None:
        return DisconnectReason(
            normalized,
            f"Disconnect code {normalized} is not documented",
            "unknown",
            True,
            False,
        )
    label, category, retryable, prefer_new_server = entry
    return DisconnectReason(normalized, label, category, retryable, prefer_new_server)


def known_disconnect_codes() -> tuple[dict[str, Any], ...]:
    """Return the catalog, ordered by code, for settings screens and docs."""

    return tuple(
        classify_disconnect(code).to_dict() for code in sorted(_CATALOG)
    )


def plan_rejoin(
    *,
    attempt: int = 0,
    max_attempts: int = 5,
    base_delay_seconds: float = 5.0,
    disconnect_code: Any = None,
    place_id: Any = None,
    job_id: Any = None,
    change_server_after: int = 2,
    backoff_factor: float = 2.0,
    max_delay_seconds: float = 300.0,
    enabled: bool = True,
    require_place: bool = True,
) -> RejoinPlan:
    """Decide whether an interrupted session should be rejoined.

    Validation happens before any decision so that a malformed rule is a loud
    error even when the feature is switched off.
    """

    spent = _bounded_int(
        attempt, 0, MAX_REJOIN_ATTEMPTS, f"Rejoin attempt count must be between 0 and {MAX_REJOIN_ATTEMPTS}."
    )
    ceiling = _bounded_int(
        max_attempts, 0, MAX_REJOIN_ATTEMPTS, f"Maximum rejoin attempts must be between 0 and {MAX_REJOIN_ATTEMPTS}."
    )
    threshold = _bounded_int(
        change_server_after,
        0,
        MAX_CHANGE_SERVER_AFTER,
        f"The server change threshold must be between 0 and {MAX_CHANGE_SERVER_AFTER}.",
    )
    base_delay = _bounded_float(
        base_delay_seconds,
        MIN_REJOIN_DELAY_SECONDS,
        MAX_REJOIN_DELAY_SECONDS,
        f"The rejoin delay must be between {MIN_REJOIN_DELAY_SECONDS:g} and {MAX_REJOIN_DELAY_SECONDS:g} seconds.",
    )
    delay_ceiling = _bounded_float(
        max_delay_seconds,
        MIN_REJOIN_DELAY_SECONDS,
        MAX_REJOIN_DELAY_SECONDS,
        f"The maximum rejoin delay must be between {MIN_REJOIN_DELAY_SECONDS:g} and {MAX_REJOIN_DELAY_SECONDS:g} seconds.",
    )
    factor = _bounded_float(
        backoff_factor,
        MIN_BACKOFF_FACTOR,
        MAX_BACKOFF_FACTOR,
        f"The rejoin backoff factor must be between {MIN_BACKOFF_FACTOR:g} and {MAX_BACKOFF_FACTOR:g}.",
    )
    if not isinstance(enabled, bool):
        raise ValidationError("The rejoin enablement flag is invalid.")
    if not isinstance(require_place, bool):
        raise ValidationError("The rejoin place requirement flag is invalid.")
    place = _optional_place(place_id)
    job = _optional_job(job_id)
    reason = classify_disconnect(disconnect_code)

    change_server = bool(reason.prefer_new_server or threshold == 0 or (spent + 1) > threshold)
    delay = min(base_delay * (factor**spent), delay_ceiling)
    delay = round(max(delay, MIN_REJOIN_DELAY_SECONDS), 3)

    if not enabled:
        return _refusal(reason, spent, delay, place, change_server, "Automatic rejoin is disabled.")
    if spent >= ceiling:
        return _refusal(
            reason,
            spent,
            delay,
            place,
            change_server,
            f"The maximum of {ceiling} rejoin attempts was reached.",
        )
    if not reason.retryable:
        return _refusal(
            reason,
            spent,
            delay,
            place,
            change_server,
            f"{reason.label} is not retried automatically.",
        )
    if require_place and place is None:
        return _refusal(
            reason,
            spent,
            delay,
            place,
            change_server,
            "The previous place is unknown, so the session cannot be restored.",
        )

    destination = "a new server" if change_server else "the same server"
    return RejoinPlan(
        should_rejoin=True,
        attempt=spent + 1,
        delay_seconds=delay,
        place_id=place,
        job_id=None if change_server else job,
        change_server=change_server,
        reason=reason,
        explanation=f"Attempt {spent + 1} of {ceiling} on {destination} in {delay:g} seconds.",
    )


def _refusal(
    reason: DisconnectReason,
    spent: int,
    delay: float,
    place: int | None,
    change_server: bool,
    explanation: str,
) -> RejoinPlan:
    return RejoinPlan(
        should_rejoin=False,
        attempt=spent,
        delay_seconds=delay,
        place_id=place,
        job_id=None,
        change_server=change_server,
        reason=reason,
        explanation=explanation,
    )


def _optional_code(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 < value <= MAX_DISCONNECT_CODE else None


def _optional_place(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError("The rejoin place identifier is invalid.")
    return value


def _optional_job(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("The rejoin server identifier is invalid.")
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > MAX_JOB_ID_CHARS:
        raise ValidationError(f"A server identifier cannot exceed {MAX_JOB_ID_CHARS} characters.")
    return normalized


def _bounded_int(value: Any, minimum: int, maximum: int, message: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValidationError(message)
    return value


def _bounded_float(value: Any, minimum: float, maximum: float, message: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(message)
    number = float(value)
    if number != number or not minimum <= number <= maximum:
        raise ValidationError(message)
    return number
