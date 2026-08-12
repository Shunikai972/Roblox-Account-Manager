"""Random server selection strategy for Roblox experience launching."""

from __future__ import annotations

import random
import logging
from typing import Any

from app.backend.roblox.client import RobloxClient

logger = logging.getLogger("astro.random_server")


class RandomServerSelector:
    """Picks a random active server for a given PlaceId."""

    def __init__(self, roblox_client: RobloxClient | None = None) -> None:
        self.client = roblox_client or RobloxClient()

    def get_random_server(self, place_id: int) -> dict[str, Any] | None:
        """Fetch server list for place_id and return a randomly chosen server."""

        page = self.client.list_public_servers(place_id, limit=25)
        servers = page.servers
        if not servers:
            return None

        chosen = random.choice(servers)
        return {
            "job_id": chosen.job_id,
            "place_id": place_id,
            "playing": chosen.playing,
            "capacity": chosen.max_players,
            "ping": chosen.ping,
        }
