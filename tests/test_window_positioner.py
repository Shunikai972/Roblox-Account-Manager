"""Tests for window positioning service and bridge integration."""

import sys
from pathlib import Path

from app.backend.api.bridge import DesktopBridge
from app.backend.core.config import AppPaths
from app.backend.repositories.sqlite_repository import SQLiteRepository
from app.backend.services.application_service import ApplicationService
from app.backend.watchers.window_positioner import RobloxWindowPositioner


def _paths(tmp_path: Path) -> AppPaths:
    return AppPaths(
        root=tmp_path,
        database=tmp_path / "astro.db",
        logs=tmp_path / "logs",
        backups=tmp_path / "backups",
        cache=tmp_path / "cache",
        exports=tmp_path / "exports",
    )


def test_window_positioner_handles():
    # Non-existent PID returns False gracefully without throwing
    success = RobloxWindowPositioner.position_window(pid=999999, x=100, y=100, width=800, height=600)
    assert success is False
    assert RobloxWindowPositioner.position_window(pid=1, x=0, y=0, width=0, height=0) is False
    assert RobloxWindowPositioner.position_window(pid=True, x=0, y=0) is False


def test_position_window_service_and_bridge(tmp_path: Path):
    paths = _paths(tmp_path)
    repo = SQLiteRepository(paths.database)
    service = ApplicationService(paths=paths, repository=repo)
    bridge = DesktopBridge(service)

    res = bridge.position_instance_window(pid=1234, x=50, y=50, width=1024, height=768)
    assert res["pid"] == 1234
    assert res["x"] == 50
    assert res["y"] == 50
    assert res["width"] == 1024
    assert res["height"] == 768

    service.close()
