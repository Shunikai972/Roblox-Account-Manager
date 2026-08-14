"""Minimal Discord local RPC client for one redacted Astro activity."""

from __future__ import annotations

import json
import os
import struct
import threading
import time
from typing import Any, BinaryIO, Callable, Mapping, Sequence
from uuid import uuid4


MAX_FRAME = 64 * 1024
Connector = Callable[[], BinaryIO]


class DiscordRpcError(RuntimeError):
    """Safe local Discord integration error."""


def _default_connector() -> BinaryIO:
    if os.name != "nt":
        raise DiscordRpcError("Discord Rich Presence is available on Windows.")
    for index in range(10):
        try:
            return open(rf"\\?\pipe\discord-ipc-{index}", "r+b", buffering=0)
        except OSError:
            continue
    raise DiscordRpcError("Discord is not running or its local RPC pipe is unavailable.")


class DiscordPresenceManager:
    """Publish a single bounded activity without exposing a Roblox session."""

    def __init__(self, connector: Connector = _default_connector, *, process_id: int | None = None) -> None:
        self._connector = connector
        self._process_id = process_id or os.getpid()
        self._lock = threading.RLock()
        self._stream: BinaryIO | None = None
        self._client_id: str | None = None
        self._last_payload: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._connected = False
        self._updated_at: float | None = None

    def close(self) -> None:
        with self._lock:
            stream, self._stream = self._stream, None
            self._connected = False
            self._client_id = None
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "connected": self._connected,
                "configured": bool(self._client_id),
                "last_error": self._last_error,
                "updated_at": self._updated_at,
                "activity": dict(self._last_payload or {}),
            }

    def publish(self, client_id: str, activity: Mapping[str, Any] | None) -> dict[str, Any]:
        normalized_id = str(client_id or "").strip()
        if not normalized_id.isdigit() or not 5 <= len(normalized_id) <= 32:
            raise DiscordRpcError("Discord Application ID must be numeric.")
        payload = _sanitize_activity(activity)
        with self._lock:
            try:
                if self._stream is None or self._client_id != normalized_id:
                    self.close()
                    self._stream = self._connector()
                    self._write(0, {"v": 1, "client_id": normalized_id})
                    opcode, reply = self._read()
                    if opcode not in {1, 2} or not isinstance(reply, dict):
                        raise DiscordRpcError("Discord rejected the local RPC handshake.")
                    self._client_id = normalized_id
                    self._connected = True
                command = {
                    "cmd": "SET_ACTIVITY",
                    "args": {"pid": self._process_id, "activity": payload},
                    "nonce": str(uuid4()),
                }
                self._write(1, command)
                opcode, reply = self._read()
                if opcode not in {1, 2} or (isinstance(reply, dict) and reply.get("evt") == "ERROR"):
                    raise DiscordRpcError("Discord rejected the activity update.")
                self._last_payload = payload
                self._last_error = None
                self._updated_at = time.time()
                return self.status()
            except (OSError, EOFError, ValueError, DiscordRpcError) as exc:
                self._last_error = str(exc) if isinstance(exc, DiscordRpcError) else "Discord local RPC is unavailable."
                self.close()
                raise DiscordRpcError(self._last_error) from exc

    def clear(self, client_id: str) -> dict[str, Any]:
        return self.publish(client_id, None)

    def activity_for_instances(
        self,
        instances: Sequence[Mapping[str, Any]],
        *,
        strategy: str = "latest",
        show_account: bool = False,
        game_lookup: Callable[[int], str | None] | None = None,
    ) -> dict[str, Any] | None:
        rows = [row for row in instances if isinstance(row, Mapping) and row.get("place_id")]
        if not rows:
            return None
        if strategy == "aggregate" and len(rows) > 1:
            return {"details": f"Managing {len(rows)} Roblox instances", "state": "Astro Account Manager"}
        row = rows[-1]
        place_id = int(row["place_id"])
        game_name = game_lookup(place_id) if game_lookup else None
        details = str(game_name or f"Roblox Place {place_id}")[:128]
        state = "Astro Account Manager"
        if show_account and row.get("account_username"):
            state = f"@{str(row['account_username'])[:100]}"
        return {"details": details, "state": state, "timestamps": {"start": int(time.time())}}

    def _write(self, opcode: int, payload: Mapping[str, Any]) -> None:
        if self._stream is None:
            raise DiscordRpcError("Discord local RPC is disconnected.")
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(raw) > MAX_FRAME:
            raise DiscordRpcError("Discord activity frame is too large.")
        self._stream.write(struct.pack("<II", int(opcode), len(raw)) + raw)
        flush = getattr(self._stream, "flush", None)
        if callable(flush):
            flush()

    def _read(self) -> tuple[int, dict[str, Any]]:
        if self._stream is None:
            raise DiscordRpcError("Discord local RPC is disconnected.")
        header = _read_exact(self._stream, 8)
        opcode, length = struct.unpack("<II", header)
        if length > MAX_FRAME:
            raise DiscordRpcError("Discord returned an oversized frame.")
        payload = json.loads(_read_exact(self._stream, length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise DiscordRpcError("Discord returned an invalid frame.")
        return opcode, payload


def _sanitize_activity(activity: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if activity is None:
        return None
    allowed: dict[str, Any] = {}
    for key in ("details", "state", "large_image", "large_text", "small_image", "small_text"):
        if key in activity and activity[key] is not None:
            text = str(activity[key]).strip()
            if text:
                allowed[key] = text[:128]
    timestamps = activity.get("timestamps")
    if isinstance(timestamps, Mapping):
        values = {key: int(timestamps[key]) for key in ("start", "end") if isinstance(timestamps.get(key), (int, float))}
        if values:
            allowed["timestamps"] = values
    return allowed or None


def _read_exact(stream: BinaryIO, length: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        data = stream.read(length - len(chunks))
        if not data:
            raise EOFError("Discord closed its local RPC pipe.")
        chunks.extend(data)
    return bytes(chunks)
