from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.backend.api import DesktopBridge
from app.backend.core.config import AppPaths
from app.backend.services import ApplicationService
from app.backend.watchers import RobloxPlayerLogDiscovery, RobloxPlayerLogRuntime, RobloxProcessMonitor


JOB_ID = "01234567-89ab-cdef-0123-456789abcdef"
_PLAYER_LOG_NAME = "0.623.0.623_20260810T120000_Player_123_last.log"


def _joined_line(place_id: int = 123) -> str:
    return f"[FLog::Output] ! Joining game '{JOB_ID}' place {place_id} at 127.0.0.1\n"


def _player_log(directory: Path, content: str = "") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / _PLAYER_LOG_NAME
    path.write_text(content, encoding="utf-8")
    return path


def test_current_user_player_log_discovery_is_bounded_and_filters_the_filename(tmp_path: Path) -> None:
    local_app_data = tmp_path / "LocalAppData"
    logs = local_app_data / "Roblox" / "logs"
    expected = _player_log(logs, _joined_line())
    (logs / "arbitrary.log").write_text("SHOULD_NOT_BE_READ", encoding="utf-8")
    (logs / "0.623_123_not_a_player_log.log").write_text("SHOULD_NOT_BE_READ", encoding="utf-8")

    discovery = RobloxPlayerLogDiscovery(environ={"LOCALAPPDATA": str(local_app_data)})
    snapshot = discovery.discover()

    assert discovery.directory == logs
    assert snapshot.directory_available is True
    assert snapshot.complete is True
    assert [candidate.path for candidate in snapshot.candidates] == [expected]


def test_runtime_requires_one_process_and_one_complete_candidate_before_tailing(tmp_path: Path) -> None:
    logs = tmp_path / "Roblox" / "logs"
    log_path = _player_log(logs, _joined_line())
    runtime = RobloxPlayerLogRuntime(discovery=RobloxPlayerLogDiscovery(logs))

    ambiguous = runtime.poll((SimpleNamespace(pid=41), SimpleNamespace(pid=42)))

    assert ambiguous.association_state == "ambiguous"
    assert ambiguous.associated_pid is None
    assert runtime.history() == ()

    associated = runtime.poll((SimpleNamespace(pid=42),))
    payloads = [event.to_dict() for event in runtime.history()]

    assert associated.association_state == "associated"
    assert associated.associated_pid == 42
    assert payloads == [
        {
            "kind": "game_joined",
            "occurred_at": payloads[0]["occurred_at"],
            "pid": 42,
            "place_id": 123,
            "job_id": JOB_ID,
            "disconnect_code": None,
        }
    ]
    assert str(log_path) not in str(payloads)
    assert "[FLog::Output]" not in str(payloads)


def test_runtime_matches_two_processes_to_two_timestamped_logs(tmp_path: Path) -> None:
    logs = tmp_path / "Roblox" / "logs"
    first = logs / "0.623.0.623_20260810T120000Z_Player_123_last.log"
    second = logs / "0.623.0.623_20260810T120008Z_Player_456_last.log"
    logs.mkdir(parents=True)
    first.write_text(_joined_line(111), encoding="utf-8")
    second.write_text(_joined_line(222), encoding="utf-8")
    runtime = RobloxPlayerLogRuntime(discovery=RobloxPlayerLogDiscovery(logs))

    snapshot = runtime.poll(
        (
            SimpleNamespace(pid=41, started_at="2026-08-10T12:00:00+00:00"),
            SimpleNamespace(pid=42, started_at="2026-08-10T12:00:08+00:00"),
        )
    )
    events = sorted(runtime.history(), key=lambda item: item.pid)

    assert snapshot.association_state == "associated"
    assert snapshot.associated_pid is None
    assert [(event.pid, event.place_id) for event in events] == [(41, 111), (42, 222)]


def test_runtime_preserves_launch_order_when_next_process_is_nearest_to_previous_log(tmp_path: Path) -> None:
    logs = tmp_path / "Roblox" / "logs"
    first = logs / "0.623.0.623_20260810T120007Z_Player_123_last.log"
    second = logs / "0.623.0.623_20260810T120015Z_Player_456_last.log"
    logs.mkdir(parents=True)
    first.write_text(_joined_line(111), encoding="utf-8")
    second.write_text(_joined_line(222), encoding="utf-8")
    runtime = RobloxPlayerLogRuntime(discovery=RobloxPlayerLogDiscovery(logs))

    runtime.poll(
        (
            SimpleNamespace(pid=41, started_at="2026-08-10T12:00:00+00:00"),
            SimpleNamespace(pid=42, started_at="2026-08-10T12:00:07+00:00"),
        )
    )

    assert sorted((event.pid, event.place_id) for event in runtime.history()) == [(41, 111), (42, 222)]


