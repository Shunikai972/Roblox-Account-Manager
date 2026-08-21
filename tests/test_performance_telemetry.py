from __future__ import annotations

from types import SimpleNamespace

from app.backend.watchers.performance_telemetry import InstancePerformanceTelemetry


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class _Processes:
    def __init__(self, memory_mb: list[float]) -> None:
        self.memory_mb = memory_mb
        self.index = 0

    def __call__(self, pid: int) -> object:
        memory = self.memory_mb[min(self.index, len(self.memory_mb) - 1)]
        self.index += 1
        return SimpleNamespace(
            memory_info=lambda: SimpleNamespace(rss=int(memory * 1024 * 1024)),
            cpu_percent=lambda interval=None: 3.4,
        )


def test_performance_history_is_bounded_and_detects_sustained_memory_growth() -> None:
    clock = _Clock()
    telemetry = InstancePerformanceTelemetry(
        process_factory=_Processes([600, 700, 850, 1050]),
        clock=clock,
        min_interval_seconds=0,
        max_samples=4,
    )
    instance = SimpleNamespace(pid=42, account_id="alt")
    latest = None
    for timestamp in (0, 60, 120, 180):
        clock.value = timestamp
        latest = telemetry.sample([instance])[0]
    assert latest is not None
    assert latest["cpu_percent"] == 3.4
    assert latest["memory_mb"] == 1050.0
    assert latest["memory_leak"]["probable"] is True
    assert len(telemetry.history(42)) == 4


def test_performance_history_for_exited_processes_is_dropped() -> None:
    telemetry = InstancePerformanceTelemetry(
        process_factory=_Processes([100]),
        min_interval_seconds=0,
    )
    telemetry.sample([SimpleNamespace(pid=7, account_id=None)])
    assert telemetry.history(7)
    telemetry.sample([])
    assert telemetry.history(7) == []
