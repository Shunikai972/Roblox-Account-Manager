"""Tests for historical Roblox automations: FPS patcher & batch launcher."""

import time
from pathlib import Path

import pytest

from app.backend.api.bridge import DesktopBridge
from app.backend.core.config import AppPaths
from app.backend.repositories.sqlite_repository import SQLiteRepository
from app.backend.roblox.batch_launcher import BatchLauncher
from app.backend.roblox.client_settings import ClientSettingsPatcher
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


def test_client_settings_patcher(tmp_path: Path):
    patcher = ClientSettingsPatcher(local_app_data=tmp_path)
    assert patcher.get_fps_cap() is None

    success = patcher.set_fps_cap(144)
    assert success is True
    assert patcher.get_fps_cap() == 144

    removed = patcher.remove_fps_cap()
    assert removed is True
    assert patcher.get_fps_cap() is None


def test_client_settings_updates_are_atomic_and_preserve_existing_flags(tmp_path: Path):
    patcher = ClientSettingsPatcher(local_app_data=tmp_path)
    patcher.settings_dir.mkdir(parents=True)
    patcher.settings_file.write_text('{"ExistingFlag": true}', encoding="utf-8")

    assert patcher.set_fps_cap(120) is True

    assert patcher.read_settings() == {"ExistingFlag": True, "DFIntTaskSchedulerTargetFps": 120}
    assert patcher.backup_file.read_text(encoding="utf-8") == '{"ExistingFlag": true}'


def test_client_settings_invalid_json_is_never_overwritten(tmp_path: Path):
    patcher = ClientSettingsPatcher(local_app_data=tmp_path)
    patcher.settings_dir.mkdir(parents=True)
    patcher.settings_file.write_text("{broken", encoding="utf-8")

    with pytest.raises(Exception, match="left it unchanged"):
        patcher.set_fps_cap(120)

    assert patcher.settings_file.read_text(encoding="utf-8") == "{broken"

def test_batch_launcher_execution():
    launched_ids = []

    def mock_launch(acc_id, target):
        launched_ids.append(acc_id)
        return {"accepted": True}

    launcher = BatchLauncher(launch_single_fn=mock_launch)
    status = launcher.start_batch(["acc1", "acc2"], delay_seconds=0.5)
    assert status["in_progress"] is True
    assert status["total"] == 2

    # Wait for completion
    time.sleep(1.2)
    final_status = launcher.get_status()
    assert final_status["in_progress"] is False
    assert final_status["launched"] == 2
    assert launched_ids == ["acc1", "acc2"]


def test_batch_launcher_rejects_duplicates_and_counts_rejected_launches():
    launcher = BatchLauncher(launch_single_fn=lambda account_id, target: {"accepted": account_id != "rejected"})
    with pytest.raises(Exception, match="duplicate"):
        launcher.start_batch(["same", "same"])

    launcher.start_batch(["accepted", "rejected"], delay_seconds=0.5)
    launcher._thread.join(timeout=2)
    assert launcher.get_status()["launched"] == 1
    assert launcher.get_status()["failed"] == 1


def test_automations_service_and_bridge_integration(tmp_path: Path):
    paths = _paths(tmp_path)
    repo = SQLiteRepository(paths.database)
    service = ApplicationService(
        paths=paths,
        repository=repo,
        client_settings=ClientSettingsPatcher(local_app_data=tmp_path),
    )
    bridge = DesktopBridge(service)

    # FPS Cap via bridge
    res_set = bridge.set_fps_cap(240)
    assert res_set["success"] is True

    res_get = bridge.get_fps_cap()
    assert res_get["fps"] == 240

    res_rem = bridge.remove_fps_cap()
    assert res_rem["success"] is True

    service.close()


def test_default_client_settings_path_uses_validated_roblox_version(monkeypatch, tmp_path: Path):
    version = tmp_path / "Versions" / "version-test"
    version.mkdir(parents=True)
    (version / "RobloxPlayerLauncher.exe").write_bytes(b"")
    monkeypatch.setattr(ClientSettingsPatcher, "_discover_version_directory", staticmethod(lambda: version))

    patcher = ClientSettingsPatcher()

    assert patcher.available is True
    assert patcher.settings_file == version / "ClientSettings" / "ClientAppSettings.json"


def test_default_client_settings_path_refuses_when_roblox_is_not_discovered(monkeypatch):
    monkeypatch.setattr(ClientSettingsPatcher, "_discover_version_directory", staticmethod(lambda: None))
    patcher = ClientSettingsPatcher()

    assert patcher.status()["available"] is False
    with pytest.raises(Exception, match="could not be found"):
        patcher.set_fps_cap(120)
