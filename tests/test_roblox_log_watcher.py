from __future__ import annotations

from pathlib import Path

from app.backend.watchers.roblox_log_watcher import RobloxLogEventKind, RobloxLogTailer


JOB_ID = "01234567-89ab-cdef-0123-456789abcdef"


def _joined_line(place_id: int = 123) -> str:
    return f"[FLog::Output] ! Joining game '{JOB_ID}' place {place_id} at 127.0.0.1\n"


def _kinds(snapshot: object) -> list[RobloxLogEventKind]:
    return [event.kind for event in snapshot.events]  # type: ignore[attr-defined]


def test_incremental_log_tailer_emits_typed_join_and_disconnect_events(tmp_path: Path) -> None:
    log_path = tmp_path / "player_last.log"
    log_path.write_text(_joined_line(), encoding="utf-8")
    tailer = RobloxLogTailer(log_path, clock=lambda: 1_700_000_000.0)

    joined = tailer.poll()

    assert _kinds(joined) == [RobloxLogEventKind.GAME_JOINED]
    assert joined.connected is True
    assert joined.in_game is True
    assert joined.place_id == 123
    assert joined.job_id == JOB_ID

    with log_path.open("a", encoding="utf-8", newline="") as log_file:
        log_file.write("[FLog::Network] Sending disconnect with reason:")
    assert tailer.poll().events == ()
    with log_path.open("a", encoding="utf-8", newline="") as log_file:
        log_file.write(" 279\n")

    disconnected = tailer.poll()

    assert _kinds(disconnected) == [RobloxLogEventKind.DISCONNECTED]
    assert disconnected.connected is False
    assert disconnected.in_game is False
    assert disconnected.events[0].disconnect_code == 279
    assert tailer.poll().events == ()


def test_data_model_lifecycle_gates_returned_to_app_like_the_historical_watcher(tmp_path: Path) -> None:
    log_path = tmp_path / "player_last.log"
    log_path.write_text(
        "\n".join(
            (
                "[FLog::SurfaceController] SurfaceController[_:1]::start dataModel(ABCD)",
                "[FLog::SurfaceController] SurfaceController[_:1]::pause dataModel(ABCD), view(1), destroyView:0.",
                "[FLog::SurfaceController] SurfaceController[_:1]::stop",
                "[FLog::SingleSurfaceApp] returnToLuaApp: ... App has been initialized, returning from game.",
                "",
            )
        ),
        encoding="utf-8",
    )
    tailer = RobloxLogTailer(log_path, clock=lambda: 1_700_000_010.0)

    snapshot = tailer.poll()

    assert _kinds(snapshot) == [
        RobloxLogEventKind.DATA_MODEL_STARTED,
        RobloxLogEventKind.DATA_MODEL_PAUSED,
        RobloxLogEventKind.DATA_MODEL_STOPPED,
        RobloxLogEventKind.RETURNED_TO_APP,
    ]
    assert snapshot.in_game is False

    unrelated = tmp_path / "unrelated.log"
    unrelated.write_text(
        "[FLog::SingleSurfaceApp] returnToLuaApp: ... App not yet initialized, returning from game.\n",
        encoding="utf-8",
    )
    assert RobloxLogTailer(unrelated).poll().events == ()


def test_tailer_recovers_from_truncation_and_rotation_without_carrying_stale_state(tmp_path: Path) -> None:
    log_path = tmp_path / "player_last.log"
    log_path.write_text(("old ignored line\n" * 40) + _joined_line(111), encoding="utf-8")
    tailer = RobloxLogTailer(log_path, clock=lambda: 1_700_000_020.0)
    assert tailer.poll().place_id == 111

    log_path.write_text(_joined_line(222), encoding="utf-8")
    truncated = tailer.poll()

    assert _kinds(truncated) == [RobloxLogEventKind.LOG_TRUNCATED, RobloxLogEventKind.GAME_JOINED]
    assert truncated.place_id == 222

    archived = tmp_path / "old-player.log"
    log_path.replace(archived)
    log_path.write_text(_joined_line(333), encoding="utf-8")
    rotated = tailer.poll()

    assert _kinds(rotated) == [RobloxLogEventKind.LOG_ROTATED, RobloxLogEventKind.GAME_JOINED]
    assert rotated.place_id == 333


def test_log_tailer_never_returns_unmatched_raw_content_and_bounds_long_lines(tmp_path: Path) -> None:
    log_path = tmp_path / "player_last.log"
    secret_marker = "TOP_SECRET_VALUE_SHOULD_NOT_ESCAPE"
    log_path.write_text(f"{secret_marker}{'x' * 400}\n" + _joined_line(), encoding="utf-8")
    tailer = RobloxLogTailer(log_path, max_line_bytes=128, clock=lambda: 1_700_000_030.0)

    snapshot = tailer.poll()
    serialized = [event.to_dict() for event in snapshot.events]

    assert _kinds(snapshot) == [RobloxLogEventKind.LINE_DROPPED, RobloxLogEventKind.GAME_JOINED]
    assert secret_marker not in str(serialized)
    assert all("line" not in payload for payload in serialized)


def test_missing_log_is_a_bounded_availability_event_then_can_resume(tmp_path: Path) -> None:
    log_path = tmp_path / "not-created-yet.log"
    tailer = RobloxLogTailer(log_path, clock=lambda: 1_700_000_040.0)

    missing = tailer.poll()

    assert _kinds(missing) == [RobloxLogEventKind.LOG_UNAVAILABLE]
    assert missing.available is False
    assert tailer.poll().events == ()

    log_path.write_text(_joined_line(), encoding="utf-8")
    recovered = tailer.poll()
    assert recovered.available is True
    assert _kinds(recovered) == [RobloxLogEventKind.GAME_JOINED]
