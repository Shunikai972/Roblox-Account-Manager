"""Bounded per-window macro parsing and execution for verified Roblox clients."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
import os
import random
import re
import shlex
import sys
import threading
import time
from typing import Any, Callable, Mapping, Protocol, Sequence
from uuid import uuid4

import psutil

from app.backend.core.config import feature_enabled

from .direct_input import PyDirectInputRobloxBackend

# Concurrent macro windows are hidden behind a flag: see HIDDEN_FEATURES.
_MULTI_WINDOW_FEATURE = "multi_window_macros"

_ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("type", wintypes.DWORD), ("value", _INPUTUNION)]


MAX_SOURCE_CHARS = 32_000
MAX_ACTIONS = 500
MAX_DEPTH = 6
MAX_REPEAT = 100
MAX_WAIT_MS = 60_000
MAX_PRESS_MS = 10_000
MAX_TEXT_CHARS = 500
MAX_RUN_SECONDS = 86_400
MAX_SUBROUTINES = 20
MAX_SUBROUTINE_CALLS = 100
MAX_CHECKPOINT_CHARS = 40
MAX_LOG_ENTRIES = 200
# LAUNCH, TELEPORT and RESTART act on the machine rather than on a window, so
# they are bounded far more tightly than keystrokes.
MAX_CONTROL_ACTIONS = 20
MAX_CONDITION_VALUE_CHARS = 60
MAX_CONDITION_SECONDS = 86_400

# Only checks the engine can answer on its own are allowed. There is no pixel
# or screenshot check in this build, so none is offered here.
CONDITION_CHECKS = {
    "runtime_above": "seconds",
    "runtime_below": "seconds",
    "checkpoint_reached": "name",
    "checkpoint_missing": "name",
    "variable_equals": "pair",
    "variable_missing": "name",
    "account_running": "none",
    "account_stopped": "none",
}
CONTROL_ACTIONS = {"launch", "teleport", "restart"}
_PLACE_ID_PATTERN = re.compile(r"^[0-9]{1,20}$")
_JOB_ID_PATTERN = re.compile(r"^[0-9a-fA-F-]{8,64}$")
_VARIABLE_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")

# The Win32 prototype below is retained for reference only.  It is disabled
# unless this flag is set explicitly, so the default macro path is always
# pydirectinput.  See app/backend/automations/direct_input.py.
LEGACY_WIN32_INPUT_FLAG = "ASTRO_ALLOW_LEGACY_WIN32_INPUT"
_LEGACY_TRUTHY = {"1", "true", "yes", "on", "enabled"}


def legacy_win32_backend_available() -> bool:
    """Return True only when the deprecated Win32 input path is opted into."""

    return str(os.environ.get(LEGACY_WIN32_INPUT_FLAG, "")).strip().casefold() in _LEGACY_TRUTHY


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


class MacroRunNotFound(MacroParseError):
    """Raised when a run id does not match a known macro run."""


class MacroBusyError(MacroParseError):
    """Raised when a second macro would compete for the foreground window."""


class MacroInputBackend(Protocol):
    def verify(self, pid: int, expected_created_at: float | None) -> dict[str, Any] | None: ...
    def key(self, target: Mapping[str, Any], key: str, down: bool) -> bool: ...
    def click(self, target: Mapping[str, Any], x: float, y: float, button: str) -> bool: ...
    def text(self, target: Mapping[str, Any], value: str) -> bool: ...


class MacroControlBackend(Protocol):
    """What a macro needs from the application to launch, move or restart.

    Each call returns the new window descriptor, ``{"pid": int,
    "created_at": float}``, so the run can re-pin itself to the client that now
    exists.  Returning ``None`` means the action did not produce a usable
    client, and the run stops instead of typing into the wrong window.
    """

    def launch(self, account_id: str) -> dict[str, Any] | None: ...
    def teleport(self, account_id: str, place_id: str, job_id: str) -> dict[str, Any] | None: ...
    def restart(self, account_id: str) -> dict[str, Any] | None: ...
    def is_running(self, account_id: str) -> bool: ...


def parse_macro_dsl(source: str) -> list[dict[str, Any]]:
    """Parse the small Astro macro DSL without executing arbitrary code."""

    if not isinstance(source, str) or len(source) > MAX_SOURCE_CHARS:
        raise MacroParseError(f"Macro source must contain at most {MAX_SOURCE_CHARS} characters.")
    root: list[dict[str, Any]] = []
    stack: list[list[dict[str, Any]]] = [root]
    subroutines: dict[str, list[dict[str, Any]]] = {}
    defining: str | None = None
    calls = 0
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
                stack[-1].append(_parse_wait_token(parts[1]))
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
            elif command == "IF" and len(parts) >= 2:
                branch: dict[str, Any] = {
                    "type": "condition",
                    "check": parts[1].lower(),
                    "value": " ".join(parts[2:]),
                    "actions": [],
                }
                stack[-1].append(branch)
                stack.append(branch["actions"])
                if len(stack) > MAX_DEPTH + 1:
                    raise MacroParseError(f"Line {line_number}: block nesting is too deep.")
            elif command == "LAUNCH" and len(parts) == 1:
                stack[-1].append({"type": "launch"})
            elif command == "TELEPORT" and len(parts) in {2, 3}:
                stack[-1].append({
                    "type": "teleport",
                    "place_id": parts[1],
                    "job_id": parts[2] if len(parts) == 3 else "",
                })
            elif command == "RESTART" and len(parts) == 1:
                stack[-1].append({"type": "restart"})
            elif command == "END" and len(parts) == 1:
                if len(stack) <= (2 if defining is not None else 1):
                    raise MacroParseError(f"Line {line_number}: END has no matching REPEAT or IF.")
                stack.pop()
            elif command == "STOP" and len(parts) == 1:
                stack[-1].append({"type": "stop"})
            elif command == "CHECKPOINT" and len(parts) >= 2:
                stack[-1].append({"type": "checkpoint", "name": " ".join(parts[1:])})
            elif command == "DEF" and len(parts) == 2:
                if defining is not None or len(stack) != 1:
                    raise MacroParseError(f"Line {line_number}: DEF cannot be nested.")
                name = parts[1].upper()
                if name in subroutines:
                    raise MacroParseError(f"Line {line_number}: subroutine {name} is already defined.")
                if len(subroutines) >= MAX_SUBROUTINES:
                    raise MacroParseError(f"A macro may define at most {MAX_SUBROUTINES} subroutines.")
                defining = name
                subroutines[name] = []
                stack.append(subroutines[name])
            elif command == "ENDDEF" and len(parts) == 1:
                if defining is None or len(stack) != 2:
                    raise MacroParseError(f"Line {line_number}: ENDDEF has no matching DEF.")
                stack.pop()
                defining = None
            elif command == "CALL" and len(parts) == 2:
                name = parts[1].upper()
                if name == defining:
                    raise MacroParseError(f"Line {line_number}: a subroutine cannot call itself.")
                if name not in subroutines:
                    raise MacroParseError(f"Line {line_number}: subroutine {name} is not defined yet.")
                calls += 1
                if calls > MAX_SUBROUTINE_CALLS:
                    raise MacroParseError(
                        f"A macro may contain at most {MAX_SUBROUTINE_CALLS} CALL statements."
                    )
                stack[-1].extend(deepcopy(subroutines[name]))
            else:
                raise MacroParseError(f"Line {line_number}: unsupported command or arguments.")
        except (TypeError, ValueError) as exc:
            if isinstance(exc, MacroParseError):
                raise
            raise MacroParseError(f"Line {line_number}: invalid numeric value.") from exc
    if defining is not None:
        raise MacroParseError(f"Subroutine {defining} is missing ENDDEF.")
    if len(stack) != 1:
        raise MacroParseError("A REPEAT or IF block is missing END.")
    return validate_macro_actions(root)


def _parse_wait_token(token: str) -> dict[str, Any]:
    """Parse `WAIT 800` or the randomised `WAIT 500-1500` form."""

    text = str(token).strip()
    if "-" in text[1:]:
        low, _, high = text.partition("-")
        return {
            "type": "wait",
            "milliseconds": int(low),
            "max_milliseconds": int(high),
        }
    return {"type": "wait", "milliseconds": int(text)}


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
            if raw.get("max_milliseconds") is not None:
                upper = _bounded_int(
                    raw.get("max_milliseconds"), 0, MAX_WAIT_MS, "Maximum wait duration"
                )
                if upper < action["milliseconds"]:
                    raise MacroParseError("A randomised wait must end after it starts.")
                if upper != action["milliseconds"]:
                    action["max_milliseconds"] = upper
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
        elif kind == "checkpoint":
            name = " ".join(str(raw.get("name") or "").split())
            if not name or len(name) > MAX_CHECKPOINT_CHARS:
                raise MacroParseError(
                    f"Checkpoint names must contain 1 to {MAX_CHECKPOINT_CHARS} characters."
                )
            action["name"] = name
        elif kind == "stop":
            pass
        elif kind == "condition":
            action["check"], action["value"] = _valid_condition(raw.get("check"), raw.get("value"))
            action["actions"] = validate_macro_actions(raw.get("actions"), _depth=_depth + 1)
            if not action["actions"]:
                raise MacroParseError("A condition block needs at least one action inside it.")
        elif kind == "launch":
            pass
        elif kind == "teleport":
            place_id = str(raw.get("place_id") or "").strip()
            if not _PLACE_ID_PATTERN.fullmatch(place_id):
                raise MacroParseError("A teleport needs a numeric place id.")
            job_id = str(raw.get("job_id") or "").strip()
            if job_id and not _JOB_ID_PATTERN.fullmatch(job_id):
                raise MacroParseError("That server id is not valid.")
            action["place_id"] = place_id
            action["job_id"] = job_id
        elif kind == "restart":
            pass
        else:
            raise MacroParseError(f"Unsupported macro action: {kind or 'empty'}.")
        normalized.append(action)
    if _action_count(normalized) > MAX_ACTIONS:
        raise MacroParseError(f"A macro may contain at most {MAX_ACTIONS} expanded block definitions.")
    if _depth == 0 and _control_count(normalized) > MAX_CONTROL_ACTIONS:
        raise MacroParseError(
            f"A macro may launch, teleport or restart at most {MAX_CONTROL_ACTIONS} times."
        )
    return normalized


def _valid_condition(check: Any, value: Any) -> tuple[str, str]:
    """Validate one condition and return its normalized check and argument."""

    name = str(check or "").strip().lower()
    shape = CONDITION_CHECKS.get(name)
    if shape is None:
        allowed = ", ".join(sorted(CONDITION_CHECKS))
        raise MacroParseError(f"Unsupported condition: {name or 'empty'}. Use one of {allowed}.")
    text = " ".join(str(value or "").split())
    if len(text) > MAX_CONDITION_VALUE_CHARS:
        raise MacroParseError(f"A condition value may contain at most {MAX_CONDITION_VALUE_CHARS} characters.")
    if shape == "none":
        return name, ""
    if shape == "seconds":
        seconds = _bounded_int(text or None, 0, MAX_CONDITION_SECONDS, "Condition duration")
        return name, str(seconds)
    if shape == "name":
        if not text:
            raise MacroParseError(f"The {name} condition needs a name.")
        return name, text
    variable, _, expected = text.partition(" ")
    if not _VARIABLE_NAME_PATTERN.fullmatch(variable):
        raise MacroParseError("A variable condition needs a variable name, then the value to compare.")
    return name, f"{variable} {expected}".strip()


def _control_count(actions: Sequence[Mapping[str, Any]]) -> int:
    total = 0
    for action in actions:
        kind = action.get("type")
        if kind in CONTROL_ACTIONS:
            total += 1
        children = action.get("actions")
        if isinstance(children, Sequence) and not isinstance(children, (str, bytes)):
            multiplier = int(action.get("count") or 1) if kind == "repeat" else 1
            total += _control_count(children) * max(1, multiplier)
    return total


def _started_event() -> threading.Event:
    """A run starts un-paused: the event stays set while the run may proceed."""

    event = threading.Event()
    event.set()
    return event


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
    delivery_mode: str = "unknown"
    dry_run: bool = False
    checkpoint: str | None = None
    checkpoints_reached: int = 0
    variables: dict[str, str] = field(default_factory=dict)
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    resumed: threading.Event = field(default_factory=_started_event, repr=False)
    log: deque = field(
        default_factory=lambda: deque(maxlen=MAX_LOG_ENTRIES), repr=False
    )

    def record(self, kind: str, detail: str = "") -> None:
        """Append one bounded audit line to the run log."""

        self.log.append(
            {
                "at": datetime.now(UTC).isoformat(),
                "step": self.current_step,
                "type": kind,
                "detail": str(detail)[:160],
            }
        )

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
            "delivery_mode": self.delivery_mode,
            "dry_run": self.dry_run,
            "paused": not self.resumed.is_set(),
            "checkpoint": self.checkpoint,
            "checkpoints_reached": self.checkpoints_reached,
        }


class MacroEngine:
    """Run independent macro workers against immutable Roblox identities."""

    def __init__(
        self,
        backend: MacroInputBackend | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        controller: MacroControlBackend | None = None,
    ) -> None:
        self._backend = backend or PyDirectInputRobloxBackend()
        self._clock = clock
        self._controller = controller
        self._lock = threading.RLock()
        self._runs: dict[str, MacroRun] = {}
        self._threads: dict[str, threading.Thread] = {}

    def set_controller(self, controller: MacroControlBackend | None) -> None:
        """Wire the launch/teleport/restart backend once the app is built."""

        self._controller = controller

    def start(self, definition: Mapping[str, Any], *, pid: int, expected_created_at: float | None, account_id: str | None, dry_run: bool = False, variables: Mapping[str, Any] | None = None) -> dict[str, Any]:
        actions = validate_macro_actions(definition.get("actions"))
        if not actions:
            raise MacroParseError("Macro has no actions.")
        # A dry run delivers no input, so it never competes for the foreground.
        if not dry_run:
            self._require_single_window_capacity()
        # A dry run traces the macro without touching Roblox, so it skips
        # window verification and never delivers input.
        target = None if dry_run else self._backend.verify(pid, expected_created_at)
        if target is None and not dry_run:
            raise MacroParseError("The selected Roblox process or window could not be verified.")
        run = MacroRun(
            run_id=str(uuid4()),
            macro_id=str(definition.get("id") or ""),
            macro_name=str(definition.get("name") or "Macro")[:120],
            pid=pid,
            account_id=account_id,
            expected_created_at=expected_created_at,
            background_delivery_supported=bool((target or {}).get("background_delivery_supported", False)),
            delivery_mode="dry_run" if dry_run else str((target or {}).get("delivery_mode") or "foreground_fallback"),
            dry_run=bool(dry_run),
            variables={str(key): str(value) for key, value in (variables or {}).items()},
        )
        thread = threading.Thread(target=self._execute, args=(run, actions), name=f"astro-macro-{run.run_id[:8]}", daemon=True)
        with self._lock:
            self._runs[run.run_id] = run
            self._threads[run.run_id] = thread
        thread.start()
        return run.to_dict()

    def stop(self, run_id: str) -> dict[str, Any]:
        run = self._run(run_id)
        run.cancel.set()
        # A paused run must still observe cancellation immediately.
        run.resumed.set()
        run.record("stop_requested")
        return run.to_dict()

    def pause(self, run_id: str) -> dict[str, Any]:
        """Hold a run before its next action, keeping its progress intact."""

        run = self._run(run_id)
        if run.finished_at is not None:
            raise MacroParseError("Macro run has already finished.")
        run.resumed.clear()
        run.record("pause_requested")
        return run.to_dict()

    def resume(self, run_id: str) -> dict[str, Any]:
        """Release a paused run so it continues from the next action."""

        run = self._run(run_id)
        if run.finished_at is not None:
            raise MacroParseError("Macro run has already finished.")
        run.record("resume_requested")
        run.resumed.set()
        return run.to_dict()

    def run_log(self, run_id: str) -> list[dict[str, Any]]:
        """Return the bounded action log recorded for one run."""

        return list(self._run(run_id).log)

    def _run(self, run_id: str) -> MacroRun:
        with self._lock:
            run = self._runs.get(str(run_id))
        if run is None:
            raise MacroRunNotFound("Macro run was not found.")
        return run

    def list_runs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [run.to_dict() for run in sorted(self._runs.values(), key=lambda item: item.started_at, reverse=True)[:100]]

    def _require_single_window_capacity(self) -> None:
        """Refuse a second live run while single-window mode is in force.

        pydirectinput delivers input to whichever window holds the foreground.
        Two live runs therefore interleave their keystrokes into one window and
        silently corrupt both macros, so this build serves one window at a time.
        """

        if feature_enabled(_MULTI_WINDOW_FEATURE):
            return
        with self._lock:
            busy = [
                run
                for run in self._runs.values()
                if run.finished_at is None and not run.dry_run
            ]
        if not busy:
            return
        if all(run.cancel.is_set() for run in busy):
            raise MacroBusyError(
                "The previous macro is still stopping. Try again in a moment."
            )
        names = ", ".join(sorted({run.macro_name for run in busy}))
        raise MacroBusyError(
            f"Macros run on one Roblox window at a time in this build. Stop {names} first."
        )

    def active_run_count(self) -> int:
        """Return how many runs are still live, dry runs excluded."""

        with self._lock:
            return sum(
                1
                for run in self._runs.values()
                if run.finished_at is None and not run.dry_run
            )

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
        session_target: Mapping[str, Any] | None = None
        try:
            if run.dry_run:
                run.record("dry_run_started", "No input is delivered during a dry run.")
            else:
                session_target = self._backend.verify(run.pid, run.expected_created_at)
                if session_target is None:
                    raise MacroParseError("The selected Roblox process or window could not be verified.")
                begin_run = getattr(self._backend, "begin_run", None)
                if callable(begin_run) and not begin_run(session_target):
                    raise MacroParseError("Roblox could not be focused for reliable input delivery.")
            stopped = self._execute_actions(run, actions, started)
            run.state = "cancelled" if run.cancel.is_set() else ("stopped" if stopped else "completed")
            run.record(run.state)
        except MacroParseError as exc:
            run.state = "failed"
            run.error = str(exc)
        except Exception:
            run.state = "failed"
            run.error = "Macro input delivery failed."
        finally:
            end_run = getattr(self._backend, "end_run", None)
            if session_target is not None and callable(end_run):
                end_run(session_target)
            run.finished_at = datetime.now(UTC).isoformat()

    def _execute_actions(self, run: MacroRun, actions: list[dict[str, Any]], started: float) -> bool:
        for action in actions:
            if run.cancel.is_set():
                return True
            if not run.resumed.is_set():
                run.state = "paused"
                # Stay responsive to cancellation while parked.
                while not run.resumed.is_set() and not run.cancel.is_set():
                    run.resumed.wait(0.1)
                if run.cancel.is_set():
                    return True
                run.state = "running"
            if self._clock() - started > MAX_RUN_SECONDS:
                raise MacroParseError("Macro exceeded the maximum run duration.")
            if run.dry_run:
                target: Mapping[str, Any] = {"dry_run": True}
            else:
                verified = self._backend.verify(run.pid, run.expected_created_at)
                if verified is None:
                    raise MacroParseError("The target Roblox process changed or closed.")
                target = verified
            run.current_step += 1
            kind = action["type"]
            if kind == "checkpoint":
                run.checkpoint = action["name"]
                run.checkpoints_reached += 1
                run.record("checkpoint", action["name"])
                continue
            run.record(kind, _describe_action(action))
            if run.dry_run:
                if kind == "repeat":
                    for _ in range(action["count"]):
                        if self._execute_actions(run, action["actions"], started):
                            return True
                elif kind == "condition":
                    # A dry run traces both sides so the operator sees every
                    # step, and says so rather than pretending it evaluated.
                    run.record("condition_traced", f"{action['check']} {action['value']}".strip())
                    if self._execute_actions(run, action["actions"], started):
                        return True
                elif kind == "stop":
                    return True
                continue
            if kind == "wait":
                run.cancel.wait(_wait_seconds(action))
            elif kind == "key_down":
                if not self._backend.key(target, action["key"], True):
                    raise MacroParseError("A key-down event was rejected by the target window.")
            elif kind == "key_up":
                if not self._backend.key(target, action["key"], False):
                    raise MacroParseError("A key-up event was rejected by the target window.")
            elif kind == "key_press":
                press = getattr(self._backend, "press", None)
                if callable(press):
                    accepted = press(
                        target,
                        action["key"],
                        action["milliseconds"],
                        run.cancel,
                    )
                else:
                    accepted = self._backend.key(target, action["key"], True)
                    if accepted:
                        run.cancel.wait(action["milliseconds"] / 1000.0)
                        accepted = self._backend.key(target, action["key"], False)
                if not accepted:
                    raise MacroParseError("A key press was rejected by the target window.")
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
            elif kind == "condition":
                verdict = self._evaluate_condition(run, action, started)
                if verdict is None:
                    run.record("condition_unknown", action["check"])
                elif verdict:
                    if self._execute_actions(run, action["actions"], started):
                        return True
                else:
                    run.record("condition_skipped", action["check"])
            elif kind in CONTROL_ACTIONS:
                self._run_control_action(run, action)
            elif kind == "stop":
                return True
        return False

    def _evaluate_condition(self, run: MacroRun, action: Mapping[str, Any], started: float) -> bool | None:
        """Answer one condition, or None when the engine cannot know."""

        check = str(action.get("check") or "")
        value = str(action.get("value") or "")
        if check in {"runtime_above", "runtime_below"}:
            elapsed = self._clock() - started
            limit = float(value or 0)
            return elapsed > limit if check == "runtime_above" else elapsed < limit
        if check in {"checkpoint_reached", "checkpoint_missing"}:
            reached = (run.checkpoint or "").casefold() == value.casefold()
            return reached if check == "checkpoint_reached" else not reached
        if check == "variable_equals":
            name, _, expected = value.partition(" ")
            return run.variables.get(name, "") == expected
        if check == "variable_missing":
            return not run.variables.get(value.split(" ")[0], "")
        controller = self._controller
        if controller is None or not run.account_id:
            return None
        running = bool(controller.is_running(run.account_id))
        return running if check == "account_running" else not running

    def _run_control_action(self, run: MacroRun, action: Mapping[str, Any]) -> None:
        """Launch, teleport or restart, then re-pin the run to the new client."""

        controller = self._controller
        if controller is None:
            raise MacroParseError(
                "This macro launches or restarts a client, which the macro engine cannot do on its own."
            )
        if not run.account_id:
            raise MacroParseError("Launch, teleport and restart need a macro bound to an account.")
        kind = str(action.get("type"))
        if kind == "launch":
            target = controller.launch(run.account_id)
        elif kind == "teleport":
            target = controller.teleport(run.account_id, str(action.get("place_id") or ""), str(action.get("job_id") or ""))
        else:
            target = controller.restart(run.account_id)
        if not isinstance(target, Mapping) or not target.get("pid"):
            raise MacroParseError(f"The {kind} step did not produce a usable Roblox client.")
        # The client changed, so every later keystroke must follow it.
        run.pid = int(target["pid"])
        run.expected_created_at = target.get("created_at")
        run.checkpoint = None
        run.record(f"{kind}_done", f"now pinned to pid {run.pid}")


class Win32RobloxInputBackend:
    """DEPRECATED prototype. Disabled unless ASTRO_ALLOW_LEGACY_WIN32_INPUT is set.

    This is the old AttachThreadInput + SetForegroundWindow + SendInput path,
    including the layered-window trick that clicked into minimized clients at
    alpha 1/255.  It did drive a real avatar, but it is not the requested
    design and is no longer the default: MacroEngine now uses
    PyDirectInputRobloxBackend.  Every entry point below returns a refusal
    while the flag is unset, so it cannot be reached by accident.

    Roblox consumes raw/global input and can silently ignore PostMessage even
    when Windows reports that the message was queued.  This backend attaches
    the input queues long enough to activate the exact verified HWND and uses
    SendInput while an already-minimized Roblox client remains iconic.  A
    position-dependent click needs a real client rectangle, so the backend
    restores that client at alpha 1/255, sends a Raw Input mouse move/click,
    and minimizes it again before restoring its normal opacity.  The client is
    never visibly shown and no code is injected into Roblox.
    """

    _input_lock = threading.RLock()
    _INPUT_KEYBOARD = 1
    _INPUT_MOUSE = 0
    _KEYEVENTF_KEYUP = 0x0002
    _KEYEVENTF_UNICODE = 0x0004
    _MOUSEEVENTF_MOVE = 0x0001
    _MOUSEEVENTF_ABSOLUTE = 0x8000
    _MOUSEEVENTF_VIRTUALDESK = 0x4000
    _GWL_EXSTYLE = -20
    _WS_EX_LAYERED = 0x00080000
    _LWA_ALPHA = 0x00000002
    _SW_RESTORE = 9
    _SW_MINIMIZE = 6
    _BUTTONS = {
        "left": (0x0002, 0x0004),
        "right": (0x0008, 0x0010),
        "middle": (0x0020, 0x0040),
    }

    def __init__(self) -> None:
        self._sessions: dict[int, dict[str, Any]] = {}

    def verify(self, pid: int, expected_created_at: float | None) -> dict[str, Any] | None:
        if not legacy_win32_backend_available():
            return None
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
            found = {"hwnd": 0, "area": 0}

            def callback(hwnd: int, _extra: int) -> bool:
                process_id = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
                if (
                    int(process_id.value) == pid
                    and user32.IsWindow(hwnd)
                    and user32.IsWindowVisible(hwnd)
                ):
                    rectangle = wintypes.RECT()
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
            if not found["hwnd"]:
                return None
            minimized = bool(user32.IsIconic(found["hwnd"]))
            return {
                "pid": pid,
                "created_at": actual_created,
                "hwnd": int(found["hwnd"]),
                "minimized": minimized,
                "background_delivery_supported": True,
                "delivery_mode": "minimized_input" if minimized else "foreground_input",
            }
        except (psutil.Error, OSError, TypeError, ValueError):
            return None

    def begin_run(self, target: Mapping[str, Any]) -> bool:
        if not legacy_win32_backend_available():
            return False
        hwnd = int(target["hwnd"])
        try:
            user32 = ctypes.windll.user32
            if not user32.IsWindow(hwnd) or threading.get_ident() in self._sessions:
                return False
            self._sessions[threading.get_ident()] = {
                "hwnd": hwnd,
                "previous": 0,
                "current_thread": 0,
                "attached": [],
                "cursor": None,
                "held": set(),
                "input_active": False,
            }
            return True
        except Exception:
            return False

    def end_run(self, target: Mapping[str, Any]) -> None:
        session = self._sessions.pop(threading.get_ident(), None)
        if session is None:
            return
        try:
            if session["held"] and not session["input_active"]:
                self._activate_session(session)
            for code in tuple(session["held"]):
                self._send_key(int(code), False)
            session["held"].clear()
        finally:
            self._deactivate_session(session)

    def _active_session(self, target: Mapping[str, Any]) -> dict[str, Any] | None:
        session = self._sessions.get(threading.get_ident())
        if session is None or int(session["hwnd"]) != int(target["hwnd"]):
            return None
        if not ctypes.windll.user32.IsWindow(int(session["hwnd"])):
            return None
        return session

    def _activate_session(self, session: dict[str, Any]) -> bool:
        hwnd = int(session["hwnd"])
        user32 = ctypes.windll.user32
        if session["input_active"]:
            return int(user32.GetForegroundWindow() or 0) == hwnd
        self._input_lock.acquire()
        try:
            previous = int(user32.GetForegroundWindow() or 0)
            cursor = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(cursor))
            current_thread = int(ctypes.windll.kernel32.GetCurrentThreadId())
            target_thread = int(user32.GetWindowThreadProcessId(hwnd, None) or 0)
            previous_thread = int(user32.GetWindowThreadProcessId(previous, None) or 0) if previous else 0
            attached: list[int] = []
            for thread_id in (target_thread, previous_thread):
                if not thread_id or thread_id == current_thread or thread_id in attached:
                    continue
                if not user32.AttachThreadInput(current_thread, thread_id, True):
                    for attached_thread in reversed(attached):
                        user32.AttachThreadInput(current_thread, attached_thread, False)
                    self._input_lock.release()
                    return False
                attached.append(thread_id)
            user32.BringWindowToTop(hwnd)
            user32.SetActiveWindow(hwnd)
            user32.SetForegroundWindow(hwnd)
            deadline = time.monotonic() + 0.75
            while int(user32.GetForegroundWindow() or 0) != hwnd and time.monotonic() < deadline:
                time.sleep(0.025)
                user32.BringWindowToTop(hwnd)
                user32.SetActiveWindow(hwnd)
                user32.SetForegroundWindow(hwnd)
            if int(user32.GetForegroundWindow() or 0) != hwnd:
                for attached_thread in reversed(attached):
                    user32.AttachThreadInput(current_thread, attached_thread, False)
                self._input_lock.release()
                return False
            session.update({
                "previous": previous,
                "current_thread": current_thread,
                "attached": attached,
                "cursor": (int(cursor.x), int(cursor.y)),
                "input_active": True,
            })
            return True
        except Exception:
            self._input_lock.release()
            return False

    def _deactivate_session(self, session: dict[str, Any]) -> None:
        if not session.get("input_active"):
            return
        user32 = ctypes.windll.user32
        try:
            cursor = session.get("cursor")
            if cursor is not None:
                user32.SetCursorPos(*cursor)
            hwnd = int(session["hwnd"])
            previous = int(session.get("previous") or 0)
            if previous and previous != hwnd and user32.IsWindow(previous):
                user32.BringWindowToTop(previous)
                user32.SetActiveWindow(previous)
                user32.SetForegroundWindow(previous)
        finally:
            current_thread = int(session.get("current_thread") or 0)
            for attached_thread in reversed(session.get("attached") or []):
                user32.AttachThreadInput(current_thread, int(attached_thread), False)
            session.update({
                "previous": 0,
                "current_thread": 0,
                "attached": [],
                "cursor": None,
                "input_active": False,
            })
            self._input_lock.release()

    @staticmethod
    def _send_input(event: _INPUT) -> bool:
        return int(ctypes.windll.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_INPUT))) == 1

    def _send_key(self, code: int, down: bool) -> bool:
        scan = int(ctypes.windll.user32.MapVirtualKeyW(code, 0))
        event = _INPUT(
            type=self._INPUT_KEYBOARD,
            value=_INPUTUNION(ki=_KEYBDINPUT(code, scan, 0 if down else self._KEYEVENTF_KEYUP, 0, 0)),
        )
        return self._send_input(event)

    def key(self, target: Mapping[str, Any], key: str, down: bool) -> bool:
        code = _KEY_CODES.get(key.upper())
        session = self._active_session(target)
        if code is None or session is None:
            return False
        if not self._activate_session(session):
            return False
        sent = self._send_key(code, down)
        if sent:
            if down:
                session["held"].add(code)
            else:
                session["held"].discard(code)
        elif not down:
            session["held"].discard(code)
        if not session["held"]:
            self._deactivate_session(session)
        return sent

    def press(
        self,
        target: Mapping[str, Any],
        key: str,
        milliseconds: int,
        cancel: threading.Event,
    ) -> bool:
        if not self.key(target, key, True):
            return False
        cancel.wait(max(0, int(milliseconds)) / 1000.0)
        return self.key(target, key, False)

    def click(self, target: Mapping[str, Any], x: float, y: float, button: str) -> bool:
        session = self._active_session(target)
        if session is None:
            return False
        if not self._activate_session(session):
            return False
        user32 = ctypes.windll.user32
        hwnd = int(target["hwnd"])
        was_minimized = bool(user32.IsIconic(hwnd))
        original_exstyle: int | None = None
        try:
            if was_minimized:
                original_exstyle = int(user32.GetWindowLongW(hwnd, self._GWL_EXSTYLE))
                user32.SetWindowLongW(hwnd, self._GWL_EXSTYLE, original_exstyle | self._WS_EX_LAYERED)
                if not user32.SetLayeredWindowAttributes(hwnd, 0, 1, self._LWA_ALPHA):
                    return False
                user32.ShowWindowAsync(hwnd, self._SW_RESTORE)
                deadline = time.monotonic() + 0.75
                while user32.IsIconic(hwnd) and time.monotonic() < deadline:
                    time.sleep(0.025)
                if user32.IsIconic(hwnd):
                    return False
                user32.BringWindowToTop(hwnd)
                user32.SetActiveWindow(hwnd)
                user32.SetForegroundWindow(hwnd)

            rectangle = wintypes.RECT()
            if not user32.GetClientRect(hwnd, ctypes.byref(rectangle)):
                return False
            width = int(rectangle.right) - int(rectangle.left)
            height = int(rectangle.bottom) - int(rectangle.top)
            if width <= 1 or height <= 1:
                return False
            px = max(0, min(width - 1, round(float(x) * (width - 1))))
            py = max(0, min(height - 1, round(float(y) * (height - 1))))
            point = wintypes.POINT(px, py)
            if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
                return False
            virtual_x = int(user32.GetSystemMetrics(76))
            virtual_y = int(user32.GetSystemMetrics(77))
            virtual_width = max(1, int(user32.GetSystemMetrics(78)))
            virtual_height = max(1, int(user32.GetSystemMetrics(79)))
            absolute_x = round((int(point.x) - virtual_x) * 65_535 / max(1, virtual_width - 1))
            absolute_y = round((int(point.y) - virtual_y) * 65_535 / max(1, virtual_height - 1))
            move_event = _INPUT(
                type=self._INPUT_MOUSE,
                value=_INPUTUNION(mi=_MOUSEINPUT(
                    absolute_x,
                    absolute_y,
                    0,
                    self._MOUSEEVENTF_MOVE | self._MOUSEEVENTF_ABSOLUTE | self._MOUSEEVENTF_VIRTUALDESK,
                    0,
                    0,
                )),
            )
            down, up = self._BUTTONS[button]
            down_event = _INPUT(type=self._INPUT_MOUSE, value=_INPUTUNION(mi=_MOUSEINPUT(0, 0, 0, down, 0, 0)))
            up_event = _INPUT(type=self._INPUT_MOUSE, value=_INPUTUNION(mi=_MOUSEINPUT(0, 0, 0, up, 0, 0)))
            if not self._send_input(move_event):
                return False
            time.sleep(0.025)
            return self._send_input(down_event) and self._send_input(up_event)
        finally:
            if was_minimized and original_exstyle is not None:
                user32.ShowWindowAsync(hwnd, self._SW_MINIMIZE)
                deadline = time.monotonic() + 0.75
                while not user32.IsIconic(hwnd) and time.monotonic() < deadline:
                    time.sleep(0.025)
                user32.SetWindowLongW(hwnd, self._GWL_EXSTYLE, original_exstyle)
            if not session["held"]:
                self._deactivate_session(session)

    def text(self, target: Mapping[str, Any], value: str) -> bool:
        session = self._active_session(target)
        if session is None or not self._activate_session(session):
            return False
        try:
            for character in value:
                code = ord(character)
                down = _INPUT(
                    type=self._INPUT_KEYBOARD,
                    value=_INPUTUNION(ki=_KEYBDINPUT(0, code, self._KEYEVENTF_UNICODE, 0, 0)),
                )
                up = _INPUT(
                    type=self._INPUT_KEYBOARD,
                    value=_INPUTUNION(ki=_KEYBDINPUT(0, code, self._KEYEVENTF_UNICODE | self._KEYEVENTF_KEYUP, 0, 0)),
                )
                if not self._send_input(down) or not self._send_input(up):
                    return False
            return True
        finally:
            if not session["held"]:
                self._deactivate_session(session)


def _wait_seconds(action: Mapping[str, Any]) -> float:
    """Return the wait duration, randomised when a range was configured."""

    low = int(action.get("milliseconds") or 0)
    high = int(action.get("max_milliseconds") or low)
    if high > low:
        return random.randint(low, high) / 1000.0
    return low / 1000.0


def _describe_action(action: Mapping[str, Any]) -> str:
    """One-line summary used by run logs and dry runs."""

    kind = str(action.get("type") or "")
    if kind == "wait":
        high = action.get("max_milliseconds")
        if high:
            return f"{action.get('milliseconds')}-{high} ms"
        return f"{action.get('milliseconds')} ms"
    if kind in {"key_down", "key_up"}:
        return str(action.get("key") or "")
    if kind == "key_press":
        return f"{action.get('key')} for {action.get('milliseconds')} ms"
    if kind == "mouse_click":
        return f"{action.get('button')} at {action.get('x')}, {action.get('y')}"
    if kind == "text":
        return f"{len(str(action.get('value') or ''))} characters"
    if kind == "repeat":
        return f"{action.get('count')} iterations"
    if kind == "condition":
        return f"{action.get('check')} {action.get('value')}".strip()
    if kind == "teleport":
        return f"place {action.get('place_id')}" + (f" server {action.get('job_id')}" if action.get("job_id") else "")
    if kind in {"launch", "restart"}:
        return kind
    return ""


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
    return sum(
        1 + (_action_count(action.get("actions", [])) if action.get("type") in {"repeat", "condition"} else 0)
        for action in actions
    )