def test_runtime_refuses_association_when_bounded_discovery_is_incomplete(tmp_path: Path) -> None:
    logs = tmp_path / "Roblox" / "logs"
    _player_log(logs, _joined_line())
    second = logs / "0.623.0.623_20260810T120001_Player_456_last.log"
    second.write_text(_joined_line(456), encoding="utf-8")
    runtime = RobloxPlayerLogRuntime(
        discovery=RobloxPlayerLogDiscovery(logs, max_candidates=1),
    )

    snapshot = runtime.poll((SimpleNamespace(pid=42),))

    assert snapshot.discovery_complete is False
    assert snapshot.association_state == "discovery_truncated"
    assert runtime.history() == ()


def test_runtime_marks_an_entry_cap_as_incomplete_without_looking_past_it(tmp_path: Path) -> None:
    logs = tmp_path / "Roblox" / "logs"
    _player_log(logs, _joined_line())
    runtime = RobloxPlayerLogRuntime(
        discovery=RobloxPlayerLogDiscovery(logs, max_directory_entries=1),
    )

    snapshot = runtime.poll((SimpleNamespace(pid=42),))

    assert snapshot.discovery_complete is False
    assert snapshot.association_state == "discovery_truncated"
    assert runtime.history() == ()


def test_runtime_refuses_association_when_the_process_scan_is_incomplete(tmp_path: Path) -> None:
    logs = tmp_path / "Roblox" / "logs"
    _player_log(logs, _joined_line())
    runtime = RobloxPlayerLogRuntime(discovery=RobloxPlayerLogDiscovery(logs))

    snapshot = runtime.poll((SimpleNamespace(pid=42),), process_scan_complete=False)

    assert snapshot.association_state == "process_scan_incomplete"
    assert snapshot.associated_pid is None
    assert runtime.history() == ()


@dataclass
class _Memory:
    rss: int = 1_024


class _Process:
    def __init__(self, pid: int) -> None:
        self.pid = pid

    @property
    def info(self) -> dict[str, object]:
        return {
            "pid": self.pid,
            "name": "RobloxPlayerBeta.exe",
            "create_time": 1_700_000_000.0,
            "memory_info": _Memory(),
            "status": "running",
        }


class _ProcessSource:
    def __init__(self, processes: list[_Process]) -> None:
        self.processes = processes

    def __call__(self, *, attrs: list[str] | None = None) -> list[_Process]:
        return list(self.processes)


class _Roblox:
    def close(self) -> None:
        return None


def _paths(tmp_path: Path) -> AppPaths:
    root = tmp_path / "app-data"
    return AppPaths(
        root=root,
        database=root / "astro.db",
        logs=root / "logs",
        backups=root / "backups",
        cache=root / "cache",
        exports=root / "exports",
    )


def test_service_and_bridge_expose_redacted_log_events_without_control_actions(tmp_path: Path) -> None:
    logs = tmp_path / "LocalAppData" / "Roblox" / "logs"
    raw_marker = "RAW_LOCAL_CONTENT_MUST_NOT_ESCAPE"
    _player_log(
        logs,
        raw_marker + "\n[FLog::Network] Sending disconnect with reason: 279\n",
    )
    source = _ProcessSource([_Process(84)])
    monitor = RobloxProcessMonitor(
        process_iter=source,
        process_factory=lambda _: source.processes[0],
        clock=lambda: 1_700_000_100.0,
    )
    runtime = RobloxPlayerLogRuntime(discovery=RobloxPlayerLogDiscovery(logs))
    service = ApplicationService(
        paths=_paths(tmp_path),
        roblox=_Roblox(),  # type: ignore[arg-type]
        monitor=monitor,
        log_runtime=runtime,
    )
    try:
        service.refresh_instances()
        payload = DesktopBridge(service).get_instance_monitor()

        assert payload["log_watcher"] == {
            "directory_available": True,
            "discovery_complete": True,
            "candidate_count": 1,
            "observed_instance_count": 1,
            "association_state": "associated",
            "associated_pid": 84,
        }
        assert payload["log_events"] == [
            {
                "kind": "disconnected",
                "occurred_at": payload["log_events"][0]["occurred_at"],
                "pid": 84,
                "place_id": None,
                "job_id": None,
                "disconnect_code": 279,
            }
        ]
        assert raw_marker not in str(payload)
        assert str(logs) not in str(payload)
        assert monitor.pending_restarts() == ()
        assert all(event["kind"] != "disconnected" for event in payload["events"])
    finally:
        service.close()
