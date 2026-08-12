"""Unit tests for newly ported AccountUtils, VIP links, Player Search, Random Server, Beta Home, and Updater."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.backend.api.bridge import DesktopBridge
from app.backend.core.config import AppPaths
from app.backend.repositories.sqlite_repository import SQLiteRepository
from app.backend.roblox.account_utils import AccountUtils
from app.backend.roblox.player_search import PlayerSearchService
from app.backend.roblox.private_servers import PrivateServerHelper
from app.backend.roblox.random_server import RandomServerSelector
from app.backend.roblox.types import PresenceState, ServerPage, UserPresence
from app.backend.models.domain import Server
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


def test_random_server_uses_public_server_model_contract():
    client = MagicMock()
    client.list_public_servers.return_value = ServerPage(
        servers=(Server(job_id="job-1", place_id=123, playing=4, max_players=12, ping=42),),
        next_page_cursor=None,
        previous_page_cursor=None,
    )

    result = RandomServerSelector(client).get_random_server(123)

    client.list_public_servers.assert_called_once_with(123, limit=25)
    assert result == {"job_id": "job-1", "place_id": 123, "playing": 4, "capacity": 12, "ping": 42}


def test_player_presence_maps_roblox_game_id_to_ram_job_id():
    client = MagicMock()
    client.get_public_presence.return_value = (
        UserPresence(
            user_id=99,
            state=PresenceState.IN_GAME,
            place_id=123,
            game_id="job-abc",
            last_online="2026-08-11T00:00:00Z",
        ),
    )

    result = PlayerSearchService(client).get_player_presence(99)

    assert result["job_id"] == "job-abc"
    assert result["game_id"] == "job-abc"


def test_beta_home_cleaner_enforces_the_automatic_grace_period() -> None:
    process = MagicMock()
    process.name.return_value = "RobloxPlayerBeta.exe"
    process.create_time.return_value = 1_000.0
    with patch("app.backend.watchers.beta_home_cleaner.psutil.Process", return_value=process):
        assert BetaHomeCleaner._is_roblox_process(42, min_age_seconds=30, now=1_029.9) is False
        assert BetaHomeCleaner._is_roblox_process(42, min_age_seconds=30, now=1_030.0) is True


def test_watcher_tick_runs_the_automatic_beta_home_cleaner(tmp_path: Path) -> None:
    service = ApplicationService(paths=_paths(tmp_path))
    scan = MagicMock()
    try:
        with patch.object(service, "_scan_instances", return_value=scan), patch(
            "app.backend.services.application_service.BetaHomeCleaner.close_beta_home_windows",
            return_value=0,
        ) as cleaner:
            assert service._watcher_tick() is scan
        cleaner.assert_called_once_with(min_age_seconds=30.0)
    finally:
        service.close()


@patch("requests.Session.patch")
@patch("requests.Session.post")
def test_account_utils(mock_post, mock_patch):
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_post.return_value = mock_res
    mock_patch.return_value = mock_res

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
    assert utils.set_follow_privacy(cookie, "friends") is True
    assert utils.unlock_parental_pin(cookie, "1234") is True
    with pytest.raises(Exception, match="six digits"):
        utils.quick_log_in(cookie, "123")


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

    with pytest.raises(RuntimeError, match="confirmation"):
        bridge.export_account_sessions([acc.id], False)
    exported = bridge.export_account_sessions([acc.id], True)
    exported_path = Path(exported["path"])
    assert exported_path.parent == paths.exports.resolve()
    assert exported["plaintext"] is True
    assert exported_path.read_text(encoding="utf-8") == f"ExtUser:{cookie_str}\n"
    assert cookie_str not in str(service.get_activity())

    session_client = MagicMock()
    session_client.__enter__.return_value.authenticated_user.return_value = SimpleNamespace(
        user_id=8888,
        username="ExtUser",
        display_name="Refreshed User",
    )
    with patch("app.backend.roblox.SessionRobloxClient", return_value=session_client):
        refreshed = bridge.refresh_account_session(acc.id)
    assert refreshed["display_name"] == "Refreshed User"
    assert refreshed["has_session"] is True

    # Test bridge calls with mocked requests
    with patch("requests.Session.post") as mock_post, patch("requests.Session.patch") as mock_patch:
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_post.return_value = mock_res
        mock_patch.return_value = mock_res

        res_pw = bridge.change_account_password(acc.id, "old", "new")
        assert res_pw["success"] is True

        res_dn = bridge.set_account_display_name(acc.id, "SuperUser")
        assert res_dn["display_name"] == "SuperUser"

        res_fr = bridge.send_account_friend_request(acc.id, 5555)
        assert res_fr["success"] is True

        service.player_search.search_players = MagicMock(
            return_value=[{"user_id": 7777, "name": "ExactTarget", "display_name": "Target"}]
        )
        assert bridge.block_account_user(acc.id, "ExactTarget")["target_user_id"] == 7777
        assert bridge.set_account_follow_privacy(acc.id, "Friends")["success"] is True
        assert bridge.unlock_account_pin(acc.id, "1234")["success"] is True
        with pytest.raises(RuntimeError, match="six digits"):
            bridge.quick_log_in_account(acc.id, "12")

    # Test VIP link bridge call
    vip_res = bridge.parse_vip_link("https://www.roblox.com/games/100/Test?code=vip_code_999")
    assert vip_res["place_id"] == 100
    assert vip_res["link_code"] == "vip_code_999"

    service.close()
