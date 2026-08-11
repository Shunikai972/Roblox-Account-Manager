from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.backend.core.config import AppPaths
from app.backend.core.errors import ValidationError
from app.backend.api import DesktopBridge
from app.backend.models.domain import Game, Server
from app.backend.roblox.types import LaunchResult, PresenceState, PublicUserProfile, UserPresence
from app.backend.services import ApplicationService
from app.backend.watchers import RobloxProcessMonitor


class _Monitor:
    def scan(self) -> SimpleNamespace:
        return SimpleNamespace(instances=(), events=())

    def current_instances(self) -> tuple[object, ...]:
        return ()


class _Roblox:
    def close(self) -> None:
        return None

    def get_game_details(self, place_id: int) -> Game:
        return Game(place_id=place_id, name="Example world", universe_id=99, playing=12, max_players=20)

    def list_public_servers(self, place_id: int) -> SimpleNamespace:
        return SimpleNamespace(
            servers=(Server(job_id="job-1", place_id=place_id, playing=4, max_players=20, ping=32.0),)
        )

    def get_public_profile(self, user_id: int) -> PublicUserProfile:
        return PublicUserProfile(
            user_id=user_id,
            username="RemoteIdentity",
            display_name="Remote display",
            description="Public account description",
            created_at="2020-01-01T00:00:00Z",
            avatar_url="https://tr.rbxcdn.com/example/150/150/AvatarHeadshot/Png",
            avatar_state="Completed",
        )

    def get_public_presence(self, user_ids: list[int]) -> tuple[UserPresence, ...]:
        return tuple(
            UserPresence(
                user_id=user_id,
                state=PresenceState.IN_GAME,
                last_location="Example world",
                place_id=123,
                root_place_id=123,
                game_id="job-public",
                universe_id=99,
            )
            for user_id in user_ids
        )


@dataclass
class _Launcher:
    launches: list[object]

    def launch(self, target: object) -> LaunchResult:
        self.launches.append(target)
        return LaunchResult(uri="roblox://experiences/start?placeId=123", launched=True)


@dataclass
class _ProcessMemory:
    rss: int


class _WatchedProcess:
    def __init__(self, pid: int, created_at: float) -> None:
        self.pid = pid
        self.created_at_value = created_at
        self.terminate_calls = 0
        self.kill_calls = 0

    @property
    def info(self) -> dict[str, object]:
        return {
            "pid": self.pid,
            "name": "RobloxPlayerBeta.exe",
            "create_time": self.created_at_value,
            "memory_info": _ProcessMemory(1_024),
            "status": "running",
        }

    def name(self) -> str:
        return "RobloxPlayerBeta.exe"

    def create_time(self) -> float:
        return self.created_at_value

    def terminate(self) -> None:
        self.terminate_calls += 1

    def wait(self, *, timeout: float) -> None:
        return None

    def kill(self) -> None:
        self.kill_calls += 1


class _ProcessSource:
    def __init__(self, processes: list[_WatchedProcess]) -> None:
        self.processes = processes

    def __call__(self, *, attrs: list[str] | None = None) -> list[_WatchedProcess]:
        return list(self.processes)


