"""Update checker for Astro Account Manager."""

from __future__ import annotations

import logging
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlparse

import requests

from app.backend.core.config import APP_VERSION

logger = logging.getLogger("astro.updater")

CURRENT_VERSION = APP_VERSION
RELEASES_URL = "https://api.github.com/repos/Shunikai972/Roblox-Account-Manager/releases/latest"
EXPECTED_ASSET = "AstroAccountManager.exe"
MAX_UPDATE_BYTES = 200 * 1024 * 1024
_DOWNLOAD_HOSTS = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}


_VERSION_RE = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:(?P<label>a|alpha|b|beta|rc)(?P<number>\d+))?$",
    re.IGNORECASE,
)


def _version_key(value: str) -> tuple[int, int, int, int, int] | None:
    """Return a comparison key for Astro release tags without string ordering."""

    match = _VERSION_RE.fullmatch(str(value).strip())
    if match is None:
        return None
    label = (match.group("label") or "").lower()
    stage = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "rc": 2, "": 3}[label]
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        stage,
        int(match.group("number") or 0),
    )


class UpdateChecker:
    """Checks for latest releases on GitHub."""

    @staticmethod
    def check_for_updates() -> dict[str, Any]:
        """Fetch release info from GitHub API."""

        try:
            res = requests.get(
                RELEASES_URL,
                timeout=5.0,
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": "AstroAccountManager",
                },
            )
            if res.status_code == 200:
                data = res.json()
                if not isinstance(data, dict):
                    raise ValueError("The GitHub release payload is not an object.")
                tag_name = str(data.get("tag_name") or "").lstrip("v")
                current_key = _version_key(CURRENT_VERSION)
                latest_key = _version_key(tag_name)
                has_update = bool(current_key is not None and latest_key is not None and latest_key > current_key)
                raw_assets = data.get("assets")
                if raw_assets is None:
                    raw_assets = []
                if not isinstance(raw_assets, list):
                    raise ValueError("The GitHub release asset list is invalid.")
                return {
                    "current_version": CURRENT_VERSION,
                    "latest_version": tag_name or CURRENT_VERSION,
                    "update_available": has_update,
                    "release_notes": str(data.get("body") or "")[:100_000],
                    "download_url": str(data.get("html_url") or "")[:2_048],
                    "checked_at": int(time.time()),
                    "assets": [
                        {
                            "name": str(asset.get("name") or ""),
                            "size": int(asset.get("size") or 0),
                            "url": str(asset.get("browser_download_url") or ""),
                        }
                        for asset in raw_assets
                        if isinstance(asset, dict)
                    ],
                }
            return {
                "current_version": CURRENT_VERSION,
                "latest_version": CURRENT_VERSION,
                "update_available": False,
                "reason": f"HTTP {res.status_code}",
            }
        except Exception:
            logger.warning("Failed to check for updates", exc_info=True)
            return {
                "current_version": CURRENT_VERSION,
                "latest_version": CURRENT_VERSION,
                "update_available": False,
                "reason": "The release service could not be reached.",
            }


class UpdateError(RuntimeError):
    """Safe updater failure suitable for the desktop bridge."""


