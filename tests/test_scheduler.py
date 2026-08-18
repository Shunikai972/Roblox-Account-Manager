"""Scheduler: validation, next run, due detection, one run per slot."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.backend.automations.scheduler import (
    MAX_TASKS,
    describe_schedule,
    due_tasks,
    next_run_at,
    validated_task,
    validated_tasks,
)
from app.backend.core.errors import ValidationError


def _at(year: int, month: int, day: int, hour: int, minute: int = 0) -> float:
    return datetime(year, month, day, hour, minute).timestamp()


def test_a_group_launch_task_is_accepted() -> None:
    task = validated_task({"name": "Farm", "action": "launch_group", "at": "18:00", "group_id": "g1"})
    assert task.action == "launch_group"
    assert task.at == "18:00"
    assert task.days == tuple(range(7))
    assert task.to_dict()["action_label"] == "Launch a group"


def test_a_group_launch_without_a_group_is_refused() -> None:
    with pytest.raises(ValidationError):
        validated_task({"action": "launch_group", "at": "18:00"})


def test_an_unsupported_action_is_refused() -> None:
    with pytest.raises(ValidationError):
        validated_task({"action": "format_disk", "at": "18:00"})


def test_the_time_must_use_the_24_hour_form() -> None:
    for bad in ("6pm", "25:00", "18:60", "8:00", ""):
        with pytest.raises(ValidationError):
            validated_task({"action": "stop_macros", "at": bad})


def test_days_outside_the_week_are_refused() -> None:
    with pytest.raises(ValidationError):
        validated_task({"action": "stop_macros", "at": "23:00", "days": [0, 9]})


def test_duplicate_task_ids_are_refused() -> None:
    rows = [
        {"id": "same", "action": "stop_macros", "at": "23:00"},
        {"id": "same", "action": "stop_macros", "at": "22:00"},
    ]
    with pytest.raises(ValidationError):
        validated_tasks(rows)


def test_the_schedule_is_bounded() -> None:
    rows = [{"id": f"t{index}", "action": "stop_macros", "at": "23:00"} for index in range(MAX_TASKS + 1)]
    with pytest.raises(ValidationError):
        validated_tasks(rows)


def test_the_next_run_skips_days_that_are_not_selected() -> None:
    # Friday 14 August 2026, task runs on Monday only.
    task = validated_task({"action": "stop_macros", "at": "23:00", "days": [0]})
    upcoming = next_run_at(task, now=_at(2026, 8, 14, 12))
    assert upcoming is not None
    assert datetime.fromtimestamp(upcoming).weekday() == 0
    assert datetime.fromtimestamp(upcoming).hour == 23


def test_a_disabled_task_never_runs() -> None:
    task = validated_task({"action": "stop_macros", "at": "23:00", "enabled": False})
    assert next_run_at(task, now=_at(2026, 8, 14, 12)) is None
    assert due_tasks([task], now=_at(2026, 8, 14, 23)) == []


def test_a_task_is_due_inside_its_grace_window_only() -> None:
    task = validated_task({"action": "stop_macros", "at": "23:00"})
    assert due_tasks([task], now=_at(2026, 8, 14, 23), grace_seconds=120)
    assert due_tasks([task], now=_at(2026, 8, 14, 23) + 60, grace_seconds=120)
    assert due_tasks([task], now=_at(2026, 8, 14, 23) + 600, grace_seconds=120) == []
    assert due_tasks([task], now=_at(2026, 8, 14, 23) - 60, grace_seconds=120) == []


def test_a_task_runs_once_per_slot_even_if_the_loop_ticks_twice() -> None:
    slot = _at(2026, 8, 14, 23)
    task = validated_task({"action": "stop_macros", "at": "23:00"})
    first = due_tasks([task], now=slot + 5)
    assert len(first) == 1
    ran = validated_task({**task.to_dict(), "last_run_at": slot + 5})
    assert due_tasks([ran], now=slot + 30) == []


def test_yesterdays_slot_can_still_fire_inside_the_grace_window() -> None:
    # 00:20 with a task at 23:50 the night before, wide grace.
    task = validated_task({"action": "stop_macros", "at": "23:50"})
    now = _at(2026, 8, 15, 0, 10)
    assert due_tasks([task], now=now, grace_seconds=3_600)


def test_the_schedule_view_is_sorted_by_the_soonest_run() -> None:
    now = _at(2026, 8, 14, 12)
    rows = describe_schedule(
        [
            validated_task({"id": "late", "action": "stop_macros", "at": "23:00"}),
            validated_task({"id": "soon", "action": "stop_macros", "at": "13:00"}),
            validated_task({"id": "off", "action": "stop_macros", "at": "14:00", "enabled": False}),
        ],
        now=now,
    )
    assert [row["id"] for row in rows] == ["soon", "late", "off"]
    assert rows[0]["next_run_in_seconds"] == 3600.0
    assert rows[-1]["next_run_at"] is None
