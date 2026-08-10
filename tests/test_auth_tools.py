"""Tests for authenticated Roblox account tools."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.backend.api.bridge import DesktopBridge
from app.backend.core.config import AppPaths
from app.backend.repositories.sqlite_repository import SQLiteRepository
from app.backend.roblox.auth_tools import RobloxAuthTools
from app.backend.services.application_service import ApplicationService


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
