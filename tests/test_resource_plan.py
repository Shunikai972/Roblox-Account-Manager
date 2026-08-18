"""Bounded coverage for adaptive frame rates, the RAM watchdog and capacity.

The policy is pure, so these tests pin the shipped decisions, including the
awkward one: Roblox caps frames globally, so the applied cap follows the most
demanding window instead of pretending to be per-window.
"""

from __future__ import annotations

import pytest

from app.backend.core.errors import ValidationError
from app.backend.watchers.resource_plan import (
    ACTION_NONE,
    ACTION_PAUSE_LAUNCHES,
    ACTION_RECOMMEND_CLOSE,
    BYTES_PER_MB,
    LEVEL_CRITICAL,
    LEVEL_OK,
    LEVEL_WARN,
    MAX_PLANNED_INSTANCES,
    PROFILE_IDLE,
    PROFILE_MACRO,
    PROFILE_WATCHED,
    InstanceFacts,
    MachineFacts,
    ResourceSettings,
    estimated_capacity,
    plan_resources,
    validated_resource_settings,
)


def _on(**overrides: object) -> ResourceSettings:
    base = {"adaptive_fps_enabled": True}
    base.update(overrides)
    return validated_resource_settings(base)


def _machine(**overrides: object) -> MachineFacts:
    base = {
        "cpu_percent": 40.0,
        "memory_percent": 55.0,
        "total_bytes": 34_359_738_368,
        "available_bytes": 16_000_000_000,
    }
    base.update(overrides)
    return MachineFacts(**base)  # type: ignore[arg-type]


# --- Adaptive frame rates ---------------------------------------------------


def test_each_window_gets_the_profile_it_deserves():
    plan = plan_resources(
        instances=[
            InstanceFacts(pid=1, username="Alt01", watched=True),
            InstanceFacts(pid=2, username="Alt02", macro_running=True),
            InstanceFacts(pid=3, username="Alt03"),
        ],
        machine=_machine(),
        settings=_on(),
    )
    assert [target.profile for target in plan.targets] == [
        PROFILE_WATCHED,
        PROFILE_MACRO,
        PROFILE_IDLE,
    ]
    assert [target.target_fps for target in plan.targets] == [60, 20, 5]


def test_a_watched_window_running_a_macro_is_still_watched():
    plan = plan_resources(
        instances=[InstanceFacts(pid=1, watched=True, macro_running=True)],
        machine=_machine(),
        settings=_on(),
    )
    assert plan.targets[0].profile == PROFILE_WATCHED


def test_the_applied_cap_follows_the_most_demanding_window():
    # A global cap must never throttle the window the user is looking at.
    plan = plan_resources(
        instances=[
            InstanceFacts(pid=1, username="Alt01"),
            InstanceFacts(pid=2, username="Alt02", watched=True),
        ],
        machine=_machine(),
        settings=_on(),
    )
    assert plan.applied_fps == 60
    assert "most demanding" in plan.applied_reason


def test_macros_alone_keep_the_cap_low():
    plan = plan_resources(
        instances=[InstanceFacts(pid=1, macro_running=True), InstanceFacts(pid=2)],
        machine=_machine(),
        settings=_on(),
    )
    assert plan.applied_fps == 20


def test_idle_windows_alone_drop_to_the_floor():
    plan = plan_resources(
        instances=[InstanceFacts(pid=1), InstanceFacts(pid=2)],
        machine=_machine(),
        settings=_on(),
    )
    assert plan.applied_fps == 5


def test_nothing_is_applied_while_the_feature_is_off():
    plan = plan_resources(
        instances=[InstanceFacts(pid=1, watched=True)],
        machine=_machine(),
        settings=validated_resource_settings({}),
    )
    assert plan.applied_fps is None
    assert "off" in plan.applied_reason
    # The advice is still computed, so the UI can show what it would do.
    assert plan.targets[0].target_fps == 60


def test_nothing_is_applied_without_a_single_window():
    plan = plan_resources(instances=[], machine=_machine(), settings=_on())
    assert plan.applied_fps is None
    assert plan.instance_count == 0


def test_the_payload_never_promises_per_window_frame_rates():
    payload = plan_resources(
        instances=[InstanceFacts(pid=1)], machine=_machine(), settings=_on()
    ).to_dict()
    assert payload["per_window_fps_supported"] is False


# --- The RAM watchdog -------------------------------------------------------


def test_a_calm_machine_reports_ok():
    plan = plan_resources(instances=[InstanceFacts(pid=1)], machine=_machine(), settings=_on())
    assert plan.level == LEVEL_OK
    assert plan.action == ACTION_NONE


def test_pressure_holds_new_launches_back():
    plan = plan_resources(
        instances=[InstanceFacts(pid=1)],
        machine=_machine(memory_percent=88.0),
        settings=_on(),
    )
    assert plan.level == LEVEL_WARN
    assert plan.action == ACTION_PAUSE_LAUNCHES
    assert "88%" in plan.message


