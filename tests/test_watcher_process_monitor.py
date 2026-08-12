from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Any

import psutil
import pytest

from app.backend.roblox.errors import ProcessMonitorError
from app.backend.watchers.process_monitor import (
    InstanceState,
    MonitorPollingLoop,
    ProcessScan,
    RestartPolicy,
    RobloxProcessMonitor,
    TerminationStatus,
)


@dataclass
class FakeMemory:
    rss: int


class FakeProcess:
    def __init__(
        self,
        pid: int,
        name: str = "RobloxPlayerBeta.exe",
        created_at: float = 1_700_000_000.0,
        *,
        rss: int = 12_345,
        status: str = "running",
        wait_error: Exception | None = None,
    ) -> None:
        self.pid = pid
        self._name = name
        self._created_at = created_at
        self._rss = rss
        self._status = status
        self._wait_error = wait_error
        self.terminate_calls = 0
        self.kill_calls = 0

    @property
    def info(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "name": self._name,
            "create_time": self._created_at,
            "memory_info": FakeMemory(self._rss),
            "status": self._status,
        }

    def name(self) -> str:
        return self._name

    def create_time(self) -> float:
        return self._created_at

    def terminate(self) -> None:
        self.terminate_calls += 1

    def wait(self, *, timeout: float) -> None:
        if self._wait_error:
            raise self._wait_error

    def kill(self) -> None:
        self.kill_calls += 1


class ProcessSource:
    def __init__(self, processes: list[FakeProcess]) -> None:
        self.processes = processes
        self.calls = 0

    def __call__(self, *, attrs: list[str] | None = None) -> list[FakeProcess]:
        self.calls += 1
        return list(self.processes)


def test_scan_detects_roblox_processes_and_emits_lifecycle_events() -> None:
    roblox = FakeProcess(100)
    source = ProcessSource([roblox, FakeProcess(101, name="notepad.exe")])
    monitor = RobloxProcessMonitor(process_iter=source, clock=lambda: 1_700_000_100.0)

    first = monitor.scan()
    source.processes = []
    second = monitor.scan()

    assert [(instance.pid, instance.name, instance.memory_bytes) for instance in first.instances] == [
        (100, "RobloxPlayerBeta.exe", 12_345)
    ]
    assert [event.kind for event in first.events] == ["started", "orphaned"]
    assert first.orphaned[0].pid == 100
    assert first.instances[0].status == InstanceState.ORPHANED.value
    assert [instance.pid for instance in second.exited] == [100]
    assert [event.kind for event in monitor.history()] == ["started", "orphaned", "crashed"]


def test_monitor_bounds_current_state_and_history() -> None:
    source = ProcessSource([FakeProcess(1, created_at=1), FakeProcess(2, created_at=2), FakeProcess(3, created_at=3)])
    monitor = RobloxProcessMonitor(
        process_iter=source,
        max_tracked=2,
        max_history=2,
        clock=lambda: 1_700_000_100.0,
    )

    scan = monitor.scan()

    assert scan.truncated is True
    assert [instance.pid for instance in scan.instances] == [2, 3]
    assert len(monitor.current_instances()) == 2
    assert len(monitor.history()) == 2


def test_duplicate_guard_covers_pending_launch_before_process_is_seen() -> None:
    monitor = RobloxProcessMonitor(process_iter=ProcessSource([]), clock=lambda: 100.0)

    monitor.register_launch_intent(
        account_id="account-one",
        account_username="AccountOne",
        place_id=123,
    )

    assert monitor.has_active_or_pending_account("account-one") is True
    assert monitor.has_active_or_pending_account("account-two") is False


def test_termination_is_disabled_by_default_and_never_calls_process() -> None:
    process = FakeProcess(100)
    source = ProcessSource([process])
    monitor = RobloxProcessMonitor(process_iter=source, process_factory=lambda _: process)
    monitor.scan()

    with pytest.raises(ProcessMonitorError) as captured:
        monitor.terminate_known_process(100, confirm=True)

    assert captured.value.code == "termination_not_enabled"
    assert process.terminate_calls == 0


def test_termination_requires_confirmation_even_when_opted_in() -> None:
    process = FakeProcess(100)
    source = ProcessSource([process])
    monitor = RobloxProcessMonitor(
        process_iter=source, process_factory=lambda _: process, termination_enabled=True
    )
    monitor.scan()

    with pytest.raises(ProcessMonitorError) as captured:
        monitor.terminate_known_process(100)

    assert captured.value.code == "termination_confirmation_required"
    assert process.terminate_calls == 0


def test_opted_in_termination_verifies_identity_and_never_force_kills() -> None:
    observed = FakeProcess(100, created_at=100.0)
    live_process = FakeProcess(100, created_at=100.0)
    source = ProcessSource([observed])
    monitor = RobloxProcessMonitor(
        process_iter=source,
        process_factory=lambda _: live_process,
        termination_enabled=True,
        clock=lambda: 1_700_000_100.0,
    )
    monitor.scan()

    result = monitor.terminate_known_process(100, confirm=True)

    assert result.status is TerminationStatus.TERMINATED
    assert live_process.terminate_calls == 1
    assert live_process.kill_calls == 0
    assert monitor.current_instances() == ()


def test_termination_refuses_reused_pid_or_changed_executable() -> None:
    observed = FakeProcess(100, created_at=100.0)
    reused_pid = FakeProcess(100, created_at=101.0)
    source = ProcessSource([observed])
    monitor = RobloxProcessMonitor(
        process_iter=source,
        process_factory=lambda _: reused_pid,
        termination_enabled=True,
    )
    monitor.scan()

    result = monitor.terminate_known_process(100, confirm=True)

    assert result.status is TerminationStatus.IDENTITY_CHANGED
    assert reused_pid.terminate_calls == 0


