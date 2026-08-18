"""Account health, tags and custom fields."""

from __future__ import annotations

import pytest

from app.backend.core.account_health import (
    HEALTH_AUTH_EXPIRED,
    HEALTH_AUTH_EXPIRING,
    HEALTH_AUTH_REQUIRED,
    HEALTH_LAUNCH_FAILED,
    HEALTH_NEVER_LAUNCHED,
    HEALTH_OK,
    HEALTH_RUNNING,
    MAX_TAGS,
    collect_tags,
    evaluate_account_health,
    matches_filters,
    normalize_tags,
    validated_custom_fields,
)
from app.backend.core.errors import ValidationError

NOW = 1_800_000_000.0


def test_a_running_account_reads_as_in_game() -> None:
    health = evaluate_account_health({"has_password": True}, now=NOW, running=True)
    assert health["status"] == HEALTH_RUNNING
    assert health["needs_attention"] is False


def test_an_expired_sign_in_is_reported() -> None:
    health = evaluate_account_health({"oauth_expires_at": NOW - 10, "has_password": True}, now=NOW)
    assert health["status"] == HEALTH_AUTH_EXPIRED
    assert health["needs_attention"] is True


def test_a_sign_in_expiring_within_three_days_is_a_warning_not_an_error() -> None:
    health = evaluate_account_health({"oauth_expires_at": NOW + 3600, "has_password": True}, now=NOW)
    assert health["status"] == HEALTH_AUTH_EXPIRING
    assert health["needs_attention"] is False


def test_an_account_without_any_saved_sign_in_asks_for_one() -> None:
    health = evaluate_account_health({"has_password": False, "has_cookie": False}, now=NOW)
    assert health["status"] == HEALTH_AUTH_REQUIRED
    assert health["needs_attention"] is True


def test_a_failed_launch_is_surfaced_with_its_reason() -> None:
    account = {"has_password": True, "metadata": {"last_launch_error": "Roblox did not start"}}
    health = evaluate_account_health(account, now=NOW)
    assert health["status"] == HEALTH_LAUNCH_FAILED
    assert "Roblox did not start" in health["detail"]


def test_a_never_launched_account_is_not_an_error() -> None:
    health = evaluate_account_health({"has_password": True, "metadata": {}}, now=NOW)
    assert health["status"] == HEALTH_NEVER_LAUNCHED
    assert health["needs_attention"] is False


def test_a_healthy_account_reads_as_ready() -> None:
    account = {"has_password": True, "metadata": {"last_launch_at": NOW - 100}}
    assert evaluate_account_health(account, now=NOW)["status"] == HEALTH_OK


def test_no_health_status_can_contain_a_credential_word() -> None:
    # Status codes travel into flattened settings keys, and the repository
    # refuses any key that looks like a credential.
    banned = ("session", "token", "cookie", "password", "secret", "credential")
    for status in (
        HEALTH_OK,
        HEALTH_RUNNING,
        HEALTH_AUTH_EXPIRED,
        HEALTH_AUTH_EXPIRING,
        HEALTH_AUTH_REQUIRED,
        HEALTH_LAUNCH_FAILED,
        HEALTH_NEVER_LAUNCHED,
    ):
        assert not any(word in status.lower() for word in banned)


def test_tags_are_deduplicated_case_insensitively_and_keep_their_typed_case() -> None:
    assert normalize_tags(["Trade", "trade", " Main "]) == ["Trade", "Main"]
    assert normalize_tags("Farm, Storage") == ["Farm", "Storage"]
    assert normalize_tags(None) == []


def test_too_many_tags_are_refused() -> None:
    with pytest.raises(ValidationError):
        normalize_tags([f"tag{index}" for index in range(MAX_TAGS + 1)])


def test_custom_fields_cannot_smuggle_a_credential() -> None:
    for name in ("password", "Roblosecurity", "api_key", "my token", "session"):
        with pytest.raises(ValidationError):
            validated_custom_fields({name: "x"})


def test_custom_fields_accept_the_ordinary_ones() -> None:
    fields = validated_custom_fields({"Level": 42, "Gems": "1200", "Trait": "Vanguard"})
    assert fields == {"Level": "42", "Gems": "1200", "Trait": "Vanguard"}


def test_tags_in_use_are_counted_most_used_first() -> None:
    accounts = [
        {"metadata": {"tags": ["Farm", "Main"]}},
        {"metadata": {"tags": ["farm"]}},
        {"metadata": {}},
    ]
    rows = collect_tags(accounts)
    assert rows[0]["count"] == 2
    assert rows[0]["tag"].casefold() == "farm"


def test_a_tag_filter_narrows_instead_of_widening() -> None:
    account = {"username": "Alt1", "metadata": {"tags": ["Farm"]}}
    assert matches_filters(account, tags=["Farm"]) is True
    assert matches_filters(account, tags=["Farm", "Trade"]) is False


def test_the_attention_filter_catches_every_actionable_state() -> None:
    needs = {"username": "A", "health": {"status": HEALTH_AUTH_REQUIRED, "needs_attention": True}}
    fine = {"username": "B", "health": {"status": HEALTH_OK, "needs_attention": False}}
    assert matches_filters(needs, status="attention") is True
    assert matches_filters(fine, status="attention") is False
    assert matches_filters(fine, status=HEALTH_OK) is True


def test_the_text_filter_looks_at_the_fields_a_person_would_search() -> None:
    account = {"username": "Alt1", "display_name": "Vanguard", "note": "needs quest", "group_name": "Farm"}
    assert matches_filters(account, query="vanguard") is True
    assert matches_filters(account, query="quest") is True
    assert matches_filters(account, query="nothing") is False
