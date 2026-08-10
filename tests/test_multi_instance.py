"""Tests for Windows Multi-Instance controller and service integration."""

import sys
from pathlib import Path

import pytest

from app.backend.api.bridge import DesktopBridge
from app.backend.core.config import AppPaths
from app.backend.repositories.sqlite_repository import SQLiteRepository
from app.backend.roblox.multi_instance import WindowsMultiInstanceController
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


def test_multi_instance_controller_lifecycle():
    controller = WindowsMultiInstanceController()
    status_initial = controller.get_status()
    assert status_initial["supported"] == (sys.platform == "win32")
    assert status_initial["enabled"] is False

    # Enable
    success = controller.enable_multi_instance()
    assert success is True
    assert controller.is_enabled is True

    status_enabled = controller.get_status()
    assert status_enabled["enabled"] is True

    # Disable
    controller.disable_multi_instance()
    assert controller.is_enabled is False

    status_disabled = controller.get_status()
    assert status_disabled["enabled"] is False


def test_multi_instance_service_and_bridge_integration(tmp_path: Path):
    paths = _paths(tmp_path)
    repo = SQLiteRepository(paths.database)
    service = ApplicationService(paths=paths, repository=repo)
    bridge = DesktopBridge(service)

    # Bridge status check
    status = bridge.get_multi_instance_status()
    assert "supported" in status
    assert "enabled" in status

    # Toggle via bridge
    toggled = bridge.set_multi_instance(True)
    assert toggled["enabled"] is True

    toggled_off = bridge.set_multi_instance(False)
    assert toggled_off["enabled"] is False

    service.close()
