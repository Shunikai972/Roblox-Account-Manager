from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.backend.core.config import AppPaths
from app.backend.core.errors import NotFoundError, ValidationError
from app.backend.models.domain import Account, Group, InstanceInfo
from app.backend.roblox.window_visibility import (
    SW_HIDE,
    SW_MINIMIZE,
    SW_SHOWNOACTIVATE,
    WindowVisibilityManager,
)
from app.backend.services import ApplicationService


class _WindowApi:
    supported = True

    def __init__(self) -> None:
        self.windows = {101: 1001, 202: 2002}
        self.visible = {1001: True, 2002: True}
        self.minimized = {1001: False, 2002: False}
        self.calls: list[tuple[int, int]] = []

    def windows_for_pids(self, pids: set[int]) -> dict[int, int]:
        return {pid: self.windows[pid] for pid in pids if pid in self.windows}

    def is_window(self, hwnd: int) -> bool:
        return hwnd in self.visible

    def is_visible(self, hwnd: int) -> bool:
        return self.visible[hwnd]

    def is_minimized(self, hwnd: int) -> bool:
        return self.minimized[hwnd]

    def show(self, hwnd: int, command: int) -> bool:
        self.calls.append((hwnd, command))
        if command == SW_HIDE:
            self.visible[hwnd] = False
        elif command == SW_MINIMIZE:
            self.visible[hwnd] = True
            self.minimized[hwnd] = True
        elif command == SW_SHOWNOACTIVATE:
            self.visible[hwnd] = True
            self.minimized[hwnd] = False
        return True


class _Monitor:
    def __init__(self, instances: list[InstanceInfo]) -> None:
        self.instances = instances

    def current_instances(self) -> tuple[InstanceInfo, ...]:
        return tuple(self.instances)

    def scan(self) -> SimpleNamespace:
        return SimpleNamespace(instances=tuple(self.instances), events=(), complete=True)


class _Roblox:
    def close(self) -> None:
        return None


class _CompatibilitySettings:
    settings_file = Path("ClientAppSettings.json")

    def status(self) -> dict[str, object]:
        return {"available": True, "version_directory": r"C:\Roblox\Versions\version-abc", "reason": None}

    def read_global_settings(self) -> dict[str, object]:
        return {"available": True, "reason": None, "basic": {}, "advanced": []}

    def get_fps_cap(self) -> None:
        return None

    def verify_fps_targets(self) -> list[object]:
        return []

    def patch_launch_settings(self, *args: object, **kwargs: object) -> bool:
        return True


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


def test_visibility_manager_inspects_in_bulk_and_never_activates_a_window() -> None:
    api = _WindowApi()
    manager = WindowVisibilityManager(api)

    snapshots = manager.snapshot_many([101, 202])
    assert snapshots[101].visible is True
    assert snapshots[202].window_found is True

    assert manager.set_visible(101, False).to_dict()["hidden"] is True
    assert manager.set_visible(101, True).visible is True
    assert manager.minimize(202).minimized is True
    assert manager.restore(202).minimized is False
    assert api.calls == [
        (1001, SW_HIDE),
        (1001, SW_SHOWNOACTIVATE),
        (2002, SW_MINIMIZE),
        (2002, SW_SHOWNOACTIVATE),
    ]


def test_visibility_manager_rejects_unknown_or_invalid_processes() -> None:
    manager = WindowVisibilityManager(_WindowApi())
    with pytest.raises(ValidationError):
        manager.snapshot(0)
    with pytest.raises(ValidationError, match="No top-level"):
        manager.set_visible(999, False)


def test_service_visibility_is_limited_to_observed_pids_and_groups(tmp_path: Path) -> None:
    api = _WindowApi()
    monitor = _Monitor(
        [
            InstanceInfo(pid=101, name="Roblox", account_id="a1"),
            InstanceInfo(pid=202, name="Roblox", account_id="a2"),
        ]
    )
    service = ApplicationService(
        paths=_paths(tmp_path),
        roblox=_Roblox(),  # type: ignore[arg-type]
        monitor=monitor,  # type: ignore[arg-type]
        window_visibility=WindowVisibilityManager(api),
    )
    try:
        service.repository.save_group(Group(id="farm", name="Farm"))
        service.repository.save_account(Account(id="a1", username="AltOne", group_id="farm"))
        service.repository.save_account(Account(id="a2", username="Main"))

        assert service.list_instances()[0]["visibility"]["visible"] is True
        assert service.set_instance_visibility(101, False)["hidden"] is True
        grouped = service.set_group_visibility("farm", True)
        assert grouped["requested"] == 1
        assert grouped["applied"] == 1
        with pytest.raises(NotFoundError):
            service.set_instance_visibility(999, False)
    finally:
        service.close()


def test_focus_and_sleep_apply_the_real_plan_instead_of_reporting_false_success(tmp_path: Path) -> None:
    api = _WindowApi()
    monitor = _Monitor(
        [
            InstanceInfo(pid=101, name="Roblox", account_id="a1"),
            InstanceInfo(pid=202, name="Roblox", account_id="a2"),
        ]
    )
    service = ApplicationService(
        paths=_paths(tmp_path),
        roblox=_Roblox(),  # type: ignore[arg-type]
        monitor=monitor,  # type: ignore[arg-type]
        window_visibility=WindowVisibilityManager(api),
    )
    try:
        service.repository.save_account(Account(id="a1", username="AltOne"))
        service.repository.save_account(Account(id="a2", username="Main"))
        result = service.apply_comfort_action("focus", {"pid": 202})
        assert result["requested"] == 2
        assert result["minimized"] == 1
        assert result["applied"] is True
        assert api.calls[-2:] == [(1001, SW_MINIMIZE), (2002, SW_SHOWNOACTIVATE)]
    finally:
        service.close()


def test_compatibility_report_detects_and_records_a_roblox_version_without_launching(tmp_path: Path) -> None:
    service = ApplicationService(
        paths=_paths(tmp_path),
        roblox=_Roblox(),  # type: ignore[arg-type]
        monitor=_Monitor([]),  # type: ignore[arg-type]
        client_settings=_CompatibilitySettings(),  # type: ignore[arg-type]
        window_visibility=WindowVisibilityManager(_WindowApi()),
    )
    try:
        first = service.get_compatibility_report()
        assert first["roblox_version"] == "version-abc"
        assert first["recorded"] is False
        with pytest.raises(Exception, match="confirmation"):
            service.acknowledge_roblox_version()
        recorded = service.acknowledge_roblox_version(confirm=True)
        assert recorded["previous_roblox_version"] == "version-abc"
        assert recorded["version_changed"] is False
    finally:
        service.close()
