from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.backend.models.domain import Game
from app.backend.repositories.sqlite_repository import SQLiteRepository
from app.backend.security.dpapi import CurrentUserDPAPI
from app.backend.storage.backups import VersionedBackupManager
from app.backend.storage.legacy_migrator import (
    LEGACY_DPAPI_ENTROPY,
    LEGACY_RAM_HEADER,
    LegacyDataMigrator,
    LegacyFormat,
)


def _migrator(tmp_path: Path) -> tuple[SQLiteRepository, LegacyDataMigrator]:
    repository = SQLiteRepository(tmp_path / "app.db")
    return repository, LegacyDataMigrator(repository, VersionedBackupManager(tmp_path / "backups"))


def test_scan_and_default_migration_do_not_parse_account_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    account_data = tmp_path / "AccountData.json"
    account_data.write_text("[]", encoding="utf-8")
    repository, migrator = _migrator(tmp_path)
    try:
        assert migrator.scan(tmp_path)[0].format is LegacyFormat.PLAINTEXT_JSON
        monkeypatch.setattr(
            migrator,
            "_load_account_payload",
            lambda *args, **kwargs: pytest.fail("default migration must not load AccountData"),
        )
        report = migrator.migrate(tmp_path)
        assert not report.account_metadata_imported
        assert report.accounts_imported == 0
        assert repository.list_accounts() == []
        assert len(report.backup_records) == 1
    finally:
        repository.close()


def test_explicit_plaintext_metadata_import_excludes_sessions_and_passwords(tmp_path: Path) -> None:
    payload = [
        {
            "Username": "metadata-only-user",
            "UserID": 42,
            "Group": "Imported",
            "Alias": "A",
            "Description": "Safe metadata",
            "SecurityToken": "non-production-session-placeholder",
            "Password": "non-production-password-placeholder",
            "BrowserTrackerID": "legacy-browser-tracker-placeholder",
            "Fields": {
                "Window_Position_X": "12",
                "password": "ignored",
                "BrowserTrackerWindow": "legacy-browser-tracker-placeholder",
            },
        }
    ]
    (tmp_path / "AccountData.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "RAMSettings.ini").write_text(
        "[General]\nCheckForUpdates=true\n[WebServer]\nPassword=must-not-import\n", encoding="utf-8"
    )
    repository, migrator = _migrator(tmp_path)
    try:
        report = migrator.migrate(tmp_path, import_account_metadata=True)
        assert report.account_metadata_imported
        assert report.accounts_imported == 1
        assert report.sessions_imported == 0
        assert report.saved_passwords_imported == 0
        account = repository.list_accounts()[0]
        assert account.has_session is False
        assert account.browser_tracker_id is None
        assert "password" not in account.custom_fields
        assert not any("browsertracker" in key.casefold() for key in account.custom_fields)
        assert repository.load_protected_secret(account.id, "session") is None
        assert repository.get_setting("legacy.settings.webserver.password") is None
        assert "non-production-session-placeholder" not in str(report)
        assert "non-production-password-placeholder" not in str(report)
    finally:
        repository.close()


def test_metadata_import_preserves_legacy_numeric_group_prefix_order(tmp_path: Path) -> None:
    # The account list itself is deliberately in a different order: RAM 3.7.2
    # ordered group headers using the hidden numeric name prefix instead.
    (tmp_path / "AccountData.json").write_text(
        json.dumps(
            [
                {"Username": "zebra-user", "Group": "Zebra"},
                {"Username": "ten-user", "Group": "10 Tangerine"},
                {"Username": "first-user", "Group": "001 Apple"},
                {"Username": "second-user", "Group": "2 Banana"},
            ]
        ),
        encoding="utf-8",
    )
    repository, migrator = _migrator(tmp_path)
    try:
        report = migrator.migrate(tmp_path, import_account_metadata=True)
        assert report.groups_imported == 4
        assert [group.name for group in repository.list_groups()] == [
            "001 Apple",
            "2 Banana",
            "10 Tangerine",
            "Zebra",
        ]
        assert [group.sort_order for group in repository.list_groups()] == [0, 1, 2, 3]
    finally:
        repository.close()


