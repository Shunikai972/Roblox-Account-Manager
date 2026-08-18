"""Clock driven tasks: launch a group at 18:00, stop the macros at 23:00.

The schedule is pure data.  This module validates it, says what is due and
when the next run lands; the service performs the action.  Nothing here can
start or close anything by itself, which keeps the dangerous half testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping

from app.backend.core.errors import ValidationError

MAX_TASKS = 40
MAX_NAME_CHARS = 60
MAX_ID_CHARS = 128
MAX_TARGET_ACCOUNTS = 50
DEFAULT_GRACE_SECONDS = 120
MAX_GRACE_SECONDS = 3_600

# Only actions the service already exposes, and none of them closes a live
# client without the operator asking for it.
TASK_ACTIONS = {
    "launch_group": "Launch a group",
    "launch_accounts": "Launch selected accounts",
    "stop_macros": "Stop every macro",
    "start_macro": "Start a macro",
    "apply_resource_plan": "Apply the resource plan",
    "close_instances": "Close the listed instances",
}
GROUP_ACTIONS = {"launch_group"}
ACCOUNT_ACTIONS = {"launch_accounts", "close_instances"}
MACRO_ACTIONS = {"start_macro"}

_TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_DAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True, slots=True)
class ScheduledTask:
    id: str
    name: str
    action: str
    at: str
    days: tuple[int, ...]
    enabled: bool = True
    group_id: str = ""
    account_ids: tuple[str, ...] = ()
    macro_id: str = ""
    last_run_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "action": self.action,
            "action_label": TASK_ACTIONS.get(self.action, self.action),
            "at": self.at,
            "days": list(self.days),
            "day_labels": [_DAY_LABELS[day] for day in self.days],
            "enabled": self.enabled,
            "group_id": self.group_id,
            "account_ids": list(self.account_ids),
            "macro_id": self.macro_id,
            "last_run_at": self.last_run_at,
        }


def _identifier(value: Any, label: str, *, required: bool) -> str:
    text = str(value or "").strip()
    if not text:
        if required:
            raise ValidationError(f"{label} is required for this task.")
        return ""
    if len(text) > MAX_ID_CHARS or any(ord(char) < 33 for char in text):
        raise ValidationError(f"{label} is invalid.")
    return text


def validated_task(raw: Any, *, existing_id: str = "") -> ScheduledTask:
    """Validate one schedule entry, refusing anything the service cannot run."""

    if not isinstance(raw, Mapping):
        raise ValidationError("A scheduled task must be an object.")
    action = str(raw.get("action") or "").strip().lower()
    if action not in TASK_ACTIONS:
        raise ValidationError("That scheduled action is not supported.")
    at = str(raw.get("at") or "").strip()
    if not _TIME_PATTERN.match(at):
        raise ValidationError("Task time must use the 24 hour HH:MM form.")
    name = str(raw.get("name") or TASK_ACTIONS[action]).strip()[:MAX_NAME_CHARS]
    if not name:
        raise ValidationError("Task name is required.")

    raw_days = raw.get("days")
    if raw_days is None or raw_days == []:
        days: tuple[int, ...] = tuple(range(7))
    else:
        if not isinstance(raw_days, (list, tuple)):
            raise ValidationError("Task days must be a list.")
        parsed: set[int] = set()
        for item in raw_days:
            try:
                day = int(item)
            except (TypeError, ValueError) as exc:
                raise ValidationError("Task days must be numbers from 0 to 6.") from exc
            if not 0 <= day <= 6:
                raise ValidationError("Task days must be numbers from 0 to 6.")
            parsed.add(day)
        if not parsed:
            raise ValidationError("Select at least one day for the task.")
        days = tuple(sorted(parsed))

    group_id = _identifier(raw.get("group_id"), "Group", required=action in GROUP_ACTIONS)
    macro_id = _identifier(raw.get("macro_id"), "Macro", required=action in MACRO_ACTIONS)
    account_ids: tuple[str, ...] = ()
    raw_accounts = raw.get("account_ids")
    if raw_accounts:
        if not isinstance(raw_accounts, (list, tuple)):
            raise ValidationError("Task accounts must be a list.")
        if len(raw_accounts) > MAX_TARGET_ACCOUNTS:
            raise ValidationError(f"A task may target at most {MAX_TARGET_ACCOUNTS} accounts.")
        seen: list[str] = []
        for item in raw_accounts:
            value = _identifier(item, "Account", required=True)
            if value not in seen:
                seen.append(value)
        account_ids = tuple(seen)
    if action in ACCOUNT_ACTIONS and not account_ids:
        raise ValidationError("Select at least one account for this task.")

    last_run_raw = raw.get("last_run_at")
    try:
        last_run = float(last_run_raw) if last_run_raw is not None else None
    except (TypeError, ValueError):
        last_run = None

    return ScheduledTask(
        id=_identifier(raw.get("id") or existing_id, "Task id", required=False),
        name=name,
        action=action,
        at=at,
        days=days,
        enabled=bool(raw.get("enabled", True)),
        group_id=group_id,
        account_ids=account_ids,
        macro_id=macro_id,
        last_run_at=last_run,
    )


def validated_tasks(raw: Any) -> list[ScheduledTask]:
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise ValidationError("The schedule must be a list of tasks.")
    if len(raw) > MAX_TASKS:
        raise ValidationError(f"The schedule holds at most {MAX_TASKS} tasks.")
    tasks = [validated_task(item) for item in raw]
    identifiers = [task.id for task in tasks if task.id]
    if len(identifiers) != len(set(identifiers)):
        raise ValidationError("Two scheduled tasks share the same id.")
    return tasks


def next_run_at(task: ScheduledTask, *, now: float) -> float | None:
    """Return the next epoch second this task should fire, local time."""

    if not task.enabled or not task.days:
        return None
    hour, minute = (int(part) for part in task.at.split(":"))
    moment = datetime.fromtimestamp(float(now))
    for offset in range(0, 8):
        candidate = (moment + timedelta(days=offset)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if candidate.weekday() not in task.days:
            continue
        stamp = candidate.timestamp()
        if stamp > float(now):
            return stamp
    return None


def due_tasks(
    tasks: Iterable[ScheduledTask],
    *,
    now: float,
    grace_seconds: int = DEFAULT_GRACE_SECONDS,
) -> list[dict[str, Any]]:
    """Return the tasks whose slot just passed and that have not run for it.

    The grace window lets a task still fire if the app was busy, while
    ``last_run_at`` guarantees one run per slot even if the loop ticks twice.
    """

    grace = max(0, min(int(grace_seconds or 0), MAX_GRACE_SECONDS))
    moment = datetime.fromtimestamp(float(now))
    due: list[dict[str, Any]] = []
    for task in tasks:
        if not task.enabled or not task.days:
            continue
        hour, minute = (int(part) for part in task.at.split(":"))
        for offset in (0, 1):
            slot_day = moment - timedelta(days=offset)
            if slot_day.weekday() not in task.days:
                continue
            slot = slot_day.replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()
            if not (slot <= float(now) <= slot + grace):
                continue
            if task.last_run_at is not None and float(task.last_run_at) >= slot:
                continue
            due.append({"task": task, "slot": slot})
            break
    due.sort(key=lambda item: item["slot"])
    return due


def describe_schedule(tasks: Iterable[ScheduledTask], *, now: float) -> list[dict[str, Any]]:
    """Schedule rows ready for display, soonest first."""

    rows: list[dict[str, Any]] = []
    for task in tasks:
        payload = task.to_dict()
        upcoming = next_run_at(task, now=now)
        payload["next_run_at"] = upcoming
        payload["next_run_in_seconds"] = round(upcoming - float(now), 1) if upcoming else None
        rows.append(payload)
    rows.sort(key=lambda row: (row["next_run_at"] is None, row["next_run_at"] or 0.0))
    return rows
