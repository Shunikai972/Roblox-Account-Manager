"""Authenticated account operations for Roblox endpoints."""

from __future__ import annotations

import logging
import re
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

        try:
            res = session.post(url, json=json_payload, timeout=15.0)
            if res.status_code == 403 and "x-csrf-token" in res.headers:
                session.headers["x-csrf-token"] = res.headers["x-csrf-token"]
                res = session.post(url, json=json_payload, timeout=15.0)
            return res
        finally:
            session.close()

    @staticmethod
    def _session_post_form(cookie: str, url: str, form_payload: dict[str, str]) -> requests.Response:
        session = requests.Session()
        session.headers.update({
            "Referer": "https://www.roblox.com/",
            "Origin": "https://www.roblox.com",
            "User-Agent": "AstroAccountManager/4",
        })
        session.cookies.set(".ROBLOSECURITY", cookie, domain=".roblox.com")
        try:
            res = session.post(url, data=form_payload, timeout=15.0)
            if res.status_code == 403 and "x-csrf-token" in res.headers:
                session.headers["x-csrf-token"] = res.headers["x-csrf-token"]
                res = session.post(url, data=form_payload, timeout=15.0)
            return res
        finally:
            session.close()

    @staticmethod
    def _session_patch(cookie: str, url: str, json_payload: dict[str, Any]) -> requests.Response:
        session = requests.Session()
        session.headers.update({
            "Referer": "https://www.roblox.com/",
            "Origin": "https://www.roblox.com",
            "User-Agent": "AstroAccountManager/4",
        })
        session.cookies.set(".ROBLOSECURITY", cookie, domain=".roblox.com")
        try:
            res = session.patch(url, json=json_payload, timeout=15.0)
            if res.status_code == 403 and "x-csrf-token" in res.headers:
                session.headers["x-csrf-token"] = res.headers["x-csrf-token"]
                res = session.patch(url, json=json_payload, timeout=15.0)
            return res
        finally:
            session.close()

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
            logger.info("Email change requested.")
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
        res = self._session_patch(cookie, url, {"newDisplayName": new_display_name})
        if res.status_code == 200:
            logger.info("Display name updated.")
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
        if not isinstance(code, str) or not re.fullmatch(r"\d{6}", code.strip()):
            raise RobloxServiceError("Quick Log In code must contain exactly six digits.")
        url = "https://auth.roblox.com/v1/quick-login/login"
        res = self._session_post(cookie, url, {"code": code.strip()})
        if res.status_code == 200:
            logger.info("Quick Log In code accepted.")
            return True
        raise RobloxServiceError(f"Failed Quick Log In (HTTP {res.status_code}).")

    def get_blocked_users(self, cookie: str) -> list[dict[str, Any]]:
        session = requests.Session()
        session.cookies.set(".ROBLOSECURITY", cookie, domain=".roblox.com")
        url = "https://accountsettings.roblox.com/v1/users/get-blocked-users"
        try:
            res = session.get(url, headers={"User-Agent": "AstroAccountManager/4"}, timeout=15.0)
            if res.status_code == 200:
                data = res.json()
                return data.get("blockedUsers", []) if isinstance(data, dict) else []
            return []
        except requests.RequestException as exc:
            raise RobloxServiceError("Could not fetch the blocked-user list from Roblox.") from exc

    def unblock_everyone(self, cookie: str) -> int:
        blocked = self.get_blocked_users(cookie)
        unblocked_count = 0
        for user in blocked:
            target_id = user.get("id")
            if target_id and self.unblock_user(cookie, target_id):
                unblocked_count += 1
        return unblocked_count

    def set_avatar(self, cookie: str, asset_ids: list[int]) -> bool:
        if (
            not isinstance(asset_ids, list)
            or not 1 <= len(asset_ids) <= 100
            or any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in asset_ids)
        ):
            raise RobloxServiceError("Avatar asset IDs must be a list of positive integers.")
        url = "https://avatar.roblox.com/v1/avatar/set-wearing-assets"
        res = self._session_post(cookie, url, {"assetIds": asset_ids})
        if res.status_code == 200:
            logger.info("Avatar outfit updated.")
            return True
        raise RobloxServiceError(f"Failed to update avatar outfit (HTTP {res.status_code}).")

    def list_outfits(self, user_id: int) -> list[dict[str, Any]]:
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
            raise RobloxServiceError("UserId must be a positive integer.")
        session = requests.Session()
        try:
            res = session.get(
                f"https://avatar.roblox.com/v1/users/{user_id}/outfits",
                params={"page": 1, "itemsPerPage": 50},
                headers={"User-Agent": "AstroAccountManager/4"},
                timeout=15.0,
            )
            if res.status_code != 200:
                raise RobloxServiceError(f"Failed to list avatar outfits (HTTP {res.status_code}).")
            payload = res.json()
            values = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(values, list):
                raise RobloxServiceError("Roblox returned an invalid outfit list.")
            return [
                {"id": int(item["id"]), "name": str(item.get("name") or "Outfit")[:120]}
                for item in values[:50]
                if isinstance(item, dict) and isinstance(item.get("id"), int) and item["id"] > 0
            ]
        except requests.RequestException as exc:
            raise RobloxServiceError("Could not fetch Roblox avatar outfits.") from exc
        finally:
            session.close()

    def get_outfit_details(self, outfit_id: int) -> dict[str, Any]:
        if isinstance(outfit_id, bool) or not isinstance(outfit_id, int) or outfit_id <= 0:
            raise RobloxServiceError("Outfit ID must be a positive integer.")
        session = requests.Session()
        try:
            res = session.get(
                f"https://avatar.roblox.com/v1/outfits/{outfit_id}/details",
                headers={"User-Agent": "AstroAccountManager/4"}, timeout=15.0
            )
            if res.status_code != 200:
                raise RobloxServiceError(f"Failed to read outfit details (HTTP {res.status_code}).")
            payload = res.json()
            if not isinstance(payload, dict):
                raise RobloxServiceError("Roblox returned invalid outfit details.")
            assets = payload.get("assets")
            asset_ids = [
                int(item["id"]) for item in assets or []
                if isinstance(item, dict) and isinstance(item.get("id"), int) and item["id"] > 0
            ]
            if not asset_ids:
                raise RobloxServiceError("The selected outfit has no wearable assets.")
            return {"id": outfit_id, "name": str(payload.get("name") or "Outfit")[:120], "asset_ids": asset_ids[:100]}
        except requests.RequestException as exc:
            raise RobloxServiceError("Could not fetch Roblox outfit details.") from exc
        finally:
            session.close()

    def wear_outfit(self, cookie: str, outfit_id: int) -> dict[str, Any]:
        details = self.get_outfit_details(outfit_id)
        self.set_avatar(cookie, details["asset_ids"])
        return details

    def join_group(self, cookie: str, group_id: int) -> bool:
        if isinstance(group_id, bool) or not isinstance(group_id, int) or group_id <= 0:
            raise RobloxServiceError("Group ID must be a positive integer.")
        res = self._session_post(cookie, f"https://groups.roblox.com/v1/groups/{group_id}/users")
        if res.status_code in (200, 201):
            return True
        raise RobloxServiceError(f"Failed to join Roblox group (HTTP {res.status_code}).")

    def set_follow_privacy(self, cookie: str, privacy: str) -> bool:
        choices = {
            "all": "All",
            "followers": "Followers",
            "following": "Following",
            "friends": "Friends",
            "noone": "NoOne",
            "no_one": "NoOne",
        }
        normalized = choices.get(str(privacy).strip().lower())
        if normalized is None:
            raise RobloxServiceError("Follow privacy must be All, Followers, Following, Friends, or NoOne.")
        res = self._session_post_form(
            cookie,
            "https://www.roblox.com/account/settings/follow-me-privacy",
            {"FollowMePrivacy": normalized},
        )
        if res.status_code == 200:
            logger.info("Follow privacy updated.")
            return True
        raise RobloxServiceError(f"Failed to update follow privacy (HTTP {res.status_code}).")

    def unlock_parental_pin(self, cookie: str, pin: str) -> bool:
        if not isinstance(pin, str) or not re.fullmatch(r"\d{4}", pin.strip()):
            raise RobloxServiceError("Account PIN must contain exactly four digits.")
        res = self._session_post_form(
            cookie,
            "https://auth.roblox.com/v1/account/pin/unlock",
            {"pin": pin.strip()},
        )
        if res.status_code == 200:
            logger.info("Account PIN unlock requested.")
            return True
        if res.status_code in (404, 410):
            raise RobloxServiceError(
                "Roblox retired the parental Account PIN system; this historical unlock endpoint is no longer available."
            )
        raise RobloxServiceError(f"Failed to unlock the account PIN (HTTP {res.status_code}).")
