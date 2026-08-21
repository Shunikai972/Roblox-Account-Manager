from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.backend.core.updater import (
    CURRENT_VERSION,
    EXPECTED_ASSET,
    UpdateChecker,
    UpdateError,
    UpdateManager,
    _version_key,
)
from app.backend.services.application_service import ApplicationService

NEXT_VERSION = "5.1.1"


def _pe_bytes(size: int = 1024) -> bytes:
    raw = bytearray(max(512, size))
    raw[:2] = b"MZ"
    raw[0x3C:0x40] = (0x80).to_bytes(4, "little")
    raw[0x80:0x84] = b"PE\x00\x00"
    return bytes(raw)


class _Response:
    def __init__(self, raw: bytes, url: str) -> None:
        self.raw = raw
        self.url = url

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, _size: int):
        yield self.raw[:311]
        yield self.raw[311:]


class _Session:
    def __init__(self, payloads: dict[str, bytes], *, final_host: str | None = None) -> None:
        self.payloads = payloads
        self.final_host = final_host
        self.closed = False

    def get(self, url: str, **_kwargs: Any) -> _Response:
        final_url = self.final_host or url
        return _Response(self.payloads[url], final_url)

    def close(self) -> None:
        self.closed = True


def _checker(executable: bytes, checksum: bytes | None = None):
    exe_url = f"https://github.com/example/project/releases/download/v{NEXT_VERSION}/AstroAccountManager.exe"
    assets: list[dict[str, Any]] = [{"name": EXPECTED_ASSET, "size": len(executable), "url": exe_url}]
    payloads = {exe_url: executable}
    if checksum is not None:
        checksum_url = exe_url + ".sha256"
        assets.append({"name": EXPECTED_ASSET + ".sha256", "size": len(checksum), "url": checksum_url})
        payloads[checksum_url] = checksum

    class Checker:
        @staticmethod
        def check_for_updates() -> dict[str, Any]:
            return {
                "current_version": CURRENT_VERSION,
                "latest_version": NEXT_VERSION,
                "update_available": True,
                "assets": assets,
            }

    return Checker, payloads


def test_version_comparison_handles_prereleases_semantically() -> None:
    assert _version_key("4.0.0") > _version_key("4.0.0rc2") > _version_key("4.0.0b9") > _version_key("4.0.0a1")
    assert _version_key("4.0.10") > _version_key("4.0.9")
    assert _version_key("not-a-version") is None


@patch("app.backend.core.updater.requests.get")
def test_update_checker_uses_astro_version_and_semantic_release_order(mock_get: MagicMock) -> None:
    response = MagicMock(status_code=200)
    response.json.return_value = {"tag_name": f"v{NEXT_VERSION}", "body": "stable", "html_url": "https://example.invalid/release"}
    mock_get.return_value = response

    result = UpdateChecker.check_for_updates()

    assert result["current_version"] == CURRENT_VERSION == "5.1.0"
    assert result["latest_version"] == NEXT_VERSION
    assert result["update_available"] is True


@patch("app.backend.core.updater.requests.get")
def test_update_checker_handles_malformed_github_assets_without_crashing(mock_get: MagicMock) -> None:
    response = MagicMock(status_code=200)
    response.json.return_value = {"tag_name": f"v{NEXT_VERSION}", "assets": {"not": "a list"}}
    mock_get.return_value = response

    result = UpdateChecker.check_for_updates()

    assert result["update_available"] is False
    assert result["reason"] == "The release service could not be reached."


def test_update_download_stages_a_size_pe_and_checksum_verified_executable(tmp_path: Path) -> None:
    executable = _pe_bytes(2048)
    digest = hashlib.sha256(executable).hexdigest().upper()
    checksum = f"{digest}  {EXPECTED_ASSET}\n".encode("ascii")
    checker, payloads = _checker(executable, checksum)
    manager = UpdateManager(tmp_path / "updates", checker=checker, session=_Session(payloads), runtime_is_frozen=False)

    result = manager.download_latest(confirm=True)

    assert result["staged"] is True
    assert result["checksum_verified"] is True
    assert result["sha256"] == digest
    assert manager.staged_path.read_bytes() == executable
    assert manager.status()["staged_valid"] is True
    manifest = json.loads(manager.manifest_path.read_text(encoding="utf-8"))
    assert manifest["version"] == NEXT_VERSION
    assert manifest["size"] == len(executable)


