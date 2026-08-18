"""Bounded coverage for the automatic rejoin decision rules.

These tests pin the behaviour that the watcher depends on: which disconnect
codes are worth retrying, how the delay grows, when a fresh server is
preferred, and which malformed rule is refused loudly.
"""

from __future__ import annotations

import pytest

from app.backend.core.errors import ValidationError
from app.backend.watchers.rejoin_rules import (
    MAX_JOB_ID_CHARS,
    MAX_REJOIN_ATTEMPTS,
    classify_disconnect,
    known_disconnect_codes,
    plan_rejoin,
)

# A retryable code that does *not* blame the server, so the same-server path
# stays observable in tests.
IDLE_CODE = 278
# The classic "lost connection" code that must always move to a new server.
NETWORK_CODE = 277
PLACE_ID = 1818


# Classification -------------------------------------------------------------


def test_network_disconnects_are_retried_on_a_new_server() -> None:
    reason = classify_disconnect(NETWORK_CODE)
    assert reason.code == NETWORK_CODE
    assert reason.category == "network"
    assert reason.retryable is True
    assert reason.prefer_new_server is True


def test_kicked_sessions_are_never_retried() -> None:
    reason = classify_disconnect(267)
    assert reason.category == "kicked"
    assert reason.retryable is False


def test_duplicate_logins_are_never_retried() -> None:
    assert classify_disconnect(273).retryable is False


def test_security_disconnects_are_never_retried() -> None:
    reason = classify_disconnect(270)
    assert reason.category == "security"
    assert reason.retryable is False


def test_server_shutdowns_prefer_a_new_server() -> None:
    reason = classify_disconnect(274)
    assert reason.category == "shutdown"
    assert reason.prefer_new_server is True


def test_teleport_failures_prefer_a_new_server() -> None:
    reason = classify_disconnect(284)
    assert reason.category == "teleport"
    assert reason.retryable is True
    assert reason.prefer_new_server is True


def test_undocumented_codes_stay_retryable_without_pretending_to_be_known() -> None:
    reason = classify_disconnect(4242)
    assert reason.code == 4242
    assert reason.category == "unknown"
    assert reason.retryable is True
    assert reason.prefer_new_server is False
    assert "4242" in reason.label


def test_a_missing_code_is_reported_as_unknown() -> None:
    reason = classify_disconnect(None)
    assert reason.code is None
    assert reason.category == "unknown"


def test_boolean_codes_are_not_coerced() -> None:
    assert classify_disconnect(True).code is None


def test_string_codes_are_not_coerced() -> None:
    assert classify_disconnect("277").code is None


def test_negative_codes_are_ignored() -> None:
    assert classify_disconnect(-5).code is None


def test_every_catalog_entry_is_well_formed() -> None:
    catalog = known_disconnect_codes()
    assert catalog
    for entry in catalog:
        assert isinstance(entry["code"], int)
        assert isinstance(entry["label"], str) and entry["label"]
        assert isinstance(entry["category"], str) and entry["category"]
        assert isinstance(entry["retryable"], bool)
        assert isinstance(entry["prefer_new_server"], bool)


def test_the_catalog_is_ordered_by_code() -> None:
    codes = [entry["code"] for entry in known_disconnect_codes()]
    assert codes == sorted(codes)


# Delay and backoff ----------------------------------------------------------


def test_the_first_attempt_uses_the_base_delay() -> None:
    plan = plan_rejoin(
        attempt=0, base_delay_seconds=5.0, disconnect_code=IDLE_CODE, place_id=PLACE_ID
    )
    assert plan.should_rejoin is True
    assert plan.attempt == 1
    assert plan.delay_seconds == 5.0


def test_the_delay_grows_with_every_spent_attempt() -> None:
    plan = plan_rejoin(
        attempt=2,
        base_delay_seconds=5.0,
        backoff_factor=2.0,
        disconnect_code=IDLE_CODE,
        place_id=PLACE_ID,
    )
    assert plan.attempt == 3
    assert plan.delay_seconds == 20.0


def test_the_delay_is_capped() -> None:
    plan = plan_rejoin(
        attempt=3,
        base_delay_seconds=5.0,
        backoff_factor=2.0,
        max_delay_seconds=30.0,
        disconnect_code=IDLE_CODE,
        place_id=PLACE_ID,
    )
    assert plan.delay_seconds == 30.0


def test_a_factor_of_one_keeps_a_flat_delay() -> None:
    plan = plan_rejoin(
        attempt=4,
        base_delay_seconds=7.0,
        backoff_factor=1.0,
        disconnect_code=IDLE_CODE,
        place_id=PLACE_ID,
    )
    assert plan.delay_seconds == 7.0


# Refusals -------------------------------------------------------------------


def test_the_attempt_ceiling_stops_the_loop() -> None:
    plan = plan_rejoin(
        attempt=5, max_attempts=5, disconnect_code=IDLE_CODE, place_id=PLACE_ID
    )
    assert plan.should_rejoin is False
    assert "maximum of 5" in plan.explanation


