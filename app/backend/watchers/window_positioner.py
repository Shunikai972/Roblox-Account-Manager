"""Roblox process window positioning and window layout management."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import sys
from typing import Any

import psutil

logger = logging.getLogger("astro.window_positioner")

# Win32 Constants
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010


class RobloxWindowPositioner:
    """Manages window positions and sizes for running Roblox process instances."""

    @staticmethod
    def position_window(pid: int, x: int, y: int, width: int = 800, height: int = 600) -> bool:
        """Position and resize the main window of a given process ID."""

        values = (pid, x, y, width, height)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            return False
        if pid <= 0 or width < 160 or height < 120 or width > 16_384 or height > 16_384:
            return False
        if x < -32_768 or x > 32_767 or y < -32_768 or y > 32_767:
            return False

        if sys.platform != "win32":
            logger.info("Window positioning is supported on Windows platforms.")
            return False

        try:
            if psutil.Process(pid).name().casefold() not in {
                "robloxplayerbeta.exe",
                "robloxplayerbeta",
                "robloxplayer.exe",
                "robloxplayer",
            }:
                logger.warning("Refusing to position a non-Roblox process window")
                return False
            user32 = ctypes.windll.user32
            found_hwnd = None

            # Callback for EnumWindows
            def enum_windows_callback(hwnd, extra):
                nonlocal found_hwnd
                lpdw_process_id = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(lpdw_process_id))
                if lpdw_process_id.value == pid and user32.IsWindowVisible(hwnd):
                    found_hwnd = hwnd
                    return False  # Stop enumeration
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            user32.EnumWindows(WNDENUMPROC(enum_windows_callback), 0)

            if found_hwnd:
                positioned = user32.SetWindowPos(
                    found_hwnd,
                    0,
                    int(x),
                    int(y),
                    int(width),
                    int(height),
                    SWP_NOZORDER | SWP_NOACTIVATE,
                )
                if positioned:
                    logger.info("Positioned a verified Roblox process window")
                    return True
                return False
            else:
                logger.warning(f"No visible window found for PID {pid}")
                return False
        except (psutil.Error, OSError, ValueError):
            logger.warning("Roblox process window could not be inspected or positioned")
            return False
        except Exception:
            logger.exception("Failed to position a verified Roblox process window")
            return False

    @staticmethod
    def inspect_window(pid: int) -> dict[str, Any] | None:
        """Return title/focus/geometry for one verified Roblox window.

        The payload contains no command line, executable path, window text
        beyond the main title, or process memory.  It is used by the opt-in
        watcher rules and by per-account layout persistence.
        """

        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0 or sys.platform != "win32":
            return None
        try:
            if psutil.Process(pid).name().casefold() not in {
                "robloxplayerbeta.exe",
                "robloxplayerbeta",
                "robloxplayer.exe",
                "robloxplayer",
            }:
                return None
            user32 = ctypes.windll.user32
            found_hwnd = None

            def enum_windows_callback(hwnd, _extra):
                nonlocal found_hwnd
                process_id = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
                if process_id.value == pid and user32.IsWindowVisible(hwnd):
                    found_hwnd = hwnd
                    return False
                return True

            callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            user32.EnumWindows(callback_type(enum_windows_callback), 0)
            if not found_hwnd:
                return None

            length = max(0, int(user32.GetWindowTextLengthW(found_hwnd)))
            title_buffer = ctypes.create_unicode_buffer(min(length + 1, 1025))
            user32.GetWindowTextW(found_hwnd, title_buffer, len(title_buffer))
            rectangle = wintypes.RECT()
            if not user32.GetWindowRect(found_hwnd, ctypes.byref(rectangle)):
                return None
            width = int(rectangle.right - rectangle.left)
            height = int(rectangle.bottom - rectangle.top)
            if width < 1 or height < 1:
                return None
            return {
                "pid": pid,
                "title": title_buffer.value[:1024],
                "focused": bool(user32.GetForegroundWindow() == found_hwnd),
                "x": int(rectangle.left),
                "y": int(rectangle.top),
                "width": width,
                "height": height,
            }
        except (psutil.Error, OSError, TypeError, ValueError):
            return None
        except Exception:
            logger.exception("Failed to inspect a verified Roblox process window")
            return None
