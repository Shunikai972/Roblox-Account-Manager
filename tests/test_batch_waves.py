"""Batch launcher waves: pause, readiness gate, bounded waiting.

The launcher refuses a delay under 0.5 s on purpose, so these tests use the
smallest delay the product actually allows instead of weakening the rule.
"""

from __future__ import annotations

import time

import pytest

from app.backend.core.errors import ValidationError
from app.backend.roblox.batch_launcher import BatchLauncher

MIN_DELAY = 0.5


def _wait_until_done(launcher: BatchLauncher, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not launcher.get_status()["in_progress"]:
            return
        time.sleep(0.01)
    raise AssertionError("The batch did not finish in time.")


def test_a_batch_without_waves_keeps_the_old_flat_delay() -> None:
    launched: list[str] = []

    def _launch(account_id: str, target: object) -> dict[str, object]:
        launched.append(account_id)
        return {"accepted": True}

    launcher = BatchLauncher(_launch)
    launcher.start_batch(["a", "b", "c"], delay_seconds=MIN_DELAY)
    _wait_until_done(launcher)
    status = launcher.get_status()
    assert launched == ["a", "b", "c"]
    assert status["launched"] == 3
    assert status["waves"] == 1
    assert status["waiting_for_wave"] is False


def test_a_wave_pause_happens_only_at_the_wave_boundary() -> None:
    stamps: list[float] = []

    def _launch(account_id: str, target: object) -> dict[str, object]:
        stamps.append(time.monotonic())
        return {"accepted": True}

    launcher = BatchLauncher(_launch)
    launcher.start_batch(["a", "b", "c", "d"], delay_seconds=MIN_DELAY, wave_size=2, wave_pause_seconds=1.6)
    _wait_until_done(launcher)
    assert len(stamps) == 4
    # Inside a wave the gap is the plain delay; across the boundary it is the
    # wave pause, which is what protects the machine.
    assert stamps[1] - stamps[0] < 1.2
    assert stamps[2] - stamps[1] >= 1.3
    assert stamps[3] - stamps[2] < 1.2


def test_the_wave_counter_reaches_the_last_wave() -> None:
    launcher = BatchLauncher(lambda account_id, target: {"accepted": True})
    launcher.start_batch(["a", "b", "c", "d"], delay_seconds=MIN_DELAY, wave_size=2, wave_pause_seconds=0.6)
    _wait_until_done(launcher)
    status = launcher.get_status()
    assert status["waves"] == 2
    assert status["wave"] == 2
    assert status["launched"] == 4


def test_the_queue_waits_while_the_machine_says_it_is_busy() -> None:
    calls: list[int] = []

    def _ready() -> dict[str, object]:
        calls.append(1)
        # Busy for the first polls of the first gate, then free.
        if len(calls) < 3:
            return {"allowed": False, "reason": "CPU is at 95%, above the 80% launch limit"}
        return {"allowed": True, "reason": ""}

    launcher = BatchLauncher(lambda account_id, target: {"accepted": True})
    launcher._WAVE_POLL_SECONDS = 0.05
    launcher.start_batch(
        ["a", "b", "c"],
        delay_seconds=MIN_DELAY,
        wave_size=1,
        wave_pause_seconds=0.5,
        ready_check=_ready,
    )
    _wait_until_done(launcher)
    assert len(calls) >= 3
    assert launcher.get_status()["launched"] == 3


def test_a_failing_readiness_probe_never_strands_the_batch() -> None:
    def _ready() -> dict[str, object]:
        raise RuntimeError("probe exploded")

    launcher = BatchLauncher(lambda account_id, target: {"accepted": True})
    launcher.start_batch(
        ["a", "b"],
        delay_seconds=MIN_DELAY,
        wave_size=1,
        wave_pause_seconds=0.5,
        ready_check=_ready,
    )
    _wait_until_done(launcher)
    assert launcher.get_status()["launched"] == 2


def test_cancelling_during_a_wave_pause_stops_the_batch() -> None:
    launched: list[str] = []

    def _launch(account_id: str, target: object) -> dict[str, object]:
        launched.append(account_id)
        return {"accepted": True}

    launcher = BatchLauncher(_launch)
    launcher.start_batch(["a", "b", "c", "d"], delay_seconds=MIN_DELAY, wave_size=1, wave_pause_seconds=30.0)
    time.sleep(0.4)
    launcher.cancel_batch()
    _wait_until_done(launcher, timeout=5.0)
    assert len(launched) < 4


def test_impossible_wave_settings_are_refused() -> None:
    launcher = BatchLauncher(lambda account_id, target: {"accepted": True})
    with pytest.raises(ValidationError):
        launcher.start_batch(["a"], wave_size=500)
    with pytest.raises(ValidationError):
        launcher.start_batch(["a"], wave_pause_seconds=99_999)
    with pytest.raises(ValidationError):
        launcher.start_batch(["a"], ready_check="not callable")
