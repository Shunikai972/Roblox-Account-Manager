"""Fleet coordination: spread, main + followers, synced actions, party.

These are *plans*, not actions.  Each function answers "who goes where, and
when", and the service performs the launches and teleports it already knows
how to perform.

Honest limit: Roblox exposes no public way to invite an account to a party
from outside the client.  "Party" here means the accounts are sent to the same
server at the same moment, which is the part a launcher can actually do.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from app.backend.core.errors import ValidationError

MAX_COORDINATED_ACCOUNTS = 50
MAX_PARTY_SIZE = 8
MIN_STAGGER_SECONDS = 0.0
MAX_STAGGER_SECONDS = 120.0
DEFAULT_STAGGER_SECONDS = 1.5
DEFAULT_MAX_PER_SERVER = 1
MAX_PER_SERVER = 20

SYNC_ACTIONS = {"launch", "teleport", "rejoin"}


@dataclass(frozen=True, slots=True)
class CoordinatedStep:
    account_id: str
    username: str
    order: int
    offset_seconds: float
    job_id: str = ""
    place_id: str = ""
    role: str = "member"

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "username": self.username,
            "order": self.order,
            "offset_seconds": round(self.offset_seconds, 2),
            "job_id": self.job_id,
            "place_id": self.place_id,
            "role": self.role,
        }


def _accounts(raw: Iterable[Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in list(raw or [])[: MAX_COORDINATED_ACCOUNTS + 1]:
        if isinstance(item, Mapping):
            account_id = str(item.get("id") or item.get("account_id") or "").strip()
            username = str(item.get("username") or "").strip()
        else:
            account_id = str(item or "").strip()
            username = ""
        if not account_id or account_id in seen:
            continue
        seen.add(account_id)
        rows.append({"id": account_id, "username": username or account_id})
    if len(rows) > MAX_COORDINATED_ACCOUNTS:
        raise ValidationError(f"Coordinate at most {MAX_COORDINATED_ACCOUNTS} accounts at once.")
    return rows


def _stagger(value: Any) -> float:
    try:
        seconds = float(value if value is not None else DEFAULT_STAGGER_SECONDS)
    except (TypeError, ValueError) as exc:
        raise ValidationError("The stagger delay must be a number.") from exc
    if not math.isfinite(seconds) or not MIN_STAGGER_SECONDS <= seconds <= MAX_STAGGER_SECONDS:
        raise ValidationError(
            f"The stagger delay must be between {MIN_STAGGER_SECONDS:g} and {MAX_STAGGER_SECONDS:g} seconds."
        )
    return seconds


def spread_plan(
    accounts: Iterable[Any],
    *,
    servers: Sequence[Any] = (),
    max_per_server: int = DEFAULT_MAX_PER_SERVER,
    place_id: str = "",
    stagger_seconds: float = DEFAULT_STAGGER_SECONDS,
) -> dict[str, Any]:
    """Spread accounts over distinct servers so they do not stack up.

    With fewer servers than accounts the remainder is left unassigned rather
    than silently piled onto the last server.
    """

    rows = _accounts(accounts)
    if not rows:
        raise ValidationError("Select at least one account to spread.")
    per_server = max(1, min(int(max_per_server or DEFAULT_MAX_PER_SERVER), MAX_PER_SERVER))
    delay = _stagger(stagger_seconds)

    pool: list[str] = []
    for item in servers or ():
        job_id = str(item.get("job_id") if isinstance(item, Mapping) else item or "").strip()
        if job_id and job_id not in pool:
            pool.append(job_id)

    capacity = len(pool) * per_server
    steps: list[CoordinatedStep] = []
    unassigned: list[dict[str, str]] = []
    for index, row in enumerate(rows):
        if pool and index >= capacity:
            unassigned.append(row)
            continue
        job_id = pool[index // per_server] if pool else ""
        steps.append(
            CoordinatedStep(
                account_id=row["id"],
                username=row["username"],
                order=index + 1,
                offset_seconds=index * delay,
                job_id=job_id,
                place_id=str(place_id or ""),
            )
        )
    return {
        "mode": "spread",
        "steps": [step.to_dict() for step in steps],
        "unassigned": unassigned,
        "servers": pool,
        "max_per_server": per_server,
        "stagger_seconds": delay,
        "estimated_seconds": round(max((step.offset_seconds for step in steps), default=0.0), 2),
        "note": (
            "Every account gets its own server."
            if per_server == 1 and pool
            else "Accounts are spread across the known servers."
        )
        if pool
        else "No server list was given, so the accounts are only staggered in time.",
    }


def follower_plan(
    *,
    main: Any,
    followers: Iterable[Any],
    job_id: str = "",
    place_id: str = "",
    stagger_seconds: float = DEFAULT_STAGGER_SECONDS,
) -> dict[str, Any]:
    """Send every follower to the main account's server, main first."""

    leader = _accounts([main])
    if not leader:
        raise ValidationError("Choose a main account.")
    crew = [row for row in _accounts(followers) if row["id"] != leader[0]["id"]]
    if not crew:
        raise ValidationError("Choose at least one follower.")
    delay = _stagger(stagger_seconds)
    steps = [
        CoordinatedStep(
            account_id=leader[0]["id"],
            username=leader[0]["username"],
            order=1,
            offset_seconds=0.0,
            job_id=str(job_id or ""),
            place_id=str(place_id or ""),
            role="main",
        )
    ]
    for index, row in enumerate(crew, start=1):
        steps.append(
            CoordinatedStep(
                account_id=row["id"],
                username=row["username"],
                order=index + 1,
                offset_seconds=index * delay,
                job_id=str(job_id or ""),
                place_id=str(place_id or ""),
                role="follower",
            )
        )
    return {
        "mode": "followers",
        "steps": [step.to_dict() for step in steps],
        "main": leader[0],
        "followers": crew,
        "stagger_seconds": delay,
        "estimated_seconds": round(steps[-1].offset_seconds, 2),
        "note": (
            "Followers join the main account's server."
            if job_id
            else "No server id yet: launch the main account first, then follow it once its server is known."
        ),
        "ready": bool(job_id),
    }