def test_legacy_ini_maps_compatible_settings_and_theme_without_enabling_unsafe_controls(tmp_path: Path) -> None:
    (tmp_path / "RAMSettings.ini").write_text(
        """[General]
MaxRecentGames=12
AccountJoinDelay=8
ShowPresence=false
PresenceUpdateRate=5
EnableMultiRbx=true
AutoCookieRefresh=true
UnlockFPS=true
NopechaKey=must-not-import

[Developer]
DevMode=true
EnableWebServer=true

[WebServer]
WebServerPort=8123
AllowExternalConnections=true
Password=must-not-import

[Watcher]
Enabled=false
ScanInterval=11
ExpectedWindowTitle=Roblox Player
SaveWindowPositions=true
ExitIfNoConnection=true

[Extension]
ColumnWidth=44
""",
        encoding="utf-8",
    )
    (tmp_path / "RAMTheme.ini").write_text(
        """[Roblox Account Manager]
FormsBG=#E0E0E0
ButtonsBG=#2468AC
AccountsBG=#1E1F28
ButtonsFG=#FFFFFF
DarkTopBar=false
ButtonStyle=Popup
""",
        encoding="utf-8",
    )
    repository, migrator = _migrator(tmp_path)
    try:
        report = migrator.migrate(tmp_path)
        assert report.settings_imported >= 20
        assert repository.get_setting("general.max_recent_games") == 12
        assert repository.get_setting("general.launch_delay_ms") == 8_000
        assert repository.get_setting("accounts.show_presence") is False
        assert repository.get_setting("accounts.presence_update_seconds") == 300
        assert repository.get_setting("developer.enabled") is True
        assert repository.get_setting("api.port") == 8123
        assert repository.get_setting("watcher.enabled") is False
        assert repository.get_setting("watcher.scan_interval_seconds") == 11
        assert repository.get_setting("watcher.expected_window_title") == "Roblox Player"
        assert repository.get_setting("instances.remember_window_positions") is True
        assert repository.get_setting("appearance.theme") == "light"
        assert repository.get_setting("appearance.accent") == "#2468ac"
        assert repository.get_setting("legacy.theme.roblox_account_manager.accountsbg") == "#1e1f28"
        assert repository.get_setting("legacy.theme.roblox_account_manager.buttonstyle") == "popup"
        assert repository.get_setting("legacy.settings.extension.columnwidth") == 44

        # Do not restore patching, browser-cookie refresh, remote binding, or
        # password controls merely because an old INI had them enabled.
        assert repository.get_setting("instances.allow_multiple_launches") is None
        assert repository.get_setting("api.enabled") is None
        assert repository.get_setting("api.host") is None
        assert repository.get_setting("legacy.settings.general.enablemultirbx") is None
        assert repository.get_setting("legacy.settings.general.autocookierefresh") is None
        assert repository.get_setting("legacy.settings.general.nopechakey") is None
        assert repository.get_setting("legacy.settings.webserver.password") is None
        assert repository.get_setting("legacy.settings.webserver.allowexternalconnections") is None
        assert repository.get_setting("legacy.settings.watcher.exitifnoconnection") is None
    finally:
        repository.close()


def test_invalid_legacy_settings_and_theme_values_are_retained_only_when_safe(tmp_path: Path) -> None:
    (tmp_path / "RAMSettings.ini").write_text(
        """[General]
MaxRecentGames=0
AccountJoinDelay=61
ShowPresence=not-a-boolean
PresenceUpdateRate=10000

[WebServer]
WebServerPort=70000

[Watcher]
ScanInterval=600
ExpectedWindowTitle=\x01invalid
""",
        encoding="utf-8",
    )
    (tmp_path / "RAMTheme.ini").write_text(
        """[Roblox Account Manager]
FormsBG=red
ButtonsBG=url(javascript:alert(1))
ButtonStyle=not-a-winforms-style
""",
        encoding="utf-8",
    )
    repository, migrator = _migrator(tmp_path)
    try:
        migrator.migrate(tmp_path)
        assert repository.get_setting("legacy.settings.general.maxrecentgames") == 0
        assert repository.get_setting("general.max_recent_games") is None
        assert repository.get_setting("general.launch_delay_ms") is None
        assert repository.get_setting("accounts.show_presence") is None
        assert repository.get_setting("accounts.presence_update_seconds") is None
        assert repository.get_setting("api.port") is None
        assert repository.get_setting("watcher.scan_interval_seconds") is None
        assert repository.get_setting("watcher.expected_window_title") is None
        assert repository.get_setting("appearance.theme") is None
        assert repository.get_setting("appearance.accent") is None
        assert repository.get_setting("legacy.theme.roblox_account_manager.formsbg") is None
        assert repository.get_setting("legacy.theme.roblox_account_manager.buttonstyle") is None
    finally:
        repository.close()


