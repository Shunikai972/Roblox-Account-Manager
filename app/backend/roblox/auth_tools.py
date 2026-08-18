"""Authenticated account tools: ticket generation, rbx-player URIs, and session exports."""

from __future__ import annotations

import logging
import ipaddress
import re
import time
from typing import Any
from urllib.parse import quote

import requests

from app.backend.roblox.client import RobloxClient
from app.backend.roblox.errors import RobloxServiceError

logger = logging.getLogger("astro.auth_tools")
_JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SHARE_CODE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_INVITE_CODE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


def read_private_server_invite(payload: Any) -> dict[str, Any]:
    """Read Roblox's share-link response into a place id and private server code.

    Kept as a module function so the parsing can be tested without a network
    call: every failure mode below has been seen from Roblox at least once.
    """

    if not isinstance(payload, dict):
        raise RobloxServiceError("Roblox returned an unreadable share link response.")
    invite = payload.get("privateServerInviteData")
    if not isinstance(invite, dict):
        raise RobloxServiceError("That share link is not an invite to a private server.")
    status = str(invite.get("status") or "").strip()
    if status and status.casefold() != "valid":
        raise RobloxServiceError(f"Roblox reports this private server link as {status.lower()}.")
    try:
        place_id = int(invite.get("placeId"))
    except (TypeError, ValueError) as exc:
        raise RobloxServiceError("Roblox did not say which place that share link belongs to.") from exc
    code = invite.get("linkCode") or invite.get("inviteCode") or invite.get("code")
    if place_id <= 0 or not isinstance(code, str) or not _INVITE_CODE.fullmatch(code):
        raise RobloxServiceError("Roblox did not return a usable private server code.")
    return {"place_id": place_id, "link_code": code, "status": status or "Valid"}


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

    def probe_server_instance(self, cookie: str, place_id: int, job_id: str) -> dict[str, Any]:
        """Resolve one public JobId to the machine address RAM used for region UI."""

        if not isinstance(cookie, str) or not cookie.strip():
            raise RobloxServiceError("A Roblox session is required for server-region probing.")
        if isinstance(place_id, bool) or not isinstance(place_id, int) or place_id <= 0:
            raise RobloxServiceError("PlaceId must be a positive integer.")
        if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
            raise RobloxServiceError("JobId is invalid.")
        session = requests.Session()
        session.headers.update(
            {
                "Referer": "https://www.roblox.com/",
                "Origin": "https://www.roblox.com",
                "User-Agent": "AstroAccountManager/4.0",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        session.cookies.set(".ROBLOSECURITY", cookie, domain=".roblox.com")
        endpoint = "https://gamejoin.roblox.com/v1/join-game-instance"
        body = {"gameId": job_id, "placeId": place_id}
        try:
            response = session.post(endpoint, json=body, timeout=15.0)
            if response.status_code == 403 and response.headers.get("x-csrf-token"):
                session.headers["x-csrf-token"] = response.headers["x-csrf-token"]
                response = session.post(endpoint, json=body, timeout=15.0)
            if response.status_code != 200:
                raise RobloxServiceError(
                    f"Roblox server-region probe returned HTTP {response.status_code}."
                )
            payload = response.json()
        except RobloxServiceError:
            raise
        except (requests.RequestException, TypeError, ValueError) as exc:
            raise RobloxServiceError("Roblox did not return a usable server join response.") from exc
        finally:
            session.close()
        if not isinstance(payload, dict):
            raise RobloxServiceError("Roblox returned an invalid server join response.")
        join_script = payload.get("joinScript")
        if not isinstance(join_script, dict):
            raise RobloxServiceError("Roblox did not expose this server's machine address.")
        address = join_script.get("MachineAddress")
        port = join_script.get("ServerPort")
        try:
            normalized_address = str(ipaddress.ip_address(str(address or "").strip()))
        except ValueError as exc:
            raise RobloxServiceError("Roblox did not expose this server's machine address.") from exc
        normalized_port = int(port) if isinstance(port, (int, str)) and str(port).isdigit() else None
        if normalized_port is not None and not 1 <= normalized_port <= 65535:
            normalized_port = None
        return {"address": normalized_address, "port": normalized_port}

    def resolve_share_link(self, cookie: str, share_code: str) -> dict[str, Any]:
        """Expand a roblox.com/share invite code into a place and private server code.

        A share link holds no place id, so the only honest way to open one is to
        ask Roblox to resolve it while signed in as the account that will join.
        """

        if not isinstance(cookie, str) or not cookie.strip():
            raise RobloxServiceError("A Roblox session is required to open a share link.")
        if not isinstance(share_code, str) or not _SHARE_CODE.fullmatch(share_code):
            raise RobloxServiceError("That share link code is invalid.")
        session = requests.Session()
        session.headers.update(
            {
                "Referer": "https://www.roblox.com/",
                "Origin": "https://www.roblox.com",
                "User-Agent": "AstroAccountManager/4.0",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        session.cookies.set(".ROBLOSECURITY", cookie, domain=".roblox.com")
        endpoint = "https://apis.roblox.com/sharelinks/v1/resolve-link"
        body = {"linkId": share_code, "linkType": "Server"}
        try:
            response = session.post(endpoint, json=body, timeout=15.0)
            if response.status_code == 403 and response.headers.get("x-csrf-token"):
                session.headers["x-csrf-token"] = response.headers["x-csrf-token"]
                response = session.post(endpoint, json=body, timeout=15.0)
            if response.status_code == 401:
                raise RobloxServiceError("This account's Roblox session expired, so the share link could not be opened.")
            if response.status_code != 200:
                raise RobloxServiceError(f"Roblox refused to resolve that share link (HTTP {response.status_code}).")
            payload = response.json()
        except RobloxServiceError:
            raise
        except (requests.RequestException, TypeError, ValueError) as exc:
            raise RobloxServiceError("Could not reach Roblox to resolve that share link.") from exc
        finally:
            session.close()
        return read_private_server_invite(payload)

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
