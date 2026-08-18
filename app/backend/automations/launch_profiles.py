"""Named launch profiles.

A launch profile stores *what a launch should look like*, so ten accounts can be
sent to the same place, the same server and the same FPS target without
retyping anything.  The dashboard already knew how to launch one account; what
was missing was a way to name a destination once and reuse it.

A profile deliberately holds no secret: a place id, an optional job id or
private-server link code, an optional FPS target and an optional group scope.
Everything is bounded and validated here so the service layer never persists a
half-checked profile.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from ..core.errors import ValidationError

MAX_PROFILES = 40
MAX_NAME_CHARS = 60
MAX_NOTE_CHARS = 200
MIN_FPS = 24
MAX_FPS = 1000

_PLACE_ID_PATTERN = re.compile(r"^[0-9]{1,20}$")
_JOB_ID_PATTERN = re.compile(r"^[0-9a-fA-F-]{8,64}$")
_LINK_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,64}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value: Any, *, field: str, limit: int, required: bool = False) -> str:
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value.strip()
    else:
        raise ValidationError(f"{field} must be text.")
    if required and not text:
        raise ValidationError(f"{field} is required.")
    if len(text) > limit:
        raise ValidationError(f"{field} must be at most {limit} characters.")
    return text


def _place_id(value: Any) -> int:
    text = str(value if value is not None else "").strip()
    if not _PLACE_ID_PATTERN.match(text):
        raise ValidationError("A launch profile needs a numeric Place ID.")
    place = int(text)
    if place <= 0:
        raise ValidationError("A launch profile needs a numeric Place ID.")
    return place


def _job_id(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        return ""
    if not _JOB_ID_PATTERN.match(text):
        raise ValidationError("That JobId does not look like a Roblox server id.")
    return text


def _link_code(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        return ""
    if not _LINK_CODE_PATTERN.match(text):
        raise ValidationError("That private server code does not look valid.")
    return text


def _fps(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        raise ValidationError("An FPS target must be a whole number.")
    try:
        fps = int(value)
    except (TypeError, ValueError) as error:
        raise ValidationError("An FPS target must be a whole number.") from error
    if fps == 0:
        return 0
    if fps < MIN_FPS or fps > MAX_FPS:
        raise ValidationError(f"An FPS target must be between {MIN_FPS} and {MAX_FPS}.")
    return fps


def validated_profile(raw: Any, *, existing_id: str = "") -> dict[str, Any]:
    """Return one bounded profile ready to persist.

    A job id and a private-server code describe two different destinations, so
    asking for both is a mistake worth reporting instead of silently dropping
    one of them.
    """

    if not isinstance(raw, Mapping):
        raise ValidationError("A launch profile must be an object.")
    job_id = _job_id(raw.get("job_id"))
    link_code = _link_code(raw.get("link_code") or raw.get("private_server_link_code"))
    if job_id and link_code:
        raise ValidationError("Choose either a JobId or a private server code, not both.")
    profile_id = _text(raw.get("id") or existing_id, field="Profile id", limit=64) or str(uuid.uuid4())
    return {
        "id": profile_id,
        "name": _text(raw.get("name"), field="Profile name", limit=MAX_NAME_CHARS, required=True),
        "place_id": _place_id(raw.get("place_id")),
        "job_id": job_id,
        "link_code": link_code,
        "fps": _fps(raw.get("fps")),
        "group_id": _text(raw.get("group_id"), field="Group", limit=64),
        "note": _text(raw.get("note"), field="Note", limit=MAX_NOTE_CHARS),
        "updated_at": _utc_now(),
    }


def normalize_profiles(raw: Any) -> list[dict[str, Any]]:
    """Return the stored profiles, dropping anything no longer readable."""

    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return []
    profiles: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        try:
            profile = validated_profile(item, existing_id=str(item.get("id") or ""))
        except ValidationError:
            # A profile written by an older build is skipped rather than
            # blocking the whole screen.
            continue
        if profile["id"] in seen:
            continue
        seen.add(profile["id"])
        profile["updated_at"] = str(item.get("updated_at") or profile["updated_at"])
        profiles.append(profile)
        if len(profiles) >= MAX_PROFILES:
            break
    profiles.sort(key=lambda row: str(row.get("name", "")).casefold())
    return profiles


def upsert_profile(profiles: Sequence[Mapping[str, Any]], profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the list with this profile added or replaced."""

    rows = [dict(row) for row in profiles if str(row.get("id")) != str(profile.get("id"))]
    if len(rows) >= MAX_PROFILES:
        raise ValidationError(f"A workspace may hold at most {MAX_PROFILES} launch profiles.")
    rows.append(dict(profile))
    rows.sort(key=lambda row: str(row.get("name", "")).casefold())
    return rows


def profile_target(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Return the launch target this profile describes.

    The shape matches what ``launch_account`` already accepts, so a profile
    launch takes exactly the same path as a manual one.
    """

    target: dict[str, Any] = {"place_id": _place_id(profile.get("place_id"))}
    job_id = _job_id(profile.get("job_id"))
    link_code = _link_code(profile.get("link_code"))
    if job_id:
        target["job_id"] = job_id
    elif link_code:
        target["private_server_link_code"] = link_code
    return target


def describe_profile(profile: Mapping[str, Any]) -> str:
    """Return one line an operator can read at a glance."""

    parts = [f"Place {profile.get('place_id')}"]
    if profile.get("job_id"):
        parts.append("same server")
    elif profile.get("link_code"):
        parts.append("private server")
    else:
        parts.append("any public server")
    fps = int(profile.get("fps") or 0)
    if fps:
        parts.append(f"{fps} FPS")
    if profile.get("group_id"):
        parts.append("group scoped")
    return ", ".join(parts)
