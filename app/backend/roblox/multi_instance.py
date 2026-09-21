"""Safe Windows multi-instance support for Roblox desktop clients.

Roblox serialises client startup through named kernel objects. Astro opens the
same objects on one long-lived thread and owns the mutex before launching any
client. If Roblox was already running first, the thread waits in the normal
Win32 queue and acquires the mutex as soon as that client exits.

Astro deliberately never closes handles inside a running Roblox process.
Doing that makes Roblox's own waiter fail with ``ERROR_INVALID_HANDLE`` and can
terminate the client that was supposed to stay open.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from typing import Any

import psutil

logger = logging.getLogger("astro.multi_instance")

ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0x00000000
WAIT_ABANDONED_0 = 0x00000080
WAIT_TIMEOUT = 0x00000102
WAIT_FAILED = 0xFFFFFFFF


class WindowsMultiInstanceController:
    """Own Roblox's singleton mutex on a dedicated, long-lived thread."""

    MUTEX_NAME = "ROBLOX_singletonMutex"
    EVENT_NAME = "ROBLOX_singletonEvent"

    HEAL_INTERVAL_SECONDS = 2.0
    START_TIMEOUT_SECONDS = 5.0
    MUTEX_POLL_MS = 100

    def __init__(self) -> None:
        self._state_lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._release = threading.Event()
        self._ready = threading.Event()
        self._enabled = False
        self._waiting_for_mutex = False
        self._handles: dict[str, Any] = {}
        self._owned: set[str] = set()
        self._adopted_existing = False
        self._reacquisitions = 0
        self._last_prepared_pids: list[int] = []
        self._last_preparation_error: str | None = None
        self._last_error: str | None = None

    @property
    def is_enabled(self) -> bool:
        with self._state_lock:
            return self._enabled

    @property
    def adopted_existing(self) -> bool:
        with self._state_lock:
            return self._adopted_existing

    @property
    def holder_thread_alive(self) -> bool:
        thread = self._thread
        return bool(thread and thread.is_alive())

    def get_status(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "supported": sys.platform == "win32",
                "enabled": self._enabled,
                "waiting_for_mutex": self._waiting_for_mutex,
                "handle_count": len(self._handles),
                "held_objects": sorted(self._handles),
                "owned_objects": sorted(self._owned),
                "adopted_existing": self._adopted_existing,
                "event_held": self.EVENT_NAME in self._handles,
                "mutex_held": self.MUTEX_NAME in self._handles,
                "holder_thread_alive": self.holder_thread_alive,
                "reacquisitions": self._reacquisitions,
                # Retained for bridge compatibility. Safe builds never close
                # handles that belong to another process.
                "remote_event_handles_closed": 0,
                "remote_singleton_handles_closed": 0,
                "last_prepared_pids": list(self._last_prepared_pids),
                "last_preparation_error": self._last_preparation_error,
                "last_error": self._last_error,
            }

    def enable_multi_instance(self) -> bool:
        """Start the holder thread and report whether the mutex is owned now."""

        with self._state_lock:
            if self.holder_thread_alive:
                return self._enabled
            if sys.platform != "win32":
                self._last_error = "Multi Roblox requires Windows."
                return False

            self._release.clear()
            self._ready.clear()
            self._enabled = False
            self._waiting_for_mutex = False
            self._handles.clear()
            self._owned.clear()
            self._adopted_existing = False
            self._last_error = None
            thread = threading.Thread(
                target=self._hold_until_released,
                name="astro-roblox-singleton",
                daemon=True,
            )
            self._thread = thread
            thread.start()

        if not self._ready.wait(timeout=self.START_TIMEOUT_SECONDS):
            with self._state_lock:
                self._last_error = "The singleton holder thread did not start in time."
            self.disable_multi_instance()
            return False
        return self.is_enabled

    def prepare_for_launch(self) -> dict[str, Any]:
        """Confirm mutex ownership without modifying any Roblox process."""

        if sys.platform != "win32":
            return {"supported": False, "pids": [], "closed": 0, "error": "Windows required."}

        pids = self._roblox_player_pids()
        ready = self.is_enabled or self.enable_multi_instance()
        error = None
        if not ready:
            error = (
                "Multi Roblox is waiting for an existing Roblox client to release its mutex. "
                "Close all Roblox clients once, then launch every account from Astro."
            )

        with self._state_lock:
            self._last_prepared_pids = list(pids)
            self._last_preparation_error = error
        return {"supported": True, "pids": pids, "closed": 0, "error": error}

    def disable_multi_instance(self) -> None:
        """Release the objects on their owning thread and stop the waiter."""

        with self._state_lock:
            thread = self._thread
        self._release.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=self.START_TIMEOUT_SECONDS)

        with self._state_lock:
            self._thread = None
            self._enabled = False
            self._waiting_for_mutex = False
            self._handles.clear()
            self._owned.clear()
            self._adopted_existing = False
        logger.info("Multi-instance disabled: singleton objects released.")

    def _hold_until_released(self) -> None:
        """Open, acquire, hold and release all objects on one thread."""

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        try:
            opened = self._acquire(kernel32)
        except Exception as exc:  # pragma: no cover - live Windows failure
            logger.exception("Failed to initialise Roblox singleton objects")
            with self._state_lock:
                self._last_error = str(exc)
            self._ready.set()
            return

        self._ready.set()
        if not opened:
            return

        try:
            if not self.is_enabled and not self._wait_for_mutex(kernel32):
                return
            while not self._release.wait(self.HEAL_INTERVAL_SECONDS):
                self._heal(kernel32)
        finally:
            self._release_objects(kernel32)
            with self._state_lock:
                self._enabled = False
                self._waiting_for_mutex = False

    def _acquire(self, kernel32: Any) -> bool:
        """Open both singleton objects and try immediate mutex ownership.

        Existing objects are adopted without touching the process that created
        them. A busy mutex is left open while the holder thread queue-waits.
        """

        mutex = self._create_mutex(kernel32)
        if mutex is None:
            with self._state_lock:
                self._last_error = "Windows refused to create the Roblox singleton mutex."
            return False

        mutex_handle, mutex_existed = mutex
        with self._state_lock:
            self._handles[self.MUTEX_NAME] = mutex_handle
            self._adopted_existing = mutex_existed

        event = self._create_event(kernel32)
        if event is not None:
            event_handle, event_existed = event
            with self._state_lock:
                self._handles[self.EVENT_NAME] = event_handle
                self._adopted_existing = self._adopted_existing or event_existed

        result = self._wait_result(kernel32, mutex_handle, 0)
        if result in (WAIT_OBJECT_0, WAIT_ABANDONED_0):
            self._mark_mutex_owned(reacquired=False)
        elif result == WAIT_TIMEOUT:
            with self._state_lock:
                self._waiting_for_mutex = True
                self._last_error = (
                    "An existing Roblox client owns the singleton mutex. "
                    "Close it once so Astro can take ownership safely."
                )
        else:
            error = ctypes.get_last_error() if result == WAIT_FAILED else result
            with self._state_lock:
                self._last_error = f"Windows could not wait for the Roblox mutex ({error})."
            return False
        return True

    def _wait_for_mutex(self, kernel32: Any) -> bool:
        with self._state_lock:
            handle = self._handles.get(self.MUTEX_NAME)
        if not handle:
            return False

        while not self._release.is_set():
            result = self._wait_result(kernel32, handle, self.MUTEX_POLL_MS)
            if result in (WAIT_OBJECT_0, WAIT_ABANDONED_0):
                self._mark_mutex_owned(reacquired=True)
                logger.info("Multi Roblox acquired the mutex after the previous client exited.")
                return True
            if result == WAIT_TIMEOUT:
                continue
            error = ctypes.get_last_error() if result == WAIT_FAILED else result
            with self._state_lock:
                self._last_error = f"Windows stopped waiting for the Roblox mutex ({error})."
                self._waiting_for_mutex = False
            return False
        return False

    def _mark_mutex_owned(self, *, reacquired: bool) -> None:
        with self._state_lock:
            self._owned.add(self.MUTEX_NAME)
            self._enabled = True
            self._waiting_for_mutex = False
            self._last_error = None
            if reacquired:
                self._reacquisitions += 1

    def _heal(self, kernel32: Any) -> None:
        """Retry only a missing local event; never edit remote processes."""

        with self._state_lock:
            missing_event = self.EVENT_NAME not in self._handles
        if not missing_event:
            return
        event = self._create_event(kernel32)
        if event is None:
            return
        with self._state_lock:
            self._handles[self.EVENT_NAME] = event[0]
            self._adopted_existing = self._adopted_existing or event[1]
            self._reacquisitions += 1

    def _release_objects(self, kernel32: Any) -> None:
        release_mutex = kernel32.ReleaseMutex
        release_mutex.argtypes = [ctypes.c_void_p]
        release_mutex.restype = ctypes.c_bool
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [ctypes.c_void_p]
        close_handle.restype = ctypes.c_bool

        with self._state_lock:
            handles = dict(self._handles)
            owned = set(self._owned)
            self._handles.clear()
            self._owned.clear()

        for name, handle in handles.items():
            try:
                if name == self.MUTEX_NAME and name in owned:
                    release_mutex(handle)
                close_handle(handle)
            except Exception:  # pragma: no cover - live Windows failure
                logger.exception("Failed to release singleton object %s", name)

    def _create_mutex(self, kernel32: Any) -> tuple[Any, bool] | None:
        create_mutex = kernel32.CreateMutexW
        create_mutex.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        create_mutex.restype = ctypes.c_void_p
        ctypes.set_last_error(0)
        handle = create_mutex(None, False, self.MUTEX_NAME)
        if not handle:
            return None
        return handle, ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    def _create_event(self, kernel32: Any) -> tuple[Any, bool] | None:
        create_event = kernel32.CreateEventW
        create_event.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_bool, ctypes.c_wchar_p]
        create_event.restype = ctypes.c_void_p
        ctypes.set_last_error(0)
        handle = create_event(None, True, False, self.EVENT_NAME)
        if not handle:
            return None
        return handle, ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    @staticmethod
    def _wait_result(kernel32: Any, handle: Any, timeout_ms: int) -> int:
        wait_for_single_object = kernel32.WaitForSingleObject
        wait_for_single_object.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        wait_for_single_object.restype = ctypes.c_ulong
        return int(wait_for_single_object(handle, timeout_ms))

    @staticmethod
    def _roblox_player_pids() -> list[int]:
        pids: list[int] = []
        try:
            for process in psutil.process_iter(["pid", "name"]):
                if str(process.info.get("name") or "").casefold() == "robloxplayerbeta.exe":
                    pids.append(int(process.info["pid"]))
        except (psutil.Error, OSError):
            return sorted(set(pids))
        return sorted(set(pids))


__all__ = ["WindowsMultiInstanceController"]