class _Clock:
    def __init__(self, value: float = 1_700_000_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _paths(tmp_path: Path) -> AppPaths:
    root = tmp_path / "app-data"
    return AppPaths(
        root=root,
        database=root / "asteria.db",
        logs=root / "logs",
        backups=root / "backups",
        cache=root / "cache",
        exports=root / "exports",
    )


def test_account_group_game_and_backup_use_cases_are_persisted(tmp_path: Path) -> None:
    launcher = _Launcher([])
    service = ApplicationService(
        paths=_paths(tmp_path),
        roblox=_Roblox(),  # type: ignore[arg-type]
        launcher=launcher,  # type: ignore[arg-type]
        monitor=_Monitor(),  # type: ignore[arg-type]
    )
    try:
        group = service.create_group({"name": "Raiders", "color": "#ff665a"})
        account = service.create_account({"username": "ExampleUser", "group_id": group["id"]})

        assert account["group_id"] == group["id"]
        assert service.list_accounts("example")[0]["username"] == "ExampleUser"

        edited = service.update_account(account["id"], {"notes": "Local note", "favorite": True})
        assert edited["notes"] == "Local note"
        assert edited["favorite"] is True

        game = service.get_game(123)
        assert game["title"] == "Example world"
        assert service.list_servers(123)[0]["job_id"] == "job-1"

        result = service.launch_account(account["id"], {"place_id": 123})
        assert result["accepted"] is True
        assert launcher.launches

        backup = service.backup_data()
        assert backup["verified"] is True
        assert Path(backup["path"]).is_dir()
        assert service.get_activity()
        assert service.get_notifications()
    finally:
        service.close()


def test_flat_frontend_settings_are_mapped_to_central_categories(tmp_path: Path) -> None:
    service = ApplicationService(
        paths=_paths(tmp_path),
        roblox=_Roblox(),  # type: ignore[arg-type]
        launcher=_Launcher([]),  # type: ignore[arg-type]
        monitor=_Monitor(),  # type: ignore[arg-type]
    )
    try:
        settings = service.update_settings(
            {"theme": "light", "accent": "#2367d1", "watcher_enabled": False}
        )

        assert settings["theme"] == "light"
        assert settings["accent"] == "#2367d1"
        assert settings["watcher_enabled"] is False
    finally:
        service.close()


def test_public_profile_avatar_and_presence_are_refreshable_without_a_session(tmp_path: Path) -> None:
    service = ApplicationService(
        paths=_paths(tmp_path),
        roblox=_Roblox(),  # type: ignore[arg-type]
        launcher=_Launcher([]),  # type: ignore[arg-type]
        monitor=_Monitor(),  # type: ignore[arg-type]
    )
    try:
        account = service.create_account({"username": "LocalName", "user_id": 42})

        profile = service.get_public_profile("42")
        refreshed_profile = service.refresh_account_public_profile(account["id"])
        presence = service.get_public_presence([42])
        refreshed_presence = service.refresh_account_presence([account["id"]])

        assert profile["username"] == "RemoteIdentity"
        assert profile["profile_url"] == "https://www.roblox.com/users/42/profile"
        assert refreshed_profile["account"]["username"] == "LocalName"
        assert refreshed_profile["account"]["display_name"] == "Remote display"
        assert refreshed_profile["account"]["avatar_url"].startswith("https://tr.rbxcdn.com/")
        assert refreshed_profile["account"]["metadata"]["public_profile"]["username"] == "RemoteIdentity"
        assert presence == [
            {
                "user_id": 42,
                "state": "in_game",
                "last_location": "Example world",
                "place_id": 123,
                "root_place_id": 123,
                "game_id": "job-public",
                "universe_id": 99,
                "last_online": None,
            }
        ]
        assert refreshed_presence[0]["presence"]["state"] == "in_game"
        persisted = service.list_accounts()[0]
        assert persisted["status"] == "ready"
        assert persisted["metadata"]["public_presence"]["state"] == "in_game"
        assert persisted["has_session"] is False
    finally:
        service.close()


def test_public_profile_bridge_methods_do_not_require_or_return_a_session(tmp_path: Path) -> None:
    service = ApplicationService(
        paths=_paths(tmp_path),
        roblox=_Roblox(),  # type: ignore[arg-type]
        launcher=_Launcher([]),  # type: ignore[arg-type]
        monitor=_Monitor(),  # type: ignore[arg-type]
    )
    try:
        bridge = DesktopBridge(service)
        account = bridge.create_account({"username": "BridgePublic", "user_id": 73})

        profile = bridge.get_public_profile(73)
        presence = bridge.refresh_account_presence([account["id"]])

        assert profile["user_id"] == 73
        assert "session" not in profile
        assert presence[0]["user_id"] == 73
        assert bridge.refresh_account_public_profile(account["id"])["account"]["has_session"] is False
    finally:
        service.close()


def test_recent_games_favorites_and_removal_are_persisted_and_bounded(tmp_path: Path) -> None:
    service = ApplicationService(
        paths=_paths(tmp_path),
        roblox=_Roblox(),  # type: ignore[arg-type]
        launcher=_Launcher([]),  # type: ignore[arg-type]
        monitor=_Monitor(),  # type: ignore[arg-type]
    )
    try:
        service.update_settings({"categories": {"general": {"max_recent_games": 2}}})
        service.get_game(101)
        service.get_game(102)
        service.get_game(103)

        assert [game["place_id"] for game in service.list_recent_games()] == [103, 102]
        assert service.repository.get_game_by_place_id(101) is None

        favorite = service.set_game_favorite(101, True)
        assert favorite["favorite"] is True
        assert favorite["last_used_at"] is None
        assert [game["place_id"] for game in service.list_favorite_games()] == [101]
        assert service.set_game_favorite(101, False)["favorite"] is False
        assert service.remove_game(102) == {"deleted": 102}
        assert [game["place_id"] for game in service.list_recent_games()] == [103]

        bridge = DesktopBridge(service)
        assert bridge.set_game_favorite(103, True)["favorite"] is True
        assert bridge.remove_game(103) == {"deleted": 103}
    finally:
        service.close()


def test_successful_launch_records_a_recent_game_without_a_network_lookup(tmp_path: Path) -> None:
    launcher = _Launcher([])
    service = ApplicationService(
        paths=_paths(tmp_path),
        roblox=_Roblox(),  # type: ignore[arg-type]
        launcher=launcher,  # type: ignore[arg-type]
        monitor=_Monitor(),  # type: ignore[arg-type]
    )
    try:
        service.repository.save_game(Game(place_id=456, name="Launch world"))
        account = service.create_account({"username": "LaunchHistory", "place_id": 456})

        result = service.launch_account(account["id"])

        assert result["accepted"] is True
        recent = service.list_recent_games()
        assert [game["place_id"] for game in recent] == [456]
        assert recent[0]["title"] == "Launch world"
        assert launcher.launches
    finally:
        service.close()


def test_lowering_recent_game_limit_trims_immediately_without_losing_a_favorite(tmp_path: Path) -> None:
    service = ApplicationService(
        paths=_paths(tmp_path),
        roblox=_Roblox(),  # type: ignore[arg-type]
        launcher=_Launcher([]),  # type: ignore[arg-type]
        monitor=_Monitor(),  # type: ignore[arg-type]
    )
    try:
        service.repository.save_game(
            Game(place_id=1, name="Favorite older", is_favorite=True, last_used_at="2026-08-10T10:00:00+00:00")
        )
        service.repository.save_game(Game(place_id=2, name="Newest", last_used_at="2026-08-10T11:00:00+00:00"))

        service.update_settings({"categories": {"general": {"max_recent_games": 1}}})

        assert [game["place_id"] for game in service.list_recent_games()] == [2]
        favorite = service.repository.get_game_by_place_id(1)
        assert favorite is not None
        assert favorite.is_favorite is True
        assert favorite.last_used_at is None
    finally:
        service.close()


def test_rebrand_metadata_filename_and_diagnostic_log_fallback(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    service = ApplicationService(
        paths=paths,
        roblox=_Roblox(),  # type: ignore[arg-type]
        launcher=_Launcher([]),  # type: ignore[arg-type]
        monitor=_Monitor(),  # type: ignore[arg-type]
    )
    try:
        legacy_log = paths.logs / "asteria.log"
        legacy_log.write_text("2026 INFO legacy diagnostic", encoding="utf-8")
        assert service.get_diagnostics()["logs"][0]["message"].endswith("legacy diagnostic")

        current_log = paths.logs / "astro-account-manager.log"
        current_log.write_text("2026 INFO current diagnostic", encoding="utf-8")
        assert service.get_diagnostics()["logs"][0]["message"].endswith("current diagnostic")
        assert service.export_metadata()["filename"].startswith("astro-metadata-")
    finally:
        service.close()


def test_group_state_and_avatar_presentation_are_persisted_without_secrets(tmp_path: Path) -> None:
    service = ApplicationService(
        paths=_paths(tmp_path),
        roblox=_Roblox(),  # type: ignore[arg-type]
        launcher=_Launcher([]),  # type: ignore[arg-type]
        monitor=_Monitor(),  # type: ignore[arg-type]
    )
    try:
        group = service.create_group({"name": "Builders", "color": "mint"})
        collapsed = service.update_group(group["id"], {"collapsed": True, "favorite": True})
        account = service.create_account(
            {"username": "PresentationUser", "group_id": group["id"], "avatar_color": "coral"}
        )

        assert collapsed["collapsed"] is True
        assert collapsed["favorite"] is True
        assert collapsed["color"] == "mint"
        assert account["avatar_color"] == "coral"
        assert "session" not in account
        assert service.bootstrap()["groups"][0]["collapsed"] is True

        assert service.delete_group(group["id"]) == {"deleted": group["id"]}
        assert service.list_accounts()[0]["group_id"] is None
    finally:
        service.close()


def test_verified_backup_restore_requires_confirmation_and_reopens_storage(tmp_path: Path) -> None:
    service = ApplicationService(
        paths=_paths(tmp_path),
        roblox=_Roblox(),  # type: ignore[arg-type]
        launcher=_Launcher([]),  # type: ignore[arg-type]
        monitor=_Monitor(),  # type: ignore[arg-type]
    )
    try:
        account = service.create_account({"username": "RestoreUser", "notes": "before"})
        backup = service.backup_data()
        service.update_account(account["id"], {"notes": "after"})

        with pytest.raises(ValidationError):
            service.restore_backup(backup["id"])

        result = service.restore_backup(backup["id"], confirm=True)
        restored = service.list_accounts()[0]
        assert result["restored"] == backup["id"]
        assert result["pre_restore_backup"]
        assert restored["notes"] == "before"
    finally:
        service.close()


def test_desktop_bridge_forwards_confirmed_restore_arguments(tmp_path: Path) -> None:
    service = ApplicationService(
        paths=_paths(tmp_path),
        roblox=_Roblox(),  # type: ignore[arg-type]
        launcher=_Launcher([]),  # type: ignore[arg-type]
        monitor=_Monitor(),  # type: ignore[arg-type]
    )
    try:
        bridge = DesktopBridge(service)
        bridge.create_account({"username": "BridgeRestore"})
        backup = bridge.backup_data()
        bridge.update_account(bridge.list_accounts()[0]["id"], {"notes": "changed"})

        result = bridge.restore_backup(backup["id"], True)
        assert result["restored"] == backup["id"]
        assert bridge.list_accounts()[0]["notes"] == ""
    finally:
        service.close()


def test_public_metadata_export_and_confirmed_import_exclude_vault_material(tmp_path: Path) -> None:
    source = ApplicationService(
        paths=_paths(tmp_path / "source"),
        roblox=_Roblox(),  # type: ignore[arg-type]
        launcher=_Launcher([]),  # type: ignore[arg-type]
        monitor=_Monitor(),  # type: ignore[arg-type]
    )
    target = ApplicationService(
        paths=_paths(tmp_path / "target"),
        roblox=_Roblox(),  # type: ignore[arg-type]
        launcher=_Launcher([]),  # type: ignore[arg-type]
        monitor=_Monitor(),  # type: ignore[arg-type]
    )
    try:
        group = source.create_group({"name": "Portable", "color": "mint"})
        source.create_account(
            {
                "username": "PortableServiceUser",
                "group_id": group["id"],
                "avatar_color": "amber",
                "notes": "public note",
            }
        )
        source.repository.save_game(Game(place_id=5678, name="Portable service game"))
        exported = source.export_metadata()

        with pytest.raises(ValidationError):
            target.import_metadata(exported["path"])
        report = target.import_metadata(exported["path"], confirm=True)

        assert report["accounts"]["imported"] == 1
        assert report["games"]["imported"] == 1
        account = target.list_accounts()[0]
        assert account["username"] == "PortableServiceUser"
        assert account["avatar_color"] == "amber"
        assert account["has_session"] is False
        assert report["pre_import_backup"]
    finally:
        source.close()
        target.close()


def test_watcher_matches_launches_updates_account_and_relaunches_only_after_double_opt_in(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    process = _WatchedProcess(42, clock.value)
    source = _ProcessSource([process])
    monitor = RobloxProcessMonitor(
        process_iter=source,
        process_factory=lambda _: process,
        clock=clock,
    )
    launcher = _Launcher([])
    service = ApplicationService(
        paths=_paths(tmp_path),
        roblox=_Roblox(),  # type: ignore[arg-type]
        launcher=launcher,  # type: ignore[arg-type]
        monitor=monitor,
    )
    try:
        service.update_settings(
            {
                "categories": {
                    "watcher": {
                        "auto_relaunch_enabled": True,
                        "relaunch_delay_seconds": 5,
                        "relaunch_max_attempts": 1,
                    }
                }
            }
        )
        account = service.create_account({"username": "WatchedUser", "place_id": 123})
        rule = service.configure_account_watcher(
            account["id"],
            {
                "auto_relaunch": True,
                "relaunch_delay_seconds": 5,
                "relaunch_max_attempts": 1,
            },
        )
        assert rule["auto_relaunch"] is True

        launched = service.launch_account(account["id"], {"place_id": 123})
        assert launched["watcher_request_id"]
        service.refresh_instances()
        assert service.list_accounts()[0]["status"] == "in_game"

        source.processes = []
        clock.value += 10
        service.refresh_instances()
        assert len(monitor.pending_restarts()) == 1

        clock.value += 5
        service.refresh_instances()
        assert len(launcher.launches) == 2
        assert service.list_accounts()[0]["status"] == "launching"
        assert all("session" not in item for item in service.get_instance_monitor()["events"])
    finally:
        service.close()


def test_confirmed_instance_close_uses_graceful_termination_without_kill(tmp_path: Path) -> None:
    clock = _Clock()
    process = _WatchedProcess(84, clock.value)
    source = _ProcessSource([process])
    monitor = RobloxProcessMonitor(
        process_iter=source,
        process_factory=lambda _: process,
        clock=clock,
    )
    service = ApplicationService(
        paths=_paths(tmp_path),
        roblox=_Roblox(),  # type: ignore[arg-type]
        launcher=_Launcher([]),  # type: ignore[arg-type]
        monitor=monitor,
    )
    try:
        service.update_settings({"categories": {"watcher": {"termination_enabled": True}}})
        service.refresh_instances()
        result = service.close_instance(84, confirm=True)

        assert result["status"] == "terminated"
        assert process.terminate_calls == 1
        assert process.kill_calls == 0
        assert service.list_instances() == []
    finally:
        service.close()


def test_complete_account_reorder_is_persisted_and_exposed_by_bridge(tmp_path: Path) -> None:
    service = ApplicationService(
        paths=_paths(tmp_path),
        roblox=_Roblox(),  # type: ignore[arg-type]
        launcher=_Launcher([]),  # type: ignore[arg-type]
        monitor=_Monitor(),  # type: ignore[arg-type]
    )
    try:
        first = service.create_account({"username": "First"})
        second = service.create_account({"username": "Second"})
        third = service.create_account({"username": "Third"})
        bridge = DesktopBridge(service)

        reordered = bridge.reorder_accounts([third["id"], first["id"], second["id"]])

        assert [account["id"] for account in reordered] == [third["id"], first["id"], second["id"]]
        assert [account["sort_order"] for account in reordered] == [0, 1, 2]
        assert [account["id"] for account in bridge.list_accounts()] == [third["id"], first["id"], second["id"]]
        with pytest.raises(RuntimeError, match="duplicates"):
            bridge.reorder_accounts([third["id"], third["id"], second["id"]])
        assert [account["id"] for account in bridge.list_accounts()] == [third["id"], first["id"], second["id"]]
    finally:
        service.close()