def test_legacy_recent_games_preserve_order_metadata_and_migrated_limit(tmp_path: Path) -> None:
    (tmp_path / "RAMSettings.ini").write_text("[General]\nMaxRecentGames=2\n", encoding="utf-8")
    (tmp_path / "RecentGames.json").write_text(
        json.dumps(
            [
                {"Details": {"placeId": 101, "name": "Oldest"}},
                {
                    "Details": {
                        "placeId": 202,
                        "name": "Kept favourite",
                        "url": "https://www.roblox.com/games/202?token=not-retained",
                        "isPlayable": "false",
                        "hasVerifiedBadge": "false",
                        "universeRootPlaceId": 201,
                        "sourceName": "Creator",
                        "sourceDescription": "Legacy game details",
                        "price": 0,
                        "imageToken": "must-not-import",
                    },
                    "ImageUrl": "https://tr.rbxcdn.com/icon.png?token=not-retained",
                },
                {"Details": {"placeId": 303, "name": "Newest"}},
            ]
        ),
        encoding="utf-8",
    )
    repository, migrator = _migrator(tmp_path)
    try:
        repository.save_game(Game(place_id=202, name="Existing", is_favorite=True, metadata={"current": "kept"}))
        report = migrator.migrate(tmp_path)
        recent = repository.list_games(recent_only=True)
        assert report.games_imported == 3
        assert [game.place_id for game in recent] == [303, 202]
        kept = repository.get_game_by_place_id(202)
        assert kept is not None
        assert kept.is_favorite is True
        assert kept.last_used_at is not None
        assert kept.icon_url == "https://tr.rbxcdn.com/icon.png"
        assert kept.metadata["current"] == "kept"
        assert kept.metadata["legacy"] == {
            "url": "https://www.roblox.com/games/202",
            "source_name": "Creator",
            "source_description": "Legacy game details",
            "is_playable": False,
            "has_verified_badge": False,
            "universe_root_place_id": 201,
            "price": 0,
            "recent_order": 1,
        }
        assert repository.get_game_by_place_id(101) is None
    finally:
        repository.close()


def test_secret_request_requires_separate_consent(tmp_path: Path) -> None:
    (tmp_path / "AccountData.json").write_text(
        json.dumps([{"Username": "consent-user", "SecurityToken": "placeholder"}]), encoding="utf-8"
    )
    repository, migrator = _migrator(tmp_path)
    try:
        report = migrator.migrate(tmp_path, import_account_metadata=True, include_sessions=True)
        account = repository.list_accounts()[0]
        assert report.secret_import_requires_consent
        assert report.sessions_imported == 0
        assert not account.has_session
        assert repository.load_protected_secret(account.id, "session") is None
    finally:
        repository.close()


def test_password_encrypted_format_is_detected_without_decrypting(tmp_path: Path) -> None:
    (tmp_path / "AccountData.json").write_bytes(LEGACY_RAM_HEADER + b"\x00" * 64)
    repository, migrator = _migrator(tmp_path)
    try:
        detection = migrator.scan(tmp_path)[0]
        assert detection.format is LegacyFormat.PASSWORD_ENCRYPTED
        report = migrator.migrate(tmp_path, import_account_metadata=True)
        assert not report.account_metadata_imported
        assert any("password-encrypted" in warning for warning in report.warnings)
    finally:
        repository.close()


def test_explicit_dpapi_metadata_migration_uses_active_windows_user_only(tmp_path: Path) -> None:
    dpapi = CurrentUserDPAPI()
    if not dpapi.available:
        pytest.skip("Windows DPAPI is unavailable")
    payload = json.dumps([{"Username": "dpapi-metadata-user", "Group": "DPAPI"}]).encode("utf-8")
    (tmp_path / "AccountData.json").write_bytes(dpapi.protect(payload, entropy=LEGACY_DPAPI_ENTROPY))
    repository, migrator = _migrator(tmp_path)
    try:
        assert migrator.scan(tmp_path)[0].format is LegacyFormat.DPAPI
        report = migrator.migrate(tmp_path, import_account_metadata=True)
        assert report.account_metadata_imported
        assert [account.username for account in repository.list_accounts()] == ["dpapi-metadata-user"]
    finally:
        repository.close()
