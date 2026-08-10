"""Nexus WebSocket Server implementation using websockets and asyncio."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import websockets
from websockets.asyncio.server import ServerConnection, serve

from app.backend.nexus.controlled_account import ControlledAccount

logger = logging.getLogger("astro.nexus")


class NexusServer:
    """Async WebSocket server providing Nexus Account Control for Roblox clients."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5242,
        on_auto_relaunch_trigger: Callable[[str], None] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.on_auto_relaunch_trigger = on_auto_relaunch_trigger
        self.on_log_callback: Callable[[str, str], None] | None = None
        self.is_running = False
        self._server = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = None
        self._connections: dict[str, WebSocketServerProtocol] = {}
        self.accounts: dict[str, ControlledAccount] = {}

    def start(self) -> None:
        """Start the Nexus WebSocket server in a background event loop thread."""
        if self.is_running:
            return

        import threading

        self.is_running = True
        ready_event = threading.Event()

        def _run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            async def _main():
                self._server = await serve(self._handle_connection, self.host, self.port)
                logger.info(f"Nexus WebSocket server started on ws://{self.host}:{self.port}/Nexus")
                ready_event.set()
                await self._server.wait_closed()

            try:
                self._loop.run_until_complete(_main())
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.error(f"Nexus server error: {exc}")
                ready_event.set()

        self._thread = threading.Thread(target=_run_loop, daemon=True, name="nexus_server")
        self._thread.start()
        ready_event.wait(timeout=5.0)

    def stop(self) -> None:
        """Stop the Nexus WebSocket server and disconnect all clients."""
        if not self.is_running:
            return

        self.is_running = False
        if self._loop and self._server:
            def _close():
                self._server.close()
                for conn in list(self._connections.values()):
                    asyncio.create_task(conn.close())

            self._loop.call_soon_threadsafe(_close)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._connections.clear()
        logger.info("Nexus WebSocket server stopped.")

    async def _handle_connection(self, websocket: WebSocketServerProtocol, path: str | None = None) -> None:
        """Handle incoming WebSocket connections and handshake query params."""
        raw_path = getattr(websocket, "path", None)
        if not raw_path and hasattr(websocket, "request"):
            raw_path = getattr(websocket.request, "path", None) or getattr(websocket.request, "uri", None)
        full_path = raw_path or "/Nexus"
        parsed_url = urlparse(full_path)
        params = parse_qs(parsed_url.query)

        username = (params.get("name") or params.get("username") or ["Unknown"])[0]
        raw_user_id = (params.get("id") or params.get("userId") or [None])[0]
        job_id = (params.get("jobId") or params.get("jobid") or [None])[0]

        user_id = int(raw_user_id) if raw_user_id and raw_user_id.isdigit() else None

        # Clean username key
        account_key = username.lower()
        self._connections[account_key] = websocket

        if account_key not in self.accounts:
            self.accounts[account_key] = ControlledAccount(
                username=username,
                user_id=user_id,
                job_id=job_id,
                status="Online",
            )
        else:
            acc = self.accounts[account_key]
            acc.status = "Online"
            acc.job_id = job_id or acc.job_id
            if user_id:
                acc.user_id = user_id
            acc.connected_at = datetime.now(UTC).isoformat()
            acc.last_ping_at = datetime.now(UTC).isoformat()

        logger.info(f"Nexus client connected: {username} (ID: {user_id}, JobId: {job_id})")
        self.accounts[account_key].add_log(f"Connected from client {username}")

        try:
            async for raw_message in websocket:
                await self._process_message(account_key, raw_message)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._connections.pop(account_key, None)
            if account_key in self.accounts:
                acc = self.accounts[account_key]
                acc.status = "Offline"
                acc.add_log("Disconnected")
                logger.info(f"Nexus client disconnected: {username}")

                if acc.auto_relaunch and self.on_auto_relaunch_trigger:
                    logger.info(f"Triggering auto-relaunch for {username}")
                    self.on_auto_relaunch_trigger(username)

    async def _process_message(self, account_key: str, raw_message: str | bytes) -> None:
        """Process incoming WebSocket JSON payload from Roblox client."""
        try:
            text = raw_message.decode("utf-8") if isinstance(raw_message, bytes) else raw_message
            data = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        cmd = data.get("Name") or data.get("name") or data.get("command")
        payload = data.get("Payload") or data.get("payload")

        if not cmd:
            return

        acc = self.accounts.get(account_key)
        if not acc:
            return

        cmd_lower = str(cmd).lower()
        acc.last_ping_at = datetime.now(UTC).isoformat()

        if cmd_lower in ("ping", "heartbeat"):
            if isinstance(payload, dict):
                acc.job_id = payload.get("jobId") or acc.job_id
                acc.place_id = payload.get("placeId") or acc.place_id
        elif cmd_lower == "log":
            msg = str(payload) if payload is not None else ""
            acc.add_log(msg)
            if self.on_log_callback:
                try:
                    self.on_log_callback(acc.username, msg)
                except Exception as exc:
                    logger.error(f"Error in on_log_callback: {exc}")
        elif cmd_lower in ("setrelaunch", "setautorelaunch"):
            acc.auto_relaunch = bool(payload)
            acc.add_log(f"AutoRelaunch set to {acc.auto_relaunch}")
        elif cmd_lower == "setplaceid":
            if str(payload).isdigit():
                acc.place_id = int(payload)
        elif cmd_lower == "setjobid":
            acc.job_id = str(payload)
        elif cmd_lower == "echo":
            ws = self._connections.get(account_key)
            if ws:
                await ws.send(json.dumps({"Name": "Echo", "Payload": payload}))

    def send_command(self, target_account: str, command_name: str, payload: Any = None) -> bool:
        """Send command JSON payload to connected client(s). Target can be 'all' or username."""
        if not self.is_running or not self._loop:
            return False

        message_json = json.dumps({
            "Name": command_name,
            "Payload": payload,
        })

        async def _broadcast():
            sent = False
            if target_account.lower() == "all":
                for ws in list(self._connections.values()):
                    try:
                        await ws.send(message_json)
                        sent = True
                    except Exception:
                        pass
            else:
                key = target_account.lower()
                ws = self._connections.get(key)
                if ws:
                    try:
                        await ws.send(message_json)
                        sent = True
                    except Exception:
                        pass
            return sent

        future = asyncio.run_coroutine_threadsafe(_broadcast(), self._loop)
        try:
            return future.result(timeout=2.0)
        except Exception:
            return False

    def get_connected_accounts(self) -> list[dict[str, Any]]:
        """Return array of all tracked accounts and their Nexus state."""
        return [acc.to_dict() for acc in self.accounts.values()]
