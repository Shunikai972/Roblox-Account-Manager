"""Automated Roblox Browser Login Cookie Interceptor using pywebview."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

import webview

logger = logging.getLogger("astro.browser_login")


class BrowserLoginService:
    """Manages opening a dedicated Roblox login browser window and intercepting .ROBLOSECURITY cookies."""

    def __init__(self) -> None:
        self._active_window: webview.Window | None = None
        self._polling_thread: threading.Thread | None = None
        self._is_polling = False

    def start_manual_login(self, on_cookie_captured: Callable[[str], Any]) -> bool:
        """Opens a browser window for Roblox login and polls for the .ROBLOSECURITY cookie."""
        if self._is_polling:
            logger.warning("Browser login already in progress.")
            return False

        try:
            window = webview.create_window(
                title="Roblox Login — Astro Account Manager",
                url="https://www.roblox.com/login",
                width=900,
                height=700,
                resizable=True,
            )
            self._active_window = window
            self._is_polling = True

            def _redeem_auth_ticket(ticket: str) -> str | None:
                """Exchanges a Roblox auth ticket for a fresh .ROBLOSECURITY cookie."""
                try:
                    import requests
                    session = requests.Session()
                    session.headers.update({
                        "Referer": "https://www.roblox.com/",
                        "Origin": "https://www.roblox.com",
                        "User-Agent": "AstroAccountManager/1.0",
                        "Content-Type": "application/json",
                    })
                    res = session.post(
                        "https://auth.roblox.com/v1/authentication-ticket/redeem",
                        json={"authenticationTicket": ticket},
                    )
                    if res.status_code == 403 and "x-csrf-token" in res.headers:
                        session.headers["x-csrf-token"] = res.headers["x-csrf-token"]
                        res = session.post(
                            "https://auth.roblox.com/v1/authentication-ticket/redeem",
                            json={"authenticationTicket": ticket},
                        )
                    for cookie in session.cookies:
                        if cookie.name == ".ROBLOSECURITY" and cookie.value:
                            return cookie.value
                    # Check Set-Cookie headers directly
                    set_cookie = res.headers.get("Set-Cookie") or ""
                    if ".ROBLOSECURITY=" in set_cookie:
                        parts = set_cookie.split(".ROBLOSECURITY=", 1)
                        val = parts[1].split(";")[0].strip()
                        if val and len(val) > 20:
                            return val
                except Exception as exc:
                    logger.error(f"Error redeeming auth ticket: {exc}")
                return None

            def _poll_cookies() -> None:
                logger.info("Polling browser window for .ROBLOSECURITY cookie...")
                captured_cookie: str | None = None
                start_time = time.time()
                timeout = 600  # 10 minutes timeout

                js_ticket_script = r"""
                (function() {
                    try {
                        var xhr = new XMLHttpRequest();
                        xhr.open('POST', 'https://auth.roblox.com/v1/authentication-ticket', false);
                        xhr.setRequestHeader('Referer', 'https://www.roblox.com/');
                        xhr.send(null);
                        if (xhr.status === 403) {
                            var csrf = xhr.getResponseHeader('x-csrf-token');
                            if (csrf) {
                                var xhr2 = new XMLHttpRequest();
                                xhr2.open('POST', 'https://auth.roblox.com/v1/authentication-ticket', false);
                                xhr2.setRequestHeader('Referer', 'https://www.roblox.com/');
                                xhr2.setRequestHeader('x-csrf-token', csrf);
                                xhr2.send(null);
                                return xhr2.getResponseHeader('rbx-authentication-ticket') || '';
                            }
                        }
                        return xhr.getResponseHeader('rbx-authentication-ticket') || '';
                    } catch(e) {
                        return '';
                    }
                })()
                """

                while self._is_polling and (time.time() - start_time < timeout):
                    time.sleep(1.0)
                    try:
                        if not window:
                            break

                        # Method 1: Evaluate document.cookie directly in the webview context
                        try:
                            cookie_str = window.evaluate_js("document.cookie || ''")
                            if cookie_str and ".ROBLOSECURITY=" in str(cookie_str):
                                parts = str(cookie_str).split(".ROBLOSECURITY=", 1)
                                val_part = parts[1].split(";")[0].strip()
                                if val_part and len(val_part) > 20:
                                    logger.info("Captured .ROBLOSECURITY cookie via JS document.cookie!")
                                    captured_cookie = val_part
                                    break
                        except Exception as js_cookie_exc:
                            logger.debug(f"JS document.cookie error: {js_cookie_exc}")

                        # Method 2: Check pywebview window cookies
                        try:
                            cookies = window.get_cookies()
                            for c in cookies:
                                c_key = (
                                    getattr(c, "key", None)
                                    or getattr(c, "name", None)
                                    or (c.get("key") if isinstance(c, dict) else None)
                                    or (c.get("name") if isinstance(c, dict) else None)
                                )
                                c_val = (
                                    getattr(c, "value", None)
                                    or (c.get("value") if isinstance(c, dict) else None)
                                )
                                if c_key == ".ROBLOSECURITY" and c_val:
                                    logger.info("Captured .ROBLOSECURITY cookie directly from browser cookies!")
                                    captured_cookie = c_val
                                    break

                                c_str = str(c)
                                if ".ROBLOSECURITY=" in c_str:
                                    parts = c_str.split(".ROBLOSECURITY=", 1)
                                    val_part = parts[1].split(";")[0].strip()
                                    if val_part and len(val_part) > 20:
                                        logger.info("Captured .ROBLOSECURITY cookie from str(c)!")
                                        captured_cookie = val_part
                                        break
                        except Exception as cookie_exc:
                            logger.debug(f"Cookie check error: {cookie_exc}")

                        if captured_cookie:
                            break

                        # Method 3: Check current URL & attempt JS Auth Ticket extraction on logged-in pages
                        try:
                            current_url = str(window.get_current_url() or "").lower()
                            if any(p in current_url for p in ("roblox.com/home", "roblox.com/my/", "roblox.com/landing", "roblox.com/discover", "roblox.com/users")):
                                logger.info(f"User reached logged-in URL ({current_url}). Attempting JS ticket extraction...")
                                ticket = window.evaluate_js(js_ticket_script)
                                if ticket and isinstance(ticket, str) and len(ticket) > 10:
                                    logger.info(f"Retrieved Roblox auth ticket from browser session!")
                                    redeemed = _redeem_auth_ticket(ticket)
                                    if redeemed:
                                        logger.info("Successfully redeemed auth ticket for .ROBLOSECURITY cookie!")
                                        captured_cookie = redeemed
                                        break
                        except Exception as js_exc:
                            logger.debug(f"JS evaluation error: {js_exc}")

                    except Exception as exc:
                        logger.debug(f"Cookie polling check error: {exc}")
                        break

                    if captured_cookie:
                        break

                self._is_polling = False
                if window:
                    try:
                        window.destroy()
                    except Exception:
                        pass
                self._active_window = None

                if captured_cookie:
                    try:
                        logger.info("Calling on_cookie_captured callback...")
                        on_cookie_captured(captured_cookie)
                    except Exception as exc:
                        logger.error(f"Error handling captured cookie: {exc}")
                else:
                    logger.warning("Browser login closed or timed out without capturing cookie.")

            self._polling_thread = threading.Thread(target=_poll_cookies, daemon=True, name="browser_login_poll")
            self._polling_thread.start()
            return True
        except Exception as exc:
            logger.error(f"Failed to launch manual login browser window: {exc}")
            self._is_polling = False
            return False

    def cancel_login(self) -> None:
        """Cancels manual browser login and closes the window."""
        self._is_polling = False
        if self._active_window:
            try:
                self._active_window.destroy()
            except Exception:
                pass
            self._active_window = None


class EdgeCDPLoginService:
    """Uses native Windows Edge browser via Chrome DevTools Protocol for 100% cookie capture."""

    @staticmethod
    def find_edge_executable() -> str | None:
        import os
        import shutil

        edge_paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            os.path.expandencode(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe")
            if hasattr(os, "path") and hasattr(os.path, "expandencode")
            else "",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        ]
        for p in edge_paths:
            if p and os.path.isfile(p):
                return p
        return shutil.which("msedge") or shutil.which("chrome")

    def start_login(self, on_cookie_captured: Callable[[str], Any]) -> bool:
        import json
        import os
        import subprocess
        import tempfile
        import urllib.request

        exe = self.find_edge_executable()
        if not exe:
            logger.warning("Neither Edge nor Chrome executable found for CDP login.")
            return False

        temp_user_data = tempfile.mkdtemp(prefix="astro_edge_login_")
        port = 9222

        cmd = [
            exe,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={temp_user_data}",
            "--no-first-run",
            "--no-default-browser-check",
            "https://www.roblox.com/login",
        ]

        logger.info(f"Launching Edge CDP login window: {exe}")
        proc = subprocess.Popen(cmd)

        def _poll_cdp() -> None:
            import websockets.sync.client as ws_client

            start_time = time.time()
            timeout = 600  # 10 minutes
            captured: str | None = None

            ws_url = None
            for _ in range(20):
                time.sleep(0.5)
                try:
                    req = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2)
                    data = json.loads(req.read().decode("utf-8"))
                    ws_url = data.get("webSocketDebuggerUrl")
                    if ws_url:
                        break
                except Exception:
                    pass

            if not ws_url:
                logger.error("Could not obtain CDP WebSocket URL from Edge.")
                try:
                    proc.terminate()
                except Exception:
                    pass
                return

            try:
                with ws_client.connect(ws_url) as client:
                    client.send(json.dumps({"id": 1, "method": "Network.enable"}))
                    while time.time() - start_time < timeout:
                        time.sleep(1.0)
                        if proc.poll() is not None:
                            logger.info("Edge login window closed by user.")
                            break

                        client.send(json.dumps({"id": 2, "method": "Network.getAllCookies"}))
                        res_raw = client.recv(timeout=2.0)
                        if not res_raw:
                            continue
                        res = json.loads(res_raw)
                        if res.get("id") == 2:
                            cookies = res.get("result", {}).get("cookies", [])
                            for c in cookies:
                                if c.get("name") == ".ROBLOSECURITY" and c.get("value"):
                                    logger.info("Captured .ROBLOSECURITY cookie via Edge CDP Network.getAllCookies!")
                                    captured = c["value"]
                                    break
                        if captured:
                            break
            except Exception as exc:
                logger.error(f"CDP polling error: {exc}")

            try:
                proc.terminate()
                proc.wait(timeout=3.0)
            except Exception:
                pass

            if captured:
                try:
                    on_cookie_captured(captured)
                except Exception as exc:
                    logger.error(f"Error handling CDP captured cookie: {exc}")

        t = threading.Thread(target=_poll_cdp, daemon=True, name="edge_cdp_poll")
        t.start()
        return True

