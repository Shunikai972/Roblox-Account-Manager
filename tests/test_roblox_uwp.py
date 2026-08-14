from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET

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
        self.created: list[tuple[str, bool]] = []
        self.unregistered: list[str] = []

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

    def create_account_clone(self, username: str, *, supports_multiple_instances: bool):
        self.created.append((username, supports_multiple_instances))
        return {"created": True, "username": username}

    def unregister_account_clone(self, username: str):
        self.unregistered.append(username)
        return {"unregistered": True, "username": username, "files_preserved": True}


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
        account = service.create_account({"username": "UwpAccount"})
        with pytest.raises(Exception):
            bridge.create_uwp_account_clone(account["id"], False, True)
        created = bridge.create_uwp_account_clone(account["id"], True, True)
        assert created["created"] is True
        assert uwp.created == [("UwpAccount", True)]
        removed = bridge.unregister_uwp_account_clone(account["id"], True)
        assert removed["unregistered"] is True
        assert uwp.unregistered == ["UwpAccount"]
    finally:
        service.close()


def _write_source_package(root: Path) -> None:
    (root / "Assets").mkdir(parents=True)
    (root / "Windows10Universal.exe").write_bytes(b"uwp-player")
    (root / "AppxSignature.p7x").write_bytes(b"signature")
    (root / "Assets" / "icon.png").write_bytes(b"icon")
    (root / "AppxManifest.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
         xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10">
  <Identity Name="ROBLOXCORPORATION.ROBLOX" Publisher="CN=Roblox" Version="1.0.0.0" />
  <Applications><Application Id="App" Executable="Windows10Universal.exe" EntryPoint="Roblox.App">
    <uap:VisualElements DisplayName="Roblox"><uap:DefaultTile ShortName="Roblox" /></uap:VisualElements>
  </Application></Applications>
</Package>""",
        encoding="utf-8",
    )


def test_uwp_clone_copies_rewrites_and_registers_with_values_outside_argv(tmp_path: Path) -> None:
    source = tmp_path / "WindowsApps" / "Roblox"
    _write_source_package(source)

    def runner(command):
        assert "Get-AppxPackage" in command[-1]
        return PowerShellResult(
            0,
            json.dumps(
                {
                    "developerMode": True,
                    "packageFullName": "ROBLOXCORPORATION.ROBLOX_1.0_x64__abc",
                    "installLocation": str(source),
                }
            ),
        )

    mutations = []

    def mutate(command, environment):
        mutations.append((command, dict(environment)))
        assert "Astro_Account" not in " ".join(command)
        return PowerShellResult(0, "")

    clone_root = tmp_path / "clones"
    manager = WindowsUwpRobloxManager(
        runner=runner,
        mutation_runner=mutate,
        platform_name=lambda: "Windows",
        instance_root=clone_root,
    )

    result = manager.create_account_clone("Astro_Account")

    destination = clone_root / "Astro_Account"
    assert result["created"] is True
    assert (destination / "Windows10Universal.exe").read_bytes() == b"uwp-player"
    assert not (destination / "AppxSignature.p7x").exists()
    manifest = ET.parse(destination / "AppxManifest.xml").getroot()
    namespace = "http://schemas.microsoft.com/appx/manifest/foundation/windows10"
    desktop4 = "http://schemas.microsoft.com/appx/manifest/desktop/windows10/4"
    assert manifest.find(f"{{{namespace}}}Identity").get("Name") == "ROBLOXCORPORATION.ROBLOX.Astro-Account"
    assert manifest.find(f".//{{{namespace}}}Application").get(f"{{{desktop4}}}SupportsMultipleInstances") == "true"
    assert mutations[0][1]["ASTRO_UWP_MANIFEST"] == str(destination / "AppxManifest.xml")


def test_uwp_clone_rolls_back_existing_copy_when_registration_fails(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_source_package(source)
    clone_root = tmp_path / "clones"
    previous = clone_root / "RollbackUser"
    previous.mkdir(parents=True)
    (previous / "old.txt").write_text("preserve", encoding="utf-8")
    _write_source_package(previous)
    calls = []

    def runner(_command):
        return PowerShellResult(
            0,
            json.dumps({"developerMode": True, "installLocation": str(source)}),
        )

    def mutate(_command, environment):
        calls.append(dict(environment))
        return PowerShellResult(1 if len(calls) == 1 else 0, "")

    manager = WindowsUwpRobloxManager(
        runner=runner,
        mutation_runner=mutate,
        platform_name=lambda: "Windows",
        instance_root=clone_root,
    )

    with pytest.raises(RobloxUwpError, match="rejected"):
        manager.create_account_clone("RollbackUser")

    assert (previous / "old.txt").read_text(encoding="utf-8") == "preserve"
    assert len(calls) == 2


def test_uwp_unregister_targets_only_exact_discovered_account_clone(tmp_path: Path) -> None:
    runner = _Runner(_package_payload())
    mutations = []

    def mutate(command, environment):
        mutations.append((command, dict(environment)))
        return PowerShellResult(0, "")

    manager = WindowsUwpRobloxManager(
        runner=runner,
        mutation_runner=mutate,
        platform_name=lambda: "Windows",
        instance_root=tmp_path,
    )

    result = manager.unregister_account_clone("Astro")

    assert result["unregistered"] is True
    assert result["files_preserved"] is True
    assert mutations[0][1] == {
        "ASTRO_UWP_PACKAGE": "ROBLOXCORPORATION.ROBLOX.Astro_2.0.0.0_x64__55nm5eh3cm0pr"
    }
    with pytest.raises(RobloxUwpError):
        manager.unregister_account_clone("NotThere")
