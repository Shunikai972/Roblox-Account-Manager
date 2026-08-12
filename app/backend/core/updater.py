"""Update checker for Astro Account Manager."""

from __future__ import annotations

import logging
import re
from typing import Any

import requests

from app.backend.core.config import APP_VERSION

logger = logging.getLogger("astro.updater")

CURRENT_VERSION = APP_VERSION
RELEASES_URL = "https://api.github.com/repos/Shunikai972/Roblox-Account-Manager/releases/latest"


_VERSION_RE = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:(?P<label>a|alpha|b|beta|rc)(?P<number>\d+))?$",
    re.IGNORECASE,
)


def _version_key(value: str) -> tuple[int, int, int, int, int] | None:
    """Return a comparison key for Astro release tags without string ordering."""

    match = _VERSION_RE.fullmatch(str(value).strip())
    if match is None:
        return None
    label = (match.group("label") or "").lower()
    stage = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "rc": 2, "": 3}[label]
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        stage,
        int(match.group("number") or 0),
    )


class UpdateChecker:
    """Checks for latest releases on GitHub."""

    @staticmethod
    def check_for_updates() -> dict[str, Any]:
        """Fetch release info from GitHub API."""

        try:
            res = requests.get(RELEASES_URL, timeout=5.0, headers={"User-Agent": "AstroAccountManager"})
            if res.status_code == 200:
                data = res.json()
                tag_name = str(data.get("tag_name") or "").lstrip("v")
                current_key = _version_key(CURRENT_VERSION)
                latest_key = _version_key(tag_name)
                has_update = bool(current_key is not None and latest_key is not None and latest_key > current_key)
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
        except Exception:
            logger.warning("Failed to check for updates", exc_info=True)
            return {
                "current_version": CURRENT_VERSION,
                "latest_version": CURRENT_VERSION,
                "update_available": False,
                "reason": "The release service could not be reached.",
            }
