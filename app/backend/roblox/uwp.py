"""Discovery, launching, and explicit per-account Roblox UWP clones.

Read-only inventory remains side-effect free. Clone registration and removal
are separate methods used only by explicitly confirmed service actions. Values
cross into fixed PowerShell scripts through process environment variables,
never command interpolation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import time
from typing import Any
from uuid import uuid4
import xml.etree.ElementTree as ET

from .errors import RobloxUwpError


_MAX_POWERSHELL_OUTPUT = 512 * 1024
_MAX_FIELD_LENGTH = 1_024
_APP_USER_MODEL_ID = re.compile(r"^[A-Za-z0-9._-]{1,512}![A-Za-z0-9._-]{1,512}$")
_ROBLOX_PACKAGE_PREFIX = "robloxcorporation.roblox"
_ACCOUNT_NAME = re.compile(r"^[A-Za-z0-9_]{3,20}$")
_FOUNDATION_NS = "http://schemas.microsoft.com/appx/manifest/foundation/windows10"
_UAP_NS = "http://schemas.microsoft.com/appx/manifest/uap/windows10"
_DESKTOP4_NS = "http://schemas.microsoft.com/appx/manifest/desktop/windows10/4"

# This script is deliberately static.  It asks Windows for installed packages
# and their registered Start-menu application identifiers; it never receives a
# package name, path, or command from the frontend.
_DISCOVERY_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$packages = @(Get-AppxPackage -Name '*Roblox*' |
    Select-Object Name, PackageFullName, PackageFamilyName, Status)
$apps = @(Get-StartApps |
    Where-Object { $_.AppID -match '(?i)ROBLOX' } |
    Select-Object Name, AppID)
[PSCustomObject]@{ packages = $packages; apps = $apps } |
    ConvertTo-Json -Compress -Depth 4
""".strip()

