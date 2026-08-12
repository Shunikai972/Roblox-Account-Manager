"""Windows Multi-Instance controller for Roblox desktop clients.

Retains the exact named mutex used by RAM 3.7.2 so Roblox clients opened
after Astro do not become the owner of the single-instance gate.
"""

from __future__ import annotations

import ctypes
import sys
import logging
from typing import Any

logger = logging.getLogger("astro.multi_instance")

ERROR_ALREADY_EXISTS = 183


class WindowsMultiInstanceController:
    """Manages global named Windows mutexes to allow multiple Roblox clients."""

    MUTEX_NAME = "ROBLOX_singletonMutex"

    def __init__(self) -> None:
        self._handles: list[Any] = []
        self._enabled = False

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def enable_multi_instance(self) -> bool:
        """Create and retain global singleton mutex handles on Windows."""

        if self._enabled:
            return True

        if sys.platform != "win32":
            logger.info("Multi-instance controller is unavailable outside Windows.")
            return False

        try:
            kernel32 = ctypes.windll.kernel32
            create_mutex = kernel32.CreateMutexW
            create_mutex.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
            create_mutex.restype = ctypes.c_void_p

            kernel32.SetLastError(0)
            handle = create_mutex(None, True, self.MUTEX_NAME)
            if not handle:
                return False
            if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
                kernel32.CloseHandle(handle)
                logger.warning("Roblox already owns the multi-instance mutex; restart Astro before Roblox.")
                return False

            self._handles = [handle]
            self._enabled = True
            logger.info("Multi-instance enabled: holding the RAM 3.7.2 singleton mutex.")
            return True
        except Exception:
            logger.exception("Failed to enable multi-instance")
            self.disable_multi_instance()
            return False

    def disable_multi_instance(self) -> None:
        """Release open singleton handles."""

        if sys.platform == "win32" and self._handles:
            kernel32 = ctypes.windll.kernel32
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = [ctypes.c_void_p]

            for handle in self._handles:
                try:
                    close_handle(handle)
                except Exception:
                    pass

        self._handles.clear()
        self._enabled = False
        logger.info("Multi-instance disabled: released all singleton handles.")

    def get_status(self) -> dict[str, Any]:
        return {
            "supported": sys.platform == "win32",
            "enabled": self._enabled,
            "handle_count": len(self._handles),
        }
