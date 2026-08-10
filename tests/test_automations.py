"""Tests for historical Roblox automations: FPS patcher & batch launcher."""

import time
from pathlib import Path

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

    # Set FPS cap to 144
    success = patcher.set_fps_cap(144)
    assert success is True
    assert patcher.get_fps_cap() == 144

    # Remove FPS cap
    removed = patcher.remove_fps_cap()
    assert removed is True
    assert patcher.get_fps_cap() is None


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


def test_automations_service_and_bridge_integration(tmp_path: Path):
    paths = _paths(tmp_path)
    repo = SQLiteRepository(paths.database)
    service = ApplicationService(paths=paths, repository=repo)
    bridge = DesktopBridge(service)

    # FPS Cap via bridge
    res_set = bridge.set_fps_cap(240)
    assert res_set["success"] is True

    res_get = bridge.get_fps_cap()
    assert res_get["fps"] == 240

    res_rem = bridge.remove_fps_cap()
    assert res_rem["success"] is True

    service.close()