_SOURCE_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$dev = (Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock' -Name AllowDevelopmentWithoutDevLicense -ErrorAction SilentlyContinue).AllowDevelopmentWithoutDevLicense
$package = Get-AppxPackage -Name 'ROBLOXCORPORATION.ROBLOX' | Sort-Object Version -Descending | Select-Object -First 1
[PSCustomObject]@{
    developerMode = [bool]$dev
    packageFullName = if ($package) { $package.PackageFullName } else { $null }
    installLocation = if ($package) { $package.InstallLocation } else { $null }
} | ConvertTo-Json -Compress
""".strip()

_REGISTER_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$manifest = [Environment]::GetEnvironmentVariable('ASTRO_UWP_MANIFEST', 'Process')
if ([string]::IsNullOrWhiteSpace($manifest)) { throw 'Manifest is missing.' }
Add-AppxPackage -Path $manifest -Register
""".strip()

_UNREGISTER_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$package = [Environment]::GetEnvironmentVariable('ASTRO_UWP_PACKAGE', 'Process')
if ([string]::IsNullOrWhiteSpace($package)) { throw 'Package is missing.' }
Remove-AppxPackage -Package $package
""".strip()


@dataclass(frozen=True, slots=True)
class PowerShellResult:
    """The narrow result shape consumed by package discovery."""

    returncode: int
    stdout: str
    stderr: str = ""


@dataclass(frozen=True, slots=True)
class UwpRobloxPackage:
    """A current-user Roblox package with an optional registered launch target."""

    package_name: str
    package_full_name: str
    package_family_name: str
    display_name: str
    status: str
    app_user_model_id: str | None

    @property
    def launchable(self) -> bool:
        return self.app_user_model_id is not None

    def to_dict(self) -> dict[str, Any]:
        """Return presentation metadata only; installation paths stay local."""

        return {
            "package_name": self.package_name,
            "package_full_name": self.package_full_name,
            "package_family_name": self.package_family_name,
            "display_name": self.display_name,
            "status": self.status,
            "app_user_model_id": self.app_user_model_id,
            "launchable": self.launchable,
        }


@dataclass(frozen=True, slots=True)
class UwpLaunchResult:
    """Result of handing a registered UWP app off to Windows."""

    package_full_name: str
    app_user_model_id: str
    launched: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_full_name": self.package_full_name,
            "app_user_model_id": self.app_user_model_id,
            "launched": self.launched,
        }


PowerShellRunner = Callable[[tuple[str, ...]], PowerShellResult]
MutationRunner = Callable[[tuple[str, ...], Mapping[str, str]], PowerShellResult]
AppsFolderOpener = Callable[[str], object]


class WindowsUwpRobloxManager:
    """Discover, launch, and explicitly manage per-account UWP clones.

    Inventory remains read-only. Copy, manifest registration, and exact clone
    unregistration live behind separate confirmed service actions and can
    never occur as a side effect of a status refresh.
    """

    def __init__(
        self,
        *,
        runner: PowerShellRunner | None = None,
        mutation_runner: MutationRunner | None = None,
        opener: AppsFolderOpener | None = None,
        platform_name: Callable[[], str] = platform.system,
        instance_root: Path | str | None = None,
    ) -> None:
        self._runner = runner or _run_powershell
        self._mutation_runner = mutation_runner or _run_powershell_with_environment
        self._opener = opener
        self._platform_name = platform_name
        default_root = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AstroAccountManager" / "UWP_Instances"
        self._instance_root = Path(instance_root or default_root).expanduser().resolve()

    def list_packages(self) -> tuple[UwpRobloxPackage, ...]:
        """Return installed Roblox UWP packages for the current Windows user."""

        self._require_windows()
        result = self._runner(
            (
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                _DISCOVERY_SCRIPT,
            )
        )
        if result.returncode != 0:
            raise RobloxUwpError("Windows could not query Roblox UWP apps.")
        if len(result.stdout.encode("utf-8", errors="ignore")) > _MAX_POWERSHELL_OUTPUT:
            raise RobloxUwpError("Windows response for UWP apps is too large.")

        try:
            payload = json.loads(result.stdout) if result.stdout.strip() else {}
        except json.JSONDecodeError as exc:
            raise RobloxUwpError("Windows returned an invalid UWP inventory.") from exc
        if not isinstance(payload, Mapping):
            raise RobloxUwpError("Windows returned an invalid UWP inventory.")

        apps = self._registered_apps(payload.get("apps"))
        packages: list[UwpRobloxPackage] = []
        for record in _records(payload.get("packages")):
            package = self._package_from_record(record, apps)
            if package is not None:
                packages.append(package)
        return tuple(sorted(packages, key=lambda item: (item.display_name.casefold(), item.package_full_name.casefold())))

    def launch_package(self, package_full_name: str) -> UwpLaunchResult:
        """Launch one package that was just discovered from Windows.

        Accepting a package full name rather than a raw AUMID prevents the
        bridge from becoming an arbitrary shell-app launcher.  The selected
        package is re-discovered and must expose exactly one registered Roblox
        app before Windows receives a launch request.
        """

        if not isinstance(package_full_name, str) or not package_full_name.strip():
            raise RobloxUwpError("Select a valid Roblox UWP app.")
        target = next(
            (item for item in self.list_packages() if item.package_full_name == package_full_name),
            None,
        )
        if target is None:
            raise RobloxUwpError("This Roblox UWP app is no longer registered on this device.")
        if target.app_user_model_id is None:
            raise RobloxUwpError("This Roblox UWP app has no registered launch point.")

        opener = self._opener or getattr(os, "startfile", None)
        if not callable(opener):
            raise RobloxUwpError("Windows ne peut pas lancer cette application UWP.")
        try:
            opener(f"shell:AppsFolder\\{target.app_user_model_id}")
        except OSError:
            raise RobloxUwpError("Windows n'a pas pu lancer cette application Roblox UWP.") from None
        except Exception:
            # Shell handler messages may include local paths.  Keep them out of
            # logs and the pywebview bridge.
            raise RobloxUwpError("Windows n'a pas pu lancer cette application Roblox UWP.") from None
        return UwpLaunchResult(
            package_full_name=target.package_full_name,
            app_user_model_id=target.app_user_model_id,
            launched=True,
        )

    def create_account_clone(
        self,
        account_username: str,
        *,
        supports_multiple_instances: bool = True,
    ) -> dict[str, Any]:
        """Copy, edit, and register one historical-style unpackaged clone."""

        self._require_windows()
        username = self._account_username(account_username)
        source = self._source_package()
        if not source["developer_mode"]:
            raise RobloxUwpError(
                "Windows Developer Mode is required to register a Roblox UWP clone."
            )
        source_path = Path(str(source["install_location"])).resolve()
        manifest_source = source_path / "AppxManifest.xml"
        executable_source = source_path / "Windows10Universal.exe"
        if not source_path.is_dir() or not manifest_source.is_file() or not executable_source.is_file():
            raise RobloxUwpError("The installed Roblox UWP package is incomplete or unavailable.")

        root = self._instance_root
        root.mkdir(parents=True, exist_ok=True)
        destination = (root / username).resolve()
        if destination.parent != root:
            raise RobloxUwpError("The UWP clone destination is invalid.")
        staging = (root / f".{username}-{uuid4().hex}.staging").resolve()
        backups = (root / "_backups").resolve()
        backups.mkdir(parents=True, exist_ok=True)
        backup = (backups / f"{username}-{int(time.time())}-{uuid4().hex[:8]}").resolve()
        previous: Path | None = None

        try:
            shutil.copytree(source_path, staging)
            signature = staging / "AppxSignature.p7x"
            if signature.exists():
                signature.unlink()
            self._rewrite_manifest(
                staging / "AppxManifest.xml",
                username,
                supports_multiple_instances=supports_multiple_instances,
            )
            if destination.exists():
                shutil.move(str(destination), str(backup))
                previous = backup
            staging.replace(destination)
            registration = self._mutation_runner(
                self._powershell_command(_REGISTER_SCRIPT),
                {"ASTRO_UWP_MANIFEST": str(destination / "AppxManifest.xml")},
            )
            if registration.returncode != 0:
                raise RobloxUwpError("Windows rejected the Roblox UWP clone registration.")
        except Exception as exc:
            shutil.rmtree(staging, ignore_errors=True)
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            if previous is not None and previous.exists():
                shutil.move(str(previous), str(destination))
                self._mutation_runner(
                    self._powershell_command(_REGISTER_SCRIPT),
                    {"ASTRO_UWP_MANIFEST": str(destination / "AppxManifest.xml")},
                )
            if isinstance(exc, RobloxUwpError):
                raise
            raise RobloxUwpError("The Roblox UWP clone could not be created.") from exc

        return {
            "created": True,
            "username": username,
            "package_name": f"ROBLOXCORPORATION.ROBLOX.{username.replace('_', '-')}",
            "backup_preserved": previous is not None,
        }

    def unregister_account_clone(self, account_username: str) -> dict[str, Any]:
        """Unregister one exact Astro clone while preserving its files."""

        self._require_windows()
        username = self._account_username(account_username)
        expected_name = f"robloxcorporation.roblox.{username.replace('_', '-')}".casefold()
        package = next(
            (item for item in self.list_packages() if item.package_name.casefold() == expected_name),
            None,
        )
        if package is None:
            raise RobloxUwpError("No registered Roblox UWP clone exists for this account.")
        result = self._mutation_runner(
            self._powershell_command(_UNREGISTER_SCRIPT),
            {"ASTRO_UWP_PACKAGE": package.package_full_name},
        )
        if result.returncode != 0:
            raise RobloxUwpError("Windows could not unregister this Roblox UWP clone.")
        return {
            "unregistered": True,
            "username": username,
            "package_full_name": package.package_full_name,
            "files_preserved": True,
        }

    def _source_package(self) -> dict[str, Any]:
        result = self._runner(self._powershell_command(_SOURCE_SCRIPT))
        if result.returncode != 0 or len(result.stdout.encode("utf-8", errors="ignore")) > _MAX_POWERSHELL_OUTPUT:
            raise RobloxUwpError("Windows could not inspect the Roblox UWP installation.")
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RobloxUwpError("Windows returned an invalid Roblox UWP installation.") from exc
        if not isinstance(value, Mapping) or not _text(value.get("installLocation")):
            raise RobloxUwpError("Install Roblox from the Microsoft Store before creating a clone.")
        return {
            "developer_mode": value.get("developerMode") is True,
            "install_location": _text(value.get("installLocation")),
        }

    @staticmethod
    def _rewrite_manifest(
        manifest_path: Path,
        username: str,
        *,
        supports_multiple_instances: bool,
    ) -> None:
        ET.register_namespace("", _FOUNDATION_NS)
        ET.register_namespace("uap", _UAP_NS)
        ET.register_namespace("desktop4", _DESKTOP4_NS)
        try:
            tree = ET.parse(manifest_path)
            root = tree.getroot()
            identity = root.find(f"{{{_FOUNDATION_NS}}}Identity")
            application = root.find(f".//{{{_FOUNDATION_NS}}}Application")
            visual = root.find(f".//{{{_UAP_NS}}}VisualElements")
            tile = root.find(f".//{{{_UAP_NS}}}DefaultTile")
            if identity is None or application is None or visual is None or tile is None:
                raise ValueError("required manifest nodes are missing")
            title = f"Roblox {username}"
            identity.set("Name", f"ROBLOXCORPORATION.ROBLOX.{username.replace('_', '-')}")
            visual.set("DisplayName", title)
            tile.set("ShortName", title)
            if supports_multiple_instances:
                application.set(f"{{{_DESKTOP4_NS}}}SupportsMultipleInstances", "true")
            else:
                application.attrib.pop(f"{{{_DESKTOP4_NS}}}SupportsMultipleInstances", None)
            temporary = manifest_path.with_suffix(".xml.tmp")
            tree.write(temporary, encoding="utf-8", xml_declaration=True)
            os.replace(temporary, manifest_path)
        except (OSError, ET.ParseError, ValueError) as exc:
            raise RobloxUwpError("The copied Roblox UWP manifest is invalid.") from exc

    @staticmethod
    def _account_username(value: str) -> str:
        username = value.strip() if isinstance(value, str) else ""
        if not _ACCOUNT_NAME.fullmatch(username):
            raise RobloxUwpError("Select an account with a valid Roblox username.")
        return username

    @staticmethod
    def _powershell_command(script: str) -> tuple[str, ...]:
        return (
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        )

    def _require_windows(self) -> None:
        if self._platform_name().casefold() != "windows":
            raise RobloxUwpError("La gestion UWP Roblox est disponible uniquement sous Windows.")

    @staticmethod
    def _registered_apps(value: object) -> tuple[tuple[str, str], ...]:
        apps: list[tuple[str, str]] = []
        for record in _records(value):
            app_id = _text(record.get("AppID"))
            if not _APP_USER_MODEL_ID.fullmatch(app_id):
                continue
            display_name = _text(record.get("Name")) or app_id
            apps.append((display_name, app_id))
        return tuple(apps)

    @staticmethod
    def _package_from_record(
        record: Mapping[str, object], apps: tuple[tuple[str, str], ...]
    ) -> UwpRobloxPackage | None:
        package_name = _text(record.get("Name"))
        package_full_name = _text(record.get("PackageFullName"))
        package_family_name = _text(record.get("PackageFamilyName"))
        if not (
            package_name.casefold().startswith(_ROBLOX_PACKAGE_PREFIX)
            and package_full_name
            and package_family_name
        ):
            return None

        prefix = f"{package_family_name}!".casefold()
        matching_apps = sorted(
            ((name, app_id) for name, app_id in apps if app_id.casefold().startswith(prefix)),
            key=lambda item: item[1].casefold(),
        )
        # A Roblox package normally exposes one application.  Do not choose an
        # arbitrary entry when Windows reports more than one.
        display_name = matching_apps[0][0] if len(matching_apps) == 1 else package_name
        app_user_model_id = matching_apps[0][1] if len(matching_apps) == 1 else None
        return UwpRobloxPackage(
            package_name=package_name,
            package_full_name=package_full_name,
            package_family_name=package_family_name,
            display_name=display_name,
            status=_text(record.get("Status")) or "Unknown",
            app_user_model_id=app_user_model_id,
        )


def _run_powershell(command: tuple[str, ...]) -> PowerShellResult:
    """Execute the fixed discovery query without a shell or profile loading."""

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=12,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RobloxUwpError("Windows cannot run the UWP application inventory.") from exc
    return PowerShellResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _run_powershell_with_environment(
    command: tuple[str, ...], values: Mapping[str, str]
) -> PowerShellResult:
    """Run a fixed mutation script with validated values outside argv."""

    environment = os.environ.copy()
    for key, value in values.items():
        if key not in {"ASTRO_UWP_MANIFEST", "ASTRO_UWP_PACKAGE"}:
            raise RobloxUwpError("The UWP operation environment is invalid.")
        environment[key] = value
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RobloxUwpError("Windows could not complete the UWP package operation.") from exc
    return PowerShellResult(completed.returncode, completed.stdout, completed.stderr)


def _records(value: object) -> tuple[Mapping[str, object], ...]:
    if isinstance(value, Mapping):
        return (value,)
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    if len(candidate) > _MAX_FIELD_LENGTH or any(ord(character) < 32 for character in candidate):
        return ""
    return candidate


__all__ = [
    "PowerShellResult",
    "RobloxUwpError",
    "UwpLaunchResult",
    "UwpRobloxPackage",
    "WindowsUwpRobloxManager",
]
