"""Tests for Windows Multi-Instance controller and service integration."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

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
    assert success is controller.is_enabled

    status_enabled = controller.get_status()
    assert status_enabled["enabled"] is success
    assert status_enabled["handle_count"] in (0, 1)

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
    assert toggled["enabled"] in (True, False)
    assert toggled["configured"] is True
    assert service.repository.get_setting("instances.allow_multiple_launches") is True

    toggled_off = bridge.set_multi_instance(False)
    assert toggled_off["enabled"] is False
    assert toggled_off["configured"] is False
    assert service.repository.get_setting("instances.allow_multiple_launches") is False

    service.close()


def test_persisted_multi_instance_preference_is_applied_on_startup(tmp_path: Path):
    paths = _paths(tmp_path)
    repo = SQLiteRepository(paths.database)
    repo.set_setting("instances.allow_multiple_launches", True)
    controller = MagicMock()
    controller.get_status.return_value = {"supported": True, "enabled": True, "handle_count": 1}
    controller.enable_multi_instance.return_value = True

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "app.backend.services.application_service.WindowsMultiInstanceController",
            lambda: controller,
        )
        service = ApplicationService(paths=paths, repository=repo)
    try:
        controller.enable_multi_instance.assert_called_once_with()
        assert service.bootstrap()["multi_instance"]["configured"] is True
        assert service.bootstrap()["multi_instance"]["enabled"] is True
    finally:
        service.close()
