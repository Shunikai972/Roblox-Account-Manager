"""Roblox Private Server / VIP link parsing and launcher URI formatting."""

from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, quote, urlparse

from app.backend.core.errors import ValidationError

logger = logging.getLogger("astro.private_servers")
_LINK_CODE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


class PrivateServerHelper:
    """Parses VIP links and generates private server launcher URIs."""

    @staticmethod
    def parse_vip_link(link: str) -> dict[str, str | int] | None:
        """Extract placeId and privateServerLinkCode or code from a Roblox VIP link."""

        parsed = urlparse(link)
        hostname = (parsed.hostname or "").casefold()
        if parsed.scheme not in ("http", "https") or not (hostname == "roblox.com" or hostname.endswith(".roblox.com")):
            return None
        params = parse_qs(parsed.query)

        # Pattern 1: https://www.roblox.com/games/12345/Title?privateServerLinkCode=abcdef...
        place_match = re.search(r"/games/(\d+)", parsed.path)
        place_id = int(place_match.group(1)) if place_match else None

        code = (
            (params.get("privateServerLinkCode") or params.get("code") or [None])[0]
        )

        if not place_id and "placeId" in params:
            try:
                place_id = int(params["placeId"][0])
            except (ValueError, TypeError):
                pass

        if place_id and isinstance(code, str) and _LINK_CODE.fullmatch(code):
            return {"place_id": place_id, "link_code": code}

        return None

    @staticmethod
    def format_private_server_uri(auth_ticket: str, place_id: int, link_code: str, launch_time: int | None = None) -> str:
        """Format an rbx-player protocol URI for a private / VIP server link."""

        if not isinstance(auth_ticket, str) or not auth_ticket or len(auth_ticket) > 4096:
            raise ValidationError("Authentication ticket is invalid.")
        if any(ord(character) < 33 or character.isspace() for character in auth_ticket):
            raise ValidationError("Authentication ticket is invalid.")
        if isinstance(place_id, bool) or not isinstance(place_id, int) or place_id <= 0:
            raise ValidationError("PlaceId must be a positive integer.")
        if not isinstance(link_code, str) or not _LINK_CODE.fullmatch(link_code):
            raise ValidationError("Private server link code is invalid.")

        if not launch_time:
            import time
            launch_time = int(time.time() * 1000)

        return (
            f"roblox-player:1+launchmode:play+gameinfo:{quote(auth_ticket, safe='')}+launchtime:{launch_time}"
            f"+placelauncherurl:https%3A%2F%2Fassetgame.roblox.com%2Fgame%2FPlaceLauncher.ashx%3Frequest%3DRequestPrivateGame%26placeId%3D{place_id}%26linkCode%3D{quote(link_code, safe='-_')}"
        )
