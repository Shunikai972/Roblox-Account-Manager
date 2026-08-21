from __future__ import annotations

import pytest

from app.backend.core.errors import ValidationError
from app.backend.roblox.server_intelligence import rank_servers, score_server


def test_server_quality_score_explains_every_component() -> None:
    quality = score_server(
        {"players": 4, "capacity": 20, "ping": 31, "fps": 58},
        history={"joins": 8, "failures": 1},
    )
    assert quality["eligible"] is True
    assert quality["free_slots"] == 16
    assert 80 <= quality["score"] <= 100
    assert set(quality["score_breakdown"]) == {
        "ping", "free_slots", "fps", "stability", "previous_failures"
    }


def test_server_ranking_filters_previous_full_and_low_capacity_servers() -> None:
    servers = [
        {"job_id": "a", "players": 2, "capacity": 20, "ping": 80},
        {"job_id": "b", "players": 18, "capacity": 20, "ping": 20},
        {"job_id": "c", "players": 20, "capacity": 20, "ping": 10},
    ]
    ranked = rank_servers(
        servers,
        history=[{"job_id": "a", "joins": 1, "failures": 0}],
        options={"min_free_slots": 2, "avoid_previous": True, "sort": "lowest_ping"},
    )
    assert [row["job_id"] for row in ranked] == ["b"]
    with pytest.raises(ValidationError):
        rank_servers(servers, options={"sort": "magic"})


def test_blacklisted_server_stays_visible_but_is_never_ranked_as_eligible() -> None:
    rows = rank_servers(
        [{"job_id": "blocked", "players": 1, "capacity": 20, "ping": 1}],
        blacklist=[{"job_id": "blocked"}],
    )
    assert rows[0]["eligible"] is False
    assert rows[0]["score"] == 0
