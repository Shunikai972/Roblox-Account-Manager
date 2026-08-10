from __future__ import annotations

from pathlib import Path

import pytest

import app.backend.services.application_service as application_service_module
from app.backend.api import DesktopBridge
from app.backend.core.config import AppPaths
from app.backend.core.errors import StorageError, ValidationError
from app.backend.core.windows_startup import StartupRegistrationError, WindowsStartupStatus
from app.backend.services import ApplicationService


class _Roblox:
    def close(self) -> None:
        return None


class _StartupManager:
    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = enabled
        self.enable_calls = 0
        self.disable_calls = 0

    def inspect(self) -> WindowsStartupStatus:
        return WindowsStartupStatus(
            supported=True,
            accessible=True,
            registered=self.enabled,
            enabled=self.enabled,
            needs_repair=False,
        )

    def enable(self) -> WindowsStartupStatus:
        self.enable_calls += 1
        self.enabled = True
        return self.inspect()

    def disable(self) -> WindowsStartupStatus:
        self.disable_calls += 1
        self.enabled = False
        return self.inspect()


def _paths(tmp_path: Path) -> AppPaths:
    root = tmp_path / "app-data"
    return AppPaths(
        root=root,
        database=root / "astro.db",
        logs=root / "logs",
        backups=root / "backups",
        cache=root / "cache",
        exports=root / "exports",
    )


def _service(tmp_path: Path, **kwargs: object) -> ApplicationService:
    return ApplicationService(paths=_paths(tmp_path), roblox=_Roblox(), **kwargs)  # type: ignore[arg-type]


def test_development_runtime_never_registers_python_and_reports_clear_unavailability(tmp_path: Path) -> None:
    service = _service(tmp_path, runtime_is_frozen=False)
    try:
        status = service.get_windows_startup_status()

        assert status["available"] is False
        assert status["enabled"] is False
        assert "Python" in status["reason"]
        with pytest.raises(ValidationError, match="Python"):
            service.set_windows_startup(True, confirm=True)
        assert service.get_settings()["categories"]["general"]["start_with_windows"] is False
    finally:
        service.close()


def test_startup_service_requires_confirmation_then_updates_registry_and_setting_in_order(tmp_path: Path) -> None:
    manager = _StartupManager()
    service = _service(tmp_path, startup_manager=manager)
    try:
        with pytest.raises(ValidationError, match="Confirmez"):
            service.set_windows_startup(True)
        assert manager.enable_calls == 0
        assert service.get_settings()["categories"]["general"]["start_with_windows"] is False

        enabled = service.set_windows_startup(True, confirm=True)
        assert enabled["available"] is True
        assert enabled["enabled"] is True
        assert enabled["configured"] is True
        assert manager.enable_calls == 1
        assert service.get_settings()["categories"]["general"]["start_with_windows"] is True

        disabled = service.set_windows_startup(False, confirm=True)
        assert disabled["enabled"] is False
        assert disabled["configured"] is False
        assert manager.disable_calls == 1
        assert service.get_settings()["categories"]["general"]["start_with_windows"] is False
    finally:
        service.close()


def test_bridge_forwards_confirmation_and_keeps_registry_paths_out_of_status(tmp_path: Path) -> None:
    manager = _StartupManager()
    service = _service(tmp_path, startup_manager=manager)
    try:
        bridge = DesktopBridge(service)
        status = bridge.get_windows_startup_status()
        assert status["available"] is True
        assert not any("path" in key.casefold() or "command" in key.casefold() for key in status)

        with pytest.raises(RuntimeError, match="Confirmez"):
            bridge.set_windows_startup(True)
        assert manager.enable_calls == 0

        result = bridge.set_windows_startup(True, True)
        assert result["enabled"] is True
        assert service.get_settings()["categories"]["general"]["start_with_windows"] is True
    finally:
        service.close()


def test_startup_setting_is_not_mutable_through_generic_settings_route(tmp_path: Path) -> None:
    manager = _StartupManager()
    service = _service(tmp_path, startup_manager=manager)
    try:
        with pytest.raises(ValidationError, match="action dédiée"):
            service.update_settings({"categories": {"general": {"start_with_windows": True}}})
        assert manager.enable_calls == 0
        assert service.get_settings()["categories"]["general"]["start_with_windows"] is False
    finally:
        service.close()


def test_failed_registry_change_does_not_update_persisted_startup_preference(tmp_path: Path) -> None:
    class _FailingStartupManager(_StartupManager):
        def enable(self) -> WindowsStartupStatus:
            self.enable_calls += 1
            raise StartupRegistrationError("private Windows detail")

    manager = _FailingStartupManager()
    service = _service(tmp_path, startup_manager=manager)
    try:
        with pytest.raises(StorageError, match="n'a pas pu modifier"):
            service.set_windows_startup(True, confirm=True)
        assert manager.enable_calls == 1
        assert service.get_settings()["categories"]["general"]["start_with_windows"] is False
    finally:
        service.close()


def test_frozen_service_constructs_manager_from_its_runtime_executable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    executable = tmp_path / "AstroAccountManager.exe"
    executable.write_bytes(b"MZ")
    manager = _StartupManager()
    seen: list[Path] = []

    def factory(path: Path | str) -> _StartupManager:
        seen.append(Path(path))
        return manager

    monkeypatch.setattr(application_service_module, "WindowsStartupManager", factory)
    service = _service(
        tmp_path,
        runtime_is_frozen=True,
        runtime_executable=executable,
    )
    try:
        assert seen == [executable]
        assert service.get_windows_startup_status()["available"] is True
    finally:
        service.close()