def test_critical_pressure_recommends_closing_a_client():
    plan = plan_resources(
        instances=[InstanceFacts(pid=1), InstanceFacts(pid=2)],
        machine=_machine(memory_percent=95.0),
        settings=_on(),
    )
    assert plan.level == LEVEL_CRITICAL
    assert plan.action == ACTION_RECOMMEND_CLOSE
    # Closing is never automatic: the wording has to stay a recommendation.
    assert "Close a client" in plan.message


def test_the_thresholds_are_inclusive():
    warn = plan_resources(machine=_machine(memory_percent=85.0), settings=_on())
    critical = plan_resources(machine=_machine(memory_percent=93.0), settings=_on())
    assert warn.level == LEVEL_WARN
    assert critical.level == LEVEL_CRITICAL


def test_an_unmeasurable_machine_stays_quiet():
    plan = plan_resources(machine=MachineFacts(), settings=_on())
    assert plan.level == LEVEL_OK
    assert plan.action == ACTION_NONE
    assert "not measurable" in plan.message


# --- Capacity ---------------------------------------------------------------


def test_capacity_uses_what_the_clients_actually_weigh():
    plan = plan_resources(
        instances=[
            InstanceFacts(pid=1, memory_bytes=2 * BYTES_PER_MB * 1_000),
            InstanceFacts(pid=2, memory_bytes=2 * BYTES_PER_MB * 1_000),
        ],
        machine=_machine(available_bytes=10 * BYTES_PER_MB * 1_000),
        settings=_on(reserve_mb=2_048),
    )
    assert plan.measured_instance_bytes == 2 * BYTES_PER_MB * 1_000
    # (10000 - 2048) MB / 2000 MB per client
    assert plan.estimated_additional_instances == 3


def test_capacity_falls_back_to_the_expected_weight():
    plan = plan_resources(
        instances=[InstanceFacts(pid=1)],
        machine=_machine(available_bytes=8 * BYTES_PER_MB * 1_000),
        settings=_on(reserve_mb=2_048, average_instance_mb=1_200),
    )
    assert plan.measured_instance_bytes is None
    assert plan.estimated_additional_instances == 4


def test_a_saturated_machine_has_no_capacity_left():
    plan = plan_resources(
        machine=_machine(available_bytes=1 * BYTES_PER_MB * 1_000),
        settings=_on(reserve_mb=2_048),
    )
    assert plan.estimated_additional_instances == 0


def test_capacity_is_unknown_when_memory_cannot_be_read():
    assert (
        estimated_capacity(
            machine=MachineFacts(), settings=_on(), measured_bytes=None
        )
        is None
    )


# --- Bounds -----------------------------------------------------------------


def test_windows_beyond_the_ceiling_are_ignored():
    instances = [InstanceFacts(pid=index) for index in range(1, MAX_PLANNED_INSTANCES + 10)]
    plan = plan_resources(instances=instances, machine=_machine(), settings=_on())
    assert plan.instance_count == MAX_PLANNED_INSTANCES


@pytest.mark.parametrize(
    "entry",
    [InstanceFacts(pid=0), InstanceFacts(pid=-1), "not-a-window", None],
)
def test_unusable_windows_are_ignored(entry):
    plan = plan_resources(instances=[entry], machine=_machine(), settings=_on())
    assert plan.instance_count == 0


# --- Settings ---------------------------------------------------------------


def test_adaptive_frame_rates_stay_off_until_switched_on():
    settings = validated_resource_settings({})
    assert settings.adaptive_fps_enabled is False
    assert (settings.watched_fps, settings.macro_fps, settings.idle_fps) == (60, 20, 5)
    assert settings.memory_warn_percent == 85
    assert settings.memory_critical_percent == 93


@pytest.mark.parametrize(
    "payload",
    [
        {"adaptive_fps_enabled": "yes"},
        {"watched_fps": 4},
        {"watched_fps": 241},
        {"macro_fps": "low"},
        {"idle_fps": True},
        {"memory_warn_percent": 49},
        {"memory_critical_percent": 100},
        {"reserve_mb": 100},
        {"reserve_mb": 20_000},
        {"average_instance_mb": 10},
        {"average_instance_mb": 9_000},
        {"memory_warn_percent": 95, "memory_critical_percent": 90},
    ],
)
def test_out_of_range_settings_are_refused(payload):
    with pytest.raises(ValidationError):
        validated_resource_settings(payload)


def test_a_non_mapping_payload_is_refused():
    with pytest.raises(ValidationError):
        validated_resource_settings("quiet")


def test_missing_keys_keep_the_existing_value():
    existing = _on(idle_fps=8)
    assert validated_resource_settings({}, existing=existing).idle_fps == 8