def test_disabled_rules_never_rejoin() -> None:
    plan = plan_rejoin(
        enabled=False, disconnect_code=IDLE_CODE, place_id=PLACE_ID
    )
    assert plan.should_rejoin is False
    assert plan.explanation == "Automatic rejoin is disabled."


def test_non_retryable_codes_never_rejoin() -> None:
    plan = plan_rejoin(disconnect_code=267, place_id=PLACE_ID)
    assert plan.should_rejoin is False
    assert "not retried automatically" in plan.explanation


def test_an_unknown_place_blocks_the_restore() -> None:
    plan = plan_rejoin(disconnect_code=IDLE_CODE, place_id=None)
    assert plan.should_rejoin is False
    assert "previous place is unknown" in plan.explanation


def test_the_place_requirement_can_be_waived() -> None:
    plan = plan_rejoin(disconnect_code=IDLE_CODE, place_id=None, require_place=False)
    assert plan.should_rejoin is True
    assert plan.place_id is None


# Server selection -----------------------------------------------------------


def test_the_same_server_is_kept_below_the_threshold() -> None:
    plan = plan_rejoin(
        attempt=0,
        change_server_after=2,
        disconnect_code=IDLE_CODE,
        place_id=PLACE_ID,
        job_id="JOB-1",
    )
    assert plan.change_server is False
    assert plan.job_id == "JOB-1"
    assert "the same server" in plan.explanation


def test_the_server_changes_above_the_threshold() -> None:
    plan = plan_rejoin(
        attempt=2,
        change_server_after=2,
        disconnect_code=IDLE_CODE,
        place_id=PLACE_ID,
        job_id="JOB-1",
    )
    assert plan.change_server is True
    assert plan.job_id is None
    assert "a new server" in plan.explanation


def test_a_zero_threshold_always_changes_server() -> None:
    plan = plan_rejoin(
        attempt=0,
        change_server_after=0,
        disconnect_code=IDLE_CODE,
        place_id=PLACE_ID,
        job_id="JOB-1",
    )
    assert plan.change_server is True
    assert plan.job_id is None


def test_a_failed_server_is_abandoned_immediately() -> None:
    plan = plan_rejoin(
        attempt=0,
        change_server_after=5,
        disconnect_code=NETWORK_CODE,
        place_id=PLACE_ID,
        job_id="JOB-1",
    )
    assert plan.change_server is True
    assert plan.job_id is None


def test_a_blank_server_identifier_is_treated_as_absent() -> None:
    plan = plan_rejoin(
        attempt=0, change_server_after=2, disconnect_code=IDLE_CODE, place_id=PLACE_ID, job_id="   "
    )
    assert plan.job_id is None
    assert plan.change_server is False


# Validation -----------------------------------------------------------------


def test_a_negative_attempt_is_rejected() -> None:
    with pytest.raises(ValidationError):
        plan_rejoin(attempt=-1, place_id=PLACE_ID)


def test_attempts_above_the_ceiling_are_rejected() -> None:
    with pytest.raises(ValidationError):
        plan_rejoin(max_attempts=MAX_REJOIN_ATTEMPTS + 1, place_id=PLACE_ID)


def test_a_zero_delay_is_rejected() -> None:
    with pytest.raises(ValidationError):
        plan_rejoin(base_delay_seconds=0, place_id=PLACE_ID)


def test_an_absurd_delay_is_rejected() -> None:
    with pytest.raises(ValidationError):
        plan_rejoin(base_delay_seconds=4_000, place_id=PLACE_ID)


def test_a_shrinking_backoff_is_rejected() -> None:
    with pytest.raises(ValidationError):
        plan_rejoin(backoff_factor=0.5, place_id=PLACE_ID)


def test_an_explosive_backoff_is_rejected() -> None:
    with pytest.raises(ValidationError):
        plan_rejoin(backoff_factor=11, place_id=PLACE_ID)


def test_an_invalid_place_is_rejected() -> None:
    with pytest.raises(ValidationError):
        plan_rejoin(place_id=0)


def test_a_boolean_place_is_rejected() -> None:
    with pytest.raises(ValidationError):
        plan_rejoin(place_id=True)


def test_an_oversized_server_identifier_is_rejected() -> None:
    with pytest.raises(ValidationError):
        plan_rejoin(place_id=PLACE_ID, job_id="x" * (MAX_JOB_ID_CHARS + 1))


def test_validation_runs_even_when_rejoin_is_disabled() -> None:
    with pytest.raises(ValidationError):
        plan_rejoin(enabled=False, base_delay_seconds=0, place_id=PLACE_ID)


# Serialisation --------------------------------------------------------------


def test_a_plan_serialises_for_the_bridge() -> None:
    payload = plan_rejoin(
        attempt=1, disconnect_code=NETWORK_CODE, place_id=PLACE_ID, job_id="JOB-1"
    ).to_dict()
    assert set(payload) == {
        "should_rejoin",
        "attempt",
        "delay_seconds",
        "place_id",
        "job_id",
        "change_server",
        "reason",
        "explanation",
    }
    assert payload["reason"]["code"] == NETWORK_CODE
    assert payload["place_id"] == PLACE_ID
