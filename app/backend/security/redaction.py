"""Utilities that keep credentials out of diagnostics and logs.

The functions in this module deliberately preserve useful surrounding context.
They are suitable for logging arbitrary payloads, but they never mutate the
input object passed by a caller.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import dataclasses
import re
from typing import Any


REDACTED = "[REDACTED]"

# Keys are intentionally broad.  A false positive in a diagnostic is much
# cheaper than leaking a Roblox session cookie or a locally saved password.
_SENSITIVE_KEY = re.compile(
    r"(?:^|[_.-])(?:password|passwd|pwd|cookie|token|secret|credential|"
    r"authorization|api[_-]?key|session|roblosecurity)(?:$|[_.-])",
    re.IGNORECASE,
)
_SENSITIVE_KEY_EXACT = re.compile(
    r"^(?:password|passwd|pwd|cookie|token|secret|credentials?|"
    r"authorization|api[_-]?key|session(?:_?id)?|roblosecurity)$",
    re.IGNORECASE,
)

_JSON_SECRET = re.compile(
    r'(?P<key>"(?:password|passwd|pwd|cookie|token|secret|credentials?|'
    r'authorization|api[_-]?key|session(?:_?id)?|roblosecurity)")'
    r'\s*:\s*(?P<value>"(?:\\.|[^"\\])*"|[^,}\]\s]+)',
    re.IGNORECASE,
)
_ASSIGNMENT_SECRET = re.compile(
    r"(?P<key>\b(?:password|passwd|pwd|cookie|token|secret|credentials?|"
    r"authorization|api[_-]?key|session(?:_?id)?|roblosecurity)\b)"
    r"(?P<separator>\s*(?:=|:)\s*)(?P<value>[^\s,;]+)",
    re.IGNORECASE,
)
_BEARER_SECRET = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_ROBLOSECURITY_SECRET = re.compile(
    r"(?:\.ROBLOSECURITY\s*=\s*)[^;\s,]+", re.IGNORECASE
)


def is_sensitive_key(key: object) -> bool:
    """Return whether *key* commonly identifies a credential-like value."""

    if not isinstance(key, str):
        return False
    normalized = key.strip()
    if bool(
        _SENSITIVE_KEY_EXACT.fullmatch(normalized)
        or _SENSITIVE_KEY.search(normalized)
    ):
        return True
    # Legacy JSON often uses Pascal/camel case (e.g. ``SecurityToken`` or
    # ``SavedPassword``), where punctuation-boundary matching is insufficient.
    lowered = normalized.casefold()
    return any(
        marker in lowered
        for marker in (
            "password",
            "passwd",
            "cookie",
            "token",
            "secret",
            "credential",
            "authorization",
            "session",
            "apikey",
            "api_key",
            "api-key",
            "roblosecurity",
        )
    )


def redact_mapping(value: Any, *, replacement: str = REDACTED) -> Any:
    """Recursively copy *value* while masking fields with sensitive names.

    Dataclasses are converted to ordinary dictionaries because that is the most
    predictable form for structured logging.  Strings are passed through
    :func:`redact_text` as a final defense against secrets embedded in messages.
    """

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = dataclasses.asdict(value)

    if isinstance(value, Mapping):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            redacted[key] = replacement if is_sensitive_key(key) else redact_mapping(
                item, replacement=replacement
            )
        return redacted

    if isinstance(value, str):
        return redact_text(value, replacement=replacement)

    # bytes are often the encrypted form of a secret.  Retaining their repr or
    # base64 value would be unsafe and provides little diagnostic value.
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"[BINARY:{len(value)} bytes]"

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact_mapping(item, replacement=replacement) for item in value]

    return value


def redact_text(text: object, *, replacement: str = REDACTED) -> str:
    """Mask common secret formats in unstructured text.

    This is intentionally conservative: it targets explicit credential labels,
    Bearer headers, and the Roblox session-cookie name rather than attempting to
    recognize arbitrary high-entropy strings.
    """

    value = str(text)
    value = _JSON_SECRET.sub(lambda match: f'{match.group("key")}: "{replacement}"', value)
    # Do this before generic assignment masking: otherwise
    # ``Authorization: Bearer <value>`` would redact only the word Bearer and
    # leave the credential itself behind.
    value = _BEARER_SECRET.sub(f"Bearer {replacement}", value)
    value = _ASSIGNMENT_SECRET.sub(
        lambda match: f'{match.group("key")}{match.group("separator")}{replacement}', value
    )
    return _ROBLOSECURITY_SECRET.sub(f".ROBLOSECURITY={replacement}", value)


__all__ = ["REDACTED", "is_sensitive_key", "redact_mapping", "redact_text"]
