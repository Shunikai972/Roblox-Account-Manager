"""Bounded coverage for the smart launcher's planning policy.

The planner is pure, so these tests assert the real shipped behaviour rather
than a mock of it: no process table, no clock, no Roblox.
"""

from __future__ import annotations

import pytest

from app.backend.core.errors import ValidationError
from app.backend.watchers.launch_planner import (
    DEFAULT_CONCURRENT_LAUNCHES,
    DEFAULT_LAUNCH_DELAY_SECONDS,
    MAX_PLANNED_ACCOUNTS,
    SKIP_ALREADY_RUNNING,
    SKIP_DUPLICATE,
    SKIP_INVALID,
    SKIP_OVER_LIMIT,
    LauncherSettings,
    plan_launches,
    validated_launcher_settings,
)


def _accounts(count: int, *, start: int = 1) -> list[dict[str, str]]:
    return [
        {"account_id": f"acc-{index}", "username": f"Alt{index:02d}"}
        for index in range(start, start + count)
    ]


def _settings(**overrides: object) -> LauncherSettings:
    base = {"max_concurrent": 3, "delay_seconds": 4.0}
    base.update(overrides)
    return validated_launcher_settings(base)


# --- Waves and staggering ---------------------------------------------------


def test_ten_accounts_are_spread_into_waves_of_three():
    # The user's own example: launch 10, at most 3 booting at once, 4s apart.
    plan = plan_launches(accounts=_accounts(10), settings=_settings())
    assert len(plan.steps) == 10
    assert plan.waves == 4
    assert [step.wave for step in plan.steps] == [0, 0, 0, 1, 1, 1, 2, 2, 2, 3]
    assert [step.position for step in plan.steps] == [0, 1, 2, 0, 1, 2, 0, 1, 2, 0]


def test_every_launch_is_delayed_by_the_configured_gap():
    plan = plan_launches(accounts=_accounts(5), settings=_settings())
    assert [step.start_after_seconds for step in plan.steps] == [0.0, 4.0, 8.0, 12.0, 16.0]


def test_a_larger_gap_stretches_the_whole_schedule():
    plan = plan_launches(accounts=_accounts(3), settings=_settings(delay_seconds=10.0))
    assert [step.start_after_seconds for step in plan.steps] == [0.0, 10.0, 20.0]
    assert plan.estimated_seconds == 30.0


def test_an_empty_request_produces_an_empty_plan():
    plan = plan_launches(accounts=[], settings=_settings())
    assert plan.steps == ()
    assert plan.waves == 0
    assert plan.estimated_seconds == 0.0


def test_the_caller_order_is_respected():
    # Priority is the caller's decision: groups, favourites, custom priority.
    accounts = [
        {"account_id": "acc-b", "username": "Bravo"},
        {"account_id": "acc-a", "username": "Alpha"},
    ]
    plan = plan_launches(accounts=accounts, settings=_settings())
    assert [step.account_id for step in plan.steps] == ["acc-b", "acc-a"]


# --- What gets skipped, and why ---------------------------------------------


def test_running_accounts_are_skipped_with_a_reason():
    plan = plan_launches(
        accounts=_accounts(3),
        running_account_ids=["acc-2"],
        settings=_settings(),
    )
    assert [step.account_id for step in plan.steps] == ["acc-1", "acc-3"]
    assert [(item.account_id, item.reason) for item in plan.skipped] == [
        ("acc-2", SKIP_ALREADY_RUNNING)
    ]
    assert plan.running_before == 1


def test_running_accounts_can_be_relaunched_on_purpose():
    plan = plan_launches(
        accounts=_accounts(2),
        running_account_ids=["acc-1"],
        settings=_settings(skip_running=False),
    )
    assert [step.account_id for step in plan.steps] == ["acc-1", "acc-2"]
    assert plan.skipped == ()


def test_a_repeated_account_is_launched_once():
    accounts = _accounts(1) + _accounts(1)
    plan = plan_launches(accounts=accounts, settings=_settings())
    assert len(plan.steps) == 1
    assert [item.reason for item in plan.skipped] == [SKIP_DUPLICATE]


@pytest.mark.parametrize(
    "entry",
    [
        {"username": "No id"},
        {"account_id": "   "},
        "not-a-mapping",
        None,
    ],
)
def test_unusable_entries_are_skipped_instead_of_crashing(entry):
    plan = plan_launches(accounts=[entry], settings=_settings())
    assert plan.steps == ()
    assert [item.reason for item in plan.skipped] == [SKIP_INVALID]


def test_the_plan_refuses_to_grow_past_its_ceiling():
    plan = plan_launches(accounts=_accounts(MAX_PLANNED_ACCOUNTS + 5), settings=_settings())
    assert len(plan.steps) == MAX_PLANNED_ACCOUNTS
    assert {item.reason for item in plan.skipped} == {SKIP_OVER_LIMIT}


def test_a_caller_limit_is_honoured():
    plan = plan_launches(accounts=_accounts(10), settings=_settings(), limit=4)
    assert len(plan.steps) == 4
    assert len(plan.skipped) == 6


# --- The payload the UI reads -----------------------------------------------


def test_the_plan_serialises_everything_the_ui_needs():
    payload = plan_launches(
        accounts=_accounts(4),
        running_account_ids=["acc-1"],
        settings=_settings(),
    ).to_dict()
    assert payload["planned"] == 3
    assert payload["waves"] == 1
    assert payload["max_concurrent"] == 3
    assert payload["delay_seconds"] == 4.0
    assert payload["running_before"] == 1
    assert payload["steps"][0]["username"] == "Alt02"
    assert payload["skipped"][0]["reason"] == SKIP_ALREADY_RUNNING


# --- Settings ---------------------------------------------------------------


def test_defaults_stay_gentle_on_the_machine():
    settings = validated_launcher_settings({})
    assert settings.max_concurrent == DEFAULT_CONCURRENT_LAUNCHES == 3
    assert settings.delay_seconds == DEFAULT_LAUNCH_DELAY_SECONDS == 4.0
    assert settings.wait_for_wave is True
    assert settings.skip_running is True


def test_missing_keys_keep_the_existing_value():
    existing = _settings(max_concurrent=5)
    assert validated_launcher_settings({}, existing=existing).max_concurrent == 5


@pytest.mark.parametrize(
    "payload",
    [
        {"max_concurrent": 0},
        {"max_concurrent": 11},
        {"max_concurrent": "three"},
        {"max_concurrent": True},
        {"delay_seconds": 0.1},
        {"delay_seconds": 301},
        {"delay_seconds": "soon"},
        {"wait_for_wave": "yes"},
        {"skip_running": 1},
    ],
)
def test_out_of_range_settings_are_refused(payload):
    with pytest.raises(ValidationError):
        validated_launcher_settings(payload)


def test_a_non_mapping_payload_is_refused():
    with pytest.raises(ValidationError):
        validated_launcher_settings("fast")


def test_none_keeps_the_current_settings():
    existing = _settings(delay_seconds=7.0)
    assert validated_launcher_settings(None, existing=existing).delay_seconds == 7.0
