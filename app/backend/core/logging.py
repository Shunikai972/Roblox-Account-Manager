"""Logging with conservative automatic secret redaction."""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path


_SECRET_PATTERNS = (
    re.compile(r"(?i)(\.ROBLOSECURITY[=:\s]+)([^\s,;\"']+)"),
    re.compile(r"(?i)(csrf(?:[-_ ]?token)?[=:\s]+)([^\s,;\"']+)"),
    re.compile(r"(?i)(authorization[=:\s]+bearer\s+)([^\s,;\"']+)"),
    re.compile(r"(?i)(password[=:\s]+)([^\s,;\"']+)"),
    re.compile(r"(?i)(ticket[=:\s]+)([^\s,;\"']+)"),
)


def redact(value: object) -> str:
    text = str(value)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(r"\1[REDACTED]", text)
    return text


class SecretRedactionFilter(logging.Filter):
    """Redact string arguments before a handler formats a record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {key: redact(value) for key, value in record.args.items()}
            else:
                record.args = tuple(redact(value) for value in record.args)
        return True


def configure_logging(log_directory: Path, *, verbose: bool = False) -> logging.Logger:
    log_directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("astro_account_manager")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        log_directory / "astro-account-manager.log",
        encoding="utf-8",
        maxBytes=2_000_000,
        backupCount=5,
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(SecretRedactionFilter())
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(SecretRedactionFilter())
    logger.addHandler(console_handler)
    return logging.LoggerAdapter(logger, {"request_id": "startup"})  # type: ignore[return-value]
