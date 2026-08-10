"""Beta Home window auto-close cleaner for Roblox desktop processes."""

from __future__ import annotations

import ctypes
import logging
import sys
from typing import Any

logger = logging.getLogger("astro.beta_home_cleaner")

# Win32 Constants
WM_CLOSE = 0x0010


class BetaHomeCleaner:
    """Detects and closes Roblox 'Beta Home' popup windows on Windows."""

    TARGET_TITLES = (
        "Roblox Beta",
        "Roblox Home",
        "Roblox App",
    )

    @classmethod
    def close_beta_home_windows(cls) -> int:
        """Scan open windows and send WM_CLOSE to matching Beta Home windows."""

        if sys.platform != "win32":
            return 0

        closed_count = 0
        try:
            user32 = ctypes.windll.user32

            def enum_windows_cb(hwnd, extra):
                nonlocal closed_count
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buff, length + 1)
                        title = buff.value
                        if any(target in title for target in cls.TARGET_TITLES):
                            logger.info(f"Closing Beta Home window: '{title}' (HWND {hwnd})")
                            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                            closed_count += 1
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            user32.EnumWindows(WNDENUMPROC(enum_windows_cb), 0)
        except Exception as exc:
            logger.error(f"Error during Beta Home cleanup: {exc}")

        return closed_count
