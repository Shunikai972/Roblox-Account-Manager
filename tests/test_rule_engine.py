"""Tests for the bounded IF/THEN rule engine.

These tests are deliberately pure: the engine takes sampled facts and returns
decisions, so every branch can be proven without a Roblox client, a process, or
a clock.  The dangerous half matters most -- a decision that would close a live
client must never come back marked as automatic.
"""

from __future__ import annotations

import pytest

from app.backend.core.errors import ValidationError
from app.backend.watchers.rule_engine import (
    ACTION_PAUSE_MACRO,
    ACTION_RECOMMEND_RESTART_CLIENT,
    ACTION_RESTART_MACRO,
    ACTION_RESUME_MACRO,
    AUTOMATIC_ACTIONS,
    DEFAULT_PRIORITY,
    MAX_DECISIONS,
    MAX_GROUP_SCOPE,
    MAX_PRIORITY,
    MIN_PRIORITY,
    PRESSURE_RELEASE_MARGIN,
    RULE_CPU_PRESSURE,
    RULE_DISCONNECTED,
    RULE_MACRO_STUCK,
    RULE_MEMORY_PRESSURE,
    RULE_PRESSURE_RELEASED,
    RULE_SESSION_TOO_LONG,
    AccountFacts,
    RuleDecision,
    RuleSettings,
    SystemFacts,
    automatic_decisions,
    evaluate_rules,
    normalized_priority,
    recommendations,
    validated_rule_settings,
)


def _enabled(**overrides: object) -> RuleSettings:
    base = {
        "enabled": True,
        "macro_stuck_seconds": 60,
        "max_runtime_hours": 6.0,
        "cpu_pause_percent": 90,
        "memory_pause_percent": 90,
        "pause_priority_at_or_below": 3,
        "restart_stuck_macros": True,
    }
    base.update(overrides)
    return validated_rule_settings(base)


def _farming(**overrides: object) -> AccountFacts:
    values = {
        "account_id": "acc-1",
        "username": "Alt01",
        "priority": 1,
        "running": True,
        "runtime_seconds": 600.0,
        "macro_run_id": "run-1",
        "macro_id": "macro-1",
        "macro_state": "running",
        "macro_idle_seconds": 2.0,
    }
    values.update(overrides)
    return AccountFacts(**values)  # type: ignore[arg-type]


# Disabled by default --------------------------------------------------------


def test_rules_are_disabled_by_default():
    assert RuleSettings().enabled is False


def test_disabled_rules_return_no_decisions():
    decisions = evaluate_rules(
        accounts=[_farming(macro_idle_seconds=9_999)],
        system=SystemFacts(cpu_percent=99),
        settings=RuleSettings(),
    )
    assert decisions == ()


def test_missing_settings_are_treated_as_disabled():
    assert evaluate_rules(accounts=[_farming()]) == ()


def test_empty_account_list_is_safe():
    assert evaluate_rules(accounts=[], settings=_enabled()) == ()


# CPU and memory pressure ----------------------------------------------------


def test_cpu_pressure_pauses_low_priority_macro():
    decisions = evaluate_rules(
        accounts=[_farming(priority=1)],
        system=SystemFacts(cpu_percent=95),
        settings=_enabled(),
    )
    assert len(decisions) == 1
    assert decisions[0].action == ACTION_PAUSE_MACRO
    assert decisions[0].rule == RULE_CPU_PRESSURE
    assert decisions[0].automatic is True
    assert decisions[0].run_id == "run-1"


def test_cpu_pressure_spares_high_priority_macro():
    decisions = evaluate_rules(
        accounts=[_farming(priority=9)],
        system=SystemFacts(cpu_percent=95),
        settings=_enabled(),
    )
    assert decisions == ()


def test_memory_pressure_pauses_macro():
    decisions = evaluate_rules(
        accounts=[_farming()],
        system=SystemFacts(memory_percent=93),
        settings=_enabled(),
    )
    assert decisions[0].rule == RULE_MEMORY_PRESSURE
    assert decisions[0].action == ACTION_PAUSE_MACRO


def test_pressure_threshold_is_inclusive():
    decisions = evaluate_rules(
        accounts=[_farming()],
        system=SystemFacts(cpu_percent=90),
        settings=_enabled(cpu_pause_percent=90),
    )
    assert decisions[0].action == ACTION_PAUSE_MACRO


def test_usage_below_threshold_does_not_pause():
    decisions = evaluate_rules(
        accounts=[_farming()],
        system=SystemFacts(cpu_percent=89, memory_percent=50),
        settings=_enabled(cpu_pause_percent=90),
    )
    assert decisions == ()


