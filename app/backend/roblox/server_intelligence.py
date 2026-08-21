"""Explainable quality scoring and filtering for public Roblox servers."""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

from app.backend.core.errors import ValidationError

SORT_MODES = {"score", "lowest_players", "lowest_ping", "most_players"}
MAX_FILTER_JOB_IDS = 200


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def score_server(
    server: Mapping[str, Any],
    *,
    history: Mapping[str, Any] | None = None,
    blacklisted: bool = False,
) -> dict[str, Any]:
    players = max(0, int(server.get("players", server.get("playing", 0)) or 0))
    capacity = max(0, int(server.get("capacity", server.get("max_players", 0)) or 0))
    free_slots = max(0, capacity - players) if capacity else 0
    ping = _finite(server.get("ping"))
    fps = _finite(server.get("fps"))
    previous = dict(history or {})
    failures = max(0, int(previous.get("failures") or 0))
    joins = max(0, int(previous.get("joins") or 0))

    ping_score = 55.0 if ping is None else _clamp(110.0 - ping * 0.45)
    slot_score = 50.0 if capacity <= 0 else _clamp(100.0 * free_slots / capacity)
    fps_score = 50.0 if fps is None else _clamp(100.0 * fps / 60.0)
    stability_score = 75.0 if joins + failures == 0 else _clamp(100.0 * joins / (joins + failures))
    failure_score = _clamp(100.0 - failures * 25.0)
    eligible = not blacklisted and (capacity <= 0 or free_slots > 0)
    total = (
        ping_score * 0.30
        + slot_score * 0.30
        + fps_score * 0.15
        + stability_score * 0.15
        + failure_score * 0.10
    )
    if not eligible:
        total = 0.0
    return {
        "score": round(total),
        "eligible": eligible,
        "free_slots": free_slots,
        "previously_visited": joins + failures > 0,
        "failures": failures,
        "score_breakdown": {
            "ping": round(ping_score),
            "free_slots": round(slot_score),
            "fps": round(fps_score),
            "stability": round(stability_score),
            "previous_failures": round(failure_score),
        },
    }


def rank_servers(
    servers: Iterable[Mapping[str, Any]],
    *,
    history: Iterable[Mapping[str, Any]] = (),
    blacklist: Iterable[Any] = (),
    options: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    filters = dict(options or {})
    mode = str(filters.get("sort") or "score").strip().lower()
    if mode not in SORT_MODES:
        raise ValidationError("That server sort mode is not supported.")
    try:
        minimum_slots = int(filters.get("min_free_slots") or 0)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Minimum free slots must be a whole number.") from exc
    if not 0 <= minimum_slots <= 100:
        raise ValidationError("Minimum free slots must be between 0 and 100.")
    history_by_job = {str(row.get("job_id") or ""): dict(row) for row in history if isinstance(row, Mapping)}
    blocked = {
        str(row.get("job_id") if isinstance(row, Mapping) else row or "")
        for row in blacklist
    }
    avoid = {
        str(value or "")
        for value in list(filters.get("avoid_job_ids") or [])[:MAX_FILTER_JOB_IDS]
    }
    avoid_previous = bool(filters.get("avoid_previous", False))
    rows: list[dict[str, Any]] = []
    for item in servers:
        row = dict(item)
        job_id = str(row.get("job_id") or row.get("id") or "")
        quality = score_server(row, history=history_by_job.get(job_id), blacklisted=job_id in blocked)
        row.update(quality)
        if job_id in avoid or quality["free_slots"] < minimum_slots:
            continue
        if avoid_previous and quality["previously_visited"]:
            continue
        rows.append(row)
    if mode == "lowest_players":
        key = lambda row: (int(row.get("players") or 0), -int(row["score"]))
    elif mode == "most_players":
        key = lambda row: (-int(row.get("players") or 0), -int(row["score"]))
    elif mode == "lowest_ping":
        key = lambda row: (_finite(row.get("ping")) is None, _finite(row.get("ping")) or 0.0, -int(row["score"]))
    else:
        key = lambda row: (not bool(row["eligible"]), -int(row["score"]), int(row.get("players") or 0))
    rows.sort(key=key)
    return rows
