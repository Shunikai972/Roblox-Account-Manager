"""Server memory: JobId history, blacklist, region affinity, smart hopping.

Pure bookkeeping over records the app already sees when it joins a place.  It
never contacts Roblox; the caller feeds it what it observed and it answers
which server to pick next and why.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

from app.backend.core.errors import ValidationError

MAX_HISTORY = 200
MAX_BLACKLIST = 100
MAX_NOTE_CHARS = 120
MAX_REGION_CHARS = 40
DEFAULT_AVOID_RECENT_SECONDS = 900
MAX_AVOID_RECENT_SECONDS = 86_400
FAILURE_BLACKLIST_THRESHOLD = 3

_JOB_ID = re.compile(r"^[0-9a-fA-F-]{8,64}$")
_PLACE_ID = re.compile(r"^[0-9]{1,20}$")


@dataclass(frozen=True, slots=True)
class ServerRecord:
    job_id: str
    place_id: str = ""
    region: str = ""
    players: int = 0
    max_players: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0
    joins: int = 0
    failures: int = 0
    note: str = ""

    def to_dict(self, *, now: float | None = None) -> dict[str, Any]:
        moment = float(now) if now is not None else self.last_seen
        uptime = max(0.0, moment - self.first_seen) if self.first_seen else 0.0
        capacity = None
        if self.max_players > 0:
            capacity = round(100.0 * self.players / self.max_players, 1)
        return {
            "job_id": self.job_id,
            "place_id": self.place_id,
            "region": self.region,
            "players": self.players,
            "max_players": self.max_players,
            "fill_percent": capacity,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "uptime_seconds": round(uptime, 1),
            "joins": self.joins,
            "failures": self.failures,
            "note": self.note,
            "healthy": self.failures < FAILURE_BLACKLIST_THRESHOLD,
        }


def normalize_job_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationError("A server job id is required.")
    if not _JOB_ID.match(text):
        raise ValidationError("That server job id is not valid.")
    return text


def normalize_place_id(value: Any, *, required: bool = False) -> str:
    text = str(value or "").strip()
    if not text:
        if required:
            raise ValidationError("A place id is required.")
        return ""
    if not _PLACE_ID.match(text):
        raise ValidationError("That place id is not valid.")
    return text


def normalize_region(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) > MAX_REGION_CHARS:
        raise ValidationError(f"A region label may hold at most {MAX_REGION_CHARS} characters.")
    if any(ord(char) < 32 for char in text):
        raise ValidationError("That region label is not valid.")
    return text


def coerce_history(raw: Iterable[Any]) -> list[ServerRecord]:
    records: list[ServerRecord] = []
    for item in list(raw or [])[:MAX_HISTORY]:
        if isinstance(item, ServerRecord):
            records.append(item)
            continue
        if not isinstance(item, Mapping):
            continue
        try:
            job_id = normalize_job_id(item.get("job_id"))
        except ValidationError:
            continue
        records.append(
            ServerRecord(
                job_id=job_id,
                place_id=str(item.get("place_id") or "")[:20],
                region=str(item.get("region") or "")[:MAX_REGION_CHARS],
                players=max(0, int(item.get("players") or 0)),
                max_players=max(0, int(item.get("max_players") or 0)),
                first_seen=float(item.get("first_seen") or 0.0),
                last_seen=float(item.get("last_seen") or 0.0),
                joins=max(0, int(item.get("joins") or 0)),
                failures=max(0, int(item.get("failures") or 0)),
                note=str(item.get("note") or "")[:MAX_NOTE_CHARS],
            )
        )
    return records


def record_visit(
    history: Iterable[Any],
    *,
    job_id: str,
    place_id: str = "",
    region: str = "",
    players: int = 0,
    max_players: int = 0,
    now: float,
    failed: bool = False,
) -> list[ServerRecord]:
    """Fold one observation into the history, newest first."""

    identifier = normalize_job_id(job_id)
    records = coerce_history(history)
    existing = next((record for record in records if record.job_id == identifier), None)
    if existing is None:
        updated = ServerRecord(
            job_id=identifier,
            place_id=normalize_place_id(place_id),
            region=normalize_region(region),
            players=max(0, int(players or 0)),
            max_players=max(0, int(max_players or 0)),
            first_seen=float(now),
            last_seen=float(now),
            joins=0 if failed else 1,
            failures=1 if failed else 0,
        )
    else:
        records = [record for record in records if record.job_id != identifier]
        updated = replace(
            existing,
            place_id=normalize_place_id(place_id) or existing.place_id,
            region=normalize_region(region) or existing.region,
            players=max(0, int(players or 0)) or existing.players,
            max_players=max(0, int(max_players or 0)) or existing.max_players,
            last_seen=float(now),
            joins=existing.joins + (0 if failed else 1),
            failures=existing.failures + (1 if failed else 0),
        )
    return [updated, *records][:MAX_HISTORY]


def normalize_blacklist(raw: Iterable[Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in list(raw or [])[:MAX_BLACKLIST]:
        if isinstance(item, Mapping):
            candidate = item.get("job_id")
            note = str(item.get("note") or "")[:MAX_NOTE_CHARS]
            added = item.get("added_at")
        else:
            candidate = item
            note = ""
            added = None
        try:
            job_id = normalize_job_id(candidate)
        except ValidationError:
            continue
        if job_id in seen:
            continue
        seen.add(job_id)
        entries.append({"job_id": job_id, "note": note, "added_at": added})
    return entries


def blacklist_add(raw: Iterable[Any], *, job_id: str, note: str = "", now: float) -> list[dict[str, Any]]:
    identifier = normalize_job_id(job_id)
    entries = [entry for entry in normalize_blacklist(raw) if entry["job_id"] != identifier]
    if len(entries) >= MAX_BLACKLIST:
        raise ValidationError(f"The blacklist holds at most {MAX_BLACKLIST} servers.")
    entries.insert(0, {"job_id": identifier, "note": str(note or "")[:MAX_NOTE_CHARS], "added_at": float(now)})
    return entries


def blacklist_remove(raw: Iterable[Any], *, job_id: str) -> list[dict[str, Any]]:
    identifier = normalize_job_id(job_id)
    return [entry for entry in normalize_blacklist(raw) if entry["job_id"] != identifier]


def pick_server(
    history: Iterable[Any],
    *,
    place_id: str = "",
    blacklist: Iterable[Any] = (),
    prefer_region: str = "",
    avoid_recent_seconds: int = DEFAULT_AVOID_RECENT_SECONDS,
    avoid_job_ids: Iterable[str] = (),
    now: float,
) -> dict[str, Any]:
    """Choose the next server to join and explain the choice.

    Ranking, in order: never blacklisted, never failed too often, matching the
    preferred region, not visited in the cooldown window, then emptiest.
    """

    wanted_place = normalize_place_id(place_id)
    region = normalize_region(prefer_region).casefold()
    cooldown = max(0, min(int(avoid_recent_seconds or 0), MAX_AVOID_RECENT_SECONDS))
    banned = {entry["job_id"] for entry in normalize_blacklist(blacklist)}
    for value in avoid_job_ids or ():
        try:
            banned.add(normalize_job_id(value))
        except ValidationError:
            continue

    candidates: list[tuple[tuple[Any, ...], ServerRecord]] = []
    rejected = 0
    for record in coerce_history(history):
        if wanted_place and record.place_id and record.place_id != wanted_place:
            continue
        if record.job_id in banned:
            rejected += 1
            continue
        if record.failures >= FAILURE_BLACKLIST_THRESHOLD:
            rejected += 1
            continue
        if record.max_players and record.players >= record.max_players:
            rejected += 1
            continue
        recent = cooldown > 0 and (float(now) - record.last_seen) < cooldown
        region_miss = bool(region) and record.region.casefold() != region
        fill = (record.players / record.max_players) if record.max_players else 0.5
        candidates.append(((region_miss, recent, record.failures, fill, -record.last_seen), record))

    if not candidates:
        return {
            "found": False,
            "job_id": "",
            "reason": "No known server matches those filters yet. Join one manually and it will be remembered.",
            "considered": 0,
            "rejected": rejected,
        }
    candidates.sort(key=lambda item: item[0])
    key, chosen = candidates[0]
    region_miss, recent = key[0], key[1]
    if region_miss:
        reason = f"No server left in {prefer_region}, so the least busy known server was picked."
    elif recent:
        reason = "Every known server was visited recently, so the oldest visit was reused."
    else:
        reason = "Picked the least busy server that is outside the recent-visit window."
    return {
        "found": True,
        "job_id": chosen.job_id,
        "place_id": chosen.place_id,
        "region": chosen.region,
        "reason": reason,
        "considered": len(candidates),
        "rejected": rejected,
        "server": chosen.to_dict(now=now),
    }


def inspect_history(
    history: Iterable[Any],
    *,
    blacklist: Iterable[Any] = (),
    now: float,
    limit: int = 50,
) -> dict[str, Any]:
    """Return the inspector payload: known servers, regions, blacklist state."""

    banned = {entry["job_id"] for entry in normalize_blacklist(blacklist)}
    records = coerce_history(history)
    rows: list[dict[str, Any]] = []
    regions: dict[str, int] = {}
    for record in records[: max(1, min(int(limit or 50), MAX_HISTORY))]:
        payload = record.to_dict(now=now)
        payload["blacklisted"] = record.job_id in banned
        rows.append(payload)
        if record.region:
            regions[record.region] = regions.get(record.region, 0) + 1
    region_rows = [{"region": name, "servers": count} for name, count in regions.items()]
    region_rows.sort(key=lambda row: (-row["servers"], row["region"]))
    return {
        "servers": rows,
        "total": len(records),
        "blacklisted": len(banned),
        "regions": region_rows,
        "generated_at": float(now),
    }
