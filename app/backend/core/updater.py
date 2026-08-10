"""Update checker for Astro Account Manager."""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger("astro.updater")

CURRENT_VERSION = "4.0.0"
RELEASES_URL = "https://api.github.com/repos/ic3w0lf22/Roblox-Account-Manager/releases/latest"


class UpdateChecker:
    """Checks for latest releases on GitHub."""

    @staticmethod
    def check_for_updates() -> dict[str, Any]:
        """Fetch release info from GitHub API."""

        try:
            res = requests.get(RELEASES_URL, timeout=5.0, headers={"User-Agent": "AstroAccountManager"})
            if res.status_code == 200:
                data = res.json()
                tag_name = data.get("tag_name", "").lstrip("v")
                has_update = tag_name > CURRENT_VERSION if tag_name else False
                return {
                    "current_version": CURRENT_VERSION,
                    "latest_version": tag_name or CURRENT_VERSION,
                    "update_available": has_update,
                    "release_notes": data.get("body", ""),
                    "download_url": data.get("html_url", ""),
                }
            return {
                "current_version": CURRENT_VERSION,
                "latest_version": CURRENT_VERSION,
                "update_available": False,
                "reason": f"HTTP {res.status_code}",
            }
        except Exception as exc:
            logger.warning(f"Failed to check for updates: {exc}")
            return {
                "current_version": CURRENT_VERSION,
                "latest_version": CURRENT_VERSION,
                "update_available": False,
                "reason": str(exc),
            }
