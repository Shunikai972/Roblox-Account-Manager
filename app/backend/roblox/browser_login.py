"""Automated Roblox Browser Login Cookie Interceptor using pywebview."""

from __future__ import annotations

import logging
import os
from pathlib import Path
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

    def start_manual_login(
        self,
        on_cookie_captured: Callable[[str], Any],
        on_finished: Callable[[bool], Any] | None = None,
    ) -> bool:
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
                        timeout=15.0,
                    )
                    if res.status_code == 403 and "x-csrf-token" in res.headers:
                        session.headers["x-csrf-token"] = res.headers["x-csrf-token"]
                        res = session.post(
                            "https://auth.roblox.com/v1/authentication-ticket/redeem",
                            json={"authenticationTicket": ticket},
                            timeout=15.0,
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
                except Exception:
                    logger.warning("Browser authentication ticket could not be redeemed", exc_info=True)
                finally:
                    try:
                        session.close()
                    except Exception:
                        pass
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
                        xhr.setRequestHeader('Content-Type', 'application/json');
                        xhr.send('{}');
                        if (xhr.status === 403) {
                            var csrf = xhr.getResponseHeader('x-csrf-token');
                            if (csrf) {
                                var xhr2 = new XMLHttpRequest();
                                xhr2.open('POST', 'https://auth.roblox.com/v1/authentication-ticket', false);
                                xhr2.setRequestHeader('Referer', 'https://www.roblox.com/');
                                xhr2.setRequestHeader('x-csrf-token', csrf);
                                xhr2.setRequestHeader('Content-Type', 'application/json');
                                xhr2.send('{}');
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
                                logger.info("Browser reached an authenticated Roblox page; attempting ticket extraction")
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
                if on_finished is not None:
                    try:
                        on_finished(bool(captured_cookie))
                    except Exception:
                        logger.warning("Browser login completion callback failed", exc_info=True)

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
    """Uses a temporary Edge/Chrome profile and CDP for HttpOnly cookie capture."""

    @staticmethod
    def find_edge_executable() -> str | None:
        import shutil

        edge_paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        ]
        for p in edge_paths:
            if p and os.path.isfile(p):
                return p
        return shutil.which("msedge") or shutil.which("chrome")

    @staticmethod
    def build_launch_command(
        executable: str,
        user_data_directory: str,
        *,
        solver_extension_directory: str | None = None,
    ) -> list[str]:
        """Build the isolated browser command, optionally loading a solver.

        RAM 3.7.2 called the NopeCHA API against FunCaptcha's then-current
        DOM.  That DOM integration is obsolete and brittle.  Astro supports
        the equivalent current Chromium extension workflow: the user supplies
        an unpacked solver extension (and configures its own key inside that
        isolated profile), while Astro validates the directory and never
        reads, stores or logs the solver credential.
        """

        command = [
            executable,
            "--remote-debugging-port=0",
            f"--user-data-dir={user_data_directory}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if solver_extension_directory:
            extension = Path(solver_extension_directory).expanduser()
            try:
                extension = extension.resolve(strict=True)
            except (OSError, RuntimeError):
                extension = Path()
            if (
                extension.is_absolute()
                and extension.is_dir()
                and (extension / "manifest.json").is_file()
                and len(str(extension)) <= 2048
            ):
                command.extend(
                    [
                        f"--disable-extensions-except={extension}",
                        f"--load-extension={extension}",
                    ]
                )
        command.append("https://www.roblox.com/login")
        return command

    def start_login(
        self,
        on_cookie_captured: Callable[[str], Any],
        on_finished: Callable[[bool], Any] | None = None,
        *,
        prefill_username: str | None = None,
        prefill_password: str | None = None,
        auto_submit: bool = False,
    ) -> bool:
        import json
        import subprocess
        import tempfile
        import urllib.request
        import shutil
        from urllib.parse import urlsplit

        exe = self.find_edge_executable()
        if not exe:
            logger.warning("Neither Edge nor Chrome executable found for CDP login.")
            return False

        temp_user_data = tempfile.mkdtemp(prefix="astro_edge_login_")
        cmd = self.build_launch_command(
            exe,
            temp_user_data,
            solver_extension_directory=os.environ.get("ASTRO_CAPTCHA_SOLVER_EXTENSION"),
        )

        logger.info("Launching the dedicated Edge/Chrome sign-in profile")
        try:
            proc = subprocess.Popen(cmd)
        except OSError:
            shutil.rmtree(temp_user_data, ignore_errors=True)
            return False

        def _poll_cdp() -> None:
            import websockets.sync.client as ws_client

            start_time = time.time()
            timeout = 600  # 10 minutes
            captured: str | None = None

            ws_url = None
            port = None
            active_port_file = os.path.join(temp_user_data, "DevToolsActivePort")
            for _ in range(40):
                time.sleep(0.5)
                try:
                    if port is None and os.path.isfile(active_port_file):
                        with open(active_port_file, encoding="utf-8") as active_port:
                            first_line = active_port.readline().strip()
                        if first_line.isdigit() and 1 <= int(first_line) <= 65535:
                            port = int(first_line)
                    if port is None:
                        continue
                    req = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2)
                    data = json.loads(req.read().decode("utf-8"))
                    ws_url = data.get("webSocketDebuggerUrl")
                    parsed_ws = urlsplit(str(ws_url or ""))
                    if ws_url and parsed_ws.scheme in ("ws", "wss") and parsed_ws.hostname in ("127.0.0.1", "localhost"):
                        break
                    ws_url = None
                except Exception:
                    pass

            if not ws_url:
                logger.error("Could not obtain CDP WebSocket URL from Edge.")
                try:
                    proc.terminate()
                except Exception:
                    pass
                shutil.rmtree(temp_user_data, ignore_errors=True)
                return

            credentials_filled = False

            def _fill_login_form() -> bool:
                """Fill the isolated page without placing secrets in argv or logs."""

                if not port or not prefill_username or not prefill_password:
                    return False
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/json/list", timeout=2
                    ) as response:
                        targets = json.loads(response.read().decode("utf-8"))
                    page_url = next(
                        (
                            item.get("webSocketDebuggerUrl")
                            for item in targets
                            if item.get("type") == "page"
                            and "roblox.com" in str(item.get("url") or "").casefold()
                            and item.get("webSocketDebuggerUrl")
                        ),
                        None,
                    )
                    if not page_url:
                        return False
                    credentials = json.dumps(
                        {"username": prefill_username, "password": prefill_password},
                        ensure_ascii=False,
                    )
                    expression = f"""
                    (function(credentials, autoSubmit) {{
                      const find = (selectors) => selectors.map((s) => document.querySelector(s)).find(Boolean);
                      const username = find(['#login-username', 'input[name="username"]', 'input[autocomplete="username"]']);
                      const password = find(['#login-password', 'input[name="password"]', 'input[type="password"]']);
                      if (!username || !password) return {{filled: false}};
                      const write = (element, value) => {{
                        const descriptor = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), 'value');
                        if (descriptor && descriptor.set) descriptor.set.call(element, value);
                        else element.value = value;
                        element.dispatchEvent(new Event('input', {{bubbles: true}}));
                        element.dispatchEvent(new Event('change', {{bubbles: true}}));
                      }};
                      write(username, credentials.username);
                      write(password, credentials.password);
                      if (autoSubmit) window.setTimeout(() => {{
                        const submit = find(['#login-button', 'button[type="submit"]', 'button[data-testid="login-button"]']);
                        if (submit && !submit.disabled) submit.click();
                      }}, 250);
                      return {{filled: true, submitted: Boolean(autoSubmit)}};
                    }})({credentials}, {str(bool(auto_submit)).lower()})
                    """
                    with ws_client.connect(str(page_url)) as page_client:
                        page_client.send(
                            json.dumps(
                                {
                                    "id": 41,
                                    "method": "Runtime.evaluate",
                                    "params": {"expression": expression, "returnByValue": True},
                                }
                            )
                        )
                        raw_result = page_client.recv(timeout=2.0)
                    result = json.loads(raw_result or "{}")
                    value = result.get("result", {}).get("result", {}).get("value", {})
                    return bool(value.get("filled")) if isinstance(value, dict) else False
                except Exception:
                    # Roblox can revise its form; manual entry remains available.
                    return False

            try:
                with ws_client.connect(ws_url) as client:
                    while time.time() - start_time < timeout:
                        time.sleep(1.0)
                        if proc.poll() is not None:
                            logger.info("Edge login window closed by user.")
                            break

                        if not credentials_filled and prefill_username and prefill_password:
                            credentials_filled = _fill_login_form()
                            if credentials_filled:
                                logger.info(
                                    "Saved credentials were supplied to the isolated Roblox login page"
                                )

                        client.send(json.dumps({"id": 2, "method": "Storage.getCookies"}))
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
            except Exception:
                logger.warning("CDP cookie polling stopped", exc_info=True)

            try:
                proc.terminate()
                proc.wait(timeout=3.0)
            except Exception:
                pass
            shutil.rmtree(temp_user_data, ignore_errors=True)

            if captured:
                try:
                    on_cookie_captured(captured)
                except Exception:
                    logger.exception("Captured CDP session could not be handled")
            if on_finished is not None:
                try:
                    on_finished(bool(captured))
                except Exception:
                    logger.warning("CDP login completion callback failed", exc_info=True)

        t = threading.Thread(target=_poll_cdp, daemon=True, name="edge_cdp_poll")
        t.start()
        return True