def test_timeout_does_not_escalate_to_kill() -> None:
    observed = FakeProcess(100, created_at=100.0)
    timeout_process = FakeProcess(
        100,
        created_at=100.0,
        wait_error=psutil.TimeoutExpired(seconds=3.0, pid=100, name="RobloxPlayerBeta.exe"),
    )
    source = ProcessSource([observed])
    monitor = RobloxProcessMonitor(
        process_iter=source,
        process_factory=lambda _: timeout_process,
        termination_enabled=True,
    )
    monitor.scan()

    result = monitor.terminate_known_process(100, confirm=True)

    assert result.status is TerminationStatus.TIMED_OUT
    assert timeout_process.terminate_calls == 1
    assert timeout_process.kill_calls == 0


def test_incomplete_scan_marks_state_unknown_without_false_exit() -> None:
    first = FakeProcess(100, created_at=1_700_000_000.0)
    second = FakeProcess(101, created_at=1_700_000_001.0)

    class IntermittentSource(ProcessSource):
        incomplete = False

        def __call__(self, *, attrs: list[str] | None = None):  # type: ignore[override]
            if not self.incomplete:
                return super().__call__(attrs=attrs)

            def partial():
                yield first
                raise psutil.AccessDenied(pid=101, name="RobloxPlayerBeta.exe")

            return partial()

    source = IntermittentSource([first, second])
    monitor = RobloxProcessMonitor(process_iter=source, clock=lambda: 1_700_000_050.0)
    monitor.scan()
    source.incomplete = True

    uncertain = monitor.scan()

    assert uncertain.complete is False
    assert uncertain.exited == ()
    assert {item.pid: item.status for item in uncertain.instances}[101] == InstanceState.UNKNOWN.value
    assert any(event.kind == "scan_incomplete" for event in uncertain.events)

    source.incomplete = False
    source.processes = [first]
    confirmed = monitor.scan()

    assert confirmed.complete is True
    assert [item.pid for item in confirmed.exited] == [101]
    assert confirmed.exited[0].status == InstanceState.CRASHED.value


def test_launch_intent_is_matched_and_short_lived_crash_schedules_one_opt_in_restart() -> None:
    class MutableClock:
        value = 1_700_000_000.0

        def __call__(self) -> float:
            return self.value

    clock = MutableClock()
    process = FakeProcess(100, created_at=clock.value)
    source = ProcessSource([process])
    monitor = RobloxProcessMonitor(process_iter=source, clock=clock)
    monitor.register_launch_intent(
        account_id="account-1",
        account_username="ExampleUser",
        place_id=123,
        restart_policy=RestartPolicy(enabled=True, delay_seconds=5, max_attempts=1),
    )

    started = monitor.scan()

    assert started.instances[0].account_id == "account-1"
    assert started.instances[0].status == InstanceState.RUNNING.value
    assert "launch_matched" in [event.kind for event in started.events]

    source.processes = []
    clock.value += 10
    crashed = monitor.scan()

    assert [item.pid for item in crashed.crashed] == [100]
    assert "restart_scheduled" in [event.kind for event in crashed.events]
    assert len(monitor.pending_restarts()) == 1

    clock.value += 5
    due = monitor.claim_due_restarts()

    assert len(due) == 1
    assert due[0].account_id == "account-1"
    assert due[0].restart_attempt == 1
    assert monitor.claim_due_restarts() == ()


def test_ambiguous_simultaneous_launches_remain_orphaned_until_user_binds_one() -> None:
    clock = lambda: 1_700_000_000.0
    process = FakeProcess(100, created_at=1_700_000_000.0)
    source = ProcessSource([process])
    monitor = RobloxProcessMonitor(process_iter=source, clock=clock)
    for account_id in ("account-a", "account-b"):
        monitor.register_launch_intent(
            account_id=account_id,
            account_username=account_id,
            place_id=456,
        )

    scan = monitor.scan()

    assert scan.instances[0].status == InstanceState.ORPHANED.value
    assert scan.instances[0].account_id is None
    assert len(monitor.pending_restarts()) == 0
    with pytest.raises(ProcessMonitorError) as captured:
        monitor.bind_orphan(
            100,
            account_id="account-a",
            account_username="Account A",
            place_id=456,
        )
    assert captured.value.code == "instance_binding_confirmation_required"

    bound = monitor.bind_orphan(
        100,
        account_id="account-a",
        account_username="Account A",
        place_id=456,
        confirm=True,
    )

    assert bound.account_id == "account-a"
    assert bound.status == InstanceState.RUNNING.value


def test_deleted_account_work_is_cancelled_and_live_instance_becomes_orphan() -> None:
    clock = lambda: 1_700_000_000.0
    process = FakeProcess(100, created_at=1_700_000_000.0)
    source = ProcessSource([process])
    monitor = RobloxProcessMonitor(process_iter=source, clock=clock)
    monitor.register_launch_intent(
        account_id="account-1",
        account_username="ExampleUser",
        place_id=789,
    )
    monitor.scan()

    result = monitor.forget_account("account-1")

    assert result["instances_detached"] == 1
    assert monitor.current_instances()[0].account_id is None
    assert monitor.current_instances()[0].status == InstanceState.ORPHANED.value


def test_polling_loop_runs_an_initial_scan_and_stops_cleanly() -> None:
    completed = Event()
    scans: list[int] = []

    def scan() -> ProcessScan:
        scans.append(1)
        completed.set()
        return ProcessScan(instances=(), started=(), exited=(), events=())

    loop = MonitorPollingLoop(scan, interval_seconds=lambda: 300)
    assert loop.start() is True
    assert completed.wait(timeout=1.0)
    assert loop.running is True

    loop.stop()

    assert scans
    assert loop.running is False
