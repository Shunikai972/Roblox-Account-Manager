"""Typed domain objects. Secrets deliberately do not belong to these models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import re
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


_LEGACY_GROUP_PREFIX = re.compile(r"^(\d{1,3})\s?")


def legacy_group_order_key(
    name: Any,
    *,
    previous_order: Any = 0,
    identifier: Any = "",
) -> tuple[int, int, str, str, int, str]:
    """Return the stable order encoded by legacy group-name prefixes.

    The historical ObjectListView grouped by the raw name while rendering a
    leading one-to-three digit prefix (and one optional space) invisible.
    ``001 Apple`` and ``1Apple`` therefore carry an ordering hint without
    altering the display title.  The final fields make equal keys deterministic
    for a one-time storage migration.
    """

    group_name = str(name)
    match = _LEGACY_GROUP_PREFIX.match(group_name)
    try:
        fallback_order = int(previous_order)
    except (TypeError, ValueError):
        fallback_order = 0
    identifier_text = str(identifier)
    if match:
        return (
            0,
            int(match.group(1)),
            group_name[match.end() :].casefold(),
            group_name.casefold(),
            fallback_order,
            identifier_text,
        )
    return (1, 0, group_name.casefold(), group_name.casefold(), fallback_order, identifier_text)


@dataclass(slots=True)
class Group:
    name: str
    id: str = field(default_factory=lambda: str(uuid4()))
    color: str = "#7c5cff"
    icon: str = "folder"
    # The repository assigns a stable position when a group is first saved;
    # materialized groups always carry an integer.  Reordering is intentionally
    # performed through the atomic repository operation rather than a stale
    # presentation object.
    sort_order: int | None = None
    is_favorite: bool = False
    is_collapsed: bool = False
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Account:
    username: str
    id: str = field(default_factory=lambda: str(uuid4()))
    user_id: int | None = None
    display_name: str | None = None
    alias: str = ""
    description: str = ""
    group_id: str | None = None
    avatar_url: str | None = None
    status: str = "unknown"
    is_favorite: bool = False
    # Persisted by SQLite.  ``None`` means a new account should be appended to
    # the existing local order; materialized accounts always carry an integer.
    sort_order: int | None = None
    last_used_at: str | None = None
    last_refreshed_at: str | None = None
    saved_place_id: int | None = None
    saved_job_id: str | None = None
    browser_tracker_id: str | None = None
    custom_fields: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    has_session: bool = False
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Game:
    place_id: int
    name: str
    universe_id: int | None = None
    id: str = field(default_factory=lambda: str(uuid4()))
    description: str = ""
    creator_name: str | None = None
    creator_id: int | None = None
    icon_url: str | None = None
    playing: int | None = None
    max_players: int | None = None
    is_favorite: bool = False
    last_used_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Server:
    job_id: str
    place_id: int
    playing: int
    max_players: int
    ping: float | None = None
    fps: float | None = None
    region: str | None = None
    server_type: str = "public"
    player_tokens: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class InstanceInfo:
    pid: int
    name: str
    started_at: str | None = None
    memory_bytes: int | None = None
    account_id: str | None = None
    account_username: str | None = None
    place_id: int | None = None
    job_id: str | None = None
    status: str = "running"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Activity:
    kind: str
    summary: str
    id: str = field(default_factory=lambda: str(uuid4()))
    account_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Notification:
    level: str
    title: str
    message: str
    id: str = field(default_factory=lambda: str(uuid4()))
    is_dismissed: bool = False
    action: dict[str, str] | None = None
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
