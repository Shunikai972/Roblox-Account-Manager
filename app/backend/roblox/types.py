"""Value objects used by the Roblox integration.

The application-level ``Game`` and ``Server`` objects live in
``app.backend.models.domain``.  This module only contains transport and
operation results that do not belong in persistent domain storage.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from app.backend.models.domain import Server


class ServerSortOrder(str, Enum):
    """Sort directions accepted by Roblox's public-server endpoint."""

    ASCENDING = "Asc"
    DESCENDING = "Desc"


class PresenceState(str, Enum):
    """Public Roblox presence states returned by ``presence.roblox.com``."""

    OFFLINE = "offline"
    ONLINE = "online"
    IN_GAME = "in_game"
    IN_STUDIO = "in_studio"


@dataclass(frozen=True, slots=True)
class PublicUserProfile:
    """Public, credential-free Roblox identity and headshot metadata.

    This is intentionally narrower than the legacy authenticated account
    object: it only contains values supplied by Roblox's public profile and
    thumbnail endpoints.  ``profile_url`` is constructed locally from the
    numeric user id and never incorporates a request URL or session data.
    """

    user_id: int
    username: str
    display_name: str | None = None
    description: str | None = None
    created_at: str | None = None
    is_banned: bool | None = None
    has_verified_badge: bool | None = None
    avatar_url: str | None = None
    avatar_state: str | None = None

    @property
    def profile_url(self) -> str:
        return f"https://www.roblox.com/users/{self.user_id}/profile"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["profile_url"] = self.profile_url
        return payload


@dataclass(frozen=True, slots=True)
class PublicUsernameResolution:
    """The minimal public identity returned for a Roblox username lookup.

    This object deliberately stops at the public username endpoint's identity
    fields.  It does not represent a local account, an authenticated browser,
    or a Roblox game-client session.
    """

    user_id: int
    username: str
    display_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "display_name": self.display_name,
        }


@dataclass(frozen=True, slots=True)
class UserPresence:
    """A public presence snapshot for a single Roblox user."""

    user_id: int
    state: PresenceState
    last_location: str | None = None
    place_id: int | None = None
    root_place_id: int | None = None
    game_id: str | None = None
    universe_id: int | None = None
    last_online: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["state"] = self.state.value
        return payload


@dataclass(frozen=True, slots=True)
class ServerPage:
    """One cursor-based page of public Roblox servers."""

    servers: tuple[Server, ...]
    next_page_cursor: str | None
    previous_page_cursor: str | None


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """Non-sensitive identity returned for an already stored session."""

    user_id: int
    username: str
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class LaunchTarget:
    """A validated local Roblox experience target.

    ``job_id`` is optional: without it Roblox chooses an eligible public
    server.  It deliberately contains no account/session information.
    """

    place_id: int
    job_id: str | None = None


@dataclass(frozen=True, slots=True)
class LaunchResult:
    """The result of handing an experience URI to Windows."""

    uri: str
    launched: bool
