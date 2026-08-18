"""Open an isolated Chromium window authenticated with one vault session."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any
from urllib.parse import urlsplit
from urllib.request import urlopen

from app.backend.core.errors import ValidationError
from app.backend.roblox.browser_login import EdgeCDPLoginService
from app.backend.roblox.errors import RobloxLaunchError


class AuthenticatedBrowserService:
    """Inject one HttpOnly Roblox cookie through local CDP, then navigate."""

    def open(self, cookie: str, url: str = "https://www.roblox.com/home") -> dict[str, Any]:
        target = str(url or "").strip()
        parsed = urlsplit(target)
        host = (parsed.hostname or "").casefold()
        if parsed.scheme != "https" or not (host == "roblox.com" or host.endswith(".roblox.com")):
            raise ValidationError("Authenticated browser URLs must use https on roblox.com.")
        if len(target) > 2048 or any(ord(character) < 32 for character in target):
            raise ValidationError("Authenticated browser URL is invalid.")
        if not isinstance(cookie, str) or not cookie.strip() or len(cookie) > 16_384:
            raise ValidationError("Stored Roblox session is invalid.")
        executable = EdgeCDPLoginService.find_edge_executable()
        if not executable:
            raise RobloxLaunchError("Microsoft Edge or Chrome is not installed.")
        profile = tempfile.mkdtemp(prefix="astro_authenticated_browser_")
        command = [
            executable,
            "--remote-debugging-port=0",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "--disable-extensions",
            "--disable-features=msEdgeSignin,EdgeIdentity,msEdgeSync",
            "about:blank",
        ]
        try:
            process = subprocess.Popen(command)
        except OSError as exc:
            shutil.rmtree(profile, ignore_errors=True)
            raise RobloxLaunchError("The isolated Roblox browser could not be opened.") from exc

        operation_id = Path(profile).name

        def configure() -> None:
            try:
                port = _wait_for_port(Path(profile), process)
                page_ws = _page_websocket(port)
                import websockets.sync.client as ws_client

                with ws_client.connect(page_ws, open_timeout=5.0, close_timeout=2.0) as client:
                    _cdp(client, 1, "Network.enable")
                    result = _cdp(client, 2, "Network.setCookie", {
                        "name": ".ROBLOSECURITY",
                        "value": cookie,
                        "domain": ".roblox.com",
                        "path": "/",
                        "secure": True,
                        "httpOnly": True,
                        "sameSite": "None",
                    })
                    if not bool(result.get("result", {}).get("success")):
                        raise RobloxLaunchError("The stored Roblox session could not be attached to the browser.")
                    _cdp(client, 3, "Page.navigate", {"url": target})
                process.wait()
            except Exception:
                try:
                    process.terminate()
                except OSError:
                    pass
            finally:
                shutil.rmtree(profile, ignore_errors=True)

        threading.Thread(target=configure, daemon=True, name="astro-authenticated-browser").start()
        return {"opened": True, "operation_id": operation_id, "url": target}


def _wait_for_port(profile: Path, process: subprocess.Popen[Any]) -> int:
    active = profile / "DevToolsActivePort"
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline and process.poll() is None:
        try:
            first = active.read_text(encoding="utf-8").splitlines()[0]
            port = int(first)
            if 1 <= port <= 65535:
                return port
        except (OSError, IndexError, ValueError):
            time.sleep(0.2)
    raise RobloxLaunchError("The isolated browser debugging endpoint did not start.")


def _page_websocket(port: int) -> str:
    with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3.0) as response:
        payload = json.loads(response.read().decode("utf-8"))

    pages = [
        item
        for item in payload if isinstance(payload, list)
        if isinstance(item, dict) and item.get("type") == "page"
    ]
    # Edge can create sync/extension pages even for a fresh temporary profile.
    # The window launched by this service is the explicit about:blank target;
    # never inject the Roblox session into an arbitrary first CDP page.
    pages.sort(key=lambda item: 0 if item.get("url") == "about:blank" else 1)
    for item in pages:
        ws = item.get("webSocketDebuggerUrl") if isinstance(item, dict) else None
        parsed = urlsplit(str(ws or ""))
        if parsed.scheme in {"ws", "wss"} and parsed.hostname in {"127.0.0.1", "localhost"}:
            return str(ws)
    raise RobloxLaunchError("The isolated browser page endpoint is unavailable.")


def _cdp(client: Any, identifier: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    request: dict[str, Any] = {"id": identifier, "method": method}
    if params:
        request["params"] = params
    client.send(json.dumps(request, ensure_ascii=False))
    reply = json.loads(client.recv(timeout=5.0) or "{}")
    if not isinstance(reply, dict) or reply.get("error"):
        raise RobloxLaunchError("The isolated browser rejected its local configuration.")
    return reply


__all__ = ["AuthenticatedBrowserService"]
