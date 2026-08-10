"""Windows Multi-Instance controller for Roblox desktop clients.

Provides named mutex and event handling to bypass Roblox single-instance
restrictions on Windows, allowing multiple accounts to run simultaneously.
"""

from __future__ import annotations

import ctypes
import sys
import logging
from typing import Any

logger = logging.getLogger("astro.multi_instance")

# Win32 Constants
INVALID_HANDLE_VALUE = -1
ERROR_ALREADY_EXISTS = 183


class WindowsMultiInstanceController:
    """Manages global named Windows mutexes to allow multiple Roblox clients."""

    MUTEX_NAMES = (
        "ROBLOX_singletonEvent",
        "Global\\ROBLOX_singletonEvent",
        "ROBLOX_singletonMutex",
        "Global\\ROBLOX_singletonMutex",
    )

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
            logger.info("Multi-instance controller is not required on non-Windows platforms.")
            self._enabled = True
            return True

        try:
            kernel32 = ctypes.windll.kernel32
            create_mutex = kernel32.CreateMutexW
            create_mutex.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
            create_mutex.restype = ctypes.c_void_p

            create_event = kernel32.CreateEventW
            create_event.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_bool, ctypes.c_wchar_p]
            create_event.restype = ctypes.c_void_p

            handles = []
            for name in self.MUTEX_NAMES:
                # Create mutex
                handle_mutex = create_mutex(None, True, name)
                if handle_mutex and handle_mutex != INVALID_HANDLE_VALUE:
                    handles.append(handle_mutex)

                # Create event
                handle_event = create_event(None, True, False, name)
                if handle_event and handle_event != INVALID_HANDLE_VALUE:
                    handles.append(handle_event)

            self._handles = handles
            self._enabled = True
            logger.info(f"Multi-instance enabled: holding {len(handles)} singleton handles.")
            return True
        except Exception as exc:
            logger.error(f"Failed to enable multi-instance: {exc}")
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
