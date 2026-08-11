"""Player search and Follow-Player server lookup service."""

from __future__ import annotations

import logging
from typing import Any

from app.backend.roblox.client import RobloxClient
from app.backend.roblox.errors import RobloxServiceError

logger = logging.getLogger("astro.player_search")


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
        except Exception as exc:
            logger.error(f"Failed to search players for '{keyword}': {exc}")
            raise RobloxServiceError(f"Could not search for player: {exc}") from exc

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
            "job_id": presence.job_id,
            "game_id": presence.game_id,
            "last_online": presence.last_online,
        }
