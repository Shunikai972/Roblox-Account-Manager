"""Farming statistics: heatmap, reliability, macro success, session compare.

Every function here is pure.  It reads session and macro-run records that the
service already keeps and returns plain dictionaries, so the whole surface can
be tested without Roblox, without a database, and without a clock.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence

MAX_SESSIONS = 5_000
MAX_RUNS = 5_000
HEATMAP_DAYS = 7
HEATMAP_HOURS = 24
DEFAULT_WINDOW_DAYS = 28
MAX_WINDOW_DAYS = 365
MIN_SESSIONS_FOR_SCORE = 3
SHORT_SESSION_SECONDS = 120.0
LONG_SESSION_SECONDS = 3_600.0

_DAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """One finished or running Roblox session."""

    account_id: str
    username: str = ""
    started_at: float = 0.0
    ended_at: float | None = None
    crashed: bool = False
    place_id: str = ""
    macro_runs: int = 0
    macro_failures: int = 0

    def duration_seconds(self, *, now: float) -> float:
        end = self.ended_at if self.ended_at is not None else now
        return max(0.0, float(end) - float(self.started_at))


@dataclass(slots=True)
class AccountReliability:
    account_id: str
    username: str = ""
    sessions: int = 0
    crashes: int = 0
    short_sessions: int = 0
    total_seconds: float = 0.0
    macro_runs: int = 0
    macro_failures: int = 0
    samples: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        score, confidence = _reliability_score(self)
        return {
            "account_id": self.account_id,
            "username": self.username,
            "sessions": self.sessions,
            "crashes": self.crashes,
            "short_sessions": self.short_sessions,
            "total_seconds": round(self.total_seconds, 1),
            "total_hours": round(self.total_seconds / 3600.0, 2),
            "average_seconds": round(self.total_seconds / self.sessions, 1) if self.sessions else 0.0,
            "longest_seconds": round(max(self.samples), 1) if self.samples else 0.0,
            "macro_runs": self.macro_runs,
            "macro_failures": self.macro_failures,
            "score": score,
            # A score built on two sessions is noise; say so instead of
            # dressing it up as a measurement.
            "confidence": confidence,
        }


def _reliability_score(row: AccountReliability) -> tuple[int, str]:
    if row.sessions <= 0:
        return 0, "none"
    crash_ratio = row.crashes / row.sessions
    short_ratio = row.short_sessions / row.sessions
    macro_ratio = (row.macro_failures / row.macro_runs) if row.macro_runs else 0.0
    average = row.total_seconds / row.sessions
    # Staying alive is the point, so uptime carries the score and each kind of
    # failure removes a bounded slice of it.
    endurance = min(1.0, average / LONG_SESSION_SECONDS)
    score = 100.0 * (0.45 * endurance + 0.55)
    score -= 45.0 * crash_ratio
    score -= 20.0 * short_ratio
    score -= 20.0 * macro_ratio
    confidence = "low" if row.sessions < MIN_SESSIONS_FOR_SCORE else "ok"
    return int(max(0.0, min(100.0, round(score)))), confidence


def _coerce_sessions(raw: Iterable[Any]) -> list[SessionRecord]:
    sessions: list[SessionRecord] = []
    for item in list(raw)[:MAX_SESSIONS]:
        if isinstance(item, SessionRecord):
            sessions.append(item)
            continue
        if not isinstance(item, Mapping):
            continue
        try:
            started = float(item.get("started_at") or 0.0)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(started) or started <= 0:
            continue
        ended_raw = item.get("ended_at")
        try:
            ended = float(ended_raw) if ended_raw is not None else None
        except (TypeError, ValueError):
            ended = None
        if ended is not None and (not math.isfinite(ended) or ended < started):
            ended = None
        sessions.append(
            SessionRecord(
                account_id=str(item.get("account_id") or "")[:128],
                username=str(item.get("username") or "")[:64],
                started_at=started,
                ended_at=ended,
                crashed=bool(item.get("crashed", False)),
                place_id=str(item.get("place_id") or "")[:32],
                macro_runs=max(0, int(item.get("macro_runs") or 0)),
                macro_failures=max(0, int(item.get("macro_failures") or 0)),
            )
        )
    return sessions


def build_heatmap(
    sessions: Iterable[Any],
    *,
    now: float,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict[str, Any]:
    """Return farmed minutes per weekday and hour over the recent window.

    A session that spans several hours is split across the hours it really
    occupied, otherwise a six hour farm would light up a single cell.
    """

    days = max(1, min(int(window_days or DEFAULT_WINDOW_DAYS), MAX_WINDOW_DAYS))
    horizon = float(now) - days * 86_400.0
    grid = [[0.0 for _ in range(HEATMAP_HOURS)] for _ in range(HEATMAP_DAYS)]
    counted = 0
    for session in _coerce_sessions(sessions):
        end = session.ended_at if session.ended_at is not None else float(now)
        start = max(float(session.started_at), horizon)
        if end <= start:
            continue
        counted += 1
        cursor = start
        # Walk hour boundaries so long sessions spread over the cells they used.
        while cursor < end:
            moment = datetime.fromtimestamp(cursor)
            boundary = (moment.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).timestamp()
            slice_end = min(end, boundary)
            grid[moment.weekday()][moment.hour] += (slice_end - cursor) / 60.0
            cursor = slice_end
    rows = [
        {
            "day": _DAY_LABELS[index],
            "weekday": index,
            "hours": [round(value, 1) for value in row],
            "total_minutes": round(sum(row), 1),
        }
        for index, row in enumerate(grid)
    ]
    peak = 0.0
    peak_cell = None
    for index, row in enumerate(grid):
        for hour, value in enumerate(row):
            if value > peak:
                peak = value
                peak_cell = {"day": _DAY_LABELS[index], "hour": hour, "minutes": round(value, 1)}
    return {
        "window_days": days,
        "rows": rows,
        "sessions": counted,
        "peak": peak_cell,
        "peak_minutes": round(peak, 1),
        "total_minutes": round(sum(sum(row) for row in grid), 1),
    }


def reliability_table(sessions: Iterable[Any], *, now: float) -> list[dict[str, Any]]:
    """Score every account that has at least one recorded session."""

    rows: dict[str, AccountReliability] = {}
    for session in _coerce_sessions(sessions):
        key = session.account_id or session.username
        if not key:
            continue
        row = rows.setdefault(key, AccountReliability(account_id=session.account_id, username=session.username))
        if session.username and not row.username:
            row.username = session.username
        seconds = session.duration_seconds(now=now)
        row.sessions += 1
        row.total_seconds += seconds
        row.samples.append(seconds)
        row.macro_runs += session.macro_runs
        row.macro_failures += session.macro_failures
        if session.crashed:
            row.crashes += 1
        if seconds < SHORT_SESSION_SECONDS:
            row.short_sessions += 1
    table = [row.to_dict() for row in rows.values()]
    table.sort(key=lambda item: (-item["score"], -item["total_seconds"], item["username"]))
    return table


def macro_success_rate(runs: Iterable[Any]) -> dict[str, Any]:
    """Summarise finished macro runs.

    A run stopped by the operator is not a failure; only an error is.
    """

    total = 0
    completed = 0
    failed = 0
    stopped = 0
    running = 0
    seconds = 0.0
    by_macro: dict[str, dict[str, Any]] = {}
    for item in list(runs)[:MAX_RUNS]:
        if not isinstance(item, Mapping):
            continue
        total += 1
        name = str(item.get("name") or item.get("macro_id") or "macro")[:64]
        bucket = by_macro.setdefault(name, {"name": name, "runs": 0, "completed": 0, "failed": 0, "stopped": 0})
        bucket["runs"] += 1
        finished = item.get("finished_at")
        if finished is None:
            running += 1
            continue
        try:
            started_at = float(item.get("started_at") or 0.0)
            seconds += max(0.0, float(finished) - started_at) if started_at else 0.0
        except (TypeError, ValueError):
            pass
        if item.get("error"):
            failed += 1
            bucket["failed"] += 1
        elif item.get("cancelled") or item.get("stopped_by"):
            stopped += 1
            bucket["stopped"] += 1
        else:
            completed += 1
            bucket["completed"] += 1
    judged = completed + failed
    rows = sorted(by_macro.values(), key=lambda row: -row["runs"])
    for row in rows:
        decided = row["completed"] + row["failed"]
        row["success_rate"] = round(100.0 * row["completed"] / decided, 1) if decided else None
    return {
        "total": total,
        "completed": completed,
        "failed": failed,
        "stopped": stopped,
        "running": running,
        "success_rate": round(100.0 * completed / judged, 1) if judged else None,
        "average_seconds": round(seconds / judged, 1) if judged else 0.0,
        "by_macro": rows[:20],
    }


def compare_sessions(first: Any, second: Any, *, now: float) -> dict[str, Any]:
    """Compare two sessions field by field, oldest first."""

    pair = _coerce_sessions([first, second])
    if len(pair) != 2:
        return {"comparable": False, "reason": "Two complete sessions are needed for a comparison."}
    left, right = sorted(pair, key=lambda item: item.started_at)
    left_seconds = left.duration_seconds(now=now)
    right_seconds = right.duration_seconds(now=now)

    def _side(record: SessionRecord, seconds: float) -> dict[str, Any]:
        return {
            "account_id": record.account_id,
            "username": record.username,
            "started_at": record.started_at,
            "ended_at": record.ended_at,
            "seconds": round(seconds, 1),
            "crashed": record.crashed,
            "macro_runs": record.macro_runs,
            "macro_failures": record.macro_failures,
        }

    delta = right_seconds - left_seconds
    return {
        "comparable": True,
        "earlier": _side(left, left_seconds),
        "later": _side(right, right_seconds),
        "delta_seconds": round(delta, 1),
        "delta_percent": round(100.0 * delta / left_seconds, 1) if left_seconds > 0 else None,
        "macro_delta": right.macro_runs - left.macro_runs,
        "verdict": "longer" if delta > 0 else ("shorter" if delta < 0 else "equal"),
    }


def build_statistics(
    *,
    sessions: Sequence[Any] | None = None,
    runs: Sequence[Any] | None = None,
    now: float,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict[str, Any]:
    """Assemble the statistics dashboard payload in one pass."""

    records = _coerce_sessions(sessions or [])
    horizon = float(now) - max(1, min(int(window_days or DEFAULT_WINDOW_DAYS), MAX_WINDOW_DAYS)) * 86_400.0
    recent = [record for record in records if (record.ended_at or now) >= horizon]
    total_seconds = sum(record.duration_seconds(now=now) for record in recent)
    crashes = sum(1 for record in recent if record.crashed)
    return {
        "generated_at": float(now),
        "window_days": window_days,
        "totals": {
            "sessions": len(recent),
            "accounts": len({record.account_id for record in recent if record.account_id}),
            "hours": round(total_seconds / 3600.0, 2),
            "crashes": crashes,
            "crash_rate": round(100.0 * crashes / len(recent), 1) if recent else None,
        },
        "heatmap": build_heatmap(recent, now=now, window_days=window_days),
        "reliability": reliability_table(recent, now=now),
        "macros": macro_success_rate(runs or []),
        "recent": [
            {
                "account_id": record.account_id,
                "username": record.username,
                "started_at": record.started_at,
                "ended_at": record.ended_at,
                "seconds": round(record.duration_seconds(now=now), 1),
                "crashed": record.crashed,
            }
            for record in sorted(recent, key=lambda item: -item.started_at)[:20]
        ],
    }
