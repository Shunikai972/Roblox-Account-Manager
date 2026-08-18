from __future__ import annotations

import io
import json
from pathlib import Path
import struct
import time
import zipfile

import pytest

from app.backend.automations import MacroEngine, MacroParseError, parse_macro_dsl
from app.backend.core.crash_reporting import SupportBundleBuilder, redact_support_text
from app.backend.integrations import DiscordPresenceManager
from app.backend.repositories.sqlite_repository import SQLiteRepository
from app.backend.roblox.authenticated_browser import AuthenticatedBrowserService
from app.backend.roblox.authenticated_browser import _page_websocket
from app.backend.roblox.background import RobloxBackgroundManager
from app.backend.roblox.private_servers import PrivateServerHelper


class _MacroBackend:
    def __init__(self) -> None:
        self.events: list[tuple[int, str, bool]] = []

    def verify(self, pid: int, expected_created_at: float | None):
        return {"pid": pid, "hwnd": pid * 10, "background_delivery_supported": True}

    def key(self, target, key: str, down: bool) -> bool:
        self.events.append((target["pid"], key, down))
        return True

    def click(self, target, x: float, y: float, button: str) -> bool:
        return True

    def text(self, target, value: str) -> bool:
        return True


def test_macro_dsl_is_bounded_and_two_instances_run_independently(monkeypatch) -> None:
    # Macros drive one Roblox window at a time in this build, so the concurrent
    # path this test covers now lives behind ASTRO_ENABLE_MULTI_WINDOW_MACROS.
    # That path is set aside, not deleted, so its coverage stays right here.
    monkeypatch.setenv("ASTRO_ENABLE_MULTI_WINDOW_MACROS", "1")
    backend = _MacroBackend()
    engine = MacroEngine(backend)
    actions = parse_macro_dsl("PRESS W 5\nWAIT 30\nPRESS A 5")
    definition = {"id": "macro", "name": "Walk", "actions": actions}
    first = engine.start(definition, pid=101, expected_created_at=1.0, account_id="a")
    second = engine.start(definition, pid=202, expected_created_at=2.0, account_id="b")
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and any(row["state"] in {"starting", "running"} for row in engine.list_runs()):
        time.sleep(0.01)
    runs = {row["run_id"]: row for row in engine.list_runs()}
    assert runs[first["run_id"]]["state"] == "completed"
    assert runs[second["run_id"]]["state"] == "completed"
    assert {event[0] for event in backend.events} == {101, 202}
    with pytest.raises(MacroParseError):
        parse_macro_dsl("REPEAT 101\nPRESS W\nEND")


def test_macro_local_backend_run_hooks_bound_the_whole_input_run() -> None:
    class HookedBackend(_MacroBackend):
        def __init__(self) -> None:
            super().__init__()
            self.hooks: list[str] = []

        def verify(self, pid: int, expected_created_at: float | None):
            return {
                "pid": pid,
                "hwnd": pid * 10,
                "background_delivery_supported": False,
                "delivery_mode": "foreground_fallback",
            }

        def begin_run(self, target) -> bool:
            self.hooks.append("begin")
            return True

        def end_run(self, target) -> None:
            self.hooks.append("end")

    backend = HookedBackend()
    engine = MacroEngine(backend)
    started = engine.start(
        {"id": "local", "name": "Local", "actions": parse_macro_dsl("PRESS W 5")},
        pid=303,
        expected_created_at=3.0,
        account_id=None,
    )
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        row = next(item for item in engine.list_runs() if item["run_id"] == started["run_id"])
        if row["state"] not in {"starting", "running"}:
            break
        time.sleep(0.01)
    assert row["state"] == "completed"
    assert row["delivery_mode"] == "foreground_fallback"
    assert backend.hooks == ["begin", "end"]


def test_macro_definitions_persist_in_schema_v4(tmp_path: Path) -> None:
    with SQLiteRepository(tmp_path / "macro.db") as repository:
        saved = repository.save_macro({
            "name": "Idle",
            "mode": "blocks",
            "actions": [{"type": "wait", "milliseconds": 100}],
        })
        assert repository.schema_version == 4
        assert repository.get_macro(saved["id"])["actions"][0]["type"] == "wait"
        assert repository.delete_macro(saved["id"]) is True


