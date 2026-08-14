"""Bounded per-window macro parsing and execution for verified Roblox clients."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
from datetime import UTC, datetime
import re
import shlex
import sys
import threading
import time
from typing import Any, Callable, Mapping, Protocol, Sequence
from uuid import uuid4

import psutil


MAX_SOURCE_CHARS = 32_000
MAX_ACTIONS = 500
MAX_DEPTH = 6
MAX_REPEAT = 100
MAX_WAIT_MS = 60_000
MAX_PRESS_MS = 10_000
MAX_TEXT_CHARS = 500
MAX_RUN_SECONDS = 86_400
_ROBLOX_NAMES = {"robloxplayerbeta.exe", "robloxplayer.exe"}
_KEY_NAME = re.compile(r"^[A-Z0-9_]{1,24}$")
_KEY_CODES = {
    **{chr(code): code for code in range(ord("A"), ord("Z") + 1)},
    **{str(code): ord(str(code)) for code in range(10)},
    "SPACE": 0x20,
    "ENTER": 0x0D,
    "RETURN": 0x0D,
    "TAB": 0x09,
    "ESC": 0x1B,
    "ESCAPE": 0x1B,
    "SHIFT": 0x10,
    "CTRL": 0x11,
    "CONTROL": 0x11,
    "ALT": 0x12,
    "UP": 0x26,
    "DOWN": 0x28,
    "LEFT": 0x25,
    "RIGHT": 0x27,
    **{f"F{number}": 0x6F + number for number in range(1, 13)},
}


class MacroParseError(ValueError):
    """Raised for a bounded, user-correctable macro definition error."""


class MacroInputBackend(Protocol):
    def verify(self, pid: int, expected_created_at: float | None) -> dict[str, Any] | None: ...
    def key(self, target: Mapping[str, Any], key: str, down: bool) -> bool: ...
    def click(self, target: Mapping[str, Any], x: float, y: float, button: str) -> bool: ...
    def text(self, target: Mapping[str, Any], value: str) -> bool: ...


def parse_macro_dsl(source: str) -> list[dict[str, Any]]:
    """Parse the small Astro macro DSL without executing arbitrary code."""

    if not isinstance(source, str) or len(source) > MAX_SOURCE_CHARS:
        raise MacroParseError(f"Macro source must contain at most {MAX_SOURCE_CHARS} characters.")
    root: list[dict[str, Any]] = []
    stack: list[list[dict[str, Any]]] = [root]
    for line_number, raw_line in enumerate(source.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            parts = shlex.split(line, posix=True)
        except ValueError as exc:
            raise MacroParseError(f"Line {line_number}: invalid quoting.") from exc
        if not parts:
            continue
        command = parts[0].upper()
        try:
            if command == "WAIT" and len(parts) == 2:
                stack[-1].append({"type": "wait", "milliseconds": int(parts[1])})
            elif command == "PRESS" and len(parts) in {2, 3}:
                stack[-1].append({
                    "type": "key_press",
                    "key": parts[1].upper(),
                    "milliseconds": int(parts[2]) if len(parts) == 3 else 80,
                })
            elif command in {"DOWN", "UP"} and len(parts) == 2:
                stack[-1].append({"type": "key_down" if command == "DOWN" else "key_up", "key": parts[1].upper()})
            elif command == "CLICK" and len(parts) in {3, 4}:
                stack[-1].append({
                    "type": "mouse_click",
                    "x": float(parts[1]),
                    "y": float(parts[2]),
                    "button": parts[3].lower() if len(parts) == 4 else "left",
                })
            elif command == "TEXT" and len(parts) >= 2:
                stack[-1].append({"type": "text", "value": " ".join(parts[1:])})
            elif command == "REPEAT" and len(parts) == 2:
                action: dict[str, Any] = {"type": "repeat", "count": int(parts[1]), "actions": []}
                stack[-1].append(action)
                stack.append(action["actions"])
                if len(stack) > MAX_DEPTH + 1:
                    raise MacroParseError(f"Line {line_number}: repeat nesting is too deep.")
            elif command == "END" and len(parts) == 1:
                if len(stack) == 1:
                    raise MacroParseError(f"Line {line_number}: END has no matching REPEAT.")
                stack.pop()
            elif command == "STOP" and len(parts) == 1:
                stack[-1].append({"type": "stop"})
            else:
                raise MacroParseError(f"Line {line_number}: unsupported command or arguments.")
        except (TypeError, ValueError) as exc:
            if isinstance(exc, MacroParseError):
                raise
            raise MacroParseError(f"Line {line_number}: invalid numeric value.") from exc
    if len(stack) != 1:
        raise MacroParseError("A REPEAT block is missing END.")
    return validate_macro_actions(root)


def validate_macro_actions(actions: Any, *, _depth: int = 0) -> list[dict[str, Any]]:
    """Return a normalized bounded action tree suitable for persistence."""

    if _depth > MAX_DEPTH:
        raise MacroParseError("Macro nesting is too deep.")
    if not isinstance(actions, Sequence) or isinstance(actions, (str, bytes, bytearray)):
        raise MacroParseError("Macro actions must be a list.")
    normalized: list[dict[str, Any]] = []
    for raw in actions:
        if not isinstance(raw, Mapping):
            raise MacroParseError("Each macro action must be an object.")
        kind = str(raw.get("type") or "").strip().lower()
        action: dict[str, Any] = {"type": kind}
        if kind == "wait":
            action["milliseconds"] = _bounded_int(raw.get("milliseconds"), 0, MAX_WAIT_MS, "Wait duration")
        elif kind in {"key_down", "key_up", "key_press"}:
            action["key"] = _valid_key(raw.get("key"))
            if kind == "key_press":
                action["milliseconds"] = _bounded_int(raw.get("milliseconds", 80), 1, MAX_PRESS_MS, "Key duration")
        elif kind == "mouse_click":
            action["x"] = _bounded_float(raw.get("x"), 0.0, 1.0, "Click X")
            action["y"] = _bounded_float(raw.get("y"), 0.0, 1.0, "Click Y")
            button = str(raw.get("button") or "left").lower()
            if button not in {"left", "right", "middle"}:
                raise MacroParseError("Mouse button must be left, right, or middle.")
            action["button"] = button
        elif kind == "text":
            value = str(raw.get("value") or "")
            if not value or len(value) > MAX_TEXT_CHARS or any(ord(character) < 32 and character not in "\t\n" for character in value):
                raise MacroParseError(f"Text actions must contain 1 to {MAX_TEXT_CHARS} printable characters.")
            action["value"] = value
        elif kind == "repeat":
            action["count"] = _bounded_int(raw.get("count"), 1, MAX_REPEAT, "Repeat count")
            action["actions"] = validate_macro_actions(raw.get("actions"), _depth=_depth + 1)
        elif kind == "stop":
            pass
        else:
            raise MacroParseError(f"Unsupported macro action: {kind or 'empty'}.")
        normalized.append(action)
    if _action_count(normalized) > MAX_ACTIONS:
        raise MacroParseError(f"A macro may contain at most {MAX_ACTIONS} expanded block definitions.")
    return normalized


@dataclass(slots=True)
class MacroRun:
    run_id: str
    macro_id: str
    macro_name: str
    pid: int
    account_id: str | None
    expected_created_at: float | None
    state: str = "starting"
    current_step: int = 0
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished_at: str | None = None
    error: str | None = None
    background_delivery_supported: bool = True
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "macro_id": self.macro_id,
            "macro_name": self.macro_name,
            "pid": self.pid,
            "account_id": self.account_id,
            "state": self.state,
            "current_step": self.current_step,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "background_delivery_supported": self.background_delivery_supported,
        }


class MacroEngine:
    """Run independent macro workers against immutable Roblox identities."""

    def __init__(self, backend: MacroInputBackend | None = None, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._backend = backend or Win32RobloxInputBackend()
        self._clock = clock
        self._lock = threading.RLock()
        self._runs: dict[str, MacroRun] = {}
        self._threads: dict[str, threading.Thread] = {}

    def start(self, definition: Mapping[str, Any], *, pid: int, expected_created_at: float | None, account_id: str | None) -> dict[str, Any]:
        actions = validate_macro_actions(definition.get("actions"))
        if not actions:
            raise MacroParseError("Macro has no actions.")
        target = self._backend.verify(pid, expected_created_at)
        if target is None:
            raise MacroParseError("The selected Roblox process or window could not be verified.")
        run = MacroRun(
            run_id=str(uuid4()),
            macro_id=str(definition.get("id") or ""),
            macro_name=str(definition.get("name") or "Macro")[:120],
            pid=pid,
            account_id=account_id,
            expected_created_at=expected_created_at,
            background_delivery_supported=bool(target.get("background_delivery_supported", True)),
        )
        thread = threading.Thread(target=self._execute, args=(run, actions), name=f"astro-macro-{run.run_id[:8]}", daemon=True)
        with self._lock:
            self._runs[run.run_id] = run
            self._threads[run.run_id] = thread
        thread.start()
        return run.to_dict()

    def stop(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            run = self._runs.get(str(run_id))
        if run is None:
            raise MacroParseError("Macro run was not found.")
        run.cancel.set()
        return run.to_dict()

    def list_runs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [run.to_dict() for run in sorted(self._runs.values(), key=lambda item: item.started_at, reverse=True)[:100]]

    def stop_all(self) -> None:
        with self._lock:
            runs = tuple(self._runs.values())
            threads = tuple(self._threads.values())
        for run in runs:
            run.cancel.set()
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join(timeout=1.0)

    def _execute(self, run: MacroRun, actions: list[dict[str, Any]]) -> None:
        run.state = "running"
        started = self._clock()
        try:
            stopped = self._execute_actions(run, actions, started)
            run.state = "cancelled" if run.cancel.is_set() else ("stopped" if stopped else "completed")
        except MacroParseError as exc:
            run.state = "failed"
            run.error = str(exc)
        except Exception:
            run.state = "failed"
            run.error = "Macro input delivery failed."
        finally:
            run.finished_at = datetime.now(UTC).isoformat()

    def _execute_actions(self, run: MacroRun, actions: list[dict[str, Any]], started: float) -> bool:
        for action in actions:
            if run.cancel.is_set():
                return True
            if self._clock() - started > MAX_RUN_SECONDS:
                raise MacroParseError("Macro exceeded the maximum run duration.")
            target = self._backend.verify(run.pid, run.expected_created_at)
            if target is None:
                raise MacroParseError("The target Roblox process changed or closed.")
            run.current_step += 1
            kind = action["type"]
            if kind == "wait":
                run.cancel.wait(action["milliseconds"] / 1000.0)
            elif kind == "key_down":
                if not self._backend.key(target, action["key"], True):
                    raise MacroParseError("A key-down event was rejected by the target window.")
            elif kind == "key_up":
                if not self._backend.key(target, action["key"], False):
                    raise MacroParseError("A key-up event was rejected by the target window.")
            elif kind == "key_press":
                if not self._backend.key(target, action["key"], True):
                    raise MacroParseError("A key press was rejected by the target window.")
                run.cancel.wait(action["milliseconds"] / 1000.0)
                self._backend.key(target, action["key"], False)
            elif kind == "mouse_click":
                if not self._backend.click(target, action["x"], action["y"], action["button"]):
                    raise MacroParseError("A mouse click was rejected by the target window.")
            elif kind == "text":
                if not self._backend.text(target, action["value"]):
                    raise MacroParseError("Text input was rejected by the target window.")
            elif kind == "repeat":
                for _ in range(action["count"]):
                    if self._execute_actions(run, action["actions"], started):
                        return True
            elif kind == "stop":
                return True
        return False


class Win32RobloxInputBackend:
    """Deliver window messages to a verified Roblox HWND without global input."""

    _WM_KEYDOWN = 0x0100
    _WM_KEYUP = 0x0101
    _WM_CHAR = 0x0102
    _WM_MOUSEMOVE = 0x0200
    _BUTTONS = {
        "left": (0x0201, 0x0202, 0x0001),
        "right": (0x0204, 0x0205, 0x0002),
        "middle": (0x0207, 0x0208, 0x0010),
    }

    def verify(self, pid: int, expected_created_at: float | None) -> dict[str, Any] | None:
        if sys.platform != "win32" or isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            return None
        try:
            process = psutil.Process(pid)
            if process.name().casefold() not in _ROBLOX_NAMES:
                return None
            actual_created = float(process.create_time())
            if expected_created_at is not None and abs(actual_created - float(expected_created_at)) > 0.01:
                return None
            user32 = ctypes.windll.user32
            found = ctypes.c_void_p()

            def callback(hwnd: int, _extra: int) -> bool:
                process_id = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
                if int(process_id.value) == pid and user32.IsWindow(hwnd):
                    found.value = hwnd
                    return False
                return True

            callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            user32.EnumWindows(callback_type(callback), 0)
            if not found.value:
                return None
            return {
                "pid": pid,
                "created_at": actual_created,
                "hwnd": int(found.value),
                "minimized": bool(user32.IsIconic(found.value)),
                "background_delivery_supported": True,
            }
        except (psutil.Error, OSError, TypeError, ValueError):
            return None

    def key(self, target: Mapping[str, Any], key: str, down: bool) -> bool:
        code = _KEY_CODES.get(key.upper())
        if code is None:
            return False
        return bool(ctypes.windll.user32.PostMessageW(int(target["hwnd"]), self._WM_KEYDOWN if down else self._WM_KEYUP, code, 0))

    def click(self, target: Mapping[str, Any], x: float, y: float, button: str) -> bool:
        user32 = ctypes.windll.user32
        rectangle = wintypes.RECT()
        if not user32.GetClientRect(int(target["hwnd"]), ctypes.byref(rectangle)):
            return False
        px = max(0, min(int(rectangle.right) - 1, round(float(x) * max(0, int(rectangle.right) - 1))))
        py = max(0, min(int(rectangle.bottom) - 1, round(float(y) * max(0, int(rectangle.bottom) - 1))))
        lparam = (py << 16) | (px & 0xFFFF)
        down, up, flag = self._BUTTONS[button]
        user32.PostMessageW(int(target["hwnd"]), self._WM_MOUSEMOVE, 0, lparam)
        return bool(user32.PostMessageW(int(target["hwnd"]), down, flag, lparam) and user32.PostMessageW(int(target["hwnd"]), up, 0, lparam))

    def text(self, target: Mapping[str, Any], value: str) -> bool:
        user32 = ctypes.windll.user32
        return all(bool(user32.PostMessageW(int(target["hwnd"]), self._WM_CHAR, ord(character), 0)) for character in value)


def _valid_key(value: Any) -> str:
    key = str(value or "").strip().upper()
    if not _KEY_NAME.fullmatch(key) or key not in _KEY_CODES:
        raise MacroParseError("Key name is unsupported.")
    return key


def _bounded_int(value: Any, minimum: int, maximum: int, label: str) -> int:
    if isinstance(value, bool):
        raise MacroParseError(f"{label} is invalid.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise MacroParseError(f"{label} is invalid.") from exc
    if not minimum <= parsed <= maximum:
        raise MacroParseError(f"{label} must be between {minimum} and {maximum}.")
    return parsed


def _bounded_float(value: Any, minimum: float, maximum: float, label: str) -> float:
    if isinstance(value, bool):
        raise MacroParseError(f"{label} is invalid.")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise MacroParseError(f"{label} is invalid.") from exc
    if not minimum <= parsed <= maximum:
        raise MacroParseError(f"{label} must be between {minimum} and {maximum}.")
    return parsed


def _action_count(actions: Sequence[Mapping[str, Any]]) -> int:
    return sum(1 + (_action_count(action.get("actions", [])) if action.get("type") == "repeat" else 0) for action in actions)
