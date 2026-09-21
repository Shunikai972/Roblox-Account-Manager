"""Read-only Roblox background discovery and explicitly confirmed graceful close."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable, Iterable

import psutil

from app.backend.core.errors import ValidationError


_NAMES = {
    "robloxplayerbeta.exe",
    "robloxplayer.exe",
    "robloxcrashhandler.exe",
    "robloxcrashtracker.exe",
    "robloxplayerlauncher.exe",
}


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
                if str(process.name()).casefold() != identity.name or abs(float(process.create_time()) - identity.created_at) > 1.0:
                    continue
                # Terminate any child processes first
                children_fn = getattr(process, "children", None)
                if callable(children_fn):
                    try:
                        for child in children_fn(recursive=True):
                            try:
                                child.terminate()
                            except (psutil.Error, OSError):
                                pass
                    except (psutil.Error, OSError):
                        pass
                process.terminate()
                requested.append(process)
            except (psutil.Error, OSError, TypeError, ValueError):
                continue
        deadline = time.monotonic() + max(0.1, min(float(timeout_seconds), 30.0))
        closed = 0
        still_alive: list[Any] = []
        for process in requested:
            try:
                remaining_time = max(0.05, deadline - time.monotonic())
                process.wait(timeout=remaining_time)
                closed += 1
            except (psutil.Error, OSError, TimeoutError):
                still_alive.append(process)

        # Escalate to kill for stubborn processes that did not terminate
        for process in still_alive:
            try:
                kill_fn = getattr(process, "kill", None)
                if callable(kill_fn):
                    kill_fn()
                process.wait(timeout=0.5)
                closed += 1
            except (psutil.Error, OSError, TimeoutError):
                try:
                    import subprocess
                    proc_pid = getattr(process, "pid", None)
                    if proc_pid:
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(proc_pid)],
                            capture_output=True,
                            timeout=1.0,
                        )
                except Exception:
                    pass
        return {"requested": len(requested), "closed": closed, "remaining": len(self.list_running())}
