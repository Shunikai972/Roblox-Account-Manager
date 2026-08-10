from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.backend.api import DesktopBridge
from app.backend.core.config import AppPaths
from app.backend.roblox.errors import RobloxUwpError
from app.backend.roblox.uwp import (
    PowerShellResult,
    UwpLaunchResult,
    UwpRobloxPackage,
    WindowsUwpRobloxManager,
)
from app.backend.services import ApplicationService


class _Runner:
    def __init__(self, payload: object, *, returncode: int = 0) -> None:
        self.payload = payload
        self.returncode = returncode
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, command: tuple[str, ...]) -> PowerShellResult:
        self.commands.append(command)
        stdout = json.dumps(self.payload) if isinstance(self.payload, (dict, list)) else str(self.payload)
        return PowerShellResult(returncode=self.returncode, stdout=stdout)


def _package_payload() -> dict[str, object]:
    return {
        "packages": [
            {
                "Name": "ROBLOXCORPORATION.ROBLOX.Astro",
                "PackageFullName": "ROBLOXCORPORATION.ROBLOX.Astro_2.0.0.0_x64__55nm5eh3cm0pr",
                "PackageFamilyName": "ROBLOXCORPORATION.ROBLOX.Astro_55nm5eh3cm0pr",
                "Status": "Ok",
                "InstallLocation": "C:\\not-exported\\package",
            },
            {
                "Name": "NotRoblox",
                "PackageFullName": "NotRoblox_1.0_x64__abc",
                "PackageFamilyName": "NotRoblox_abc",
                "Status": "Ok",
            },
        ],
        "apps": [
            {
                "Name": "Roblox Astro",
                "AppID": "ROBLOXCORPORATION.ROBLOX.Astro_55nm5eh3cm0pr!App",
            },
            {"Name": "Other app", "AppID": "OtherFamily_abc!App"},
        ],
    }


def test_uwp_discovery_filters_to_registered_roblox_packages_without_install_paths() -> None:
    runner = _Runner(_package_payload())
    manager = WindowsUwpRobloxManager(runner=runner, platform_name=lambda: "Windows")

    packages = manager.list_packages()

    assert len(packages) == 1
    package = packages[0]
    assert package.package_name == "ROBLOXCORPORATION.ROBLOX.Astro"
    assert package.display_name == "Roblox Astro"
    assert package.launchable is True
    assert package.app_user_model_id == "ROBLOXCORPORATION.ROBLOX.Astro_55nm5eh3cm0pr!App"
    assert "InstallLocation" not in package.to_dict()
    assert runner.commands[0][:5] == (
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
    )
    assert "Get-AppxPackage" in runner.commands[0][-1]


def test_uwp_launch_rechecks_the_windows_registration_and_uses_apps_folder_only() -> None:
    runner = _Runner(_package_payload())
    opened: list[str] = []
    manager = WindowsUwpRobloxManager(
        runner=runner,
        opener=opened.append,
        platform_name=lambda: "Windows",
    )
    package_name = "ROBLOXCORPORATION.ROBLOX.Astro_2.0.0.0_x64__55nm5eh3cm0pr"

    result = manager.launch_package(package_name)

    assert result.launched is True
    assert opened == ["shell:AppsFolder\\ROBLOXCORPORATION.ROBLOX.Astro_55nm5eh3cm0pr!App"]
    assert len(runner.commands) == 1
    with pytest.raises(RobloxUwpError):
        manager.launch_package("arbitrary.application!App")
    assert len(opened) == 1


def test_uwp_discovery_has_a_clear_non_windows_capability_error() -> None:
    manager = WindowsUwpRobloxManager(runner=_Runner({}), platform_name=lambda: "Linux")

    with pytest.raises(RobloxUwpError, match="uniquement sous Windows"):
        manager.list_packages()


class _UwpManager:
    def __init__(self) -> None:
        self.package = UwpRobloxPackage(
            package_name="ROBLOXCORPORATION.ROBLOX.Astro",
            package_full_name="ROBLOXCORPORATION.ROBLOX.Astro_2.0_x64__55nm5eh3cm0pr",
            package_family_name="ROBLOXCORPORATION.ROBLOX.Astro_55nm5eh3cm0pr",
            display_name="Roblox Astro",
            status="Ok",
            app_user_model_id="ROBLOXCORPORATION.ROBLOX.Astro_55nm5eh3cm0pr!App",
        )
        self.launched: list[str] = []

    def list_packages(self) -> tuple[UwpRobloxPackage, ...]:
        return (self.package,)

    def launch_package(self, package_full_name: str) -> UwpLaunchResult:
        assert package_full_name == self.package.package_full_name
        self.launched.append(package_full_name)
        return UwpLaunchResult(
            package_full_name=package_full_name,
            app_user_model_id=self.package.app_user_model_id or "",
            launched=True,
        )


class _Roblox:
    def close(self) -> None:
        return None


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


def test_uwp_capability_is_exposed_through_service_and_pywebview_bridge(tmp_path: Path) -> None:
    uwp = _UwpManager()
    service = ApplicationService(paths=_paths(tmp_path), roblox=_Roblox(), uwp_manager=uwp)  # type: ignore[arg-type]
    try:
        bridge = DesktopBridge(service)
        inventory = bridge.list_uwp_packages()

        assert inventory["available"] is True
        assert inventory["packages"][0]["launchable"] is True
        assert "install_location" not in inventory["packages"][0]
        launched = bridge.launch_uwp_package(uwp.package.package_full_name)
        assert launched["launched"] is True
        assert uwp.launched == [uwp.package.package_full_name]
    finally:
        service.close()
