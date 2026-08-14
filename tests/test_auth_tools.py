"""Tests for authenticated Roblox account tools."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.backend.api.bridge import DesktopBridge
from app.backend.core.config import AppPaths
from app.backend.repositories.sqlite_repository import SQLiteRepository
from app.backend.roblox.auth_tools import RobloxAuthTools
from app.backend.roblox.types import LaunchResult
from app.backend.services.application_service import ApplicationService
from app.backend.watchers import RestartPolicy, RestartRequest


def _paths(tmp_path: Path) -> AppPaths:
    return AppPaths(
        root=tmp_path,
        database=tmp_path / "astro.db",
        logs=tmp_path / "logs",
        backups=tmp_path / "backups",
        cache=tmp_path / "cache",
        exports=tmp_path / "exports",
    )


def test_auth_tools_uri_generation():
    tools = RobloxAuthTools()
    link = tools.generate_rbx_player_uri(auth_ticket="TEST_TICKET_123", place_id=2753915549, job_id="job_xyz")
    assert "roblox-player:1+launchmode:play" in link
    assert "gameinfo:TEST_TICKET_123" in link
    assert "placeId%3D2753915549" in link
    assert "gameId%3Djob_xyz" in link


@patch("requests.Session.post")
def test_generate_auth_ticket(mock_post):
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.headers = {"rbx-authentication-ticket": "MOCK_TICKET_VAL_999"}
    mock_post.return_value = mock_res

    tools = RobloxAuthTools()
    ticket = tools.generate_auth_ticket(cookie="_|WARNING:-DO-NOT-SHARE-THIS...|_MOCK_COOKIE")
    assert ticket == "MOCK_TICKET_VAL_999"
    assert mock_post.call_args.kwargs == {"json": {}, "timeout": 15.0}


@patch("requests.Session.post")
def test_generate_auth_ticket_repeats_json_post_after_csrf_challenge(mock_post):
    challenge = MagicMock(status_code=403, headers={"x-csrf-token": "csrf-ticket-token"})
    success = MagicMock(
        status_code=200,
        headers={"rbx-authentication-ticket": "MOCK_TICKET_AFTER_CSRF"},
    )
    mock_post.side_effect = [challenge, success]

    ticket = RobloxAuthTools().generate_auth_ticket("_|WARNING...|_COOKIE")

    assert ticket == "MOCK_TICKET_AFTER_CSRF"
    assert mock_post.call_count == 2
    assert all(call.kwargs == {"json": {}, "timeout": 15.0} for call in mock_post.call_args_list)


@patch("requests.Session.post")
def test_get_csrf_token_uses_roblox_challenge_header(mock_post):
    mock_post.return_value = MagicMock(status_code=403, headers={"x-csrf-token": "csrf-test-token"})

    token = RobloxAuthTools().get_csrf_token("_|WARNING...|_COOKIE")

    assert token == "csrf-test-token"
    assert mock_post.call_args.kwargs["timeout"] == 15.0


@patch("requests.Session.post")
def test_authenticated_server_probe_reads_historical_machine_address(mock_post):
    response = MagicMock(status_code=200, headers={})
    response.json.return_value = {
        "status": 2,
        "joinScript": {"MachineAddress": "128.116.0.1", "ServerPort": 53640},
    }
    mock_post.return_value = response

    result = RobloxAuthTools().probe_server_instance(
        "_|WARNING...|_COOKIE", 2512643572, "job_xyz"
    )

    assert result == {"address": "128.116.0.1", "port": 53640}
    assert mock_post.call_args.kwargs == {
        "json": {"gameId": "job_xyz", "placeId": 2512643572},
        "timeout": 15.0,
    }


@patch("app.backend.services.application_service.time.sleep", return_value=None)
def test_launch_with_stored_session_uses_authenticated_player_handoff(_sleep, tmp_path: Path):
    launcher = MagicMock()
    launcher.launch_authenticated_uri.return_value = LaunchResult(uri="roblox-player:1+launchmode:play+safe", launched=True)
    service = ApplicationService(paths=_paths(tmp_path), launcher=launcher, client_settings=MagicMock())
    try:
        account = service.create_account({"username": "Authenticated"})
        domain_account = service.repository.get_account(account["id"])
        service.repository.save_protected_secret(account["id"], "session", service.vault.protect(b"cookie-value"))
        domain_account.has_session = True
        service.repository.save_account(domain_account)
        service.auth_tools = MagicMock()
        service.auth_tools.generate_auth_ticket.return_value = "ticket-value"
        service.auth_tools.generate_rbx_player_uri.return_value = "roblox-player:1+launchmode:play+safe"

        result = service.launch_account(account["id"], {"place_id": 123, "job_id": "job-1"})

        assert result["accepted"] is True
        service.auth_tools.generate_auth_ticket.assert_called_once_with("cookie-value")
        service.auth_tools.generate_rbx_player_uri.assert_called_once_with("ticket-value", 123, "job-1")
        launcher.launch_authenticated_uri.assert_called_once_with("roblox-player:1+launchmode:play+safe")
        launcher.launch.assert_not_called()
    finally:
        service.close()


def test_watcher_relaunch_reuses_the_stored_account_session(tmp_path: Path):
    launcher = MagicMock()
    launcher.launch_authenticated_uri.return_value = LaunchResult(
        uri="roblox-player:1+launchmode:play+safe-restart",
        launched=True,
    )
    monitor = MagicMock()
    monitor.has_active_or_pending_account.return_value = False
    monitor.register_launch_intent.return_value = "restart-launch-intent"
    service = ApplicationService(
        paths=_paths(tmp_path),
        launcher=launcher,
        monitor=monitor,
        client_settings=MagicMock(),
    )
    try:
        account = service.create_account({"username": "AuthenticatedRestart", "saved_place_id": 456})
        domain_account = service.repository.get_account(account["id"])
        service.repository.save_protected_secret(
            account["id"], "session", service.vault.protect(b"restart-cookie")
        )
        domain_account.has_session = True
        service.repository.save_account(domain_account)
        monitor.scan.return_value = MagicMock(
            instances=(MagicMock(account_id=account["id"], pid=9876),),
            events=(),
            complete=True,
            started=(),
        )
        monitor.claim_due_restarts.return_value = (
            RestartRequest(
                request_id="restart-request",
                account_id=account["id"],
                account_username="AuthenticatedRestart",
                place_id=456,
                job_id=None,
                due_at=0.0,
                restart_attempt=1,
                restart_policy=RestartPolicy(enabled=True, delay_seconds=1, max_attempts=2),
            ),
        )
        service.auth_tools = MagicMock()
        service.auth_tools.generate_auth_ticket.return_value = "restart-ticket"
        service.auth_tools.generate_rbx_player_uri.return_value = (
            "roblox-player:1+launchmode:play+safe-restart"
        )

        service._dispatch_due_restarts()

        service.auth_tools.generate_auth_ticket.assert_called_once_with("restart-cookie")
        launcher.launch_authenticated_uri.assert_called_once_with(
            "roblox-player:1+launchmode:play+safe-restart"
        )
        launcher.launch.assert_not_called()
        registered = monitor.register_launch_intent.call_args.kwargs
        assert registered["restart_attempt"] == 1
        assert registered["restart_policy"].enabled is True
        monitor.record_restart_result.assert_called_once()
    finally:
        service.close()


def test_auth_tools_service_and_bridge_integration(tmp_path: Path):
    paths = _paths(tmp_path)
    repo = SQLiteRepository(paths.database)
    service = ApplicationService(paths=paths, repository=repo)
    bridge = DesktopBridge(service)

    # Create account with secret
    acc = repo.save_account({"username": "AuthUser", "vault_key": "vault_authuser_key"})
    cookie_str = "_|WARNING...|_VALID_COOKIE_VAL"
    protected_blob = service.vault.protect(cookie_str.encode("utf-8"))
    repo.save_protected_secret(acc.id, "session", protected_blob)

    # Fetch cookie via bridge
    res_cookie = bridge.get_account_cookie(acc.id)
    assert res_cookie["username"] == "AuthUser"
    assert res_cookie["cookie"] == cookie_str

    service.close()