def sync_plan(
    accounts: Iterable[Any],
    *,
    action: str = "launch",
    job_id: str = "",
    place_id: str = "",
    stagger_seconds: float = 0.0,
    now: float = 0.0,
    countdown_seconds: float = 3.0,
) -> dict[str, Any]:
    """Fire the same action on several accounts from one starting instant."""

    verb = str(action or "launch").strip().lower()
    if verb not in SYNC_ACTIONS:
        raise ValidationError("That synchronized action is not supported.")
    rows = _accounts(accounts)
    if len(rows) < 2:
        raise ValidationError("Pick at least two accounts to synchronize.")
    delay = _stagger(stagger_seconds)
    countdown = max(0.0, min(float(countdown_seconds or 0.0), MAX_STAGGER_SECONDS))
    start = float(now) + countdown
    steps = [
        CoordinatedStep(
            account_id=row["id"],
            username=row["username"],
            order=index + 1,
            offset_seconds=index * delay,
            job_id=str(job_id or ""),
            place_id=str(place_id or ""),
        )
        for index, row in enumerate(rows)
    ]
    return {
        "mode": "sync",
        "action": verb,
        "steps": [step.to_dict() for step in steps],
        "starts_at": start,
        "countdown_seconds": countdown,
        "stagger_seconds": delay,
        "spread_seconds": round(steps[-1].offset_seconds, 2),
        # A zero stagger is a real request, not an accident: say what it costs.
        "note": (
            "Zero stagger sends every request in the same instant, which is the most demanding on the machine."
            if delay == 0
            else "Requests are spread slightly so the machine keeps up."
        ),
    }


def party_plan(
    accounts: Iterable[Any],
    *,
    job_id: str = "",
    place_id: str = "",
    max_size: int = MAX_PARTY_SIZE,
    stagger_seconds: float = DEFAULT_STAGGER_SECONDS,
) -> dict[str, Any]:
    """Group accounts into one server, capped at the party size."""

    limit = max(2, min(int(max_size or MAX_PARTY_SIZE), MAX_PARTY_SIZE))
    rows = _accounts(accounts)
    if len(rows) < 2:
        raise ValidationError("A party needs at least two accounts.")
    members = rows[:limit]
    overflow = rows[limit:]
    delay = _stagger(stagger_seconds)
    steps = [
        CoordinatedStep(
            account_id=row["id"],
            username=row["username"],
            order=index + 1,
            offset_seconds=index * delay,
            job_id=str(job_id or ""),
            place_id=str(place_id or ""),
            role="main" if index == 0 else "member",
        )
        for index, row in enumerate(members)
    ]
    return {
        "mode": "party",
        "steps": [step.to_dict() for step in steps],
        "size": len(members),
        "max_size": limit,
        "overflow": overflow,
        "ready": bool(job_id),
        "note": (
            "Astro cannot send a Roblox party invite from outside the client. "
            "These accounts are sent to the same server instead, which is the part a launcher can do."
        ),
    }
