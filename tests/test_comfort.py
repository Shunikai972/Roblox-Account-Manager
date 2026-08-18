"""Comfort: focus, sleep, audio, safe shutdown, dynamic launch queue."""

from __future__ import annotations

import pytest

from app.backend.core.errors import ValidationError
from app.backend.watchers.comfort import (
    audio_plan,
    focus_plan,
    queue_gate,
    shutdown_plan,
    sleep_plan,
)

NOW = 1_800_000_000.0
INSTANCES = [
    {"pid": 101, "username": "Alt1", "account_id": "a1", "last_activity_at": NOW - 60},
    {"pid": 202, "username": "Alt2", "account_id": "a2", "macro_running": True, "last_activity_at": NOW - 7200},
    {"pid": 303, "username": "Alt3", "account_id": "a3", "last_activity_at": NOW - 7200},
]


def test_focus_keeps_one_window_loud_and_quiets_the_others() -> None:
    plan = focus_plan(INSTANCES, focus_pid=101)
    targets = {target["pid"]: target for target in plan["targets"]}
    assert targets[101]["focused"] is True
    assert targets[101]["volume"] == 100
    assert targets[101]["minimize"] is False
    assert targets[202]["volume"] == 0
    assert targets[303]["minimize"] is True
    assert plan["minimized"] == 2


def test_focus_warns_when_it_would_minimize_a_running_macro() -> None:
    # Minimising a window stops foreground input, which breaks a live macro.
    plan = focus_plan(INSTANCES, focus_pid=101)
    assert plan["macro_conflicts"] == [202]


def test_focus_refuses_a_window_that_is_not_running() -> None:
    with pytest.raises(ValidationError):
        focus_plan(INSTANCES, focus_pid=999)
    with pytest.raises(ValidationError):
        focus_plan(INSTANCES, focus_pid=0)


def test_focus_on_an_empty_fleet_is_not_an_error() -> None:
    assert focus_plan([], focus_pid=101)["targets"] == []


def test_sleep_parks_idle_windows_and_leaves_macros_alone() -> None:
    plan = sleep_plan(INSTANCES, now=NOW, idle_minutes=15)
    assert [row["pid"] for row in plan["sleeping"]] == [303]
    assert any(row["pid"] == 202 and "macro" in row["reason"] for row in plan["skipped"])


def test_sleep_can_include_macro_windows_when_asked() -> None:
    plan = sleep_plan(INSTANCES, now=NOW, idle_minutes=15, include_macro_windows=True)
    assert {row["pid"] for row in plan["sleeping"]} == {202, 303}


def test_an_instance_without_activity_data_is_never_parked_silently() -> None:
    plan = sleep_plan([{"pid": 404, "username": "Alt4"}], now=NOW)
    assert plan["sleeping"] == []
    assert plan["skipped"][0]["reason"] == "no activity recorded yet"


def test_the_idle_delay_is_bounded() -> None:
    with pytest.raises(ValidationError):
        sleep_plan(INSTANCES, now=NOW, idle_minutes=0)
    with pytest.raises(ValidationError):
        sleep_plan(INSTANCES, now=NOW, idle_minutes=10_000)


def test_audio_says_plainly_when_the_machine_cannot_apply_it() -> None:
    plan = audio_plan(INSTANCES, supported=False)
    assert plan["supported"] is False
    assert "not applied" in plan["note"]
    assert len(plan["targets"]) == 3


def test_audio_levels_can_be_set_per_instance() -> None:
    plan = audio_plan(INSTANCES, volumes={"101": 20, "a3": 0}, default_volume=100, supported=True)
    targets = {target["pid"]: target["volume"] for target in plan["targets"]}
    assert targets == {101: 20, 202: 100, 303: 0}
    assert plan["supported"] is True


def test_an_out_of_range_volume_is_refused() -> None:
    with pytest.raises(ValidationError):
        audio_plan(INSTANCES, volumes={"101": 500})


def test_safe_shutdown_stops_the_macros_before_closing_anything() -> None:
    plan = shutdown_plan(INSTANCES, macro_runs=[{"id": "r1", "finished_at": None}], grace_seconds=5)
    assert [step["step"] for step in plan["steps"]] == ["stop_macros", "wait", "close_instances"]
    assert plan["steps"][-1]["requires_confirmation"] is True
    assert plan["steps"][-1]["pids"] == [101, 202, 303]


def test_safe_shutdown_skips_the_macro_step_when_none_is_running() -> None:
    plan = shutdown_plan(INSTANCES, macro_runs=[{"id": "r1", "finished_at": 10.0}])
    assert [step["step"] for step in plan["steps"]] == ["close_instances"]
    assert plan["macros"] == 0


def test_safe_shutdown_on_an_empty_fleet_has_nothing_to_do() -> None:
    plan = shutdown_plan([], macro_runs=[])
    assert plan["ready"] is False
    assert plan["steps"] == []


def test_the_launch_queue_waits_when_the_cpu_is_saturated() -> None:
    gate = queue_gate(cpu_percent=92.0, memory_percent=40.0, max_cpu_percent=80)
    assert gate["allowed"] is False
    assert "CPU is at 92%" in gate["blockers"][0]


def test_the_launch_queue_waits_when_memory_is_saturated() -> None:
    gate = queue_gate(cpu_percent=10.0, memory_percent=95.0, max_memory_percent=85)
    assert gate["allowed"] is False
    assert "memory is at 95%" in gate["blockers"][0]


def test_a_missing_reading_never_stalls_the_queue() -> None:
    gate = queue_gate(cpu_percent=None, memory_percent=None)
    assert gate["allowed"] is True
    assert gate["measured"] is False


def test_the_running_ceiling_also_holds_the_queue() -> None:
    gate = queue_gate(cpu_percent=10.0, memory_percent=10.0, running=6, max_running=6)
    assert gate["allowed"] is False
    assert "at the limit of 6" in gate["blockers"][0]


def test_a_free_machine_lets_the_next_launch_through() -> None:
    gate = queue_gate(cpu_percent=20.0, memory_percent=30.0, running=2, pending=5, max_running=10)
    assert gate["allowed"] is True
    assert gate["pending"] == 5
    assert "room for the next launch" in gate["reason"]


def test_an_impossible_limit_is_refused() -> None:
    with pytest.raises(ValidationError):
        queue_gate(cpu_percent=10.0, memory_percent=10.0, max_cpu_percent=5)
