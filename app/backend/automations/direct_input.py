"""pydirectinput-based macro delivery for one verified Roblox client.

This replaces the previous Win32 prototype as the default input path.  The
prototype attached input queues, forced the foreground window and clicked into
minimized clients through a layered window at alpha 1/255.  It moved a real
avatar, but it is not the requested design, so it now lives behind an explicit
opt-in (see ``macros.legacy_win32_backend_available``).

Design notes, stated plainly:

* pydirectinput emits scan-code SendInput events at the OS level.  They land in
  whichever window owns the foreground, so a run needs its target focused.
  Background delivery into a minimized client is therefore NOT supported here,
  and ``verify`` reports ``background_delivery_supported: False`` instead of
  pretending otherwise.
* Focus is taken once per run (``begin_run``) and released at the end
  (``end_run``), not per action, which keeps runs cheap and avoids window
  thrashing.
* A process-wide lock serialises input segments so two macro runs can never
  interleave keystrokes into different instances.
* Every Windows call goes through the ``WindowApi`` seam.  Production uses
  ``Win32WindowApi``; tests inject a fake, so this module is verifiable on any
  platform without handing the real OS a window handle it would reject.
* Nothing is injected into Roblox and no memory is read or written.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from typing import Any, Mapping, Protocol

import psutil

ROBLOX_PROCESS_NAMES = frozenset({"robloxplayerbeta.exe", "robloxplayer.exe"})

# Astro key names -> pydirectinput key names.
_PYDI_KEYS: dict[str, str] = {
    **{chr(code): chr(code).lower() for code in range(ord("A"), ord("Z") + 1)},
    **{str(digit): str(digit) for digit in range(10)},
    "SPACE": "space",
    "ENTER": "enter",
    "RETURN": "enter",
    "TAB": "tab",
    "ESC": "esc",
    "ESCAPE": "esc",
    "SHIFT": "shift",
    "CTRL": "ctrl",
    "CONTROL": "ctrl",
    "ALT": "alt",
    "UP": "up",
    "DOWN": "down",
    "LEFT": "left",
    "RIGHT": "right",
    **{f"F{number}": f"f{number}" for number in range(1, 13)},
}

_BUTTONS = frozenset({"left", "right", "middle"})
_SW_RESTORE = 9
_FOCUS_TIMEOUT_SECONDS = 1.0


class PyDirectInputUnavailable(RuntimeError):
    """Raised when pydirectinput cannot be imported on this machine."""


def load_pydirectinput() -> Any:
    """Import pydirectinput lazily and configure it for unattended use.

    The import is deliberately deferred: pydirectinput is Windows-only, and the
    test suite plus every non-Windows developer machine must still import this
    module without it installed.
    """

    try:
        import pydirectinput  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - platform dependent
        raise PyDirectInputUnavailable(
            "pydirectinput is required for macro input delivery. Install it with "
            "'pip install pydirectinput' on Windows."
        ) from exc

    # Never abort a run because the pointer reached a screen corner, and never
    # add hidden sleeps: the macro engine owns all timing.
    pydirectinput.FAILSAFE = False
    pydirectinput.PAUSE = 0
    return pydirectinput


def pydirectinput_available() -> bool:
    """Return True when the real input backend can run on this machine."""

    try:
        load_pydirectinput()
    except PyDirectInputUnavailable:
        return False
    return True


class WindowApi(Protocol):
    """The window operations the backend needs, isolated for testability."""

    def main_window(self, pid: int) -> int: ...

    def is_window(self, hwnd: int) -> bool: ...

    def is_minimized(self, hwnd: int) -> bool: ...

    def foreground_window(self) -> int: ...

    def focus(self, hwnd: int, timeout: float) -> bool: ...

    def cursor_position(self) -> tuple[int, int] | None: ...

    def move_cursor(self, x: int, y: int) -> None: ...

    def restore_foreground(self, hwnd: int) -> None: ...

    def client_point(self, hwnd: int, x: float, y: float) -> tuple[int, int] | None: ...


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class Win32WindowApi:
    """Real Windows implementation. Every ctypes call lives here."""

    @staticmethod
    def _user32() -> Any:
        return ctypes.windll.user32  # type: ignore[attr-defined]

    def main_window(self, pid: int) -> int:
        """Return the largest visible top-level window owned by ``pid``."""

        user32 = self._user32()
        found = {"hwnd": 0, "area": -1}

        def callback(hwnd: int, _extra: int) -> bool:
            process_id = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            if int(process_id.value) != pid or not user32.IsWindow(hwnd):
                return True
            if not user32.IsWindowVisible(hwnd):
                return True
            rectangle = _RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rectangle)):
                width = max(0, int(rectangle.right) - int(rectangle.left))
                height = max(0, int(rectangle.bottom) - int(rectangle.top))
                area = width * height
                if area > found["area"]:
                    found["hwnd"] = int(hwnd)
                    found["area"] = area
            return True

        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows(callback_type(callback), 0)
        return int(found["hwnd"])

    def is_window(self, hwnd: int) -> bool:
        return bool(self._user32().IsWindow(int(hwnd)))

    def is_minimized(self, hwnd: int) -> bool:
        return bool(self._user32().IsIconic(int(hwnd)))

    def foreground_window(self) -> int:
        return int(self._user32().GetForegroundWindow() or 0)

    def focus(self, hwnd: int, timeout: float) -> bool:
        """Bring the verified client forward so SendInput reaches it."""

        user32 = self._user32()
        hwnd = int(hwnd)
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, _SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        deadline = time.monotonic() + max(0.1, float(timeout))
        while time.monotonic() < deadline:
            if self.foreground_window() == hwnd:
                return True
            time.sleep(0.02)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        return self.foreground_window() == hwnd

    def cursor_position(self) -> tuple[int, int] | None:
        point = _POINT()
        if not self._user32().GetCursorPos(ctypes.byref(point)):
            return None
        return int(point.x), int(point.y)

    def move_cursor(self, x: int, y: int) -> None:
        self._user32().SetCursorPos(int(x), int(y))

    def restore_foreground(self, hwnd: int) -> None:
        user32 = self._user32()
        if hwnd and user32.IsWindow(int(hwnd)):
            user32.SetForegroundWindow(int(hwnd))

    def client_point(self, hwnd: int, x: float, y: float) -> tuple[int, int] | None:
        """Translate a 0..1 client-relative point into screen coordinates."""

        user32 = self._user32()
        rectangle = _RECT()
        if not user32.GetClientRect(int(hwnd), ctypes.byref(rectangle)):
            return None
        width = max(0, int(rectangle.right) - int(rectangle.left))
        height = max(0, int(rectangle.bottom) - int(rectangle.top))
        if width <= 0 or height <= 0:
            return None
        point = _POINT()
        point.x = int(round(min(max(x, 0.0), 1.0) * (width - 1)))
        point.y = int(round(min(max(y, 0.0), 1.0) * (height - 1)))
        if not user32.ClientToScreen(int(hwnd), ctypes.byref(point)):
            return None
        return int(point.x), int(point.y)


class PyDirectInputRobloxBackend:
    """Deliver bounded macro input to a single verified, focused Roblox window."""

    # Serialises input across every macro run in this process.
    _input_lock = threading.RLock()

    def __init__(
        self,
        *,
        window_api: WindowApi | None = None,
        focus_timeout: float = _FOCUS_TIMEOUT_SECONDS,
    ) -> None:
        self._windows: WindowApi = window_api or Win32WindowApi()
        self._focus_timeout = max(0.1, float(focus_timeout))
        self._sessions: dict[int, dict[str, Any]] = {}

    # Target verification ---------------------------------------------------
    def verify(self, pid: int, expected_created_at: float | None) -> dict[str, Any] | None:
        """Confirm the pid is still the same Roblox client and locate its window."""

        if sys.platform != "win32" or isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            return None
        try:
            process = psutil.Process(pid)
            if process.name().casefold() not in ROBLOX_PROCESS_NAMES:
                return None
            created_at = float(process.create_time())
            # A recycled pid must never inherit a running macro.
            if expected_created_at is not None and abs(created_at - float(expected_created_at)) > 0.01:
                return None
            hwnd = int(self._windows.main_window(pid))
            if not hwnd:
                return None
            return {
                "pid": pid,
                "created_at": created_at,
                "hwnd": hwnd,
                "minimized": bool(self._windows.is_minimized(hwnd)),
                # pydirectinput delivers to the foreground window, so honest
                # reporting: the client has to be focused while it runs.
                "background_delivery_supported": False,
                "delivery_mode": "foreground_input",
            }
        except (psutil.Error, OSError, TypeError, ValueError):
            return None

    # Run lifecycle ---------------------------------------------------------
    def begin_run(self, target: Mapping[str, Any]) -> bool:
        """Take the input lock, focus the client, and remember what to release."""

        thread_id = threading.get_ident()
        if thread_id in self._sessions:
            return False
        try:
            module = load_pydirectinput()
        except PyDirectInputUnavailable:
            return False
        hwnd = int(target.get("hwnd") or 0)
        if not hwnd or not self._windows.is_window(hwnd):
            return False

        self._input_lock.acquire()
        try:
            previous = self._windows.foreground_window()
            cursor = self._windows.cursor_position()
            if not self._windows.focus(hwnd, self._focus_timeout):
                self._input_lock.release()
                return False
            self._sessions[thread_id] = {
                "hwnd": hwnd,
                "module": module,
                "previous": previous,
                "cursor": cursor,
                "held": set(),
            }
            return True
        except Exception:
            self._input_lock.release()
            return False

    def end_run(self, target: Mapping[str, Any]) -> None:
        """Release every held key, restore the previous window, drop the lock."""

        session = self._sessions.pop(threading.get_ident(), None)
        if session is None:
            return
        try:
            module = session["module"]
            for key in tuple(session["held"]):
                try:
                    module.keyUp(key)
                except Exception:
                    pass
            session["held"].clear()
            cursor = session.get("cursor")
            if cursor is not None:
                try:
                    self._windows.move_cursor(int(cursor[0]), int(cursor[1]))
                except Exception:
                    pass
            previous = int(session.get("previous") or 0)
            if previous and previous != int(session["hwnd"]):
                try:
                    self._windows.restore_foreground(previous)
                except Exception:
                    pass
        finally:
            self._input_lock.release()

    def _session(self, target: Mapping[str, Any]) -> dict[str, Any] | None:
        """Return the active session, refusing input if the target drifted."""

        session = self._sessions.get(threading.get_ident())
        if session is None:
            return None
        hwnd = int(session["hwnd"])
        if hwnd != int(target.get("hwnd") or 0):
            return None
        if not self._windows.is_window(hwnd):
            return None
        # Refuse to type into whatever stole focus mid-run.
        if self._windows.foreground_window() != hwnd and not self._windows.focus(
            hwnd, self._focus_timeout
        ):
            return None
        return session

    # Input primitives ------------------------------------------------------
    def key(self, target: Mapping[str, Any], key: str, down: bool) -> bool:
        session = self._session(target)
        name = _PYDI_KEYS.get(str(key).upper())
        if session is None or name is None:
            return False
        module = session["module"]
        try:
            if down:
                module.keyDown(name)
                session["held"].add(name)
            else:
                module.keyUp(name)
                session["held"].discard(name)
        except Exception:
            return False
        return True

    def press(
        self,
        target: Mapping[str, Any],
        key: str,
        milliseconds: int,
        cancel: threading.Event | None = None,
    ) -> bool:
        """Hold a key for a bounded duration, releasing it even if cancelled."""

        if not self.key(target, key, True):
            return False
        try:
            seconds = max(0.0, int(milliseconds) / 1000.0)
            if cancel is not None:
                cancel.wait(seconds)
            else:
                time.sleep(seconds)
        finally:
            released = self.key(target, key, False)
        return released

    def click(self, target: Mapping[str, Any], x: float, y: float, button: str) -> bool:
        session = self._session(target)
        name = str(button).lower()
        if session is None or name not in _BUTTONS:
            return False
        point = self._windows.client_point(int(session["hwnd"]), float(x), float(y))
        if point is None:
            return False
        module = session["module"]
        try:
            module.moveTo(point[0], point[1])
            module.click(x=point[0], y=point[1], button=name)
        except Exception:
            return False
        return True

    def text(self, target: Mapping[str, Any], value: str) -> bool:
        session = self._session(target)
        if session is None:
            return False
        module = session["module"]
        try:
            module.write(str(value))
        except Exception:
            return False
        return True
