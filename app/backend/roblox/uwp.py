"""Non-destructive discovery and launching of installed Roblox UWP packages.

The historical UWP manager mixed package cloning, manifest edits, registration,
and uninstallation in one WinForms form.  This module intentionally isolates
the capability that Windows exposes without mutating an AppX installation:
discover Roblox packages registered for the current user and launch an
already-registered app through ``shell:AppsFolder``.

No package manifest, protocol association, credential, or client binary is
read or modified here.  Package metadata is gathered through a fixed
PowerShell query with no user-controlled interpolation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import os
import platform
import re
import subprocess
from typing import Any

from .errors import RobloxUwpError


_MAX_POWERSHELL_OUTPUT = 512 * 1024
_MAX_FIELD_LENGTH = 1_024
_APP_USER_MODEL_ID = re.compile(r"^[A-Za-z0-9._-]{1,512}![A-Za-z0-9._-]{1,512}$")
_ROBLOX_PACKAGE_PREFIX = "robloxcorporation.roblox"

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
AppsFolderOpener = Callable[[str], object]


class WindowsUwpRobloxManager:
    """Discover and launch existing Roblox UWP registrations on Windows.

    The manager intentionally has no install, unregister, copy, manifest edit,
    or package-removal operation.  Those are separate, destructive operations
    and must never occur as a side effect of a status refresh.
    """

    def __init__(
        self,
        *,
        runner: PowerShellRunner | None = None,
        opener: AppsFolderOpener | None = None,
        platform_name: Callable[[], str] = platform.system,
    ) -> None:
        self._runner = runner or _run_powershell
        self._opener = opener
        self._platform_name = platform_name

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