class UpdateManager:
    """Download a validated GitHub release and replace only a frozen Astro EXE."""

    def __init__(
        self,
        directory: Path | str,
        *,
        runtime_executable: Path | str | None = None,
        runtime_is_frozen: bool | None = None,
        checker: Any = UpdateChecker,
        session: requests.Session | None = None,
    ) -> None:
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.runtime_executable = Path(runtime_executable or sys.executable).expanduser().resolve()
        self.runtime_is_frozen = bool(getattr(sys, "frozen", False)) if runtime_is_frozen is None else bool(runtime_is_frozen)
        self.checker = checker
        self.session = session or requests.Session()
        self.staged_path = self.directory / EXPECTED_ASSET
        self.manifest_path = self.directory / "staged-update.json"
        self.pending_path = self.directory / "pending-install.json"

    def close(self) -> None:
        self.session.close()

    def status(self) -> dict[str, Any]:
        manifest = self._read_manifest(self.manifest_path)
        staged_exists = self.staged_path.is_file()
        staged_size = self.staged_path.stat().st_size if staged_exists else None
        declared_size = manifest.get("size") if manifest else None
        staged_valid = bool(
            manifest
            and staged_exists
            and isinstance(declared_size, int)
            and declared_size == staged_size
            and _version_key(str(manifest.get("version") or "")) is not None
        )
        pending_exists = self.pending_path.is_file()
        return {
            "frozen": self.runtime_is_frozen,
            "staged": bool(manifest and staged_exists),
            "staged_valid": staged_valid,
            "pending_install": pending_exists,
            "ready_to_install": bool(pending_exists and staged_valid),
            "version": manifest.get("version") if manifest else None,
            "sha256": manifest.get("sha256") if manifest else None,
            "size": manifest.get("size") if manifest else None,
        }

    def download_latest(self, *, confirm: bool = False) -> dict[str, Any]:
        if confirm is not True:
            raise UpdateError("Confirm the update download.")
        release = self.checker.check_for_updates()
        if not release.get("update_available"):
            raise UpdateError("No newer Astro release is available.")
        assets = release.get("assets")
        if not isinstance(assets, list):
            raise UpdateError("The GitHub release has no downloadable asset list.")
        executable_asset = next((asset for asset in assets if str(asset.get("name", "")).casefold() == EXPECTED_ASSET.casefold()), None)
        if executable_asset is None:
            raise UpdateError(f"The release does not contain {EXPECTED_ASSET}.")
        declared_size = int(executable_asset.get("size") or 0)
        if not 1 <= declared_size <= MAX_UPDATE_BYTES:
            raise UpdateError("The release executable has an invalid size.")
        raw = self._download(str(executable_asset.get("url") or ""), maximum=MAX_UPDATE_BYTES)
        if len(raw) != declared_size:
            raise UpdateError("The downloaded executable size does not match GitHub metadata.")
        _validate_pe(raw)
        digest = hashlib.sha256(raw).hexdigest().upper()
        checksum_asset = next((asset for asset in assets if str(asset.get("name", "")).casefold() in {f"{EXPECTED_ASSET}.sha256".casefold(), "checksums.sha256"}), None)
        checksum_verified = False
        if checksum_asset is not None:
            checksum_raw = self._download(str(checksum_asset.get("url") or ""), maximum=256 * 1024)
            checksum_text = checksum_raw.decode("ascii", errors="strict")
            expected = _checksum_for_asset(checksum_text, EXPECTED_ASSET)
            if expected is None or expected.upper() != digest:
                raise UpdateError("The release checksum does not match the executable.")
            checksum_verified = True
        temporary = self.directory / f".{EXPECTED_ASSET}.part"
        temporary.write_bytes(raw)
        os.replace(temporary, self.staged_path)
        manifest = {
            "version": str(release.get("latest_version") or ""),
            "sha256": digest,
            "size": len(raw),
            "source": RELEASES_URL,
            "checksum_verified": checksum_verified,
            "downloaded_at": int(time.time()),
        }
        self._write_manifest(self.manifest_path, manifest)
        return {**manifest, "path": str(self.staged_path), "filename": self.staged_path.name, "staged": True, "frozen": self.runtime_is_frozen}

    def install_on_exit(self, *, confirm: bool = False) -> dict[str, Any]:
        if confirm is not True:
            raise UpdateError("Confirm installation on exit.")
        if not self.runtime_is_frozen:
            raise UpdateError("Automatic replacement is available only in the packaged Astro executable.")
        manifest = self._read_manifest(self.manifest_path)
        if not manifest or not self.staged_path.is_file():
            raise UpdateError("No validated update is staged.")
        raw = self.staged_path.read_bytes()
        _validate_pe(raw)
        if len(raw) != int(manifest.get("size") or 0):
            raise UpdateError("The staged update size no longer matches its manifest.")
        digest = hashlib.sha256(raw).hexdigest().upper()
        if digest != str(manifest.get("sha256") or "").upper():
            raise UpdateError("The staged update no longer matches its manifest.")
        pending = {**manifest, "target": str(self.runtime_executable), "staged": str(self.staged_path)}
        self._write_manifest(self.pending_path, pending)
        return {"pending_install": True, "version": manifest.get("version"), "sha256": digest}

    def cancel_staged(self, *, confirm: bool = False) -> dict[str, Any]:
        if confirm is not True:
            raise UpdateError("Confirm removal of the staged update.")
        for path in (self.pending_path, self.manifest_path, self.staged_path):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                raise UpdateError("The staged update could not be removed.") from exc
        return self.status()

    def apply_pending_on_exit(self) -> bool:
        """Start a fixed helper that waits for this process, then swaps the EXE."""

        if not self.runtime_is_frozen:
            return False
        pending = self._read_manifest(self.pending_path)
        if not pending or not self.staged_path.is_file():
            return False
        target = self.runtime_executable
        if target.suffix.casefold() != ".exe" or not target.is_file():
            return False
        try:
            raw = self.staged_path.read_bytes()
            _validate_pe(raw)
            digest = hashlib.sha256(raw).hexdigest().upper()
            if len(raw) != int(pending.get("size") or 0):
                return False
            if digest != str(pending.get("sha256") or "").upper():
                return False
            if Path(str(pending.get("target") or "")).resolve() != target:
                return False
            if Path(str(pending.get("staged") or "")).resolve() != self.staged_path:
                return False
        except (OSError, TypeError, ValueError, UpdateError):
            logger.exception("The pending update failed its final integrity check")
            return False
        backup = target.with_suffix(".previous.exe")
        incoming = target.with_suffix(".astro-incoming.exe")
        script = (
            "$ErrorActionPreference='Stop';"
            "$pidToWait=[int]$env:ASTRO_UPDATE_PID;"
            "$deadline=(Get-Date).AddSeconds(60);"
            "while ((Get-Process -Id $pidToWait -ErrorAction SilentlyContinue) -and ((Get-Date) -lt $deadline)) { Start-Sleep -Milliseconds 250 };"
            "if (Get-Process -Id $pidToWait -ErrorAction SilentlyContinue) { exit 3 };"
            "Remove-Item -LiteralPath $env:ASTRO_UPDATE_INCOMING -Force -ErrorAction SilentlyContinue;"
            "Copy-Item -LiteralPath $env:ASTRO_UPDATE_SOURCE -Destination $env:ASTRO_UPDATE_INCOMING -Force;"
            "$incomingHash=(Get-FileHash -LiteralPath $env:ASTRO_UPDATE_INCOMING -Algorithm SHA256).Hash;"
            "if ($incomingHash -ne $env:ASTRO_UPDATE_SHA256) { Remove-Item -LiteralPath $env:ASTRO_UPDATE_INCOMING -Force -ErrorAction SilentlyContinue; exit 2 };"
            "Copy-Item -LiteralPath $env:ASTRO_UPDATE_TARGET -Destination $env:ASTRO_UPDATE_BACKUP -Force;"
            "Move-Item -LiteralPath $env:ASTRO_UPDATE_INCOMING -Destination $env:ASTRO_UPDATE_TARGET -Force;"
            "Remove-Item -LiteralPath $env:ASTRO_UPDATE_SOURCE -Force -ErrorAction SilentlyContinue;"
            "Remove-Item -LiteralPath $env:ASTRO_UPDATE_MANIFEST -Force -ErrorAction SilentlyContinue;"
            "Remove-Item -LiteralPath $env:ASTRO_UPDATE_PENDING -Force -ErrorAction SilentlyContinue;"
            "Start-Process -FilePath $env:ASTRO_UPDATE_TARGET"
        )
        environment = os.environ.copy()
        environment.update({
            "ASTRO_UPDATE_PID": str(os.getpid()),
            "ASTRO_UPDATE_SOURCE": str(self.staged_path),
            "ASTRO_UPDATE_TARGET": str(target),
            "ASTRO_UPDATE_BACKUP": str(backup),
            "ASTRO_UPDATE_INCOMING": str(incoming),
            "ASTRO_UPDATE_SHA256": digest,
            "ASTRO_UPDATE_MANIFEST": str(self.manifest_path),
            "ASTRO_UPDATE_PENDING": str(self.pending_path),
        })
        try:
            subprocess.Popen(
                ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script],
                env=environment,
                close_fds=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0),
            )
            return True
        except OSError:
            logger.exception("The validated update helper could not be started")
            return False

    def _download(self, url: str, *, maximum: int) -> bytes:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in _DOWNLOAD_HOSTS:
            raise UpdateError("The release asset URL is not an approved GitHub host.")
        try:
            response = self.session.get(url, timeout=(5.0, 60.0), stream=True, allow_redirects=True, headers={"User-Agent": "AstroAccountManager"})
            response.raise_for_status()
            final = urlparse(response.url)
            if final.scheme != "https" or final.hostname not in _DOWNLOAD_HOSTS:
                raise UpdateError("GitHub redirected the asset to an unapproved host.")
            content = bytearray()
            for chunk in response.iter_content(64 * 1024):
                content.extend(chunk)
                if len(content) > maximum:
                    raise UpdateError("The release download exceeded its size limit.")
            return bytes(content)
        except requests.RequestException as exc:
            raise UpdateError("The release asset could not be downloaded from GitHub.") from exc

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, ValueError):
            return None

    @staticmethod
    def _write_manifest(path: Path, value: dict[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)


def _validate_pe(raw: bytes) -> None:
    if len(raw) < 512 or raw[:2] != b"MZ":
        raise UpdateError("The release asset is not a Windows executable.")
    offset = struct.unpack_from("<I", raw, 0x3C)[0]
    if offset < 0x40 or offset + 4 > len(raw) or raw[offset : offset + 4] != b"PE\x00\x00":
        raise UpdateError("The release asset has an invalid PE header.")


def _checksum_for_asset(text: str, filename: str) -> str | None:
    for line in text.splitlines():
        parts = line.strip().replace(" *", "  ").split()
        if len(parts) >= 2 and parts[0].isalnum() and parts[-1].casefold() == filename.casefold():
            return parts[0] if len(parts[0]) == 64 else None
    stripped = text.strip()
    return stripped if re.fullmatch(r"[A-Fa-f0-9]{64}", stripped) else None