def test_update_install_revalidates_size_hash_and_pe_before_scheduling(tmp_path: Path) -> None:
    executable = _pe_bytes(1536)
    checker, payloads = _checker(executable)
    target = tmp_path / "Astro.exe"
    target.write_bytes(_pe_bytes())
    manager = UpdateManager(
        tmp_path / "updates",
        checker=checker,
        session=_Session(payloads),
        runtime_executable=target,
        runtime_is_frozen=True,
    )
    manager.download_latest(confirm=True)
    manager.staged_path.write_bytes(executable + b"tampered")

    with pytest.raises(UpdateError, match="size no longer matches"):
        manager.install_on_exit(confirm=True)


def test_pending_update_is_revalidated_then_uses_hidden_atomic_helper(tmp_path: Path) -> None:
    executable = _pe_bytes(1792)
    checker, payloads = _checker(executable)
    target = tmp_path / "AstroAccountManager.exe"
    target.write_bytes(_pe_bytes())
    manager = UpdateManager(
        tmp_path / "updates",
        checker=checker,
        session=_Session(payloads),
        runtime_executable=target,
        runtime_is_frozen=True,
    )
    manager.download_latest(confirm=True)
    manager.install_on_exit(confirm=True)

    with patch("app.backend.core.updater.subprocess.Popen") as popen:
        assert manager.apply_pending_on_exit() is True

    args, kwargs = popen.call_args
    command = args[0]
    assert command[:5] == ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-WindowStyle"]
    assert command[5] == "Hidden"
    assert "Get-FileHash" in command[-1]
    assert "ASTRO_UPDATE_INCOMING" in command[-1]
    assert "Wait-Process" not in command[-1]
    assert "Get-Process -Id $pidToWait" in command[-1]
    assert "AddSeconds(60)" in command[-1]
    assert kwargs["env"]["ASTRO_UPDATE_SHA256"] == hashlib.sha256(executable).hexdigest().upper()


def test_update_status_only_marks_a_valid_pending_payload_ready(tmp_path: Path) -> None:
    executable = _pe_bytes(1200)
    checker, payloads = _checker(executable)
    target = tmp_path / "AstroAccountManager.exe"
    target.write_bytes(_pe_bytes())
    manager = UpdateManager(
        tmp_path / "updates",
        checker=checker,
        session=_Session(payloads),
        runtime_executable=target,
        runtime_is_frozen=True,
    )
    manager.download_latest(confirm=True)
    manager.install_on_exit(confirm=True)

    assert manager.status()["ready_to_install"] is True
    manager.staged_path.write_bytes(executable + b"tampered")
    status = manager.status()
    assert status["pending_install"] is True
    assert status["staged_valid"] is False
    assert status["ready_to_install"] is False


def test_pending_update_refuses_a_tampered_staged_file_before_spawning(tmp_path: Path) -> None:
    executable = _pe_bytes(1400)
    checker, payloads = _checker(executable)
    target = tmp_path / "AstroAccountManager.exe"
    target.write_bytes(_pe_bytes())
    manager = UpdateManager(
        tmp_path / "updates",
        checker=checker,
        session=_Session(payloads),
        runtime_executable=target,
        runtime_is_frozen=True,
    )
    manager.download_latest(confirm=True)
    manager.install_on_exit(confirm=True)
    damaged = bytearray(manager.staged_path.read_bytes())
    damaged[-1] ^= 0xFF
    manager.staged_path.write_bytes(damaged)

    with patch("app.backend.core.updater.subprocess.Popen") as popen:
        assert manager.apply_pending_on_exit() is False
    popen.assert_not_called()


def test_update_download_rejects_a_redirect_outside_approved_github_hosts(tmp_path: Path) -> None:
    executable = _pe_bytes()
    checker, payloads = _checker(executable)
    manager = UpdateManager(
        tmp_path / "updates",
        checker=checker,
        session=_Session(payloads, final_host="https://downloads.example.invalid/Astro.exe"),
    )

    with pytest.raises(UpdateError, match="unapproved host"):
        manager.download_latest(confirm=True)


def test_explicitly_pending_update_is_applied_on_close_even_without_auto_install_setting() -> None:
    service = object.__new__(ApplicationService)
    service._stop_nexus_server_unchecked = MagicMock()
    service.stop_watcher = MagicMock()
    service.macro_engine = MagicMock()
    service.discord_presence = MagicMock()
    service.multi_instance = MagicMock()
    service.roblox = MagicMock()
    service.oauth_login = MagicMock()
    service.repository = MagicMock()
    service.update_manager = MagicMock()
    service.update_manager.status.return_value = {"pending_install": True}

    service.close()

    service.update_manager.apply_pending_on_exit.assert_called_once_with()
    service.update_manager.close.assert_called_once_with()
