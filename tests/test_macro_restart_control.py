"""Regression coverage for macro control-action lifecycle boundaries."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any, Mapping

from app.backend.automations.macros import MacroEngine, parse_macro_dsl
from app.backend.services.fleet_features import ServiceMacroController


def _wait_for_finish(
    engine: MacroEngine, run_id: str, timeout: float = 2.0
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for run in engine.list_runs():
            if run["run_id"] == run_id and run["finished_at"]:
                return run
        time.sleep(0.005)
    raise AssertionError("the macro did not finish in time")


class _SessionTrackingBackend:
    """Input double that rejects delivery through a stale HWND session."""

    def __init__(self, events: list[tuple[Any, ...]]) -> None:
        self.events = events
        self.session: dict[str, Any] | None = None

    @staticmethod
    def _target(pid: int, created_at: float | None) -> dict[str, Any]:
        return {
            "pid": pid,
            "created_at": created_at,
            "hwnd": pid + 10_000,
            "background_delivery_supported": False,
            "delivery_mode": "foreground_input",
        }

    def verify(self, pid: int, expected_created_at: float | None) -> dict[str, Any]:
        return self._target(pid, expected_created_at)

    def begin_run(self, target: Mapping[str, Any]) -> bool:
        if self.session is not None:
            return False
        self.session = dict(target)
        self.events.append(("begin", int(target["pid"]), int(target["hwnd"])))
        return True

    def end_run(self, target: Mapping[str, Any]) -> None:
        if self.session is None:
            return
        self.events.append(
            ("end", int(self.session["pid"]), int(self.session["hwnd"]))
        )
        self.session = None

    def key(self, target: Mapping[str, Any], key: str, down: bool) -> bool:
        accepted = bool(
            self.session is not None
            and int(self.session["hwnd"]) == int(target["hwnd"])
        )
        self.events.append(("key", int(target["pid"]), key, down, accepted))
        return accepted

    def click(
        self, target: Mapping[str, Any], x: float, y: float, button: str
    ) -> bool:
        return False

    def text(self, target: Mapping[str, Any], value: str) -> bool:
        return False


class _LegacyRestartController:
    """Old controller signature proves the cancellation extension is compatible."""

    def __init__(self, events: list[tuple[Any, ...]]) -> None:
        self.events = events

    def launch(self, account_id: str) -> dict[str, Any] | None:
        return None

    def teleport(
        self, account_id: str, place_id: str, job_id: str
    ) -> dict[str, Any] | None:
        return None

    def restart(self, account_id: str) -> dict[str, Any]:
        self.events.append(("restart", account_id))
        return {"pid": 202, "created_at": 2.0}

    def is_running(self, account_id: str) -> bool:
        return True


def test_restart_recreates_the_input_session_for_the_new_pid_and_hwnd() -> None:
    events: list[tuple[Any, ...]] = []
    backend = _SessionTrackingBackend(events)
    engine = MacroEngine(
        backend,
        controller=_LegacyRestartController(events),
    )
    definition = {
        "id": "restart-repin",
        "name": "Restart and move",
        "actions": parse_macro_dsl("RESTART\nPRESS W 1"),
    }

    started = engine.start(
        definition,
        pid=101,
        expected_created_at=1.0,
        account_id="account-1",
    )
    finished = _wait_for_finish(engine, started["run_id"])

    assert finished["state"] == "completed"
    assert finished["pid"] == 202
    assert events == [
        ("begin", 101, 10_101),
        ("end", 101, 10_101),
        ("restart", "account-1"),
        ("begin", 202, 10_202),
        ("key", 202, "W", True, True),
        ("key", 202, "W", False, True),
        ("end", 202, 10_202),
    ]


class _RestartMonitor:
    def __init__(self, account_id: str) -> None:
        self.instance: SimpleNamespace | None = SimpleNamespace(
            account_id=account_id,
            pid=303,
            started_at="2026-09-12T12:00:00+00:00",
        )

    def current_instances(self) -> tuple[SimpleNamespace, ...]:
        return (self.instance,) if self.instance is not None else ()


class _BlockingRestartService:
    def __init__(self, account_id: str) -> None:
        self.monitor = _RestartMonitor(account_id)
        self.closed = threading.Event()
        self.launches: list[str] = []

    def close_instance(self, pid: int, *, confirm: bool) -> None:
        assert pid == 303
        assert confirm is True
        self.monitor.instance = None
        self.closed.set()

    def launch_account(self, account_id: str) -> dict[str, Any]:
        self.launches.append(account_id)
        self.monitor.instance = SimpleNamespace(
            account_id=account_id,
            pid=404,
            started_at="2026-09-12T12:01:00+00:00",
        )
        return {"accepted": True}

    def _scan_instances(self, *, allow_restarts: bool) -> None:
        assert allow_restarts is False


def test_stop_during_restart_prevents_the_later_relaunch() -> None:
    events: list[tuple[Any, ...]] = []
    backend = _SessionTrackingBackend(events)
    service = _BlockingRestartService("account-2")
    engine = MacroEngine(backend, controller=ServiceMacroController(service))
    definition = {
        "id": "cancel-restart",
        "name": "Cancelable restart",
        "actions": parse_macro_dsl("RESTART\nPRESS W 1"),
    }

    started = engine.start(
        definition,
        pid=303,
        expected_created_at=3.0,
        account_id="account-2",
    )
    assert service.closed.wait(1.0), "restart never reached the post-close wait"

    engine.stop(started["run_id"])
    finished = _wait_for_finish(engine, started["run_id"])

    assert finished["state"] == "cancelled"
    assert service.launches == []
    assert backend.session is None
    assert not any(event[0] == "key" for event in events)