def test_cpu_takes_precedence_over_memory_in_the_explanation():
    decisions = evaluate_rules(
        accounts=[_farming()],
        system=SystemFacts(cpu_percent=99, memory_percent=99),
        settings=_enabled(),
    )
    assert decisions[0].rule == RULE_CPU_PRESSURE


def test_unmeasured_system_never_pauses():
    decisions = evaluate_rules(
        accounts=[_farming()],
        system=SystemFacts(cpu_percent=None, memory_percent=None),
        settings=_enabled(),
    )
    assert decisions == ()


def test_negative_measurements_are_ignored():
    decisions = evaluate_rules(
        accounts=[_farming()],
        system=SystemFacts(cpu_percent=-5),
        settings=_enabled(),
    )
    assert decisions == ()


def test_pressure_pauses_lowest_priority_accounts_first():
    accounts = [
        _farming(account_id="acc-high", username="Main", priority=3, macro_run_id="run-high"),
        _farming(account_id="acc-low", username="Farm", priority=0, macro_run_id="run-low"),
    ]
    decisions = evaluate_rules(
        accounts=accounts,
        system=SystemFacts(cpu_percent=97),
        settings=_enabled(),
    )
    assert [item.account_id for item in decisions] == ["acc-low", "acc-high"]


def test_only_running_macros_are_paused():
    decisions = evaluate_rules(
        accounts=[_farming(macro_state="completed")],
        system=SystemFacts(cpu_percent=99),
        settings=_enabled(),
    )
    assert decisions == ()


# Hysteresis -----------------------------------------------------------------


def test_paused_macro_resumes_once_load_falls_below_the_margin():
    account = _farming(macro_state="paused", macro_paused_by_rule=True)
    decisions = evaluate_rules(
        accounts=[account],
        system=SystemFacts(cpu_percent=90 - PRESSURE_RELEASE_MARGIN),
        settings=_enabled(cpu_pause_percent=90),
    )
    assert decisions[0].action == ACTION_RESUME_MACRO
    assert decisions[0].rule == RULE_PRESSURE_RELEASED
    assert decisions[0].automatic is True


def test_macro_stays_paused_inside_the_hysteresis_band():
    account = _farming(macro_state="paused", macro_paused_by_rule=True)
    decisions = evaluate_rules(
        accounts=[account],
        system=SystemFacts(cpu_percent=85),
        settings=_enabled(cpu_pause_percent=90),
    )
    assert decisions == ()


def test_memory_still_high_blocks_resume_even_when_cpu_recovered():
    account = _farming(macro_state="paused", macro_paused_by_rule=True)
    decisions = evaluate_rules(
        accounts=[account],
        system=SystemFacts(cpu_percent=10, memory_percent=88),
        settings=_enabled(cpu_pause_percent=90, memory_pause_percent=90),
    )
    assert decisions == ()


def test_macros_paused_by_a_human_are_never_resumed_by_rules():
    account = _farming(macro_state="paused", macro_paused_by_rule=False)
    decisions = evaluate_rules(
        accounts=[account],
        system=SystemFacts(cpu_percent=5),
        settings=_enabled(),
    )
    assert decisions == ()


# Stuck macros ---------------------------------------------------------------


def test_stuck_macro_is_restarted():
    decisions = evaluate_rules(
        accounts=[_farming(macro_idle_seconds=75)],
        system=SystemFacts(cpu_percent=20),
        settings=_enabled(macro_stuck_seconds=60),
    )
    assert decisions[0].action == ACTION_RESTART_MACRO
    assert decisions[0].rule == RULE_MACRO_STUCK
    assert decisions[0].automatic is True
    assert "75s" in decisions[0].explanation


def test_stuck_threshold_is_inclusive():
    decisions = evaluate_rules(
        accounts=[_farming(macro_idle_seconds=60)],
        system=SystemFacts(cpu_percent=20),
        settings=_enabled(macro_stuck_seconds=60),
    )
    assert decisions[0].action == ACTION_RESTART_MACRO


def test_progressing_macro_is_left_alone():
    decisions = evaluate_rules(
        accounts=[_farming(macro_idle_seconds=5)],
        system=SystemFacts(cpu_percent=20),
        settings=_enabled(macro_stuck_seconds=60),
    )
    assert decisions == ()


def test_stuck_macro_restart_can_be_switched_off():
    decisions = evaluate_rules(
        accounts=[_farming(macro_idle_seconds=999)],
        system=SystemFacts(cpu_percent=20),
        settings=_enabled(restart_stuck_macros=False),
    )
    assert decisions == ()


