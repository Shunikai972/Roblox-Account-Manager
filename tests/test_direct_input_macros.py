"""Tests for the pydirectinput macro backend and the disabled Win32 prototype.

These tests never touch a real desktop.  Both the input library and the window
layer are injected, so they behave identically on a real Windows machine and on
a headless CI box: no invented HWND is ever handed to the actual Win32 API.
"""

from __future__ import annotations

import threading

import pytest

from app.backend.automations import (
    MacroEngine,
    PyDirectInputRobloxBackend,
    PyDirectInputUnavailable,
    Win32RobloxInputBackend,
    legacy_win32_backend_available,
)
from app.backend.automations.direct_input import (
    Win32WindowApi,
    _PYDI_KEYS,
    load_pydirectinput,
)
from app.backend.automations.macros import LEGACY_WIN32_INPUT_FLAG

TARGET_HWND = 4242


class _FakePyDirectInput:
    """Records calls so delivery can be asserted without moving a real mouse."""

    FAILSAFE = True
    PAUSE = 0.1

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def keyDown(self, key: str) -> None:
        self.calls.append(("keyDown", key))

    def keyUp(self, key: str) -> None:
        self.calls.append(("keyUp", key))

    def moveTo(self, x: int, y: int) -> None:
        self.calls.append(("moveTo", (x, y)))

    def click(self, x: int = 0, y: int = 0, button: str = "left") -> None:
        self.calls.append(("click", (x, y, button)))

    def write(self, value: str) -> None:
        self.calls.append(("write", value))


class _FakeWindows:
    """In-memory stand-in for the Win32 window layer."""

    def __init__(self, hwnd: int = TARGET_HWND, *, focused: bool = True) -> None:
        self.hwnd = hwnd
        self.foreground = hwnd if focused else 999
        self.focus_calls = 0
        self.can_focus = True
        self.cursor: tuple[int, int] | None = (10, 20)
        self.restored: list[int] = []
        self.moved: list[tuple[int, int]] = []
        self.client_size = (800, 600)

    def main_window(self, pid: int) -> int:
        return self.hwnd

    def is_window(self, hwnd: int) -> bool:
        return int(hwnd) == self.hwnd

    def is_minimized(self, hwnd: int) -> bool:
        return False

    def foreground_window(self) -> int:
        return self.foreground

    def focus(self, hwnd: int, timeout: float) -> bool:
        self.focus_calls += 1
        if not self.can_focus:
            return False
        self.foreground = int(hwnd)
        return True

    def cursor_position(self) -> tuple[int, int] | None:
        return self.cursor

    def move_cursor(self, x: int, y: int) -> None:
        self.moved.append((int(x), int(y)))

    def restore_foreground(self, hwnd: int) -> None:
        self.restored.append(int(hwnd))

    def client_point(self, hwnd: int, x: float, y: float) -> tuple[int, int] | None:
        # Mirrors Win32WindowApi.client_point, including the 0..1 clamp.
        width, height = self.client_size
        clamped_x = min(max(x, 0.0), 1.0)
        clamped_y = min(max(y, 0.0), 1.0)
        return int(round(clamped_x * (width - 1))), int(round(clamped_y * (height - 1)))


def _backend(
    module: _FakePyDirectInput,
    windows: _FakeWindows | None = None,
) -> tuple[PyDirectInputRobloxBackend, _FakeWindows]:
    """Build a backend with an already-established session."""

    windows = windows or _FakeWindows()
    backend = PyDirectInputRobloxBackend(window_api=windows)
    backend._sessions[threading.get_ident()] = {
        "hwnd": windows.hwnd,
        "module": module,
        "previous": 0,
        "cursor": (0, 0),
        "cursor_dirty": False,
        "held": set(),
    }
    return backend, windows


# Engine wiring ------------------------------------------------------------


def test_engine_defaults_to_the_pydirectinput_backend() -> None:
    engine = MacroEngine()

    assert isinstance(engine._backend, PyDirectInputRobloxBackend)


def test_backend_defaults_to_the_real_window_layer() -> None:
    backend = PyDirectInputRobloxBackend()

    assert isinstance(backend._windows, Win32WindowApi)


def test_pydirectinput_is_imported_lazily() -> None:
    """Constructing the backend must never require the Windows-only package."""

    PyDirectInputRobloxBackend()


# Key mapping --------------------------------------------------------------


def test_every_dsl_key_maps_to_a_pydirectinput_name() -> None:
    from app.backend.automations.macros import _KEY_CODES

    missing = sorted(name for name in _KEY_CODES if name not in _PYDI_KEYS)

    assert missing == [], missing


def test_key_names_are_translated_for_pydirectinput() -> None:
    module = _FakePyDirectInput()
    backend, windows = _backend(module)
    target = {"hwnd": windows.hwnd}

    assert backend.key(target, "W", True) is True
    assert backend.key(target, "SPACE", False) is True
    assert backend.key(target, "ESCAPE", True) is True

    assert module.calls == [("keyDown", "w"), ("keyUp", "space"), ("keyDown", "esc")]


def test_unknown_keys_are_refused() -> None:
    module = _FakePyDirectInput()
    backend, windows = _backend(module)

    assert backend.key({"hwnd": windows.hwnd}, "NOPE", True) is False
    assert module.calls == []


# Held keys are always released -------------------------------------------


def test_press_releases_the_key_and_tracks_held_state() -> None:
    module = _FakePyDirectInput()
    backend, windows = _backend(module)
    cancel = threading.Event()
    cancel.set()  # Skip the wait: a cancelled run must still release the key.

    assert backend.press({"hwnd": windows.hwnd}, "W", 5_000, cancel) is True

    assert module.calls == [("keyDown", "w"), ("keyUp", "w")]
    assert backend._sessions[threading.get_ident()]["held"] == set()


