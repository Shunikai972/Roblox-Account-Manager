"""Authenticated account tools: ticket generation, rbx-player URIs, and session exports."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from app.backend.roblox.client import RobloxClient
from app.backend.roblox.errors import RobloxServiceError

logger = logging.getLogger("astro.auth_tools")


class RobloxAuthTools:
    """Provides authenticated session tools matching Roblox Account Manager 3.7.2 capabilities."""

    def __init__(self, roblox_client: RobloxClient | None = None) -> None:
        self.client = roblox_client or RobloxClient()

    def generate_auth_ticket(self, cookie: str) -> str:
        """Request a single-use authentication ticket from auth.roblox.com/v1/authentication-ticket."""

        session = requests.Session()
        session.headers.update({
            "Referer": "https://www.roblox.com/",
            "Origin": "https://www.roblox.com",
            "User-Agent": "AstroAccountManager/1.0",
        })
        session.cookies.set(".ROBLOSECURITY", cookie, domain=".roblox.com")

        url = "https://auth.roblox.com/v1/authentication-ticket"
        try:
            res = session.post(url)
            # Handle CSRF token challenge
            if res.status_code == 403 and "x-csrf-token" in res.headers:
                session.headers["x-csrf-token"] = res.headers["x-csrf-token"]
                res = session.post(url)

            ticket = res.headers.get("rbx-authentication-ticket")
            if ticket:
                return ticket

            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict) and "ticket" in data:
                    return str(data["ticket"])

            raise RobloxServiceError(f"Le serveur Roblox a retourné le statut HTTP {res.status_code}.")
        except Exception as exc:
            logger.error(f"Failed to generate auth ticket: {exc}")
            raise RobloxServiceError(f"Impossible de générer le ticket d'authentification: {exc}") from exc

    def generate_rbx_player_uri(self, auth_ticket: str, place_id: int, job_id: str | None = None) -> str:
        """Format an rbx-player protocol URI using a valid auth ticket."""

        launch_time = int(time.time() * 1000)
        base = f"roblox-player:1+launchmode:play+gameinfo:{auth_ticket}+launchtime:{launch_time}+placelauncherurl:https%3A%2F%2Fassetgame.roblox.com%2Fgame%2FPlaceLauncher.ashx%3Frequest%3DRequestGame%26placeId%3D{place_id}"
        if job_id:
            base += f"%26gameId%3D{job_id}"
        return base
