"""Authenticated account tools: ticket generation, rbx-player URIs, and session exports."""

from __future__ import annotations

import logging
import re
import time
from typing import Any
from urllib.parse import quote

import requests

from app.backend.roblox.client import RobloxClient
from app.backend.roblox.errors import RobloxServiceError

logger = logging.getLogger("astro.auth_tools")
_JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


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
            "Accept": "application/json",
        })
        session.cookies.set(".ROBLOSECURITY", cookie, domain=".roblox.com")

        url = "https://auth.roblox.com/v1/authentication-ticket"
        try:
            # Roblox now rejects an empty POST without a media type with
            # HTTP 415.  Sending an explicit empty JSON object preserves the
            # historical CSRF challenge flow while satisfying the endpoint's
            # current content-type contract.
            res = session.post(url, json={}, timeout=15.0)
            # Handle CSRF token challenge
            if res.status_code == 403 and "x-csrf-token" in res.headers:
                session.headers["x-csrf-token"] = res.headers["x-csrf-token"]
                res = session.post(url, json={}, timeout=15.0)

            ticket = res.headers.get("rbx-authentication-ticket")
            if ticket:
                return ticket

            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict) and "ticket" in data:
                    return str(data["ticket"])

            raise RobloxServiceError(f"Roblox server returned HTTP status {res.status_code}.")
        except RobloxServiceError:
            raise
        except requests.RequestException as exc:
            logger.warning("Authentication-ticket request failed", exc_info=True)
            raise RobloxServiceError("Could not reach Roblox to generate an authentication ticket.") from exc
        except (TypeError, ValueError) as exc:
            raise RobloxServiceError("Roblox returned an invalid authentication-ticket response.") from exc

    def get_csrf_token(self, cookie: str) -> str:
        """Obtain the session's X-CSRF token without logging or persisting it."""

        session = requests.Session()
        session.headers.update({
            "Referer": "https://www.roblox.com/",
            "Origin": "https://www.roblox.com",
            "User-Agent": "AstroAccountManager/4",
        })
        session.cookies.set(".ROBLOSECURITY", cookie, domain=".roblox.com")
        try:
            response = session.post("https://auth.roblox.com/v2/logout", timeout=15.0)
        except requests.RequestException as exc:
            raise RobloxServiceError("Could not reach Roblox to obtain an X-CSRF token.") from exc
        finally:
            session.close()
        token = response.headers.get("x-csrf-token")
        if not token or any(ord(character) < 33 for character in token):
            raise RobloxServiceError("Roblox did not return an X-CSRF token for this session.")
        return token

    def generate_rbx_player_uri(self, auth_ticket: str, place_id: int, job_id: str | None = None) -> str:
        """Format an rbx-player protocol URI using a valid auth ticket."""

        if not isinstance(auth_ticket, str) or not auth_ticket or len(auth_ticket) > 4096:
            raise RobloxServiceError("Authentication ticket is invalid.")
        if any(ord(character) < 33 or character.isspace() for character in auth_ticket):
            raise RobloxServiceError("Authentication ticket is invalid.")
        if isinstance(place_id, bool) or not isinstance(place_id, int) or place_id <= 0:
            raise RobloxServiceError("PlaceId must be a positive integer.")
        if job_id is not None and (not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id)):
            raise RobloxServiceError("JobId is invalid.")

        launch_time = int(time.time() * 1000)
        base = f"roblox-player:1+launchmode:play+gameinfo:{quote(auth_ticket, safe='')}+launchtime:{launch_time}+placelauncherurl:https%3A%2F%2Fassetgame.roblox.com%2Fgame%2FPlaceLauncher.ashx%3Frequest%3DRequestGame%26placeId%3D{place_id}"
        if job_id:
            base += f"%26gameId%3D{quote(job_id, safe='-_')}"
        return base
