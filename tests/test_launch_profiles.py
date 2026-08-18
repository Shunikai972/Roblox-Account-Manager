"""Launch profiles: a saved destination must stay bounded and unambiguous.

These tests pin the rules that matter to an operator: a profile always knows
which place it targets, it never claims two different servers at once, and a
profile written by an older build never blocks the screen.
"""

from __future__ import annotations

import pytest

from app.backend.automations.launch_profiles import (
    MAX_PROFILES,
    describe_profile,
    normalize_profiles,
    profile_target,
    upsert_profile,
    validated_profile,
)
from app.backend.core.errors import ValidationError
from app.backend.services import ApplicationService

JOB_ID = "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d"


def test_a_profile_needs_a_name_and_a_numeric_place_id() -> None:
    with pytest.raises(ValidationError):
        validated_profile({"place_id": "920587237"})
    with pytest.raises(ValidationError):
        validated_profile({"name": "Farm", "place_id": "not a place"})
    with pytest.raises(ValidationError):
        validated_profile({"name": "Farm"})

    profile = validated_profile({"name": "  Evening farm ", "place_id": " 920587237 "})
    assert profile["name"] == "Evening farm"
    assert profile["place_id"] == 920587237
    assert profile["id"]
    assert profile["job_id"] == ""
    assert profile["fps"] == 0


def test_a_profile_refuses_to_claim_two_different_servers() -> None:
    with pytest.raises(ValidationError) as error:
        validated_profile(
            {"name": "Farm", "place_id": "1", "job_id": JOB_ID, "link_code": "abc123def"}
        )
    assert "not both" in str(error.value)


def test_an_fps_target_is_optional_but_bounded() -> None:
    assert validated_profile({"name": "a", "place_id": "1", "fps": ""})["fps"] == 0
    assert validated_profile({"name": "a", "place_id": "1", "fps": 240})["fps"] == 240
    with pytest.raises(ValidationError):
        validated_profile({"name": "a", "place_id": "1", "fps": 3})
    with pytest.raises(ValidationError):
        validated_profile({"name": "a", "place_id": "1", "fps": 99_999})


def test_unreadable_profiles_are_skipped_instead_of_breaking_the_screen() -> None:
    rows = normalize_profiles(
        [
            {"id": "keep", "name": "Zulu", "place_id": "2"},
            {"id": "broken", "name": "", "place_id": "3"},
            "not even an object",
            {"id": "keep", "name": "duplicate id", "place_id": "4"},
            {"id": "other", "name": "alpha", "place_id": "5"},
        ]
    )
    assert [row["name"] for row in rows] == ["alpha", "Zulu"]
    assert normalize_profiles("nonsense") == []


def test_saving_the_same_profile_twice_replaces_it_and_the_list_stays_bounded() -> None:
    first = validated_profile({"name": "Farm", "place_id": "1"})
    renamed = dict(first)
    renamed["name"] = "Farm night"
    rows = upsert_profile(upsert_profile([], first), renamed)
    assert [row["name"] for row in rows] == ["Farm night"]

    full = [validated_profile({"name": f"p{index}", "place_id": "1"}) for index in range(MAX_PROFILES)]
    with pytest.raises(ValidationError):
        upsert_profile(full, validated_profile({"name": "one too many", "place_id": "1"}))


def test_a_profile_describes_exactly_one_destination() -> None:
    public = validated_profile({"name": "Public", "place_id": "7"})
    assert profile_target(public) == {"place_id": 7}
    assert "any public server" in describe_profile(public)

    same_server = validated_profile({"name": "Together", "place_id": "7", "job_id": JOB_ID})
    assert profile_target(same_server) == {"place_id": 7, "job_id": JOB_ID}
    assert "same server" in describe_profile(same_server)

    private = validated_profile({"name": "VIP", "place_id": "7", "link_code": "abc123def", "fps": 120})
    assert profile_target(private) == {"place_id": 7, "private_server_link_code": "abc123def"}
    assert "private server" in describe_profile(private)
    assert "120 FPS" in describe_profile(private)


def test_the_dashboard_word_for_an_account_is_honest() -> None:
    """A client nobody automates is reported as unattended, not as farming."""

    state = ApplicationService._dashboard_state
    assert state(None, None) == "offline"
    assert state({"state": "crashed"}, None) == "error"
    assert state({"place_id": 1, "runtime_seconds": 60}, None) == "in_game"
    assert state({"place_id": 1, "runtime_seconds": 60}, None, idle_after_seconds=900) == "in_game"
    assert state({"place_id": 1, "runtime_seconds": 1200}, None, idle_after_seconds=900) == "afk"
    assert state({"place_id": 1, "runtime_seconds": 1200}, {"state": "running"}, idle_after_seconds=900) == "farming"
    assert state({"place_id": 1}, {"state": "running", "paused": True}) == "macro_paused"
    assert state({"place_id": None}, None) == "launching"