def test_pressure_outranks_a_stuck_macro():
    decisions = evaluate_rules(
        accounts=[_farming(macro_idle_seconds=999, priority=0)],
        system=SystemFacts(cpu_percent=99),
        settings=_enabled(),
    )
    assert len(decisions) == 1
    assert decisions[0].action == ACTION_PAUSE_MACRO


# Recommendations that need a human -----------------------------------------


def test_disconnected_live_client_is_only_a_recommendation():
    decisions = evaluate_rules(
        accounts=[_farming(disconnected=True, macro_state=None, macro_run_id=None)],
        system=SystemFacts(cpu_percent=10),
        settings=_enabled(),
    )
    assert decisions[0].action == ACTION_RECOMMEND_RESTART_CLIENT
    assert decisions[0].rule == RULE_DISCONNECTED
    assert decisions[0].automatic is False
    assert "confirmation" in decisions[0].explanation


def test_long_session_is_only_a_recommendation():
    decisions = evaluate_rules(
        accounts=[_farming(runtime_seconds=7 * 3_600, macro_state=None, macro_run_id=None)],
        system=SystemFacts(cpu_percent=10),
        settings=_enabled(max_runtime_hours=6),
    )
    assert decisions[0].action == ACTION_RECOMMEND_RESTART_CLIENT
    assert decisions[0].rule == RULE_SESSION_TOO_LONG
    assert decisions[0].automatic is False


def test_no_recommendation_before_the_session_limit():
    decisions = evaluate_rules(
        accounts=[_farming(runtime_seconds=3 * 3_600, macro_state=None, macro_run_id=None)],
        system=SystemFacts(cpu_percent=10),
        settings=_enabled(max_runtime_hours=6),
    )
    assert decisions == ()


def test_stopped_account_is_never_recommended_for_restart():
    decisions = evaluate_rules(
        accounts=[
            _farming(
                running=False,
                disconnected=True,
                runtime_seconds=99 * 3_600,
                macro_state=None,
                macro_run_id=None,
            )
        ],
        system=SystemFacts(cpu_percent=10),
        settings=_enabled(),
    )
    assert decisions == ()


def test_closing_a_client_is_never_marked_automatic():
    decisions = evaluate_rules(
        accounts=[_farming(disconnected=True, macro_state=None, macro_run_id=None)],
        system=SystemFacts(cpu_percent=10),
        settings=_enabled(),
    )
    assert automatic_decisions(decisions) == ()
    assert len(recommendations(decisions)) == 1


def test_automatic_actions_never_include_client_restart():
    assert ACTION_RECOMMEND_RESTART_CLIENT not in AUTOMATIC_ACTIONS


def test_automatic_and_recommendation_filters_partition_decisions():
    accounts = [
        _farming(account_id="acc-stuck", macro_idle_seconds=999, macro_run_id="run-stuck"),
        _farming(
            account_id="acc-old",
            priority=8,
            runtime_seconds=99 * 3_600,
            macro_state=None,
            macro_run_id=None,
        ),
    ]
    decisions = evaluate_rules(
        accounts=accounts, system=SystemFacts(cpu_percent=10), settings=_enabled()
    )
    assert len(decisions) == 2
    assert len(automatic_decisions(decisions)) + len(recommendations(decisions)) == 2


# Group scope and priority ---------------------------------------------------


def test_group_scope_limits_the_rules():
    accounts = [
        _farming(account_id="acc-farm", group_id="group-farm", macro_idle_seconds=999),
        _farming(account_id="acc-main", group_id="group-main", macro_idle_seconds=999),
    ]
    decisions = evaluate_rules(
        accounts=accounts,
        system=SystemFacts(cpu_percent=10),
        settings=_enabled(group_ids=["group-farm"]),
    )
    assert [item.account_id for item in decisions] == ["acc-farm"]


def test_empty_group_scope_covers_every_account():
    settings = _enabled()
    assert settings.covers(None) is True
    assert settings.covers("group-any") is True


def test_scoped_rules_skip_ungrouped_accounts():
    settings = _enabled(group_ids=["group-farm"])
    assert settings.covers(None) is False
    assert settings.covers("group-farm") is True


def test_priority_is_clamped_and_defaults_safely():
    assert normalized_priority(None) == DEFAULT_PRIORITY
    assert normalized_priority(True) == DEFAULT_PRIORITY
    assert normalized_priority("nonsense") == DEFAULT_PRIORITY
    assert normalized_priority(-4) == MIN_PRIORITY
    assert normalized_priority(99) == MAX_PRIORITY
    assert normalized_priority("7") == 7


