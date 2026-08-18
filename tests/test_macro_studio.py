"""Macro studio: key profiles, variables, profiler, debugger, versioning."""

from __future__ import annotations

import pytest

from app.backend.automations.macro_studio import (
    MAX_VERSIONS,
    apply_profile_and_variables,
    describe_versions,
    flatten_steps,
    profile_macro,
    push_version,
    rollback_version,
    validated_key_profile,
    validated_key_profiles,
    validated_variables,
)
from app.backend.core.errors import ValidationError

NOW = 1_800_000_000.0
WALK = [
    {"type": "key_press", "key": "W", "milliseconds": 500},
    {"type": "repeat", "count": 3, "actions": [{"type": "key_press", "key": "E", "milliseconds": 100}]},
    {"type": "wait", "milliseconds": 1000},
]


def test_a_key_profile_needs_a_name_and_at_least_one_key() -> None:
    profile = validated_key_profile({"name": "Blox Fruits", "keys": {"w": "z"}})
    assert profile == {"name": "Blox Fruits", "keys": {"W": "Z"}}
    with pytest.raises(ValidationError):
        validated_key_profile({"name": "", "keys": {"W": "Z"}})
    with pytest.raises(ValidationError):
        validated_key_profile({"name": "Empty", "keys": {}})


def test_a_key_profile_refuses_something_that_is_not_a_key() -> None:
    with pytest.raises(ValidationError):
        validated_key_profile({"name": "Bad", "keys": {"W": "run forward please"}})


def test_two_profiles_cannot_share_a_name() -> None:
    rows = [{"name": "Same", "keys": {"W": "Z"}}, {"name": "same", "keys": {"A": "Q"}}]
    with pytest.raises(ValidationError):
        validated_key_profiles(rows)


def test_a_key_profile_rewrites_the_keys_of_a_macro() -> None:
    profile = validated_key_profile({"name": "AZERTY", "keys": {"W": "Z", "A": "Q"}})
    result = apply_profile_and_variables(WALK, profile=profile)
    assert result["actions"][0]["key"] == "Z"
    assert result["actions"][1]["actions"][0]["key"] == "E"
    assert result["remapped_keys"] == 1


def test_variable_names_are_checked() -> None:
    assert validated_variables({"Slot": 3}) == {"Slot": "3"}
    for bad in ({"9lives": "x"}, {"has space": "x"}, {"": "x"}):
        with pytest.raises(ValidationError):
            validated_variables(bad)


def test_variables_are_substituted_inside_typed_text() -> None:
    actions = [{"type": "text", "value": "/join {{TARGET}}"}]
    result = apply_profile_and_variables(actions, variables={"TARGET": "Alt7"})
    assert result["actions"][0]["value"] == "/join Alt7"
    assert result["resolved"] is True


def test_an_unbound_variable_is_reported_instead_of_being_typed_into_the_game() -> None:
    actions = [{"type": "text", "value": "hello {{MISSING}}"}]
    result = apply_profile_and_variables(actions, variables={})
    assert result["missing_variables"] == ["MISSING"]
    assert result["resolved"] is False
    assert result["actions"][0]["value"] == "hello {{MISSING}}"


def test_resolving_never_mutates_the_original_tree() -> None:
    original = [{"type": "key_press", "key": "W", "milliseconds": 10}]
    apply_profile_and_variables(original, profile={"keys": {"W": "Z"}})
    assert original[0]["key"] == "W"


def test_the_debugger_numbers_every_step_including_nested_ones() -> None:
    steps = flatten_steps(WALK)
    assert [step["path"] for step in steps] == ["1", "2", "2.1", "3"]
    assert [step["depth"] for step in steps] == [0, 0, 1, 0]
    assert steps[0]["label"] == "Press W for 500 ms"
    assert steps[1]["label"] == "Repeat 3 times"


def test_the_profiler_multiplies_the_body_of_a_loop() -> None:
    report = profile_macro(WALK)
    # 500 + 3 * 100 + 1000
    assert report["estimated_ms"] == 1800
    assert report["estimated_seconds"] == 1.8
    assert report["steps"] == 4
    assert report["slowest"][0]["milliseconds"] == 1000


def test_the_profiler_averages_a_randomised_wait() -> None:
    report = profile_macro([{"type": "wait", "milliseconds": 500, "max_milliseconds": 1500}])
    assert report["estimated_ms"] == 1000


def test_saving_a_version_keeps_the_newest_first() -> None:
    history = push_version([], macro={"name": "Walk", "actions": WALK}, now=NOW)
    history = push_version(history, macro={"name": "Walk", "actions": []}, now=NOW + 10, label="cleared")
    assert [row["version"] for row in history] == [2, 1]
    assert history[0]["label"] == "cleared"


def test_saving_an_unchanged_macro_does_not_create_a_version() -> None:
    history = push_version([], macro={"name": "Walk", "actions": WALK}, now=NOW)
    again = push_version(history, macro={"name": "Walk", "actions": WALK}, now=NOW + 60)
    assert len(again) == 1


def test_the_version_history_is_bounded() -> None:
    history: list = []
    for index in range(MAX_VERSIONS + 5):
        history = push_version(history, macro={"name": f"v{index}", "actions": []}, now=NOW + index)
    assert len(history) == MAX_VERSIONS
    assert history[0]["version"] == MAX_VERSIONS + 5


def test_rolling_back_returns_the_stored_snapshot() -> None:
    history = push_version([], macro={"name": "Walk", "actions": WALK}, now=NOW)
    history = push_version(history, macro={"name": "Walk", "actions": []}, now=NOW + 10)
    restored = rollback_version(history, version=1)
    assert restored["actions"] == WALK
    assert restored["name"] == "Walk"


def test_rolling_back_to_an_unknown_version_is_refused() -> None:
    with pytest.raises(ValidationError):
        rollback_version([], version=7)


def test_the_version_list_shows_the_step_count_of_each_snapshot() -> None:
    history = push_version([], macro={"name": "Walk", "actions": WALK}, now=NOW)
    rows = describe_versions(history)
    assert rows[0]["version"] == 1
    assert rows[0]["steps"] == 4