def test_end_run_releases_keys_left_held() -> None:
    module = _FakePyDirectInput()
    backend, windows = _backend(module)
    target = {"hwnd": windows.hwnd}
    assert backend.key(target, "W", True) is True

    # end_run drops the shared input lock, so it must be held first.
    backend._input_lock.acquire()
    backend.end_run(target)

    assert module.calls == [("keyDown", "w"), ("keyUp", "w")]
    assert threading.get_ident() not in backend._sessions


def test_keyboard_only_run_does_not_move_the_users_cursor() -> None:
    module = _FakePyDirectInput()
    backend, windows = _backend(module)
    target = {"hwnd": windows.hwnd}
    assert backend.key(target, "W", True) is True

    backend._input_lock.acquire()
    backend.end_run(target)

    assert windows.moved == []


def test_click_run_restores_the_cursor_after_macro_mouse_input() -> None:
    module = _FakePyDirectInput()
    backend, windows = _backend(module)
    target = {"hwnd": windows.hwnd}
    assert backend.click(target, 0.5, 0.5, "left") is True

    backend._input_lock.acquire()
    backend.end_run(target)

    assert windows.moved == [(0, 0)]


# Focus and target drift ---------------------------------------------------


def test_input_is_refused_when_the_window_drifts() -> None:
    module = _FakePyDirectInput()
    backend, _windows = _backend(module)

    assert backend.key({"hwnd": 9999}, "W", True) is False
    assert backend.text({"hwnd": 9999}, "hello") is False
    assert module.calls == []


def test_focus_is_reclaimed_when_another_window_steals_it() -> None:
    module = _FakePyDirectInput()
    windows = _FakeWindows(focused=False)
    backend, _windows = _backend(module, windows)

    assert backend.key({"hwnd": windows.hwnd}, "W", True) is True
    assert windows.focus_calls == 1
    assert module.calls == [("keyDown", "w")]


def test_input_is_refused_when_focus_cannot_be_reclaimed() -> None:
    module = _FakePyDirectInput()
    windows = _FakeWindows(focused=False)
    windows.can_focus = False
    backend, _windows = _backend(module, windows)

    assert backend.key({"hwnd": windows.hwnd}, "W", True) is False
    assert module.calls == []


def test_input_is_refused_without_an_active_session() -> None:
    backend = PyDirectInputRobloxBackend(window_api=_FakeWindows())

    assert backend.key({"hwnd": TARGET_HWND}, "W", True) is False
    assert backend.text({"hwnd": TARGET_HWND}, "hi") is False
    assert backend.click({"hwnd": TARGET_HWND}, 0.5, 0.5, "left") is False


# Text and clicks ----------------------------------------------------------


def test_text_delivery_uses_pydirectinput_write() -> None:
    module = _FakePyDirectInput()
    backend, windows = _backend(module)

    assert backend.text({"hwnd": windows.hwnd}, "hello") is True
    assert module.calls == [("write", "hello")]


def test_click_maps_normalised_coordinates_onto_the_client_area() -> None:
    module = _FakePyDirectInput()
    backend, windows = _backend(module)

    assert backend.click({"hwnd": windows.hwnd}, 0.5, 0.5, "left") is True

    # 800x600 client area -> centre point, then a click at the same spot.
    assert module.calls == [("moveTo", (400, 300)), ("click", (400, 300, "left"))]


def test_click_is_clamped_to_the_client_area() -> None:
    module = _FakePyDirectInput()
    backend, windows = _backend(module)

    assert backend.click({"hwnd": windows.hwnd}, 5.0, -3.0, "right") is True

    assert module.calls == [("moveTo", (799, 0)), ("click", (799, 0, "right"))]


def test_invalid_mouse_button_is_refused() -> None:
    module = _FakePyDirectInput()
    backend, windows = _backend(module)

    assert backend.click({"hwnd": windows.hwnd}, 0.5, 0.5, "scroll") is False
    assert module.calls == []


# Verification contract ----------------------------------------------------


def test_verify_rejects_invalid_pids() -> None:
    backend = PyDirectInputRobloxBackend(window_api=_FakeWindows())

    assert backend.verify(0, None) is None
    assert backend.verify(-1, None) is None
    assert backend.verify(True, None) is None  # type: ignore[arg-type]


def test_backend_reports_foreground_only_delivery() -> None:
    """Honesty check: pydirectinput cannot type into a minimized client."""

    from pathlib import Path

    source = Path("app/backend/automations/direct_input.py").read_text(encoding="utf-8")

    assert '"background_delivery_supported": False' in source
    assert '"delivery_mode": "foreground_input"' in source


# The retired prototype ----------------------------------------------------


def test_legacy_win32_prototype_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LEGACY_WIN32_INPUT_FLAG, raising=False)
    backend = Win32RobloxInputBackend()

    assert legacy_win32_backend_available() is False
    assert backend.verify(4321, None) is None
    assert backend.begin_run({"hwnd": TARGET_HWND}) is False


def test_legacy_win32_prototype_can_be_opted_into(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LEGACY_WIN32_INPUT_FLAG, "1")

    assert legacy_win32_backend_available() is True


def test_legacy_flag_ignores_meaningless_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("", "0", "false", "off", "perhaps"):
        monkeypatch.setenv(LEGACY_WIN32_INPUT_FLAG, value)
        assert legacy_win32_backend_available() is False, value


def test_missing_pydirectinput_raises_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "pydirectinput":
            raise ImportError("no pydirectinput here")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(PyDirectInputUnavailable) as error:
        load_pydirectinput()

    assert "pip install pydirectinput" in str(error.value)
