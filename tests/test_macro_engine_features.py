"""Bounded coverage for the macro engine's randomised waits, subroutines,
checkpoints, dry runs, pause/resume and run logs.

These tests never touch Windows APIs: the dry-run path is asserted to leave the
input backend completely untouched.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

import pytest

from app.backend.automations.macros import (
    MAX_LOG_ENTRIES,
    MacroEngine,
    MacroParseError,
    MacroRun,
    MacroRunNotFound,
    parse_macro_dsl,
    validate_macro_actions,
)


class _ExplodingBackend:
    """Any call proves a dry run leaked into real input delivery."""

    def verify(self, pid: int, expected_created_at: float | None) -> dict[str, Any] | None:
        raise AssertionError("verify must not be called during a dry run")

    def key(self, target: Mapping[str, Any], key: str, down: bool) -> bool:
        raise AssertionError("key must not be called during a dry run")

    def click(self, target: Mapping[str, Any], x: float, y: float, button: str) -> bool:
        raise AssertionError("click must not be called during a dry run")

    def text(self, target: Mapping[str, Any], value: str) -> bool:
        raise AssertionError("text must not be called during a dry run")


def _run(run_id: str) -> MacroRun:
    return MacroRun(
        run_id=run_id,
        macro_id="macro-1",
        macro_name="Portal farm",
        pid=4321,
        account_id=None,
        expected_created_at=None,
    )


def _wait_for_finish(engine: MacroEngine, run_id: str, timeout: float = 5.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for run in engine.list_runs():
            if run["run_id"] == run_id and run["finished_at"]:
                return run
        time.sleep(0.01)
    raise AssertionError("the macro dry run did not finish in time")


# --- Randomised waits -------------------------------------------------------


def test_wait_range_is_parsed_into_bounds():
    assert parse_macro_dsl("WAIT 500-1500") == [
        {"type": "wait", "milliseconds": 500, "max_milliseconds": 1500}
    ]


def test_equal_wait_bounds_collapse_to_a_fixed_delay():
    assert parse_macro_dsl("WAIT 750-750") == [{"type": "wait", "milliseconds": 750}]


def test_inverted_wait_range_is_rejected():
    with pytest.raises(MacroParseError):
        parse_macro_dsl("WAIT 1500-500")


def test_wait_range_stays_inside_the_engine_bounds():
    with pytest.raises(MacroParseError):
        parse_macro_dsl("WAIT 100-600000")


def test_plain_wait_still_parses():
    assert parse_macro_dsl("WAIT 800") == [{"type": "wait", "milliseconds": 800}]


# --- Checkpoints ------------------------------------------------------------


def test_checkpoint_keeps_its_name():
    assert parse_macro_dsl("CHECKPOINT portal cleared") == [
        {"type": "checkpoint", "name": "portal cleared"}
    ]


def test_checkpoint_names_are_bounded():
    with pytest.raises(MacroParseError):
        validate_macro_actions([{"type": "checkpoint", "name": "x" * 41}])


def test_blank_checkpoint_names_are_rejected():
    with pytest.raises(MacroParseError):
        validate_macro_actions([{"type": "checkpoint", "name": "   "}])


# --- Subroutines ------------------------------------------------------------


def test_subroutines_are_inlined_at_every_call_site():
    actions = parse_macro_dsl(
        "DEF OPENMENU\nPRESS E 60\nWAIT 200\nENDDEF\nCALL OPENMENU\nPRESS W 100\nCALL OPENMENU"
    )
    assert actions == [
        {"type": "key_press", "key": "E", "milliseconds": 60},
        {"type": "wait", "milliseconds": 200},
        {"type": "key_press", "key": "W", "milliseconds": 100},
        {"type": "key_press", "key": "E", "milliseconds": 60},
        {"type": "wait", "milliseconds": 200},
    ]


def test_a_definition_alone_executes_nothing():
    assert parse_macro_dsl("DEF NOOP\nPRESS Q 50\nENDDEF") == []


def test_repeat_blocks_inside_a_subroutine_are_preserved():
    assert parse_macro_dsl("DEF FARM\nREPEAT 2\nPRESS W 50\nEND\nENDDEF\nCALL FARM") == [
        {
            "type": "repeat",
            "count": 2,
            "actions": [{"type": "key_press", "key": "W", "milliseconds": 50}],
        }
    ]


def test_calling_an_undefined_subroutine_is_rejected():
    with pytest.raises(MacroParseError):
        parse_macro_dsl("CALL MISSING")


def test_self_recursive_subroutines_are_rejected():
    with pytest.raises(MacroParseError):
        parse_macro_dsl("DEF LOOPY\nCALL LOOPY\nENDDEF")


def test_missing_enddef_is_rejected():
    with pytest.raises(MacroParseError):
        parse_macro_dsl("DEF OPENMENU\nPRESS E 60")


def test_nested_definitions_are_rejected():
    with pytest.raises(MacroParseError):
        parse_macro_dsl("DEF ONE\nDEF TWO\nENDDEF\nENDDEF")


def test_duplicate_definitions_are_rejected():
    with pytest.raises(MacroParseError):
        parse_macro_dsl("DEF ONE\nPRESS Q 50\nENDDEF\nDEF ONE\nPRESS Q 50\nENDDEF")


# --- Dry runs ---------------------------------------------------------------


def test_dry_run_traces_every_step_without_touching_the_backend():
    engine = MacroEngine(_ExplodingBackend())
    definition = {
        "id": "macro-1",
        "name": "Portal farm",
        "actions": parse_macro_dsl(
            "CHECKPOINT lobby\nPRESS W 120\nWAIT 30000\nREPEAT 3\nPRESS E 50\nEND"
        ),
    }
    started = engine.start(
        definition, pid=4321, expected_created_at=None, account_id=None, dry_run=True
    )
    assert started["dry_run"] is True
    assert started["delivery_mode"] == "dry_run"
    assert started["background_delivery_supported"] is False

    finished = _wait_for_finish(engine, started["run_id"])
    assert finished["state"] == "completed"
    assert finished["error"] is None
    assert finished["checkpoint"] == "lobby"
    assert finished["checkpoints_reached"] == 1

    kinds = [entry["type"] for entry in engine.run_log(started["run_id"])]
    assert kinds[0] == "dry_run_started"
    assert kinds.count("checkpoint") == 1
    assert kinds.count("key_press") == 4
    assert kinds[-1] == "completed"


def test_dry_run_skips_long_waits_instead_of_sleeping():
    engine = MacroEngine(_ExplodingBackend())
    definition = {"id": "m", "name": "Sleeper", "actions": parse_macro_dsl("WAIT 60000")}
    began = time.monotonic()
    started = engine.start(
        definition, pid=1, expected_created_at=None, account_id=None, dry_run=True
    )
    _wait_for_finish(engine, started["run_id"])
    assert time.monotonic() - began < 5.0


def test_dry_run_honours_stop_actions():
    engine = MacroEngine(_ExplodingBackend())
    definition = {
        "id": "m",
        "name": "Halting",
        "actions": parse_macro_dsl("PRESS W 50\nSTOP\nPRESS E 50"),
    }
    started = engine.start(
        definition, pid=1, expected_created_at=None, account_id=None, dry_run=True
    )
    finished = _wait_for_finish(engine, started["run_id"])
    assert finished["state"] == "stopped"
    kinds = [entry["type"] for entry in engine.run_log(started["run_id"])]
    assert kinds.count("key_press") == 1


# --- Pause, resume and logs -------------------------------------------------


def test_a_new_run_is_not_paused():
    assert _run("run-0").to_dict()["paused"] is False


def test_pause_and_resume_toggle_the_run():
    engine = MacroEngine(_ExplodingBackend())
    run = _run("run-1")
    engine._runs[run.run_id] = run

    assert engine.pause("run-1")["paused"] is True
    assert engine.resume("run-1")["paused"] is False
    assert [entry["type"] for entry in engine.run_log("run-1")] == [
        "pause_requested",
        "resume_requested",
    ]


def test_pausing_a_finished_run_is_rejected():
    engine = MacroEngine(_ExplodingBackend())
    run = _run("run-2")
    run.finished_at = "2026-01-01T00:00:00+00:00"
    engine._runs[run.run_id] = run
    with pytest.raises(MacroParseError):
        engine.pause("run-2")
    with pytest.raises(MacroParseError):
        engine.resume("run-2")


def test_stopping_a_paused_run_releases_it():
    engine = MacroEngine(_ExplodingBackend())
    run = _run("run-3")
    engine._runs[run.run_id] = run
    engine.pause("run-3")
    stopped = engine.stop("run-3")
    assert stopped["paused"] is False
    assert run.cancel.is_set() is True


def test_unknown_run_ids_are_reported_as_missing():
    engine = MacroEngine(_ExplodingBackend())
    with pytest.raises(MacroRunNotFound):
        engine.run_log("missing")
    with pytest.raises(MacroRunNotFound):
        engine.pause("missing")
    with pytest.raises(MacroRunNotFound):
        engine.resume("missing")


def test_run_logs_are_bounded():
    run = _run("run-4")
    for index in range(MAX_LOG_ENTRIES + 25):
        run.record("wait", str(index))
    assert len(run.log) == MAX_LOG_ENTRIES
    assert run.log[-1]["detail"] == str(MAX_LOG_ENTRIES + 24)


def test_recorded_entries_are_truncated():
    run = _run("run-5")
    run.record("text", "x" * 400)
    assert len(run.log[-1]["detail"]) == 160
