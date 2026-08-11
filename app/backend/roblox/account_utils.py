"""Authenticated account operations for Roblox endpoints."""

from __future__ import annotations

import logging
from typing import Any

import requests

from app.backend.roblox.errors import RobloxServiceError

logger = logging.getLogger("astro.account_utils")


class AccountUtils:
    """Authenticated operations for Roblox user profiles."""

    @staticmethod
    def _session_post(cookie: str, url: str, json_payload: dict[str, Any] | None = None) -> requests.Response:
        session = requests.Session()
        session.headers.update({
            "Referer": "https://www.roblox.com/",
            "Origin": "https://www.roblox.com",
            "User-Agent": "AstroAccountManager/1.0",
        })
        session.cookies.set(".ROBLOSECURITY", cookie, domain=".roblox.com")

        res = session.post(url, json=json_payload)
        if res.status_code == 403 and "x-csrf-token" in res.headers:
            session.headers["x-csrf-token"] = res.headers["x-csrf-token"]
            res = session.post(url, json=json_payload)
        return res

    def change_password(self, cookie: str, current_pass: str, new_pass: str) -> bool:
        url = "https://auth.roblox.com/v2/passwords/change"
        res = self._session_post(cookie, url, {"currentPassword": current_pass, "newPassword": new_pass})
        if res.status_code == 200:
            logger.info("Password changed successfully.")
            return True
        raise RobloxServiceError(f"Failed to change password (HTTP {res.status_code}).")

    def change_email(self, cookie: str, password: str, new_email: str) -> bool:
        url = "https://accountsettings.roblox.com/v1/email"
        res = self._session_post(cookie, url, {"password": password, "emailAddress": new_email})
        if res.status_code in (200, 204):
            logger.info(f"Email change requested for {new_email}.")
            return True
        raise RobloxServiceError(f"Failed to change email address (HTTP {res.status_code}).")

    def logout_all_sessions(self, cookie: str) -> bool:
        url = "https://auth.roblox.com/v1/logout-from-all-sessions"
        res = self._session_post(cookie, url)
        if res.status_code in (200, 204):
            logger.info("Logged out from all sessions.")
            return True
        raise RobloxServiceError(f"Failed to logout from all sessions (HTTP {res.status_code}).")

    def set_display_name(self, cookie: str, user_id: int, new_display_name: str) -> bool:
        url = f"https://users.roblox.com/v1/users/{user_id}/display-names"
        res = self._session_post(cookie, url, {"newDisplayName": new_display_name})
        if res.status_code == 200:
            logger.info(f"Display name updated to {new_display_name} for user {user_id}.")
            return True
        raise RobloxServiceError(f"Failed to update display name (HTTP {res.status_code}).")

    def send_friend_request(self, cookie: str, target_user_id: int) -> bool:
        url = f"https://friends.roblox.com/v1/users/{target_user_id}/request-friendship"
        res = self._session_post(cookie, url)
        if res.status_code == 200:
            logger.info(f"Friend request sent to user {target_user_id}.")
            return True
        raise RobloxServiceError(f"Failed to send friend request (HTTP {res.status_code}).")

    def block_user(self, cookie: str, target_user_id: int) -> bool:
        url = f"https://accountsettings.roblox.com/v1/users/{target_user_id}/block"
        res = self._session_post(cookie, url)
        if res.status_code == 200:
            logger.info(f"Blocked user {target_user_id}.")
            return True
        raise RobloxServiceError(f"Failed to block user (HTTP {res.status_code}).")

    def unblock_user(self, cookie: str, target_user_id: int) -> bool:
        url = f"https://accountsettings.roblox.com/v1/users/{target_user_id}/unblock"
        res = self._session_post(cookie, url)
        if res.status_code == 200:
            logger.info(f"Unblocked user {target_user_id}.")
            return True
        raise RobloxServiceError(f"Failed to unblock user (HTTP {res.status_code}).")

    def quick_log_in(self, cookie: str, code: str) -> bool:
        url = "https://auth.roblox.com/v1/quick-login/login"
        res = self._session_post(cookie, url, {"code": code})
        if res.status_code == 200:
            logger.info("Quick Log In code accepted.")
            return True
        raise RobloxServiceError(f"Failed Quick Log In (HTTP {res.status_code}).")

    def get_blocked_users(self, cookie: str) -> list[dict[str, Any]]:
        session = requests.Session()
        session.cookies.set(".ROBLOSECURITY", cookie, domain=".roblox.com")
        url = "https://accountsettings.roblox.com/v1/users/get-blocked-users"
        try:
            res = session.get(url, headers={"User-Agent": "AstroAccountManager/1.0"})
            if res.status_code == 200:
                data = res.json()
                return data.get("blockedUsers", []) if isinstance(data, dict) else []
            return []
        except Exception as exc:
            logger.error(f"Failed to fetch blocked users: {exc}")
            return []

    def unblock_everyone(self, cookie: str) -> int:
        blocked = self.get_blocked_users(cookie)
        unblocked_count = 0
        for user in blocked:
            target_id = user.get("id")
            if target_id and self.unblock_user(cookie, target_id):
                unblocked_count += 1
        return unblocked_count

    def set_avatar(self, cookie: str, asset_ids: list[int]) -> bool:
        url = "https://avatar.roblox.com/v1/avatar/set-wearing-assets"
        res = self._session_post(cookie, url, {"assetIds": asset_ids})
        if res.status_code == 200:
            logger.info(f"Avatar updated with assets {asset_ids}.")
            return True
        raise RobloxServiceError(f"Failed to update avatar outfit (HTTP {res.status_code}).")