def test_decision_count_is_bounded():
    accounts = [
        _farming(account_id=f"acc-{index:03d}", macro_run_id=f"run-{index}", macro_idle_seconds=999)
        for index in range(MAX_DECISIONS + 25)
    ]
    decisions = evaluate_rules(
        accounts=accounts, system=SystemFacts(cpu_percent=10), settings=_enabled()
    )
    assert len(decisions) == MAX_DECISIONS


def test_invalid_fact_entries_are_ignored():
    decisions = evaluate_rules(
        accounts=[None, "nope", _farming(account_id=""), _farming(macro_idle_seconds=999)],  # type: ignore[list-item]
        system=SystemFacts(cpu_percent=10),
        settings=_enabled(),
    )
    assert len(decisions) == 1


# Settings validation --------------------------------------------------------


def test_partial_updates_keep_existing_values():
    existing = _enabled(macro_stuck_seconds=120)
    updated = validated_rule_settings({"cpu_pause_percent": 80}, existing=existing)
    assert updated.macro_stuck_seconds == 120
    assert updated.cpu_pause_percent == 80
    assert updated.enabled is True


def test_none_payload_returns_existing_settings():
    existing = _enabled()
    assert validated_rule_settings(None, existing=existing) == existing


def test_non_mapping_payload_is_refused():
    with pytest.raises(ValidationError):
        validated_rule_settings(["enabled"])


@pytest.mark.parametrize(
    "payload",
    [
        {"enabled": "yes"},
        {"macro_stuck_seconds": 5},
        {"macro_stuck_seconds": 99_999},
        {"macro_stuck_seconds": True},
        {"max_runtime_hours": 0.5},
        {"max_runtime_hours": 99},
        {"cpu_pause_percent": 10},
        {"cpu_pause_percent": 150},
        {"memory_pause_percent": 1},
        {"pause_priority_at_or_below": 99},
        {"pause_priority_at_or_below": -1},
        {"restart_stuck_macros": "true"},
        {"group_ids": "group-farm"},
        {"group_ids": [""]},
        {"group_ids": [123]},
    ],
)
def test_out_of_range_settings_are_refused(payload):
    with pytest.raises(ValidationError):
        validated_rule_settings(payload)


def test_group_scope_is_bounded_and_deduplicated():
    settings = validated_rule_settings({"group_ids": ["a", "a", "b"]})
    assert settings.group_ids == ("a", "b")
    with pytest.raises(ValidationError):
        validated_rule_settings({"group_ids": [f"group-{index}" for index in range(MAX_GROUP_SCOPE + 1)]})


def test_settings_round_trip_through_dict():
    settings = _enabled(group_ids=["group-farm"])
    payload = settings.to_dict()
    assert payload["group_ids"] == ["group-farm"]
    assert validated_rule_settings(payload) == settings


def test_default_settings_expose_bounded_rules():
    """The shipped defaults must be acceptable to the engine that reads them.

    A default that fails its own validator would break every settings save, so
    this guard ties the stored category to the rules instead of trusting both
    to be edited together.
    """

    from app.backend.core.config import DEFAULT_SETTINGS

    settings = validated_rule_settings(DEFAULT_SETTINGS["rules"])
    assert settings.enabled is False
    assert settings.macro_stuck_seconds == 60
    assert settings.max_runtime_hours == 6.0
    assert settings.cpu_pause_percent == 90
    assert settings.memory_pause_percent == 90
    assert settings.pause_priority_at_or_below == 3
    assert settings.restart_stuck_macros is True
    assert settings.group_ids == ()


def test_rules_stay_inert_until_switched_on_in_settings():
    from app.backend.core.config import DEFAULT_SETTINGS

    settings = validated_rule_settings(DEFAULT_SETTINGS["rules"])
    decisions = evaluate_rules(
        accounts=[_farming(macro_idle_seconds=9_999, runtime_seconds=99 * 3_600)],
        system=SystemFacts(cpu_percent=99, memory_percent=99),
        settings=settings,
    )
    assert decisions == ()


def test_decision_serialization_is_stable():
    decision = RuleDecision(
        action=ACTION_PAUSE_MACRO,
        rule=RULE_CPU_PRESSURE,
        account_id="acc-1",
        username="Alt01",
        explanation="because",
        run_id="run-1",
        macro_id="macro-1",
        automatic=True,
    )
    assert decision.to_dict() == {
        "action": ACTION_PAUSE_MACRO,
        "rule": RULE_CPU_PRESSURE,
        "account_id": "acc-1",
        "username": "Alt01",
        "explanation": "because",
        "run_id": "run-1",
        "macro_id": "macro-1",
        "automatic": True,
    }
