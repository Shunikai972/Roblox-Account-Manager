"""Beta Home window auto-close cleaner for Roblox desktop processes."""

from __future__ import annotations

import ctypes
import logging
import math
import sys
import time

import psutil

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
    PROCESS_NAMES = frozenset({"robloxplayerbeta.exe", "robloxplayerbeta"})

    @classmethod
    def _is_roblox_process(
        cls, pid: int, *, min_age_seconds: float = 0.0, now: float | None = None
    ) -> bool:
        try:
            process = psutil.Process(pid)
            if process.name().casefold() not in cls.PROCESS_NAMES:
                return False
            if min_age_seconds <= 0:
                return True
            current = time.time() if now is None else float(now)
            return current - float(process.create_time()) >= min_age_seconds
        except (psutil.Error, OSError, ValueError):
            return False

    @classmethod
    def close_beta_home_windows(cls, *, min_age_seconds: float = 0.0) -> int:
        """Scan open windows and send WM_CLOSE to matching Beta Home windows.

        The periodic watcher uses a 30-second grace period, matching the
        historical cleaner without racing a normal client startup.  The
        explicit UI action keeps the zero-second default.
        """

        if (
            isinstance(min_age_seconds, bool)
            or not isinstance(min_age_seconds, (int, float))
            or not math.isfinite(float(min_age_seconds))
            or not 0 <= float(min_age_seconds) <= 300
        ):
            raise ValueError("Beta Home grace period is invalid.")

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
                            process_id = ctypes.c_ulong()
                            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
                            if cls._is_roblox_process(
                                int(process_id.value), min_age_seconds=float(min_age_seconds)
                            ):
                                logger.info("Closing a verified Roblox Beta Home window")
                                if user32.PostMessageW(hwnd, WM_CLOSE, 0, 0):
                                    closed_count += 1
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            user32.EnumWindows(WNDENUMPROC(enum_windows_cb), 0)
        except Exception:
            logger.exception("Error during Beta Home cleanup")

        return closed_count
