"""Unit tests for newly ported AccountUtils, VIP links, Player Search, Random Server, Beta Home, and Updater."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.backend.api.bridge import DesktopBridge
from app.backend.core.config import AppPaths
from app.backend.repositories.sqlite_repository import SQLiteRepository
from app.backend.roblox.account_utils import AccountUtils
from app.backend.roblox.player_search import PlayerSearchService
from app.backend.roblox.private_servers import PrivateServerHelper
from app.backend.roblox.random_server import RandomServerSelector
from app.backend.services.application_service import ApplicationService
from app.backend.watchers.beta_home_cleaner import BetaHomeCleaner


def _paths(tmp_path: Path) -> AppPaths:
    return AppPaths(
        root=tmp_path,
        database=tmp_path / "astro.db",
        logs=tmp_path / "logs",
        backups=tmp_path / "backups",
        cache=tmp_path / "cache",
        exports=tmp_path / "exports",
    )


def test_private_server_link_parsing():
    link = "https://www.roblox.com/games/2753915549/Blox-Fruits?privateServerLinkCode=1234567890abcdef"
    res = PrivateServerHelper.parse_vip_link(link)
    assert res is not None
    assert res["place_id"] == 2753915549
    assert res["link_code"] == "1234567890abcdef"

    uri = PrivateServerHelper.format_private_server_uri(
        auth_ticket="TICKET_XYZ", place_id=2753915549, link_code="1234567890abcdef", launch_time=1700000000000
    )
    assert "roblox-player:1+launchmode:play" in uri
    assert "gameinfo:TICKET_XYZ" in uri
    assert "linkCode%3D1234567890abcdef" in uri


@patch("requests.Session.post")
def test_account_utils(mock_post):
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_post.return_value = mock_res

    utils = AccountUtils()
    cookie = "_|WARNING...|_COOKIE"

    assert utils.change_password(cookie, "old_pass", "new_pass") is True
    assert utils.change_email(cookie, "pass", "new@example.com") is True
    assert utils.logout_all_sessions(cookie) is True
    assert utils.set_display_name(cookie, 123456, "NewDisplay") is True
    assert utils.send_friend_request(cookie, 9999) is True
    assert utils.block_user(cookie, 9999) is True
    assert utils.unblock_user(cookie, 9999) is True
    assert utils.quick_log_in(cookie, "123456") is True


def test_extended_service_and_bridge_integration(tmp_path: Path):
    paths = _paths(tmp_path)
    repo = SQLiteRepository(paths.database)
    service = ApplicationService(paths=paths, repository=repo)
    bridge = DesktopBridge(service)

    # Save account
    acc = repo.save_account({"username": "ExtUser", "user_id": 8888, "vault_key": "vkey_ext"})
    cookie_str = "_|WARNING...|_VALID_COOKIE"
    protected_blob = service.vault.protect(cookie_str.encode("utf-8"))
    repo.save_protected_secret(acc.id, "session", protected_blob)

    # Test bridge calls with mocked requests
    with patch("requests.Session.post") as mock_post:
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_post.return_value = mock_res

        res_pw = bridge.change_account_password(acc.id, "old", "new")
        assert res_pw["success"] is True

        res_dn = bridge.set_account_display_name(acc.id, "SuperUser")
        assert res_dn["display_name"] == "SuperUser"

        res_fr = bridge.send_account_friend_request(acc.id, 5555)
        assert res_fr["success"] is True

    # Test VIP link bridge call
    vip_res = bridge.parse_vip_link("https://www.roblox.com/games/100/Test?code=vip_code_999")
    assert vip_res["place_id"] == 100
    assert vip_res["link_code"] == "vip_code_999"

    service.close()
