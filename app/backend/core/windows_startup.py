"""Current-user Windows startup registration for Astro Account Manager.

The historical Settings form wrote ``Application.ProductName`` to the
current user's ``Run`` registry key and repaired the path when the executable
had moved.  This module keeps that bounded behaviour separate from settings
and UI code: it only inspects, enables, or removes Astro's own value.  It
never uses elevation, a shell command, a scheduled task, or a machine-wide
registry key.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path
import platform
from threading import RLock
from typing import Protocol

from app.backend.core.config import APP_NAME
from app.backend.core.errors import ValidationError


RUN_KEY_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
ASTRO_RUN_VALUE_NAME = APP_NAME
_MAX_EXECUTABLE_PATH_LENGTH = 8_192


class StartupRegistrationError(RuntimeError):
    """A sanitized local Registry failure while changing startup state."""


class RunValueStore(Protocol):
    """Minimal registry seam used by the manager and deterministic tests."""

    def get_value(self, name: str) -> object | None: ...

    def set_value(self, name: str, value: str) -> None: ...

    def delete_value(self, name: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class WindowsStartupStatus:
    """Safe status for the single Astro registration, without raw commands."""

    supported: bool
    accessible: bool
    registered: bool
    enabled: bool
    needs_repair: bool
    reason: str | None = None

    def to_dict(self) -> dict[str, bool | str | None]:
        return {
            "supported": self.supported,
            "accessible": self.accessible,
            "registered": self.registered,
            "enabled": self.enabled,
            "needs_repair": self.needs_repair,
            "reason": self.reason,
        }


class WindowsStartupManager:
    """Manage only Astro's current-user ``Run`` registry value.

    The registry value is always a quoted, validated absolute ``.exe`` path.
    ``inspect`` never repairs or creates a value; an explicit ``enable`` does
    so, which also handles the historical moved-executable case.  ``disable``
    deletes only :data:`ASTRO_RUN_VALUE_NAME`.
    """

    def __init__(
        self,
        executable_path: Path | str,
        *,
        store: RunValueStore | None = None,
        platform_name: Callable[[], str] = platform.system,
    ) -> None:
        self._executable_path = _validated_executable_path(executable_path)
        self._expected_command = _quoted_command(self._executable_path)
        self._store = store or WindowsRunValueStore()
        self._platform_name = platform_name
        self._lock = RLock()

    def inspect(self) -> WindowsStartupStatus:
        """Inspect the Astro value without modifying the Registry."""

        if not self._is_windows():
            return WindowsStartupStatus(
                supported=False,
                accessible=False,
                registered=False,
                enabled=False,
                needs_repair=False,
                reason="Automatic startup is available on Windows only.",
            )
        try:
            with self._lock:
                stored_value = self._store.get_value(ASTRO_RUN_VALUE_NAME)
        except StartupRegistrationError:
            return WindowsStartupStatus(
                supported=True,
                accessible=False,
                registered=False,
                enabled=False,
                needs_repair=False,
                reason="Windows startup value is inaccessible.",
            )

        registered = stored_value is not None
        enabled = isinstance(stored_value, str) and stored_value == self._expected_command
        return WindowsStartupStatus(
            supported=True,
            accessible=True,
            registered=registered,
            enabled=enabled,
            needs_repair=registered and not enabled,
        )

    def enable(self) -> WindowsStartupStatus:
        """Write the validated Astro executable command to HKCU Run.

        This is an explicit opt-in action.  It does not require administrator
        rights because it writes only the current user's Registry hive.
        """

        self._require_windows()
        try:
            with self._lock:
                self._store.set_value(ASTRO_RUN_VALUE_NAME, self._expected_command)
        except StartupRegistrationError:
            raise StartupRegistrationError("Automatic startup could not be enabled.") from None
        return self.inspect()

    def disable(self) -> WindowsStartupStatus:
        """Remove only Astro's own Run value; other startup entries are untouched."""

        self._require_windows()
        try:
            with self._lock:
                self._store.delete_value(ASTRO_RUN_VALUE_NAME)
        except StartupRegistrationError:
            raise StartupRegistrationError("Automatic startup could not be disabled.") from None
        return self.inspect()

    def _is_windows(self) -> bool:
        return self._platform_name().casefold() == "windows"

    def _require_windows(self) -> None:
        if not self._is_windows():
            raise StartupRegistrationError("Automatic startup is available on Windows only.")


class WindowsRunValueStore:
    """Thin lazy ``winreg`` adapter for the current user's Run key."""

    def get_value(self, name: str) -> object | None:
        try:
            import winreg  # type: ignore[import-not-found]

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
                try:
                    value, _ = winreg.QueryValueEx(key, name)
                except FileNotFoundError:
                    return None
                return value
        except FileNotFoundError:
            # The Run key has not been created for this user yet; that is an
            # ordinary disabled state, not an error.
            return None
        except (ImportError, OSError) as exc:
            raise StartupRegistrationError("Windows startup value is inaccessible.") from exc

    def set_value(self, name: str, value: str) -> None:
        try:
            import winreg  # type: ignore[import-not-found]

            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                RUN_KEY_PATH,
                0,
                winreg.KEY_SET_VALUE | winreg.KEY_READ,
            ) as key:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        except (ImportError, OSError) as exc:
            raise StartupRegistrationError("Windows startup value is inaccessible.") from exc

    def delete_value(self, name: str) -> bool:
        try:
            import winreg  # type: ignore[import-not-found]

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                RUN_KEY_PATH,
                0,
                winreg.KEY_SET_VALUE | winreg.KEY_READ,
            ) as key:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    return False
                return True
        except FileNotFoundError:
            return False
        except (ImportError, OSError) as exc:
            raise StartupRegistrationError("Windows startup registry value is inaccessible.") from exc


def _validated_executable_path(value: Path | str) -> Path:
    if not isinstance(value, (Path, str)):
        raise ValidationError("Windows startup executable path is invalid.")
    candidate = Path(value)
    if not candidate.is_absolute() or candidate.suffix.casefold() != ".exe":
        raise ValidationError("Windows startup requires an absolute .exe executable.")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ValidationError("Windows startup executable was not found.") from exc
    if not resolved.is_file():
        raise ValidationError("Windows startup path must point to a file.")
    text = os.fspath(resolved)
    if (
        not text
        or len(text) > _MAX_EXECUTABLE_PATH_LENGTH
        or '"' in text
        or any(ord(character) < 32 for character in text)
    ):
        raise ValidationError("Windows startup executable path is invalid.")
    return resolved


def _quoted_command(executable_path: Path) -> str:
    """Build the only Run command this manager can ever write."""

    return f'"{os.fspath(executable_path)}"'


__all__ = [
    "ASTRO_RUN_VALUE_NAME",
    "RUN_KEY_PATH",
    "StartupRegistrationError",
    "WindowsRunValueStore",
    "WindowsStartupManager",
    "WindowsStartupStatus",
]
