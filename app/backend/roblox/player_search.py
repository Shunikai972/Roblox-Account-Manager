"""Player search and Follow-Player server lookup service."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.backend.roblox.client import RobloxClient
from app.backend.roblox.errors import RobloxServiceError

logger = logging.getLogger("astro.player_search")
_GAMES_BASE = "https://games.roblox.com"
_THUMBNAILS_BASE = "https://thumbnails.roblox.com"


class PlayerSearchService:
    """Provides player search and server discovery for joining friends."""

    def __init__(self, roblox_client: RobloxClient | None = None) -> None:
        self.client = roblox_client or RobloxClient()

    def search_players(self, keyword: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search Roblox users by username or display name."""

        url = "https://users.roblox.com/v1/users/search"
        try:
            payload = self.client._request_json(url, params={"keyword": keyword, "limit": limit})
            entries = payload.get("data")
            if not isinstance(entries, list):
                return []
            return [
                {
                    "user_id": item.get("id"),
                    "name": item.get("name"),
                    "display_name": item.get("displayName"),
                    "has_verified_badge": item.get("hasVerifiedBadge", False),
                }
                for item in entries
                if isinstance(item, dict)
            ]
        except RobloxServiceError:
            raise
        except Exception as exc:
            logger.error("Failed to search Roblox players", exc_info=True)
            raise RobloxServiceError("Could not search for a Roblox player.") from exc

    def get_player_presence(self, user_id: int) -> dict[str, Any]:
        """Fetch presence and current experience destination for a player."""

        presences = self.client.get_public_presence((user_id,))
        if not presences:
            return {"user_id": user_id, "status": "Offline", "place_id": None, "job_id": None}

        presence = presences[0]
        return {
            "user_id": presence.user_id,
            "status": presence.state.value,
            "place_id": presence.place_id,
            # Roblox calls the live server identifier ``gameId``. Astro's
            # model exposes it as ``game_id`` while RAM's surface calls it a
            # JobId.
            "job_id": presence.game_id,
            "game_id": presence.game_id,
            "last_online": presence.last_online,
        }

    def find_player_server(
        self,
        place_id: int,
        user_id: int,
        *,
        max_pages: int = 10,
    ) -> dict[str, Any] | None:
        """Find a player's public server using RAM 3.7.2's thumbnail match.

        Roblox's server list exposes opaque player tokens rather than user
        identifiers.  RAM 3.7.2 resolved those tokens through the thumbnail
        batch endpoint and compared their avatar-headshot URL with the target
        user's public headshot.  This port preserves that bounded algorithm
        while limiting pagination and never returning the opaque tokens.
        """

        place_id = _positive_int(place_id, "PlaceId")
        user_id = _positive_int(user_id, "UserId")
        if isinstance(max_pages, bool) or not isinstance(max_pages, int) or not 1 <= max_pages <= 100:
            raise RobloxServiceError("Server scan page limit must be between 1 and 100.")

        profile = self.client.get_public_profile(user_id)
        target_thumbnail = _normalized_image_url(profile.avatar_url)
        if not target_thumbnail:
            raise RobloxServiceError("The target player's avatar thumbnail is unavailable.")

        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _page in range(max_pages):
            params: dict[str, str | int] = {"limit": 100, "sortOrder": "Asc"}
            if cursor:
                params["cursor"] = cursor
            payload = self.client._request_json(
                f"{_GAMES_BASE}/v1/games/{place_id}/servers/Public",
                params=params,
            )
            raw_servers = payload.get("data")
            if not isinstance(raw_servers, list):
                raise RobloxServiceError("Roblox returned an invalid server list.")

            for raw_server in raw_servers:
                if not isinstance(raw_server, dict):
                    continue
                job_id = raw_server.get("id")
                raw_tokens = raw_server.get("playerTokens")
                if not isinstance(job_id, str) or not job_id or len(job_id) > 128:
                    continue
                if not isinstance(raw_tokens, list):
                    continue
                tokens = [token for token in raw_tokens if isinstance(token, str) and 0 < len(token) <= 512]
                for offset in range(0, len(tokens), 100):
                    batch = [
                        {
                            "requestId": f"0:{token}:AvatarHeadshot:48x48:png:regular",
                            "type": "AvatarHeadShot",
                            "targetId": 0,
                            "token": token,
                            "format": "png",
                            "size": "48x48",
                        }
                        for token in tokens[offset : offset + 100]
                    ]
                    if not batch:
                        continue
                    thumbnails = self.client._post_json(
                        f"{_THUMBNAILS_BASE}/v1/batch",
                        json_body=batch,
                    ).get("data")
                    if not isinstance(thumbnails, list):
                        continue
                    if any(
                        isinstance(item, dict)
                        and _normalized_image_url(item.get("imageUrl")) == target_thumbnail
                        for item in thumbnails
                    ):
                        return {
                            "job_id": job_id,
                            "place_id": place_id,
                            "playing": _nonnegative_int(raw_server.get("playing")),
                            "capacity": _nonnegative_int(raw_server.get("maxPlayers")),
                            "ping": _optional_nonnegative_number(raw_server.get("ping")),
                        }

            next_cursor = payload.get("nextPageCursor")
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return None


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise RobloxServiceError(f"{label} must be a positive integer.")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise RobloxServiceError(f"{label} must be a positive integer.") from None
    if parsed <= 0:
        raise RobloxServiceError(f"{label} must be a positive integer.")
    return parsed


def _normalized_image_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        return None
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


def _nonnegative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _optional_nonnegative_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return float(value)
