"""Roblox process window positioning and window layout management."""

from __future__ import annotations

import ctypes
import logging
import sys
from typing import Any

logger = logging.getLogger("astro.window_positioner")

# Win32 Constants
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010


class RobloxWindowPositioner:
    """Manages window positions and sizes for running Roblox process instances."""

    @staticmethod
    def position_window(pid: int, x: int, y: int, width: int = 800, height: int = 600) -> bool:
        """Position and resize the main window of a given process ID."""

        if sys.platform != "win32":
            logger.info("Window positioning is supported on Windows platforms.")
            return False

        try:
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
                user32.SetWindowPos(
                    found_hwnd,
                    0,
                    int(x),
                    int(y),
                    int(width),
                    int(height),
                    SWP_NOZORDER | SWP_NOACTIVATE,
                )
                logger.info(f"Positioned window for PID {pid} to ({x}, {y}, {width}x{height})")
                return True
            else:
                logger.warning(f"No visible window found for PID {pid}")
                return False
        except Exception as exc:
            logger.error(f"Failed to position window for PID {pid}: {exc}")
            return False
