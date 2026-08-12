from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.backend.core.config import AppPaths
from app.backend.core.errors import ValidationError
from app.backend.models.domain import InstanceInfo
from app.backend.services.application_service import ApplicationService
from app.backend.watchers import TerminationResult, TerminationStatus


def _paths(tmp_path: Path) -> AppPaths:
    return AppPaths(
        root=tmp_path,
        database=tmp_path / "astro.db",
        logs=tmp_path / "logs",
        backups=tmp_path / "backups",
        cache=tmp_path / "cache",
        exports=tmp_path / "exports",
    )


def _instance(*, pid: int, account_id: str | None, memory_mb: int = 400) -> InstanceInfo:
    return InstanceInfo(
        pid=pid,
        name="RobloxPlayerBeta.exe",
        started_at=(datetime.now(UTC) - timedelta(seconds=90)).isoformat(),
        memory_bytes=memory_mb * 1024 * 1024,
        account_id=account_id,
        account_username="WindowUser" if account_id else None,
        place_id=123,
        status="running" if account_id else "orphaned",
    )


def test_window_layout_is_captured_and_restored_for_bound_account(tmp_path: Path) -> None:
    monitor = MagicMock()
    positioner = MagicMock()
    positioner.inspect_window.return_value = {
        "pid": 4242,
        "title": "Roblox",
        "focused": False,
        "x": 20,
        "y": 30,
        "width": 900,
        "height": 700,
    }
    positioner.position_window.return_value = True
    service = ApplicationService(paths=_paths(tmp_path), monitor=monitor, window_positioner=positioner)
    try:
        account = service.create_account({"username": "WindowUser"})
        instance = _instance(pid=4242, account_id=account["id"])
        monitor.current_instances.return_value = (instance,)
        service.update_settings({"remember_window_positions": True})

        service._apply_instance_window_runtime(
            SimpleNamespace(instances=(instance,), started=(), complete=True)
        )
        stored = service.repository.get_account(account["id"])
        assert stored.metadata["window_layout"] == {
            "x": 20,
            "y": 30,
            "width": 900,
            "height": 700,
        }

        service._apply_instance_window_runtime(
            SimpleNamespace(instances=(instance,), started=(instance,), complete=True)
        )
        positioner.position_window.assert_called_with(
            4242, x=20, y=30, width=900, height=700
        )
        assert service._pending_window_restores == {}
    finally:
        service.close()


def test_manual_window_save_restore_requires_confirmation(tmp_path: Path) -> None:
    monitor = MagicMock()
    positioner = MagicMock()
    positioner.inspect_window.return_value = {
        "pid": 5151,
        "title": "Roblox",
        "focused": False,
        "x": 1,
        "y": 2,
        "width": 800,
        "height": 600,
    }
    positioner.position_window.return_value = True
    service = ApplicationService(paths=_paths(tmp_path), monitor=monitor, window_positioner=positioner)
    try:
        account = service.create_account({"username": "ManualWindow"})
        instance = _instance(pid=5151, account_id=account["id"])
        monitor.current_instances.return_value = (instance,)

        with pytest.raises(ValidationError, match="confirmation"):
            service.capture_instance_window(5151)
        saved = service.capture_instance_window(5151, confirm=True)
        assert saved["width"] == 800

        with pytest.raises(ValidationError, match="confirmation"):
            service.restore_instance_window(5151)
        restored = service.restore_instance_window(5151, confirm=True)
        assert restored["success"] is True
        positioner.position_window.assert_called_once_with(
            5151, x=1, y=2, width=800, height=600
        )
    finally:
        service.close()


def test_opt_in_health_rule_closes_only_verified_unfocused_window(tmp_path: Path) -> None:
    monitor = MagicMock()
    positioner = MagicMock()
    positioner.inspect_window.return_value = {
        "pid": 6262,
        "title": "Roblox",
        "focused": False,
        "x": 0,
        "y": 0,
        "width": 800,
        "height": 600,
    }
    monitor.terminate_known_process.return_value = TerminationResult(
        6262,
        TerminationStatus.TERMINATED,
        "Roblox instance closed.",
    )
    service = ApplicationService(paths=_paths(tmp_path), monitor=monitor, window_positioner=positioner)
    try:
        service.update_settings(
            {
                "categories": {
                    "watcher": {
                        "termination_enabled": True,
                        "close_if_memory_low": True,
                        "memory_low_mb": 200,
                    }
                }
            }
        )
        instance = _instance(pid=6262, account_id=None, memory_mb=100)
        service._apply_instance_window_runtime(
            SimpleNamespace(instances=(instance,), started=(), complete=True)
        )
        monitor.terminate_known_process.assert_called_once_with(
            6262, confirm=True, wait_timeout_seconds=0.5
        )

        monitor.terminate_known_process.reset_mock()
        positioner.inspect_window.return_value = {
            **positioner.inspect_window.return_value,
            "focused": True,
        }
        service._apply_instance_window_runtime(
            SimpleNamespace(instances=(instance,), started=(), complete=True)
        )
        monitor.terminate_known_process.assert_not_called()
    finally:
        service.close()

