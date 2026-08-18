"""Server registry: history, blacklist, region affinity, smart hopping."""

from __future__ import annotations

import pytest

from app.backend.core.errors import ValidationError
from app.backend.roblox.server_registry import (
    FAILURE_BLACKLIST_THRESHOLD,
    MAX_HISTORY,
    blacklist_add,
    blacklist_remove,
    inspect_history,
    normalize_job_id,
    pick_server,
    record_visit,
)

NOW = 1_800_000_000.0
JOB_A = "aaaaaaaa-1111-2222-3333-444444444444"
JOB_B = "bbbbbbbb-1111-2222-3333-444444444444"
JOB_C = "cccccccc-1111-2222-3333-444444444444"


def test_a_malformed_job_id_is_refused() -> None:
    for bad in ("", "nope!", "x" * 100, None):
        with pytest.raises(ValidationError):
            normalize_job_id(bad)


def test_a_first_visit_is_recorded_with_its_timestamps() -> None:
    history = record_visit([], job_id=JOB_A, place_id="606849621", region="Paris", players=12, max_players=30, now=NOW)
    assert len(history) == 1
    row = history[0].to_dict(now=NOW)
    assert row["job_id"] == JOB_A
    assert row["place_id"] == "606849621"
    assert row["joins"] == 1
    assert row["failures"] == 0
    assert row["fill_percent"] == 40.0


def test_visiting_again_updates_the_same_row_and_keeps_the_first_seen() -> None:
    history = record_visit([], job_id=JOB_A, place_id="1", now=NOW)
    history = record_visit(history, job_id=JOB_A, place_id="1", now=NOW + 600)
    assert len(history) == 1
    row = history[0]
    assert row.first_seen == NOW
    assert row.last_seen == NOW + 600
    assert row.joins == 2


def test_a_failed_join_counts_as_a_failure_not_a_join() -> None:
    history = record_visit([], job_id=JOB_A, now=NOW, failed=True)
    assert history[0].failures == 1
    assert history[0].joins == 0


def test_the_history_is_bounded() -> None:
    history: list = []
    for index in range(MAX_HISTORY + 10):
        history = record_visit(history, job_id=f"{index:08x}-1111-2222-3333-444444444444", now=NOW + index)
    assert len(history) == MAX_HISTORY


def test_a_blacklisted_server_is_never_picked() -> None:
    history = record_visit([], job_id=JOB_A, place_id="1", players=1, max_players=30, now=NOW - 10_000)
    banned = blacklist_add([], job_id=JOB_A, note="laggy", now=NOW)
    result = pick_server(history, place_id="1", blacklist=banned, now=NOW)
    assert result["found"] is False
    assert result["rejected"] == 1


def test_removing_a_server_from_the_blacklist_makes_it_available_again() -> None:
    history = record_visit([], job_id=JOB_A, place_id="1", players=1, max_players=30, now=NOW - 10_000)
    banned = blacklist_add([], job_id=JOB_A, now=NOW)
    freed = blacklist_remove(banned, job_id=JOB_A)
    assert freed == []
    assert pick_server(history, place_id="1", blacklist=freed, now=NOW)["found"] is True


def test_a_server_that_failed_repeatedly_is_dropped_without_a_blacklist() -> None:
    history: list = []
    for _ in range(FAILURE_BLACKLIST_THRESHOLD):
        history = record_visit(history, job_id=JOB_A, place_id="1", now=NOW, failed=True)
    assert pick_server(history, place_id="1", now=NOW)["found"] is False


def test_a_full_server_is_not_offered() -> None:
    history = record_visit([], job_id=JOB_A, place_id="1", players=30, max_players=30, now=NOW - 10_000)
    assert pick_server(history, place_id="1", now=NOW)["found"] is False


def test_the_preferred_region_wins_over_a_slightly_emptier_server() -> None:
    history = record_visit([], job_id=JOB_A, place_id="1", region="Frankfurt", players=1, max_players=30, now=NOW - 10_000)
    history = record_visit(history, job_id=JOB_B, place_id="1", region="Paris", players=10, max_players=30, now=NOW - 10_000)
    result = pick_server(history, place_id="1", prefer_region="Paris", now=NOW)
    assert result["job_id"] == JOB_B
    assert result["region"] == "Paris"


def test_a_recently_visited_server_is_skipped_while_another_is_free() -> None:
    history = record_visit([], job_id=JOB_A, place_id="1", players=1, max_players=30, now=NOW - 60)
    history = record_visit(history, job_id=JOB_B, place_id="1", players=5, max_players=30, now=NOW - 10_000)
    result = pick_server(history, place_id="1", avoid_recent_seconds=900, now=NOW)
    assert result["job_id"] == JOB_B


def test_when_everything_was_visited_recently_the_pick_says_so() -> None:
    history = record_visit([], job_id=JOB_A, place_id="1", players=1, max_players=30, now=NOW - 30)
    result = pick_server(history, place_id="1", avoid_recent_seconds=900, now=NOW)
    assert result["found"] is True
    assert "visited recently" in result["reason"]


def test_an_explicitly_avoided_server_is_excluded() -> None:
    history = record_visit([], job_id=JOB_A, place_id="1", players=1, max_players=30, now=NOW - 10_000)
    history = record_visit(history, job_id=JOB_C, place_id="1", players=2, max_players=30, now=NOW - 10_000)
    result = pick_server(history, place_id="1", avoid_job_ids=[JOB_A], now=NOW)
    assert result["job_id"] == JOB_C


def test_an_empty_history_explains_itself_instead_of_failing() -> None:
    result = pick_server([], place_id="1", now=NOW)
    assert result["found"] is False
    assert "remembered" in result["reason"]


def test_the_inspector_marks_blacklisted_rows_and_counts_regions() -> None:
    history = record_visit([], job_id=JOB_A, place_id="1", region="Paris", now=NOW)
    history = record_visit(history, job_id=JOB_B, place_id="1", region="Paris", now=NOW)
    banned = blacklist_add([], job_id=JOB_A, now=NOW)
    payload = inspect_history(history, blacklist=banned, now=NOW)
    assert payload["total"] == 2
    assert payload["blacklisted"] == 1
    assert payload["regions"][0] == {"region": "Paris", "servers": 2}
    assert any(row["blacklisted"] for row in payload["servers"])
