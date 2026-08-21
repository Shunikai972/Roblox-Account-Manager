"""Bounded read-only CPU/RAM history for verified Roblox processes."""

from __future__ import annotations

from collections import deque
import math
import time
from typing import Any, Callable, Iterable

import psutil

MAX_SAMPLES_PER_PROCESS = 240
MIN_SAMPLE_INTERVAL_SECONDS = 2.0
LEAK_MIN_SPAN_SECONDS = 60.0
LEAK_MIN_GROWTH_MB = 128.0
LEAK_MIN_GROWTH_RATIO = 0.25


class InstancePerformanceTelemetry:
    def __init__(
        self,
        *,
        process_factory: Callable[[int], Any] = psutil.Process,
        clock: Callable[[], float] = time.time,
        max_samples: int = MAX_SAMPLES_PER_PROCESS,
        min_interval_seconds: float = MIN_SAMPLE_INTERVAL_SECONDS,
    ) -> None:
        self._process_factory = process_factory
        self._clock = clock
        self._max_samples = max(4, min(int(max_samples), MAX_SAMPLES_PER_PROCESS))
        self._min_interval = max(0.0, float(min_interval_seconds))
        self._history: dict[int, deque[dict[str, Any]]] = {}

    def _leak(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        if len(samples) < 4:
            return {"probable": False, "growth_mb": 0.0, "mb_per_hour": 0.0, "reason": "Not enough samples yet."}
        first, last = samples[0], samples[-1]
        span = float(last["at"]) - float(first["at"])
        growth = float(last["memory_mb"]) - float(first["memory_mb"])
        ratio = growth / max(1.0, float(first["memory_mb"]))
        rate = growth * 3600.0 / span if span > 0 else 0.0
        probable = span >= LEAK_MIN_SPAN_SECONDS and growth >= LEAK_MIN_GROWTH_MB and ratio >= LEAK_MIN_GROWTH_RATIO
        return {
            "probable": probable,
            "growth_mb": round(growth, 1),
            "mb_per_hour": round(rate, 1),
            "span_seconds": round(span, 1),
            "reason": "Sustained RAM growth exceeded the bounded leak threshold." if probable else "No sustained leak pattern detected.",
        }

    def sample(self, instances: Iterable[Any]) -> list[dict[str, Any]]:
        now = float(self._clock())
        rows: list[dict[str, Any]] = []
        active: set[int] = set()
        for instance in instances:
            try:
                pid = int(getattr(instance, "pid", 0) or 0)
            except (TypeError, ValueError):
                continue
            if pid <= 0:
                continue
            active.add(pid)
            history = self._history.setdefault(pid, deque(maxlen=self._max_samples))
            if history and now - float(history[-1]["at"]) < self._min_interval:
                latest = dict(history[-1])
            else:
                try:
                    process = self._process_factory(pid)
                    memory = float(process.memory_info().rss) / (1024.0 * 1024.0)
                    cpu = float(process.cpu_percent(interval=None))
                    if not math.isfinite(memory) or not math.isfinite(cpu):
                        raise ValueError("non-finite process reading")
                    latest = {
                        "pid": pid,
                        "account_id": getattr(instance, "account_id", None),
                        "at": now,
                        "cpu_percent": round(max(0.0, cpu), 1),
                        "memory_mb": round(max(0.0, memory), 1),
                        "available": True,
                    }
                    history.append(latest)
                except (psutil.Error, OSError, ValueError):
                    latest = {
                        "pid": pid,
                        "account_id": getattr(instance, "account_id", None),
                        "at": now,
                        "cpu_percent": None,
                        "memory_mb": None,
                        "available": False,
                    }
            valid = [dict(item) for item in history if item.get("available")]
            latest = dict(latest)
            latest["history_points"] = len(valid)
            latest["memory_leak"] = self._leak(valid)
            rows.append(latest)
        for pid in list(self._history):
            if pid not in active:
                del self._history[pid]
        return rows

    def history(self, pid: int) -> list[dict[str, Any]]:
        return [dict(item) for item in self._history.get(int(pid), ())]
