"""Account health, tags and custom fields.

Health is *derived*, never stored: it is a reading of what the account already
carries (saved credentials, OAuth expiry, last launch result) plus whether a
client is running right now.  Storing it would let it drift from reality.

Naming note: no status code or field key here may contain a credential-like
word such as password, token, cookie or session, because these values are
flattened into settings keys and ``SQLiteRepository.set_setting`` refuses
those outright.  ``auth_expired`` is used where you would expect
"session expired".
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from app.backend.core.errors import ValidationError

MAX_TAGS = 12
MAX_TAG_CHARS = 24
MAX_FIELDS = 12
MAX_FIELD_KEY_CHARS = 32
MAX_FIELD_VALUE_CHARS = 120
AUTH_WARNING_SECONDS = 3 * 86_400

HEALTH_OK = "ok"
HEALTH_RUNNING = "running"
HEALTH_AUTH_EXPIRED = "auth_expired"
HEALTH_AUTH_REQUIRED = "auth_required"
HEALTH_AUTH_EXPIRING = "auth_expiring"
HEALTH_LAUNCH_FAILED = "launch_failed"
HEALTH_NEVER_LAUNCHED = "never_launched"

_HEALTH_LABELS = {
    HEALTH_RUNNING: ("In game", "check", "ok"),
    HEALTH_OK: ("Ready", "check", "ok"),
    HEALTH_AUTH_EXPIRING: ("Sign-in expires soon", "alert", "warn"),
    HEALTH_AUTH_EXPIRED: ("Sign-in expired", "alert", "warn"),
    HEALTH_AUTH_REQUIRED: ("Sign-in required", "lock", "warn"),
    HEALTH_LAUNCH_FAILED: ("Last launch failed", "alert", "error"),
    HEALTH_NEVER_LAUNCHED: ("Never launched", "info", "muted"),
}

# Same shape as the repository guard so a custom field can never smuggle a
# credential into storage under a friendly name.
_SENSITIVE_FIELD = re.compile(
    r"(?:^|[_.\- ])(?:password|passwd|pwd|cookie|token|secret|credential|authorization|api[_-]?key|session|roblosecurity)(?:$|[_.\- ])",
    re.IGNORECASE,
)


def normalize_tags(raw: Any) -> list[str]:
    """Return a bounded, de-duplicated tag list preserving the typed case."""

    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        candidates = [part for part in re.split(r"[,\n]", raw)]
    elif isinstance(raw, (list, tuple)):
        candidates = list(raw)
    else:
        raise ValidationError("Tags must be a list or a comma separated string.")
    tags: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        text = str(item or "").strip()
        if not text:
            continue
        if len(text) > MAX_TAG_CHARS:
            raise ValidationError(f"A tag may hold at most {MAX_TAG_CHARS} characters.")
        if any(ord(char) < 32 for char in text):
            raise ValidationError("A tag contains an invalid character.")
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        tags.append(text)
        if len(tags) > MAX_TAGS:
            raise ValidationError(f"An account may carry at most {MAX_TAGS} tags.")
    return tags


def validated_custom_fields(raw: Any) -> dict[str, str]:
    """Validate free-form per-account fields such as Level or Gems."""

    if raw is None or raw == "":
        return {}
    if not isinstance(raw, Mapping):
        raise ValidationError("Custom fields must be an object.")
    if len(raw) > MAX_FIELDS:
        raise ValidationError(f"An account may carry at most {MAX_FIELDS} custom fields.")
    fields: dict[str, str] = {}
    for key, value in raw.items():
        name = str(key or "").strip()
        if not name:
            raise ValidationError("A custom field name is required.")
        if len(name) > MAX_FIELD_KEY_CHARS:
            raise ValidationError(f"A custom field name may hold at most {MAX_FIELD_KEY_CHARS} characters.")
        if _SENSITIVE_FIELD.search(name):
            raise ValidationError("Custom fields cannot store credentials.")
        text = "" if value is None else str(value).strip()
        if len(text) > MAX_FIELD_VALUE_CHARS:
            raise ValidationError(f"A custom field value may hold at most {MAX_FIELD_VALUE_CHARS} characters.")
        if any(ord(char) < 32 for char in text):
            raise ValidationError("A custom field value contains an invalid character.")
        fields[name] = text
    return fields


def evaluate_account_health(
    account: Any,
    *,
    now: float,
    running: bool = False,
) -> dict[str, Any]:
    """Read an account's health without touching it.

    ``account`` may be a domain object or a mapping; only attributes that
    already exist are consulted.
    """

    def _read(name: str, default: Any = None) -> Any:
        if isinstance(account, Mapping):
            return account.get(name, default)
        return getattr(account, name, default)

    metadata = _read("metadata") or {}
    if not isinstance(metadata, Mapping):
        metadata = {}

    status = HEALTH_OK
    detail = "This account is ready to launch."
    if running:
        status = HEALTH_RUNNING
        detail = "A Roblox client is running for this account."
    else:
        expires_raw = _read("oauth_expires_at") or metadata.get("oauth_expires_at")
        expires: float | None
        try:
            expires = float(expires_raw) if expires_raw not in (None, "") else None
        except (TypeError, ValueError):
            expires = None
        has_secret = bool(_read("has_password", False)) or bool(_read("has_cookie", False))
        last_error = str(metadata.get("last_launch_error") or "").strip()
        last_launch = metadata.get("last_launch_at")

        if expires is not None and expires <= float(now):
            status = HEALTH_AUTH_EXPIRED
            detail = "The saved sign-in expired. Sign in again to launch this account."
        elif expires is not None and expires - float(now) <= AUTH_WARNING_SECONDS:
            status = HEALTH_AUTH_EXPIRING
            detail = "The saved sign-in expires within three days."
        elif not has_secret and expires is None:
            status = HEALTH_AUTH_REQUIRED
            detail = "No saved sign-in. Add one before launching."
        elif last_error:
            status = HEALTH_LAUNCH_FAILED
            detail = f"The last launch failed: {last_error[:120]}"
        elif not last_launch:
            status = HEALTH_NEVER_LAUNCHED
            detail = "This account has never been launched from Astro."

    label, glyph, tone = _HEALTH_LABELS.get(status, ("Unknown", "info", "muted"))
    return {
        "status": status,
        "label": label,
        "icon": glyph,
        "tone": tone,
        "detail": detail,
        # Only these two ask the operator to do something.
        "needs_attention": status in {HEALTH_AUTH_EXPIRED, HEALTH_AUTH_REQUIRED, HEALTH_LAUNCH_FAILED},
    }


def collect_tags(accounts: Iterable[Any]) -> list[dict[str, Any]]:
    """Return every tag in use with its account count, most used first."""

    counts: dict[str, dict[str, Any]] = {}
    for account in accounts:
        metadata = account.get("metadata") if isinstance(account, Mapping) else getattr(account, "metadata", None)
        if not isinstance(metadata, Mapping):
            continue
        for tag in normalize_tags(metadata.get("tags")):
            row = counts.setdefault(tag.casefold(), {"tag": tag, "count": 0})
            row["count"] += 1
    rows = list(counts.values())
    rows.sort(key=lambda row: (-row["count"], row["tag"].casefold()))
    return rows


def matches_filters(
    account: Mapping[str, Any],
    *,
    tags: Iterable[str] | None = None,
    status: str = "",
    query: str = "",
) -> bool:
    """Decide whether one account payload survives the account filters."""

    wanted = {str(tag).casefold() for tag in (tags or []) if str(tag).strip()}
    if wanted:
        metadata = account.get("metadata") if isinstance(account.get("metadata"), Mapping) else {}
        owned = {tag.casefold() for tag in normalize_tags(metadata.get("tags"))}
        # Every selected tag must match, so filters narrow instead of widen.
        if not wanted.issubset(owned):
            return False
    wanted_status = str(status or "").strip().lower()
    if wanted_status:
        health = account.get("health")
        current = health.get("status") if isinstance(health, Mapping) else ""
        if wanted_status == "attention":
            if not (isinstance(health, Mapping) and health.get("needs_attention")):
                return False
        elif current != wanted_status:
            return False
    text = str(query or "").strip().casefold()
    if text:
        haystack = " ".join(
            str(account.get(key) or "")
            for key in ("username", "display_name", "note", "group_name")
        ).casefold()
        if text not in haystack:
            return False
    return True
