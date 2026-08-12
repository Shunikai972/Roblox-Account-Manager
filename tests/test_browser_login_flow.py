from __future__ import annotations

from pathlib import Path

from app.backend.core.config import AppPaths
from app.backend.roblox.browser_login import EdgeCDPLoginService
from app.backend.services.application_service import ApplicationService


def _paths(tmp_path: Path) -> AppPaths:
    return AppPaths(
        root=tmp_path,
        database=tmp_path / "astro.db",
        logs=tmp_path / "logs",
        backups=tmp_path / "backups",
        cache=tmp_path / "cache",
        exports=tmp_path / "exports",
    )


def test_manual_browser_login_reports_captured_account(monkeypatch, tmp_path: Path) -> None:
    service = ApplicationService(paths=_paths(tmp_path))
    try:
        account = service.create_account({"username": "BrowserUser"})
        monkeypatch.setattr(service, "add_account_from_cookie", lambda cookie, group_id=None: account)

        def capture_immediately(_edge, callback, on_finished):
            callback("captured-cookie")
            on_finished(True)
            return True

        monkeypatch.setattr(
            "app.backend.roblox.browser_login.EdgeCDPLoginService.start_login",
            capture_immediately,
        )

        started = service.start_manual_browser_login()
        status = service.poll_manual_browser_login(started["operation_id"])

        assert started["started"] is True
        assert started["engine"] == "edge_cdp"
        assert status["status"] == "completed"
        assert status["account"]["username"] == "BrowserUser"
        assert "cookie" not in status
    finally:
        service.close()


def test_manual_browser_login_stops_waiting_when_browser_closes(monkeypatch, tmp_path: Path) -> None:
    service = ApplicationService(paths=_paths(tmp_path))
    try:
        def close_immediately(_edge, _callback, on_finished):
            on_finished(False)
            return True

        monkeypatch.setattr(
            "app.backend.roblox.browser_login.EdgeCDPLoginService.start_login",
            close_immediately,
        )

        started = service.start_manual_browser_login()
        status = service.poll_manual_browser_login(started["operation_id"])

        assert status["status"] == "failed"
        assert "closed or timed out" in status["message"]
    finally:
        service.close()


def test_edge_login_loads_only_a_validated_solver_extension(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    extension = tmp_path / "solver-extension"
    extension.mkdir()
    (extension / "manifest.json").write_text('{"manifest_version":3}', encoding="utf-8")

    command = EdgeCDPLoginService.build_launch_command(
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        str(profile),
        solver_extension_directory=str(extension),
    )

    assert f"--load-extension={extension.resolve()}" in command
    assert f"--disable-extensions-except={extension.resolve()}" in command
    assert command[-1] == "https://www.roblox.com/login"
    assert not any("key=" in argument.casefold() for argument in command)


def test_edge_login_ignores_an_invalid_solver_extension(tmp_path: Path) -> None:
    command = EdgeCDPLoginService.build_launch_command(
        "msedge",
        str(tmp_path / "profile"),
        solver_extension_directory=str(tmp_path / "missing"),
    )

    assert not any(argument.startswith("--load-extension=") for argument in command)
