"""Windows Multi-Instance controller for Roblox desktop clients.

Holds the named singleton objects that Roblox uses to enforce a single client,
so a Roblox process started after Astro does not close itself.

Why the implementation looks like this
-------------------------------------

The Win32 documentation is explicit on two points that broke the earlier
version of this module:

* Ownership of a mutex belongs to a *thread*.  "If a thread terminates without
  releasing its ownership of a mutex object, the mutex object is considered to
  be abandoned", and another waiter can then take it.  Acquiring the mutex on a
  short-lived thread therefore gives Roblox a window in which it can reclaim
  the gate.  This module acquires and releases the objects on one dedicated
  long-lived thread that exists for exactly as long as the feature is enabled.
* Merely holding an open handle keeps the kernel object alive.  When the object
  already exists, the correct move is to keep our own handle, not to close it
  and report failure.  This is what Bloxstrap and Fishstrap do, and it is why
  those launchers must stay running for multi-instance to keep working.

Modern Roblox clients also guard the rule with a named *event*, so both
``ROBLOX_singletonMutex`` and ``ROBLOX_singletonEvent`` are held together.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
from typing import Any

import psutil

logger = logging.getLogger("astro.multi_instance")

ERROR_ALREADY_EXISTS = 183
STATUS_INFO_LENGTH_MISMATCH = ctypes.c_long(0xC0000004).value
SYSTEM_EXTENDED_HANDLE_INFORMATION = 64
PROCESS_DUP_HANDLE = 0x0040
DUPLICATE_CLOSE_SOURCE = 0x00000001
DUPLICATE_SAME_ACCESS = 0x00000002
SYNCHRONIZE = 0x00100000


class _SystemHandleEntry(ctypes.Structure):
    """64-bit-safe layout returned by SystemExtendedHandleInformation."""

    _fields_ = [
        ("object", ctypes.c_void_p),
        ("unique_process_id", ctypes.c_size_t),
        ("handle_value", ctypes.c_size_t),
        ("granted_access", ctypes.c_ulong),
        ("creator_backtrace_index", ctypes.c_ushort),
        ("object_type_index", ctypes.c_ushort),
        ("handle_attributes", ctypes.c_ulong),
        ("reserved", ctypes.c_ulong),
    ]


class _UnicodeString(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_ushort),
        ("maximum_length", ctypes.c_ushort),
        ("buffer", ctypes.c_void_p),
    ]


class WindowsMultiInstanceController:
    """Owns the Roblox singleton objects on a dedicated holder thread."""

    MUTEX_NAME = "ROBLOX_singletonMutex"
    EVENT_NAME = "ROBLOX_singletonEvent"

    #: How often the holder thread retries an object it could not create yet.
    HEAL_INTERVAL_SECONDS = 2.0
    #: How long enable_multi_instance waits for the holder thread to report.
    START_TIMEOUT_SECONDS = 5.0

    def __init__(self) -> None:
        self._state_lock = threading.RLock()
        self._scrub_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._launch_guard_thread: threading.Thread | None = None
        self._launch_guard_until = 0.0
        self._release = threading.Event()
        self._ready = threading.Event()
        self._enabled = False
        self._handles: dict[str, Any] = {}
        self._owned: set[str] = set()
        self._adopted_existing = False
        self._reacquisitions = 0
        self._remote_event_handles_closed = 0
        self._last_prepared_pids: list[int] = []
        self._last_preparation_error: str | None = None
        self._last_error: str | None = None

    # ------------------------------------------------------------------ state
    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def adopted_existing(self) -> bool:
        """True when Astro attached to an object another process created first."""

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
                "handle_count": len(self._handles),
                "held_objects": sorted(self._handles),
                "owned_objects": sorted(self._owned),
                "adopted_existing": self._adopted_existing,
                "event_held": self.EVENT_NAME in self._handles,
                "mutex_held": self.MUTEX_NAME in self._handles,
                "holder_thread_alive": self.holder_thread_alive,
                "reacquisitions": self._reacquisitions,
                "remote_event_handles_closed": self._remote_event_handles_closed,
                "last_prepared_pids": list(self._last_prepared_pids),
                "last_preparation_error": self._last_preparation_error,
                "last_error": self._last_error,
            }

    # ------------------------------------------------------------ public API
    def enable_multi_instance(self) -> bool:
        """Start holding the Roblox singleton objects.

        Returns true once the holder thread reports that the mutex is held.
        Idempotent: calling it again while the holder thread is alive is a
        no-op that returns true.
        """

        with self._state_lock:
            if self._enabled and self.holder_thread_alive:
                return True
            if sys.platform != "win32":
                logger.info("Multi-instance controller is unavailable outside Windows.")
                self._last_error = "Multi Roblox requires Windows."
                return False
            self._release.clear()
            self._ready.clear()
            self._last_error = None
            thread = threading.Thread(
                target=self._hold_until_released,
                name="astro-roblox-singleton",
                daemon=True,
            )
            self._thread = thread
            thread.start()

        if not self._ready.wait(timeout=self.START_TIMEOUT_SECONDS):
            logger.warning("The Roblox singleton holder thread did not report in time.")
            self._last_error = "The singleton holder thread did not start in time."
            self.disable_multi_instance()
            return False

        return self._enabled

    def prepare_for_launch(self) -> dict[str, Any]:
        """Detach the modern singleton event from already-running clients.

        The historic RAM mutex is still required, but current Roblox builds
        also keep a handle to ``ROBLOX_singletonEvent`` inside every player
        process.  When the next player starts, that event makes Windows replace
        the previous client even though Astro owns the mutex.  We identify the
        exact kernel object through Astro's own named-event handle and close
        only matching handles in same-user RobloxPlayerBeta processes.

        No Roblox memory or files are modified.  The operation is repeated
        before each launch so the first, second, and later clients can coexist.
        """

        if sys.platform != "win32":
            return {"supported": False, "pids": [], "closed": 0, "error": "Windows required."}
        if not self.is_enabled and not self.enable_multi_instance():
            return {
                "supported": True,
                "pids": [],
                "closed": 0,
                "error": self._last_error or "Multi Roblox is not enabled.",
            }

        pids = sorted(
            process.info["pid"]
            for process in psutil.process_iter(["pid", "name"])
            if str(process.info.get("name") or "").casefold() == "robloxplayerbeta.exe"
        )
        if not pids:
            with self._state_lock:
                self._last_prepared_pids = []
                self._last_preparation_error = None
            self._arm_launch_guard()
            return {"supported": True, "pids": [], "closed": 0, "error": None}

        try:
            with self._scrub_lock:
                closed = self._close_remote_singleton_event_handles(pids)
        except Exception as exc:  # pragma: no cover - depends on live Win32 state
            message = str(exc)
            with self._state_lock:
                self._last_prepared_pids = pids
                self._last_preparation_error = message
            logger.exception("Could not detach Roblox singleton event handles")
            return {"supported": True, "pids": pids, "closed": 0, "error": message}

        with self._state_lock:
            self._last_prepared_pids = pids
            self._last_preparation_error = None
            self._remote_event_handles_closed += closed
        logger.info(
            "Prepared Multi Roblox launch: closed %d singleton event handle(s) in PID(s) %s.",
            closed,
            pids,
        )
        self._arm_launch_guard()
        return {"supported": True, "pids": pids, "closed": closed, "error": None}

    def _arm_launch_guard(self, duration_seconds: float = 8.0) -> None:
        """Scrub a just-created player's event before its wait becomes active.

        Closing the event only when the *next* account is launched can be too
        late: a mature first client may already be blocked in a Windows wait.
        A short background guard starts before every protocol hand-off and
        catches the new process as soon as it creates the singleton object.
        """

        with self._state_lock:
            self._launch_guard_until = max(
                self._launch_guard_until,
                time.monotonic() + max(1.0, float(duration_seconds)),
            )
            if self._launch_guard_thread and self._launch_guard_thread.is_alive():
                return
            self._launch_guard_thread = threading.Thread(
                target=self._guard_launch_window,
                name="astro-roblox-singleton-guard",
                daemon=True,
            )
            self._launch_guard_thread.start()

    def _guard_launch_window(self) -> None:
        while not self._release.is_set():
            with self._state_lock:
                if time.monotonic() >= self._launch_guard_until:
                    self._launch_guard_thread = None
                    return
            pids = tuple(
                sorted(
                    process.info["pid"]
                    for process in psutil.process_iter(["pid", "name"])
                    if str(process.info.get("name") or "").casefold()
                    == "robloxplayerbeta.exe"
                )
            )
            # Query immediately when the process set changes, then several
            # more times while Roblox finishes constructing kernel objects.
            if pids:
                try:
                    with self._scrub_lock:
                        closed = self._close_remote_singleton_event_handles(list(pids))
                    if closed:
                        with self._state_lock:
                            self._remote_event_handles_closed += closed
                            self._last_prepared_pids = list(pids)
                            self._last_preparation_error = None
                        logger.info(
                            "Multi Roblox launch guard detached %d event handle(s) in PID(s) %s.",
                            closed,
                            pids,
                        )
                except Exception as exc:  # pragma: no cover - live Windows state
                    with self._state_lock:
                        self._last_preparation_error = str(exc)
            # The first second is the critical race.  A 50 ms bounded poll is
            # short-lived and uses no CPU once the eight-second guard ends.
            self._release.wait(0.08)

        with self._state_lock:
            self._launch_guard_thread = None

    def disable_multi_instance(self) -> None:
        """Release the singleton objects and stop the holder thread."""

        with self._state_lock:
            thread = self._thread
        self._release.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=self.START_TIMEOUT_SECONDS)
        with self._state_lock:
            self._thread = None
            self._launch_guard_thread = None
            self._launch_guard_until = 0.0
            self._enabled = False
            self._handles.clear()
            self._owned.clear()
            self._adopted_existing = False
        logger.info("Multi-instance disabled: singleton objects released.")

    # --------------------------------------------------------- holder thread
    def _hold_until_released(self) -> None:
        """Create the objects, then keep owning them until asked to release.

        Everything happens on this one thread so ownership is never abandoned.
        """

        kernel32 = ctypes.windll.kernel32
        try:
            acquired = self._acquire(kernel32)
        except Exception as exc:  # pragma: no cover - Windows only
            logger.exception("Failed to acquire the Roblox singleton objects")
            self._last_error = str(exc)
            self._ready.set()
            return

        if not acquired:
            self._ready.set()
            return

        with self._state_lock:
            self._enabled = True
        self._ready.set()

        try:
            while not self._release.wait(self.HEAL_INTERVAL_SECONDS):
                try:
                    self._heal(kernel32)
                except Exception as exc:  # pragma: no cover - Windows only
                    self._last_error = str(exc)
        finally:
            self._release_objects(kernel32)
            with self._state_lock:
                self._enabled = False

    def _acquire(self, kernel32: Any) -> bool:
        """Create and retain the singleton objects.

        An object that already exists is adopted, never refused: keeping our
        handle open is what stops Roblox from taking the gate back when the
        first client exits.
        """

        mutex = self._create_mutex(kernel32)
        if mutex is None:
            logger.warning("Windows refused to create the Roblox singleton mutex.")
            self._last_error = "Windows refused to create the Roblox singleton mutex."
            return False

        handle, existed = mutex
        with self._state_lock:
            self._handles[self.MUTEX_NAME] = handle
            if not existed:
                self._owned.add(self.MUTEX_NAME)
            self._adopted_existing = self._adopted_existing or existed

        event = self._create_event(kernel32)
        if event is None:
            # Not fatal: older clients only use the mutex.  The holder thread
            # keeps retrying, so a late-appearing event is still picked up.
            logger.warning(
                "Windows refused to create the Roblox singleton event; holding the mutex only."
            )
        else:
            event_handle, event_existed = event
            with self._state_lock:
                self._handles[self.EVENT_NAME] = event_handle
                if not event_existed:
                    self._owned.add(self.EVENT_NAME)
                self._adopted_existing = self._adopted_existing or event_existed

        with self._state_lock:
            held = sorted(self._handles)
            adopted = self._adopted_existing
        logger.info(
            "Multi-instance enabled on the holder thread; holding %s%s.",
            ", ".join(held),
            " (adopted an existing object)" if adopted else "",
        )
        return True

    def _heal(self, kernel32: Any) -> None:
        """Retry any object that could not be created yet."""

        with self._state_lock:
            missing_event = self.EVENT_NAME not in self._handles
            missing_mutex = self.MUTEX_NAME not in self._handles

        if missing_mutex:
            mutex = self._create_mutex(kernel32)
            if mutex is not None:
                with self._state_lock:
                    self._handles[self.MUTEX_NAME] = mutex[0]
                    self._reacquisitions += 1
                logger.info("Re-acquired the Roblox singleton mutex.")

        if missing_event:
            event = self._create_event(kernel32)
            if event is not None:
                with self._state_lock:
                    self._handles[self.EVENT_NAME] = event[0]
                    self._reacquisitions += 1
                logger.info("Re-acquired the Roblox singleton event.")

    def _release_objects(self, kernel32: Any) -> None:
        """Release ownership and close every handle, on the owning thread."""

        release_mutex = kernel32.ReleaseMutex
        release_mutex.argtypes = [ctypes.c_void_p]
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [ctypes.c_void_p]

        with self._state_lock:
            handles = dict(self._handles)
            owned = set(self._owned)
            self._handles.clear()
            self._owned.clear()

        for name, handle in handles.items():
            try:
                if name == self.MUTEX_NAME and name in owned:
                    # Releasing before closing avoids leaving an abandoned
                    # mutex behind for the next waiter.
                    release_mutex(handle)
                close_handle(handle)
            except Exception:  # pragma: no cover - Windows only
                logger.exception("Failed to release the singleton object %s", name)

    # ------------------------------------------------------------- Win32 glue
    def _create_mutex(self, kernel32: Any) -> tuple[Any, bool] | None:
        create_mutex = kernel32.CreateMutexW
        create_mutex.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        create_mutex.restype = ctypes.c_void_p
        kernel32.SetLastError(0)
        handle = create_mutex(None, True, self.MUTEX_NAME)
        if not handle:
            return None
        return handle, kernel32.GetLastError() == ERROR_ALREADY_EXISTS

    def _create_event(self, kernel32: Any) -> tuple[Any, bool] | None:
        create_event = kernel32.CreateEventW
        create_event.argtypes = [
            ctypes.c_void_p,
            ctypes.c_bool,
            ctypes.c_bool,
            ctypes.c_wchar_p,
        ]
        create_event.restype = ctypes.c_void_p
        kernel32.SetLastError(0)
        handle = create_event(None, True, False, self.EVENT_NAME)
        if not handle:
            return None
        return handle, kernel32.GetLastError() == ERROR_ALREADY_EXISTS

    def _close_remote_singleton_event_handles(self, pids: list[int]) -> int:
        """Close only handles that point to Astro's exact singleton event."""

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ntdll = ctypes.WinDLL("ntdll")

        open_event = kernel32.OpenEventW
        open_event.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_wchar_p]
        open_event.restype = ctypes.c_void_p
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [ctypes.c_void_p]
        close_handle.restype = ctypes.c_bool
        open_process = kernel32.OpenProcess
        open_process.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
        open_process.restype = ctypes.c_void_p
        duplicate_handle = kernel32.DuplicateHandle
        duplicate_handle.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_ulong,
            ctypes.c_bool,
            ctypes.c_ulong,
        ]
        duplicate_handle.restype = ctypes.c_bool
        current_process = kernel32.GetCurrentProcess
        current_process.restype = ctypes.c_void_p

        query_handles = ntdll.NtQuerySystemInformation
        query_handles.argtypes = [
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        query_handles.restype = ctypes.c_long
        query_object = ntdll.NtQueryObject
        query_object.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        query_object.restype = ctypes.c_long

        local_event = open_event(SYNCHRONIZE, False, self.EVENT_NAME)
        if not local_event:
            raise OSError(ctypes.get_last_error(), "ROBLOX_singletonEvent could not be opened")

        try:
            size = 1 << 20
            while True:
                buffer = ctypes.create_string_buffer(size)
                needed = ctypes.c_ulong()
                status = query_handles(
                    SYSTEM_EXTENDED_HANDLE_INFORMATION,
                    buffer,
                    size,
                    ctypes.byref(needed),
                )
                if status == STATUS_INFO_LENGTH_MISMATCH:
                    size = max(size * 2, int(needed.value) + 65536)
                    if size > 256 * 1024 * 1024:
                        raise RuntimeError("Windows handle table exceeded the safety limit")
                    continue
                if status != 0:
                    raise OSError(f"NtQuerySystemInformation failed with NTSTATUS 0x{status & 0xFFFFFFFF:08X}")
                break

            count = ctypes.c_size_t.from_buffer(buffer, 0).value
            entries_offset = ctypes.sizeof(ctypes.c_size_t) * 2
            entries_type = _SystemHandleEntry * count
            entries = entries_type.from_buffer(buffer, entries_offset)
            own_pid = os.getpid()
            own_value = int(local_event)
            own_entry = next(
                (
                    entry
                    for entry in entries
                    if int(entry.unique_process_id) == own_pid
                    and int(entry.handle_value) == own_value
                ),
                None,
            )
            if own_entry is None:
                raise RuntimeError("The singleton event was absent from the Windows handle table")
            event_object = int(own_entry.object or 0)
            event_type = int(own_entry.object_type_index)
            # Recent Windows builds may hide kernel object pointers from
            # non-elevated callers.  In that case we safely narrow candidates
            # to Event handles and verify their names after duplication.
            target_entries = [
                entry
                for entry in entries
                if int(entry.unique_process_id) in pids
                and (
                    (event_object and int(entry.object or 0) == event_object)
                    or (not event_object and int(entry.object_type_index) == event_type)
                )
            ]
            current = current_process()
            process_handles: dict[int, Any] = {}
            closed = 0
            try:
                for entry in target_entries:
                    pid = int(entry.unique_process_id)
                    process_handle = process_handles.get(pid)
                    if process_handle is None:
                        process_handle = open_process(PROCESS_DUP_HANDLE, False, pid)
                        if not process_handle:
                            logger.warning("Could not open Roblox PID %d for singleton detachment.", pid)
                            continue
                        process_handles[pid] = process_handle
                    if not event_object:
                        inspection_handle = ctypes.c_void_p()
                        if not duplicate_handle(
                            process_handle,
                            ctypes.c_void_p(int(entry.handle_value)),
                            current,
                            ctypes.byref(inspection_handle),
                            0,
                            False,
                            DUPLICATE_SAME_ACCESS,
                        ):
                            continue
                        try:
                            name_buffer = ctypes.create_string_buffer(4096)
                            name_needed = ctypes.c_ulong()
                            name_status = query_object(
                                inspection_handle,
                                1,  # ObjectNameInformation
                                name_buffer,
                                len(name_buffer),
                                ctypes.byref(name_needed),
                            )
                            if name_status != 0:
                                continue
                            unicode_name = _UnicodeString.from_buffer(name_buffer)
                            if not unicode_name.buffer or not unicode_name.length:
                                continue
                            handle_name = ctypes.wstring_at(
                                unicode_name.buffer,
                                unicode_name.length // ctypes.sizeof(ctypes.c_wchar),
                            )
                            if not handle_name.casefold().endswith(self.EVENT_NAME.casefold()):
                                continue
                        finally:
                            close_handle(inspection_handle)

                    duplicate = ctypes.c_void_p()
                    if duplicate_handle(
                        process_handle,
                        ctypes.c_void_p(int(entry.handle_value)),
                        current,
                        ctypes.byref(duplicate),
                        0,
                        False,
                        DUPLICATE_CLOSE_SOURCE,
                    ):
                        closed += 1
                        if duplicate.value:
                            close_handle(duplicate)
            finally:
                for process_handle in process_handles.values():
                    close_handle(process_handle)
            return closed
        finally:
            close_handle(local_event)
