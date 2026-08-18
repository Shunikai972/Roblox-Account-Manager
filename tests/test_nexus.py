"""Tests for Nexus / Account Control WebSocket server and service integration."""

import asyncio
import json
import socket
from pathlib import Path

import anyio
import pytest
import websockets

from app.backend.api.bridge import DesktopBridge
from app.backend.core.config import AppPaths
from app.backend.nexus.controlled_account import ControlledAccount
from app.backend.nexus.lua_script import get_nexus_lua_script
from app.backend.nexus.server import NexusServer
from app.backend.repositories.sqlite_repository import SQLiteRepository
from app.backend.services.application_service import ApplicationService


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _paths(tmp_path: Path) -> AppPaths:
    return AppPaths(
        root=tmp_path,
        database=tmp_path / "astro.db",
        logs=tmp_path / "logs",
        backups=tmp_path / "backups",
        cache=tmp_path / "cache",
        exports=tmp_path / "exports",
    )


def test_controlled_account_model():
    acc = ControlledAccount(username="TestUser", user_id=123456, job_id="job_999")
    assert acc.username == "TestUser"
    assert acc.user_id == 123456
    assert acc.job_id == "job_999"
    assert acc.status == "Online"
    assert len(acc.logs) == 0

    acc.add_log("Test log entry")
    assert len(acc.logs) == 1
    assert "Test log entry" in acc.logs[0]

    data = acc.to_dict()
    assert data["username"] == "TestUser"
    assert data["user_id"] == 123456
    assert data["job_id"] == "job_999"
    assert data["status"] == "Online"
    assert data["log_count"] == 1


def test_nexus_lua_script_template():
    script = get_nexus_lua_script(host="127.0.0.1", port=5242, token="secret-token")
    assert 'SERVER_HOST = "127.0.0.1"' in script
    assert "SERVER_PORT = 5242" in script
    assert "Nexus Account Control Client Script" in script
    assert 'SERVER_TOKEN = "secret-token"' in script


def test_nexus_server_lifecycle_and_handshake():
    async def _async_test():
        port = get_free_port()
        server = NexusServer(host="127.0.0.1", port=port)
        server.start()

        assert server.is_running is True

        url = f"ws://127.0.0.1:{port}/Nexus?name=TestPlayer&id=88888&jobId=job_abc"

        async with websockets.connect(url) as ws:
            await asyncio.sleep(0.2)
            accounts = server.get_connected_accounts()
            assert len(accounts) == 1
            client = accounts[0]
            assert client["username"] == "TestPlayer"
            assert client["user_id"] == 88888
            assert client["job_id"] == "job_abc"
            assert client["status"] == "Online"

            # Send ping message
            ping_msg = json.dumps({"Name": "ping", "Payload": {"jobId": "job_xyz", "placeId": 2753915549}})
            await ws.send(ping_msg)
            await asyncio.sleep(0.1)

            accounts = server.get_connected_accounts()
            assert accounts[0]["job_id"] == "job_xyz"
            assert accounts[0]["place_id"] == 2753915549

            # Send Log message
            log_msg = json.dumps({"Name": "Log", "Payload": "Executed command successfully"})
            await ws.send(log_msg)
            await asyncio.sleep(0.1)

            accounts = server.get_connected_accounts()
            assert accounts[0]["log_count"] == 2  # Connected + Executed

            # Send Echo message and wait for echo response
            echo_msg = json.dumps({"Name": "Echo", "Payload": "Hello Echo"})
            await ws.send(echo_msg)
            response = await asyncio.wait_for(ws.recv(), timeout=2.0)
            res_data = json.loads(response)
            assert res_data["Name"] == "Echo"
            assert res_data["Payload"] == "Hello Echo"

            # Test command sending from server to client
            sent = server.send_command("TestPlayer", "teleport", {"placeId": 12345})
            assert sent is True

            cmd_response = await asyncio.wait_for(ws.recv(), timeout=2.0)
            cmd_data = json.loads(cmd_response)
            assert cmd_data["Name"] == "teleport"
            assert cmd_data["Payload"] == {"placeId": 12345}

        server.stop()
        assert server.is_running is False

    anyio.run(_async_test)


def test_nexus_rejects_wrong_handshake_token_before_registering_account():
    async def _async_test():
        port = get_free_port()
        server = NexusServer(host="127.0.0.1", port=port, authentication_token="expected-token")
        server.start()
        try:
            url = f"ws://127.0.0.1:{port}/Nexus?name=TestPlayer&id=88888&token=wrong"
            async with websockets.connect(url) as ws:
                with pytest.raises(websockets.exceptions.ConnectionClosedError):
                    await ws.recv()
            assert server.get_connected_accounts() == []
        finally:
            server.stop()

    anyio.run(_async_test)


def test_nexus_application_service_and_bridge_integration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Nexus ships hidden: the surface is retained but unreachable unless the
    # recovery flag is set, so this integration test opts in explicitly.
    monkeypatch.setenv("ASTRO_ENABLE_NEXUS", "1")
    paths = _paths(tmp_path)
    repo = SQLiteRepository(paths.database)
    service = ApplicationService(paths=paths, repository=repo)
    bridge = DesktopBridge(service)

    # Initial status
    status = bridge.get_nexus_status()
    assert status["running"] is False

    # Start server
    start_res = bridge.start_nexus_server(host="127.0.0.1", port=get_free_port())
    assert start_res["running"] is True
    assert "ws://127.0.0.1:" in start_res["url"]

    # Get script
    script = bridge.get_nexus_lua_script(host="127.0.0.1", port=5242)
    assert "127.0.0.1" in script
    assert str(start_res["port"]) in script
    assert 'SERVER_TOKEN = ""' not in script

    # Stop server
    stop_res = bridge.stop_nexus_server()
    assert stop_res["running"] is False

    service.close()
