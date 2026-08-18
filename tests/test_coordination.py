"""Coordination: spread, main + followers, synchronized actions, party."""

from __future__ import annotations

import pytest

from app.backend.automations.coordination import (
    MAX_COORDINATED_ACCOUNTS,
    MAX_PARTY_SIZE,
    follower_plan,
    party_plan,
    spread_plan,
    sync_plan,
)
from app.backend.core.errors import ValidationError

ACCOUNTS = [
    {"id": "a1", "username": "Alt1"},
    {"id": "a2", "username": "Alt2"},
    {"id": "a3", "username": "Alt3"},
]
SERVERS = [{"job_id": "job-a"}, {"job_id": "job-b"}, {"job_id": "job-c"}]


def test_spread_gives_each_account_its_own_server() -> None:
    plan = spread_plan(ACCOUNTS, servers=SERVERS, max_per_server=1, place_id="606849621")
    assert [step["job_id"] for step in plan["steps"]] == ["job-a", "job-b", "job-c"]
    assert plan["unassigned"] == []
    assert plan["steps"][0]["place_id"] == "606849621"


def test_spread_leaves_the_remainder_unassigned_instead_of_piling_it_up() -> None:
    plan = spread_plan(ACCOUNTS, servers=[{"job_id": "job-a"}], max_per_server=1)
    assert len(plan["steps"]) == 1
    assert [row["id"] for row in plan["unassigned"]] == ["a2", "a3"]


def test_spread_can_pack_several_accounts_per_server() -> None:
    plan = spread_plan(ACCOUNTS, servers=[{"job_id": "job-a"}, {"job_id": "job-b"}], max_per_server=2)
    assert [step["job_id"] for step in plan["steps"]] == ["job-a", "job-a", "job-b"]
    assert plan["unassigned"] == []


def test_spread_without_servers_only_staggers_and_says_so() -> None:
    plan = spread_plan(ACCOUNTS, stagger_seconds=2)
    assert all(step["job_id"] == "" for step in plan["steps"])
    assert plan["estimated_seconds"] == 4.0
    assert "staggered in time" in plan["note"]


def test_spread_refuses_an_empty_selection_and_duplicates_are_collapsed() -> None:
    with pytest.raises(ValidationError):
        spread_plan([])
    plan = spread_plan([{"id": "a1"}, {"id": "a1"}])
    assert len(plan["steps"]) == 1


def test_coordination_is_bounded() -> None:
    with pytest.raises(ValidationError):
        spread_plan([{"id": f"a{index}"} for index in range(MAX_COORDINATED_ACCOUNTS + 1)])


def test_followers_go_after_the_main_account() -> None:
    plan = follower_plan(main=ACCOUNTS[0], followers=ACCOUNTS[1:], job_id="job-a", stagger_seconds=1)
    assert plan["steps"][0]["role"] == "main"
    assert plan["steps"][0]["offset_seconds"] == 0.0
    assert [step["role"] for step in plan["steps"][1:]] == ["follower", "follower"]
    assert all(step["job_id"] == "job-a" for step in plan["steps"])
    assert plan["ready"] is True


def test_the_main_account_cannot_also_be_a_follower() -> None:
    plan = follower_plan(main=ACCOUNTS[0], followers=ACCOUNTS, job_id="job-a")
    assert len(plan["steps"]) == 3
    assert [step["account_id"] for step in plan["steps"]] == ["a1", "a2", "a3"]


def test_following_without_a_known_server_is_not_ready_and_explains_why() -> None:
    plan = follower_plan(main=ACCOUNTS[0], followers=ACCOUNTS[1:])
    assert plan["ready"] is False
    assert "launch the main account first" in plan["note"].lower()


def test_following_needs_a_main_and_at_least_one_follower() -> None:
    with pytest.raises(ValidationError):
        follower_plan(main=ACCOUNTS[0], followers=[])
    with pytest.raises(ValidationError):
        follower_plan(main={}, followers=ACCOUNTS)


def test_a_synchronized_action_shares_one_start_instant() -> None:
    plan = sync_plan(ACCOUNTS, action="teleport", job_id="job-a", now=1000.0, countdown_seconds=3)
    assert plan["action"] == "teleport"
    assert plan["starts_at"] == 1003.0
    assert plan["spread_seconds"] == 0.0
    assert "same instant" in plan["note"]


def test_a_synchronized_action_needs_two_accounts_and_a_known_verb() -> None:
    with pytest.raises(ValidationError):
        sync_plan(ACCOUNTS[:1])
    with pytest.raises(ValidationError):
        sync_plan(ACCOUNTS, action="explode")


def test_a_party_is_capped_and_the_overflow_is_reported() -> None:
    many = [{"id": f"a{index}", "username": f"Alt{index}"} for index in range(MAX_PARTY_SIZE + 3)]
    plan = party_plan(many, job_id="job-a")
    assert plan["size"] == MAX_PARTY_SIZE
    assert len(plan["overflow"]) == 3
    assert plan["steps"][0]["role"] == "main"


def test_the_party_note_states_the_real_roblox_limit() -> None:
    plan = party_plan(ACCOUNTS, job_id="job-a")
    assert "cannot send a Roblox party invite" in plan["note"]
    assert "same server" in plan["note"]


def test_a_party_needs_two_accounts() -> None:
    with pytest.raises(ValidationError):
        party_plan(ACCOUNTS[:1])


def test_an_out_of_range_stagger_is_refused() -> None:
    with pytest.raises(ValidationError):
        spread_plan(ACCOUNTS, stagger_seconds=999)
    with pytest.raises(ValidationError):
        spread_plan(ACCOUNTS, stagger_seconds=-1)
