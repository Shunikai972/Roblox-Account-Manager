"""Redacted fatal-error reports and user-created local support bundles."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import logging
from pathlib import Path
import platform
import re
import sys
import threading
import traceback
from typing import Any, Callable, Mapping
import zipfile

from .config import APP_NAME, APP_VERSION
from .logging import redact


_COOKIE = re.compile(r"(?i)(?:_\|WARNING[^\s]{20,}|\.ROBLOSECURITY\s*[=:]\s*[^\s,;\"']+)")
_TOKEN = re.compile(r"(?i)(?:bearer|token|ticket|password|cookie|secret|authorization)\s*[=:]\s*[^\s,;\"']+")
_USER_PATH = re.compile(r"(?i)([A-Z]:\\Users\\)[^\\\r\n]+")
_MAX_LOG_BYTES = 5 * 1024 * 1024


def redact_support_text(value: Any) -> str:
    text = redact(value)
    text = _COOKIE.sub("[REDACTED_SESSION]", text)
    text = _TOKEN.sub("[REDACTED_SECRET]", text)
    return _USER_PATH.sub(r"\1[USER]", text)


class CrashReporter:
    """Install non-invasive fatal hooks that keep the original hook chain."""

    def __init__(self, log_directory: Path, logger: logging.Logger | logging.LoggerAdapter[logging.Logger]) -> None:
        self.log_directory = Path(log_directory)
        self.log_directory.mkdir(parents=True, exist_ok=True)
        self.logger = logger
        self._previous_sys = sys.excepthook
        self._previous_thread = threading.excepthook
        self._installed = False

    def install(self) -> None:
        if self._installed:
            return
        self._installed = True

        def sys_hook(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
            self.write(exc_type, exc, tb, thread_name="main")
            if self._previous_sys not in {sys_hook, sys.__excepthook__}:
                self._previous_sys(exc_type, exc, tb)

        def thread_hook(args: threading.ExceptHookArgs) -> None:
            self.write(args.exc_type, args.exc_value, args.exc_traceback, thread_name=getattr(args.thread, "name", "thread"))
            if self._previous_thread is not thread_hook:
                self._previous_thread(args)

        sys.excepthook = sys_hook
        threading.excepthook = thread_hook

    def write(self, exc_type: type[BaseException], exc: BaseException, tb: Any, *, thread_name: str) -> Path:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        path = self.log_directory / f"crash-{stamp}.log"
        formatted = "".join(traceback.format_exception(exc_type, exc, tb))
        report = (
            f"{APP_NAME} {APP_VERSION}\n"
            f"UTC: {datetime.now(UTC).isoformat()}\n"
            f"Thread: {redact_support_text(thread_name)[:120]}\n"
            f"Platform: {platform.system()} {platform.release()}\n\n"
            f"{redact_support_text(formatted)}"
        )
        path.write_text(report, encoding="utf-8")
        try:
            self.logger.error("A fatal error report was written to the local diagnostics folder.")
        except Exception:
            pass
        return path


class SupportBundleBuilder:
    """Create a local, secret-free ZIP the user may choose to share."""

    def __init__(self, log_directory: Path, export_directory: Path) -> None:
        self.log_directory = Path(log_directory)
        self.export_directory = Path(export_directory)

    def create(self, *, diagnostics: Mapping[str, Any], settings: Mapping[str, Any]) -> dict[str, Any]:
        self.export_directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        path = self.export_directory / f"astro-support-{stamp}.zip"
        public_settings = _public_settings(settings)
        manifest = {
            "application": APP_NAME,
            "version": APP_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "platform": {"system": platform.system(), "release": platform.release(), "python": platform.python_version()},
            "classification": "redacted_support_bundle",
        }
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            archive.writestr("manifest.json", _safe_json(manifest))
            archive.writestr("diagnostics.json", _safe_json(diagnostics))
            archive.writestr("settings.json", _safe_json(public_settings))
            for candidate in sorted(self.log_directory.glob("*.log"), key=lambda item: item.stat().st_mtime, reverse=True)[:8]:
                try:
                    if candidate.stat().st_size > _MAX_LOG_BYTES:
                        raw = candidate.read_bytes()[-_MAX_LOG_BYTES:]
                        content = raw.decode("utf-8", errors="replace")
                    else:
                        content = candidate.read_text(encoding="utf-8", errors="replace")
                    archive.writestr(f"logs/{candidate.name}", redact_support_text(content))
                except OSError:
                    continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest().upper()
        return {"path": str(path), "filename": path.name, "size": path.stat().st_size, "sha256": digest, "classification": "redacted_support_bundle"}


def _public_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
    blocked = {"client_id", "redirect_uri", "provider", "region_lookup_provider"}

    def clean(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(key): clean(item) for key, item in value.items() if str(key).casefold() not in blocked and not any(word in str(key).casefold() for word in ("token", "secret", "password", "cookie", "ticket"))}
        if isinstance(value, list):
            return [clean(item) for item in value[:100]]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    result = clean(settings)
    return result if isinstance(result, dict) else {}


def _safe_json(value: Mapping[str, Any]) -> str:
    return redact_support_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str))
