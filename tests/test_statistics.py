"""Statistics: heatmap, reliability, macro success, session comparison."""

from __future__ import annotations

from datetime import datetime

from app.backend.watchers.statistics import (
    build_heatmap,
    build_statistics,
    compare_sessions,
    macro_success_rate,
    reliability_table,
)


def _at(year: int, month: int, day: int, hour: int, minute: int = 0) -> float:
    return datetime(year, month, day, hour, minute).timestamp()


def test_a_long_session_spreads_across_every_hour_it_occupied() -> None:
    # A three hour farm must light three cells, not one.
    start = _at(2026, 8, 10, 20, 0)
    sessions = [{"account_id": "a", "started_at": start, "ended_at": start + 3 * 3600}]
    heatmap = build_heatmap(sessions, now=start + 4 * 3600, window_days=7)
    monday = heatmap["rows"][0]
    assert monday["day"] == "Mon"
    assert monday["hours"][20] == 60.0
    assert monday["hours"][21] == 60.0
    assert monday["hours"][22] == 60.0
    assert heatmap["total_minutes"] == 180.0
    assert heatmap["peak"]["hour"] in {20, 21, 22}


def test_sessions_older_than_the_window_are_ignored() -> None:
    now = _at(2026, 8, 14, 12)
    old = {"account_id": "a", "started_at": now - 40 * 86_400, "ended_at": now - 40 * 86_400 + 3600}
    heatmap = build_heatmap([old], now=now, window_days=7)
    assert heatmap["total_minutes"] == 0.0


def test_a_running_session_is_measured_up_to_now() -> None:
    now = _at(2026, 8, 14, 12)
    heatmap = build_heatmap([{"account_id": "a", "started_at": now - 1800, "ended_at": None}], now=now)
    assert heatmap["total_minutes"] == 30.0


def test_crashes_and_short_sessions_lower_the_reliability_score() -> None:
    now = _at(2026, 8, 14, 12)
    steady = [
        {"account_id": "steady", "username": "Steady", "started_at": now - 7200 - index * 86_400, "ended_at": now - 3600 - index * 86_400}
        for index in range(4)
    ]
    flaky = [
        {"account_id": "flaky", "username": "Flaky", "started_at": now - 60 - index * 86_400, "ended_at": now - index * 86_400, "crashed": True}
        for index in range(4)
    ]
    table = {row["account_id"]: row for row in reliability_table(steady + flaky, now=now)}
    assert table["steady"]["score"] > table["flaky"]["score"]
    assert table["flaky"]["crashes"] == 4
    assert table["flaky"]["short_sessions"] == 4


def test_a_score_built_on_too_few_sessions_says_so() -> None:
    now = _at(2026, 8, 14, 12)
    rows = reliability_table([{"account_id": "a", "started_at": now - 3600, "ended_at": now}], now=now)
    assert rows[0]["confidence"] == "low"


def test_a_macro_stopped_by_the_operator_is_not_counted_as_a_failure() -> None:
    summary = macro_success_rate(
        [
            {"name": "Walk", "started_at": 10.0, "finished_at": 20.0},
            {"name": "Walk", "started_at": 10.0, "finished_at": 20.0, "stopped_by": "operator"},
            {"name": "Walk", "started_at": 10.0, "finished_at": 15.0, "error": "window lost"},
            {"name": "Walk", "started_at": 10.0, "finished_at": None},
        ]
    )
    assert summary["completed"] == 1
    assert summary["failed"] == 1
    assert summary["stopped"] == 1
    assert summary["running"] == 1
    assert summary["success_rate"] == 50.0


def test_macro_success_rate_is_unknown_when_nothing_finished() -> None:
    assert macro_success_rate([{"name": "Walk", "finished_at": None}])["success_rate"] is None


def test_two_sessions_are_compared_oldest_first() -> None:
    now = _at(2026, 8, 14, 12)
    later = {"account_id": "a", "started_at": now - 3600, "ended_at": now}
    earlier = {"account_id": "a", "started_at": now - 90_000, "ended_at": now - 88_200}
    result = compare_sessions(later, earlier, now=now)
    assert result["comparable"] is True
    assert result["earlier"]["seconds"] == 1800.0
    assert result["later"]["seconds"] == 3600.0
    assert result["delta_seconds"] == 1800.0
    assert result["delta_percent"] == 100.0
    assert result["verdict"] == "longer"


def test_comparing_needs_two_real_sessions() -> None:
    assert compare_sessions({"started_at": 0}, None, now=100.0)["comparable"] is False


def test_the_dashboard_payload_carries_every_section() -> None:
    now = _at(2026, 8, 14, 12)
    payload = build_statistics(
        sessions=[{"account_id": "a", "username": "A", "started_at": now - 3600, "ended_at": now}],
        runs=[{"name": "Walk", "started_at": 1.0, "finished_at": 2.0}],
        now=now,
    )
    assert payload["totals"]["sessions"] == 1
    assert payload["totals"]["hours"] == 1.0
    assert payload["totals"]["crash_rate"] == 0.0
    assert payload["heatmap"]["rows"]
    assert payload["reliability"][0]["username"] == "A"
    assert payload["macros"]["success_rate"] == 100.0
    assert payload["recent"][0]["account_id"] == "a"


def test_malformed_records_are_skipped_instead_of_raising() -> None:
    payload = build_statistics(sessions=[None, {"started_at": "nope"}, 42], runs=[None], now=1.0)
    assert payload["totals"]["sessions"] == 0
    assert payload["macros"]["total"] == 0