class _RpcStream:
    def __init__(self) -> None:
        self.responses = io.BytesIO(_frame(1, {"evt": "READY"}) + _frame(1, {"cmd": "SET_ACTIVITY"}))
        self.writes: list[bytes] = []

    def read(self, length: int) -> bytes:
        return self.responses.read(length)

    def write(self, value: bytes) -> int:
        self.writes.append(bytes(value))
        return len(value)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


def _frame(opcode: int, payload: dict) -> bytes:
    raw = json.dumps(payload).encode()
    return struct.pack("<II", opcode, len(raw)) + raw


def test_discord_rpc_handshake_and_redacted_aggregate_activity() -> None:
    stream = _RpcStream()
    manager = DiscordPresenceManager(lambda: stream, process_id=42)
    activity = manager.activity_for_instances(
        [{"place_id": 1}, {"place_id": 2}], strategy="aggregate", show_account=False
    )
    status = manager.publish("123456789", activity)
    assert status["connected"] is True
    written = b"".join(stream.writes)
    assert b"Managing 2 Roblox instances" in written
    assert b"cookie" not in written.lower()


def test_support_bundle_redacts_secrets_and_excludes_database(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    exports = tmp_path / "exports"
    logs.mkdir()
    secret = ".ROBLOSECURITY=very-secret-cookie-value-that-must-not-leak"
    (logs / "astro.log").write_text(f"Authorization=BearerSecret token=abc {secret} C:\\Users\\Astro\\file", encoding="utf-8")
    result = SupportBundleBuilder(logs, exports).create(
        diagnostics={"status": "healthy", "cookie": secret},
        settings={"theme": "dark", "password": "do-not-copy"},
    )
    with zipfile.ZipFile(result["path"]) as archive:
        names = set(archive.namelist())
        combined = b"\n".join(archive.read(name) for name in names).decode("utf-8")
    assert "astro.db" not in names
    assert "very-secret" not in combined
    assert "do-not-copy" not in combined
    assert "[USER]" in combined
    assert "[REDACTED" in redact_support_text(secret)


class _Process:
    def __init__(self, pid: int, name: str = "RobloxPlayerBeta.exe", created: float = 10.0) -> None:
        self.pid = pid
        self.info = {"pid": pid, "name": name, "create_time": created}
        self._name = name
        self._created = created
        self.terminated = False

    def name(self): return self._name
    def create_time(self): return self._created
    def terminate(self): self.terminated = True
    def wait(self, timeout: float): return 0


def test_background_roblox_close_requires_confirmation_and_rechecks_identity() -> None:
    listed = _Process(99)
    current = _Process(99)
    manager = RobloxBackgroundManager(process_iter=lambda **_: [listed], process_factory=lambda pid: current)
    with pytest.raises(Exception):
        manager.close_running(confirm=False)
    result = manager.close_running(confirm=True)
    assert result["closed"] == 1
    assert current.terminated is True


def test_private_server_and_authenticated_browser_reject_lookalike_domains() -> None:
    assert PrivateServerHelper.parse_vip_link("https://roblox.com.evil.test/games/1?privateServerLinkCode=x") is None
    assert PrivateServerHelper.parse_vip_link("https://www.roblox.com/games/1?privateServerLinkCode=bad%20code") is None
    with pytest.raises(Exception):
        AuthenticatedBrowserService().open("session", "https://roblox.com.evil.test/home")


def test_authenticated_browser_selects_its_about_blank_page(monkeypatch) -> None:
    payload = [
        {
            "type": "page",
            "url": "chrome-extension://example/options.html",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9000/devtools/page/extension",
        },
        {
            "type": "page",
            "url": "edge://sync-confirmation-dialog/",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9000/devtools/page/sync",
        },
        {
            "type": "page",
            "url": "about:blank",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9000/devtools/page/isolated",
        },
    ]

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(
        "app.backend.roblox.authenticated_browser.urlopen",
        lambda *_args, **_kwargs: _Response(),
    )
    assert _page_websocket(9000).endswith("/isolated")
