"""Single-window macro mode.

pydirectinput delivers keystrokes to whichever window owns the foreground, so
two live runs interleave their input into one window and quietly corrupt both
macros.  This build therefore serves one Roblox window at a time.  The
multi-window path is not deleted: ``ASTRO_ENABLE_MULTI_WINDOW_MACROS=1`` brings
it back untouched.

No Windows API is involved here: the exploding backend proves the refusal
happens *before* any window is verified.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from app.backend.automations.macros import (
    MacroBusyError,
    MacroEngine,
    MacroParseError,
    MacroRun,
)

DEFINITION: dict[str, Any] = {
    "id": "macro-1",
    "name": "Portal farm",
    "actions": [{"type": "wait", "milliseconds": 10}],
}

MULTI_WINDOW_FLAG = "ASTRO_ENABLE_MULTI_WINDOW_MACROS"


class _ExplodingBackend:
    """Any call proves the guard let a refused run reach the window layer."""

    def verify(self, pid: int, expected_created_at: float | None) -> dict[str, Any] | None:
        raise AssertionError("verify must not be called once the run is refused")

    def key(self, target: Mapping[str, Any], key: str, down: bool) -> bool:
        raise AssertionError("key must not be called once the run is refused")

    def click(self, target: Mapping[str, Any], x: float, y: float, button: str) -> bool:
        raise AssertionError("click must not be called once the run is refused")

    def text(self, target: Mapping[str, Any], value: str) -> bool:
        raise AssertionError("text must not be called once the run is refused")


class _StubBackend:
    """Verifies a window and swallows input, without touching Windows."""

    def verify(self, pid: int, expected_created_at: float | None) -> dict[str, Any] | None:
        return {
            "pid": pid,
            "created_at": expected_created_at,
            "hwnd": 4242,
            "minimized": False,
            "background_delivery_supported": False,
            "delivery_mode": "foreground_input",
        }

    def key(self, target: Mapping[str, Any], key: str, down: bool) -> bool:
        return True

    def click(self, target: Mapping[str, Any], x: float, y: float, button: str) -> bool:
        return True

    def text(self, target: Mapping[str, Any], value: str) -> bool:
        return True


def _inject(
    engine: MacroEngine,
    run_id: str = "run-live",
    *,
    name: str = "Portal farm",
    dry_run: bool = False,
    finished: bool = False,
    cancelled: bool = False,
) -> MacroRun:
    """Place a run in the registry without starting a worker thread."""

    run = MacroRun(
        run_id=run_id,
        macro_id="macro-1",
        macro_name=name,
        pid=4321,
        account_id=None,
        expected_created_at=None,
        dry_run=dry_run,
    )
    if finished:
        run.finished_at = "2026-08-14T08:00:00+00:00"
        run.state = "completed"
    if cancelled:
        run.cancel.set()
    engine._runs[run_id] = run
    return run


def _start(engine: MacroEngine, *, dry_run: bool = False) -> dict[str, Any]:
    return engine.start(
        DEFINITION,
        pid=4321,
        expected_created_at=None,
        account_id=None,
        dry_run=dry_run,
    )


def _wait_for_finish(engine: MacroEngine, run_id: str, timeout: float = 5.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for run in engine.list_runs():
            if run["run_id"] == run_id and run["finished_at"]:
                return run
        time.sleep(0.01)
    raise AssertionError("the macro run did not finish in time")


# --- The refusal ------------------------------------------------------------


def test_a_second_live_macro_is_refused():
    engine = MacroEngine(_ExplodingBackend())
    _inject(engine)
    try:
        _start(engine)
    except MacroBusyError as error:
        assert "one Roblox window at a time" in str(error)
        assert "Portal farm" in str(error)
    else:
        raise AssertionError("a second live macro must be refused")


def test_the_refusal_names_every_blocking_macro():
    engine = MacroEngine(_ExplodingBackend())
    _inject(engine, "run-a", name="Portal farm")
    _inject(engine, "run-b", name="Trade sweep")
    try:
        _start(engine)
    except MacroBusyError as error:
        assert "Portal farm" in str(error)
        assert "Trade sweep" in str(error)
    else:
        raise AssertionError("the run must be refused")


def test_a_stopping_macro_gets_its_own_message():
    engine = MacroEngine(_ExplodingBackend())
    _inject(engine, cancelled=True)
    try:
        _start(engine)
    except MacroBusyError as error:
        assert "still stopping" in str(error)
    else:
        raise AssertionError("a stopping macro must still hold the window")


def test_the_refusal_reaches_the_user_as_a_macro_error():
    # The service already maps MacroParseError to a user-facing message, so the
    # refusal needs no extra plumbing to be readable in the UI.
    assert issubclass(MacroBusyError, MacroParseError)


# --- What must stay allowed -------------------------------------------------


def test_a_dry_run_is_allowed_while_a_macro_is_live():
    engine = MacroEngine(_ExplodingBackend())
    _inject(engine)
    started = _start(engine, dry_run=True)
    finished = _wait_for_finish(engine, started["run_id"])
    assert finished["dry_run"] is True


def test_a_finished_macro_does_not_block_the_next_one():
    engine = MacroEngine(_StubBackend())
    _inject(engine, finished=True)
    started = _start(engine)
    assert _wait_for_finish(engine, started["run_id"])["state"] == "completed"


def test_a_live_dry_run_does_not_block_a_real_macro():
    engine = MacroEngine(_StubBackend())
    _inject(engine, dry_run=True)
    started = _start(engine)
    assert _wait_for_finish(engine, started["run_id"])["state"] == "completed"


def test_the_flag_brings_concurrent_windows_back(monkeypatch):
    monkeypatch.setenv(MULTI_WINDOW_FLAG, "1")
    engine = MacroEngine(_StubBackend())
    _inject(engine)
    started = _start(engine)
    assert _wait_for_finish(engine, started["run_id"])["state"] == "completed"


def test_concurrent_windows_stay_off_without_the_flag(monkeypatch):
    monkeypatch.delenv(MULTI_WINDOW_FLAG, raising=False)
    engine = MacroEngine(_ExplodingBackend())
    _inject(engine)
    try:
        _start(engine)
    except MacroBusyError:
        pass
    else:
        raise AssertionError("single-window mode must be the default")


# --- Counting ---------------------------------------------------------------


def test_active_run_count_ignores_dry_runs_and_finished_runs():
    engine = MacroEngine(_StubBackend())
    _inject(engine, "run-live")
    _inject(engine, "run-dry", dry_run=True)
    _inject(engine, "run-done", finished=True)
    assert engine.active_run_count() == 1
