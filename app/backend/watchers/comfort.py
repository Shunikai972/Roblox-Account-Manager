"""Comfort controls: focus, sleep, per-instance audio, safe shutdown, queue.

All of these are decision functions.  They read the fleet and the machine and
return what *should* happen; the service is what actually minimises a window,
moves a slider or closes a client, and it never closes anything on its own.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

from app.backend.core.errors import ValidationError

MIN_VOLUME = 0
MAX_VOLUME = 100
DEFAULT_FOCUS_VOLUME = 100
DEFAULT_BACKGROUND_VOLUME = 0
DEFAULT_SLEEP_MINUTES = 15
MIN_SLEEP_MINUTES = 1
MAX_SLEEP_MINUTES = 720
DEFAULT_QUEUE_CPU_PERCENT = 80
DEFAULT_QUEUE_MEMORY_PERCENT = 85
MIN_QUEUE_PERCENT = 30
MAX_QUEUE_PERCENT = 99
SHUTDOWN_GRACE_SECONDS = 5
MAX_SHUTDOWN_INSTANCES = 32


def _percent(value: Any, default: int, label: str) -> int:
    try:
        number = int(round(float(value if value is not None else default)))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} must be a number.") from exc
    if not MIN_QUEUE_PERCENT <= number <= MAX_QUEUE_PERCENT:
        raise ValidationError(f"{label} must be between {MIN_QUEUE_PERCENT} and {MAX_QUEUE_PERCENT} percent.")
    return number


def _volume(value: Any, default: int, label: str) -> int:
    try:
        number = int(round(float(value if value is not None else default)))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} must be a number.") from exc
    if not MIN_VOLUME <= number <= MAX_VOLUME:
        raise ValidationError(f"{label} must be between {MIN_VOLUME} and {MAX_VOLUME}.")
    return number


def _instances(raw: Iterable[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in raw or ():
        if not isinstance(item, Mapping):
            continue
        try:
            pid = int(item.get("pid") or 0)
        except (TypeError, ValueError):
            continue
        if pid <= 0:
            continue
        rows.append(
            {
                "pid": pid,
                "account_id": str(item.get("account_id") or ""),
                "username": str(item.get("username") or ""),
                "macro_running": bool(item.get("macro_running", False)),
                "watched": bool(item.get("watched", False)),
                "last_activity_at": item.get("last_activity_at"),
            }
        )
    return rows


def focus_plan(
    instances: Iterable[Any],
    *,
    focus_pid: int | None,
    background_volume: int = DEFAULT_BACKGROUND_VOLUME,
    focus_volume: int = DEFAULT_FOCUS_VOLUME,
    minimize_others: bool = True,
) -> dict[str, Any]:
    """Keep one client in front, quiet and shrink the rest."""

    rows = _instances(instances)
    if not rows:
        return {"mode": "focus", "targets": [], "focus_pid": None, "note": "No Roblox window is running."}
    try:
        wanted = int(focus_pid or 0)
    except (TypeError, ValueError) as exc:
        raise ValidationError("The focused instance id is invalid.") from exc
    if wanted <= 0:
        raise ValidationError("Choose which instance keeps the focus.")
    if not any(row["pid"] == wanted for row in rows):
        raise ValidationError("That instance is not running any more.")
    quiet = _volume(background_volume, DEFAULT_BACKGROUND_VOLUME, "Background volume")
    loud = _volume(focus_volume, DEFAULT_FOCUS_VOLUME, "Focus volume")
    targets = [
        {
            "pid": row["pid"],
            "username": row["username"],
            "focused": row["pid"] == wanted,
            "volume": loud if row["pid"] == wanted else quiet,
            "minimize": bool(minimize_others) and row["pid"] != wanted,
            "restore": row["pid"] == wanted,
        }
        for row in rows
    ]
    return {
        "mode": "focus",
        "focus_pid": wanted,
        "targets": targets,
        "minimized": sum(1 for target in targets if target["minimize"]),
        # Minimising a client stops foreground input reaching it, so a macro
        # that is running would break. Warn instead of silently ruining a farm.
        "macro_conflicts": [
            row["pid"] for row in rows if row["macro_running"] and row["pid"] != wanted and minimize_others
        ],
    }


def sleep_plan(
    instances: Iterable[Any],
    *,
    now: float,
    idle_minutes: int = DEFAULT_SLEEP_MINUTES,
    include_macro_windows: bool = False,
) -> dict[str, Any]:
    """List the instances idle long enough to be parked at low resources."""

    try:
        minutes = int(round(float(idle_minutes if idle_minutes is not None else DEFAULT_SLEEP_MINUTES)))
    except (TypeError, ValueError) as exc:
        raise ValidationError("The idle delay must be a number.") from exc
    if not MIN_SLEEP_MINUTES <= minutes <= MAX_SLEEP_MINUTES:
        raise ValidationError(f"The idle delay must be between {MIN_SLEEP_MINUTES} and {MAX_SLEEP_MINUTES} minutes.")
    horizon = float(now) - minutes * 60.0
    sleeping: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in _instances(instances):
        if row["macro_running"] and not include_macro_windows:
            skipped.append({"pid": row["pid"], "username": row["username"], "reason": "a macro is running"})
            continue
        last = row.get("last_activity_at")
        try:
            stamp = float(last) if last is not None else None
        except (TypeError, ValueError):
            stamp = None
        if stamp is None:
            skipped.append({"pid": row["pid"], "username": row["username"], "reason": "no activity recorded yet"})
            continue
        if stamp > horizon:
            continue
        sleeping.append(
            {
                "pid": row["pid"],
                "username": row["username"],
                "idle_seconds": round(float(now) - stamp, 1),
                "volume": 0,
                "minimize": True,
            }
        )
    return {
        "mode": "sleep",
        "idle_minutes": minutes,
        "sleeping": sleeping,
        "skipped": skipped,
        "count": len(sleeping),
    }


def audio_plan(
    instances: Iterable[Any],
    *,
    volumes: Mapping[str, Any] | None = None,
    default_volume: int = DEFAULT_FOCUS_VOLUME,
    supported: bool = False,
) -> dict[str, Any]:
    """Per-instance volume targets.

    ``supported`` comes from the machine: Windows can set a per-process volume
    through the audio session API, but only when that backend is available.
    Without it this returns the intent and says plainly that nothing will move.
    """

    wanted = volumes if isinstance(volumes, Mapping) else {}
    fallback = _volume(default_volume, DEFAULT_FOCUS_VOLUME, "Default volume")
    targets = []
    for row in _instances(instances):
        raw = wanted.get(str(row["pid"]), wanted.get(row["account_id"]))
        targets.append(
            {
                "pid": row["pid"],
                "account_id": row["account_id"],
                "username": row["username"],
                "volume": _volume(raw, fallback, "Instance volume") if raw is not None else fallback,
            }
        )
    return {
        "mode": "audio",
        "supported": bool(supported),
        "targets": targets,
        "note": (
            "Per-instance volume is applied through the Windows audio session for each Roblox process."
            if supported
            else "This machine exposes no per-process audio control, so these levels are stored but not applied."
        ),
    }


def shutdown_plan(
    instances: Iterable[Any],
    *,
    macro_runs: Iterable[Any] = (),
    grace_seconds: int = SHUTDOWN_GRACE_SECONDS,
) -> dict[str, Any]:
    """Order a safe shutdown: stop the macros, wait, then close the clients.

    The closing step is returned as a request. Nothing here closes a client;
    the operator confirms it, which is the rule this build follows everywhere.
    """

    rows = _instances(instances)
    if len(rows) > MAX_SHUTDOWN_INSTANCES:
        raise ValidationError(f"Close at most {MAX_SHUTDOWN_INSTANCES} instances at once.")
    try:
        grace = int(round(float(grace_seconds if grace_seconds is not None else SHUTDOWN_GRACE_SECONDS)))
    except (TypeError, ValueError) as exc:
        raise ValidationError("The shutdown grace delay must be a number.") from exc
    if not 0 <= grace <= 120:
        raise ValidationError("The shutdown grace delay must be between 0 and 120 seconds.")
    active = [run for run in (macro_runs or ()) if isinstance(run, Mapping) and not run.get("finished_at")]
    steps: list[dict[str, Any]] = []
    if active:
        steps.append({"step": "stop_macros", "count": len(active), "detail": "Stop every running macro first."})
        steps.append({"step": "wait", "seconds": grace, "detail": "Let the macros release their keys."})
    if rows:
        steps.append(
            {
                "step": "close_instances",
                "count": len(rows),
                "pids": [row["pid"] for row in rows],
                "detail": "Close the Roblox clients. This needs your confirmation.",
                "requires_confirmation": True,
            }
        )
    return {
        "mode": "safe_shutdown",
        "steps": steps,
        "macros": len(active),
        "instances": len(rows),
        "grace_seconds": grace,
        "ready": bool(steps),
    }


def queue_gate(
    *,
    cpu_percent: float | None,
    memory_percent: float | None,
    running: int = 0,
    pending: int = 0,
    max_cpu_percent: int = DEFAULT_QUEUE_CPU_PERCENT,
    max_memory_percent: int = DEFAULT_QUEUE_MEMORY_PERCENT,
    max_running: int = 0,
) -> dict[str, Any]:
    """Say whether the next queued launch may start right now.

    An unknown reading never blocks the queue: a missing probe is not a reason
    to stall a farm, and the launcher's own concurrency cap still applies.
    """

    cpu_limit = _percent(max_cpu_percent, DEFAULT_QUEUE_CPU_PERCENT, "The CPU launch limit")
    memory_limit = _percent(max_memory_percent, DEFAULT_QUEUE_MEMORY_PERCENT, "The memory launch limit")

    def _reading(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    cpu = _reading(cpu_percent)
    memory = _reading(memory_percent)
    blockers: list[str] = []
    if cpu is not None and cpu >= cpu_limit:
        blockers.append(f"CPU is at {cpu:.0f}%, above the {cpu_limit}% launch limit")
    if memory is not None and memory >= memory_limit:
        blockers.append(f"memory is at {memory:.0f}%, above the {memory_limit}% launch limit")
    ceiling = max(0, int(max_running or 0))
    if ceiling and int(running or 0) >= ceiling:
        blockers.append(f"{running} clients are already running, at the limit of {ceiling}")
    return {
        "allowed": not blockers,
        "blockers": blockers,
        "reason": blockers[0] if blockers else "The machine has room for the next launch.",
        "cpu_percent": cpu,
        "memory_percent": memory,
        "max_cpu_percent": cpu_limit,
        "max_memory_percent": memory_limit,
        "running": int(running or 0),
        "pending": max(0, int(pending or 0)),
        "measured": cpu is not None or memory is not None,
    }
