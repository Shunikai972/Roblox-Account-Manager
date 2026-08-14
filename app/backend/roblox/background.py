"""Read-only Roblox background discovery and explicitly confirmed graceful close."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable, Iterable

import psutil

from app.backend.core.errors import ValidationError


_NAMES = {"robloxplayerbeta.exe", "robloxplayer.exe"}


@dataclass(frozen=True, slots=True)
class RobloxBackgroundProcess:
    pid: int
    created_at: float
    name: str


class RobloxBackgroundManager:
    def __init__(self, *, process_iter: Callable[..., Iterable[Any]] = psutil.process_iter, process_factory: Callable[[int], Any] = psutil.Process) -> None:
        self._process_iter = process_iter
        self._process_factory = process_factory

    def list_running(self) -> tuple[RobloxBackgroundProcess, ...]:
        rows: list[RobloxBackgroundProcess] = []
        try:
            processes = self._process_iter(attrs=["pid", "name", "create_time"])
        except (psutil.Error, OSError):
            return ()
        for process in processes:
            try:
                info = getattr(process, "info", {}) or {}
                name = str(info.get("name") or process.name()).casefold()
                if name not in _NAMES:
                    continue
                pid = int(info.get("pid") or process.pid)
                created = float(info.get("create_time") or process.create_time())
                rows.append(RobloxBackgroundProcess(pid=pid, created_at=created, name=name))
            except (psutil.Error, OSError, TypeError, ValueError):
                continue
        return tuple(sorted(rows, key=lambda item: (item.created_at, item.pid)))

    def close_running(self, *, confirm: bool = False, timeout_seconds: float = 8.0) -> dict[str, Any]:
        if confirm is not True:
            raise ValidationError("Confirm closing the currently running Roblox clients.")
        snapshot = self.list_running()
        requested: list[Any] = []
        for identity in snapshot:
            try:
                process = self._process_factory(identity.pid)
                if str(process.name()).casefold() != identity.name or abs(float(process.create_time()) - identity.created_at) > 0.01:
                    continue
                process.terminate()
                requested.append(process)
            except (psutil.Error, OSError, TypeError, ValueError):
                continue
        deadline = time.monotonic() + max(0.1, min(float(timeout_seconds), 30.0))
        closed = 0
        for process in requested:
            try:
                process.wait(timeout=max(0.0, deadline - time.monotonic()))
                closed += 1
            except (psutil.Error, OSError, TimeoutError):
                continue
        return {"requested": len(requested), "closed": closed, "remaining": len(self.list_running())}
