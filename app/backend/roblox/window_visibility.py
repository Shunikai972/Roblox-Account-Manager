"""Verified, reversible visibility control for observed Roblox windows.

The manager never searches by title alone. The service supplies PIDs already
observed by the Roblox process monitor, and this adapter resolves only a
top-level window owned by those exact processes. Showing uses a no-activate
Win32 command so Astro does not steal the operator's foreground application.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import os
from typing import Any, Iterable

from app.backend.core.errors import ValidationError


SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
SW_MINIMIZE = 6
GW_OWNER = 4


@dataclass(frozen=True, slots=True)
class WindowVisibilitySnapshot:
    pid: int
    supported: bool
    window_found: bool
    visible: bool | None = None
    minimized: bool | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "supported": self.supported,
            "window_found": self.window_found,
            "visible": self.visible,
            "minimized": self.minimized,
            "hidden": self.window_found and self.visible is False,
            "reason": self.reason,
        }


class _Win32VisibilityApi:
    def __init__(self) -> None:
        self.supported = os.name == "nt"
        self._user32 = ctypes.windll.user32 if self.supported else None

    def windows_for_pids(self, pids: set[int]) -> dict[int, int]:
        if not self.supported or self._user32 is None or not pids:
            return {}
        found: dict[int, int] = {}
        visible: dict[int, int] = {}
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        @callback_type
        def visit(hwnd: int, _lparam: int) -> bool:
            process_id = ctypes.c_ulong()
            self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            pid = int(process_id.value)
            if pid not in pids or self._user32.GetWindow(hwnd, GW_OWNER):
                return True
            found.setdefault(pid, int(hwnd))
            if self._user32.IsWindowVisible(hwnd):
                visible.setdefault(pid, int(hwnd))
            return True

        self._user32.EnumWindows(visit, 0)
        return {pid: visible.get(pid, hwnd) for pid, hwnd in found.items()}

    def is_window(self, hwnd: int) -> bool:
        return bool(self._user32 and self._user32.IsWindow(int(hwnd)))

    def is_visible(self, hwnd: int) -> bool:
        return bool(self._user32 and self._user32.IsWindowVisible(int(hwnd)))

    def is_minimized(self, hwnd: int) -> bool:
        return bool(self._user32 and self._user32.IsIconic(int(hwnd)))

    def show(self, hwnd: int, command: int) -> bool:
        return bool(self._user32 and self._user32.ShowWindowAsync(int(hwnd), int(command)))


class WindowVisibilityManager:
    """Inspect, hide, show or minimise verified process-owned windows."""

    def __init__(self, api: Any | None = None) -> None:
        self._api = api or _Win32VisibilityApi()

    def capability(self) -> dict[str, Any]:
        supported = bool(getattr(self._api, "supported", False))
        return {
            "supported": supported,
            "reason": None if supported else "Window visibility control is available only on Windows.",
        }

    @staticmethod
    def _pid(value: Any) -> int:
        if isinstance(value, bool):
            raise ValidationError("The Roblox process id is invalid.")
        try:
            pid = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError("The Roblox process id is invalid.") from exc
        if pid <= 0:
            raise ValidationError("The Roblox process id is invalid.")
        return pid

    def snapshot_many(self, pids: Iterable[int]) -> dict[int, WindowVisibilitySnapshot]:
        normalized = {self._pid(pid) for pid in pids}
        if not bool(getattr(self._api, "supported", False)):
            return {
                pid: WindowVisibilitySnapshot(
                    pid=pid,
                    supported=False,
                    window_found=False,
                    reason="Window visibility control is available only on Windows.",
                )
                for pid in normalized
            }
        windows = self._api.windows_for_pids(normalized)
        snapshots: dict[int, WindowVisibilitySnapshot] = {}
        for pid in normalized:
            hwnd = windows.get(pid)
            if not hwnd or not self._api.is_window(hwnd):
                snapshots[pid] = WindowVisibilitySnapshot(
                    pid=pid,
                    supported=True,
                    window_found=False,
                    reason="No top-level Roblox window is currently attached to this process.",
                )
                continue
            snapshots[pid] = WindowVisibilitySnapshot(
                pid=pid,
                supported=True,
                window_found=True,
                visible=bool(self._api.is_visible(hwnd)),
                minimized=bool(self._api.is_minimized(hwnd)),
            )
        return snapshots

    def snapshot(self, pid: int) -> WindowVisibilitySnapshot:
        normalized = self._pid(pid)
        return self.snapshot_many([normalized])[normalized]

    def _window(self, pid: int) -> tuple[int, int]:
        normalized = self._pid(pid)
        if not bool(getattr(self._api, "supported", False)):
            raise ValidationError("Window visibility control is available only on Windows.")
        hwnd = self._api.windows_for_pids({normalized}).get(normalized)
        if not hwnd or not self._api.is_window(hwnd):
            raise ValidationError("No top-level Roblox window is currently attached to this process.")
        return normalized, int(hwnd)

    def set_visible(self, pid: int, visible: bool) -> WindowVisibilitySnapshot:
        if not isinstance(visible, bool):
            raise ValidationError("Window visibility must be true or false.")
        normalized, hwnd = self._window(pid)
        self._api.show(hwnd, SW_SHOWNOACTIVATE if visible else SW_HIDE)
        snapshot = self.snapshot(normalized)
        if snapshot.visible is not visible:
            raise ValidationError("Windows did not apply the requested Roblox window visibility.")
        return snapshot

    def minimize(self, pid: int) -> WindowVisibilitySnapshot:
        normalized, hwnd = self._window(pid)
        self._api.show(hwnd, SW_MINIMIZE)
        snapshot = self.snapshot(normalized)
        if snapshot.minimized is not True:
            raise ValidationError("Windows did not minimise the requested Roblox window.")
        return snapshot

    def restore(self, pid: int) -> WindowVisibilitySnapshot:
        normalized, hwnd = self._window(pid)
        self._api.show(hwnd, SW_SHOWNOACTIVATE)
        return self.snapshot(normalized)
