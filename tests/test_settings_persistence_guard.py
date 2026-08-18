"""Guards on the names of persisted settings.

Settings are flattened into ``category.key`` paths before they are written with
:meth:`SQLiteRepository.set_setting`, which refuses any key that
:func:`is_sensitive_key` classifies as credential-like.  A single unlucky word
in a new setting name (``session`` is the one that bit us) therefore does not
fail at import time: it breaks the settings bootstrap at runtime and takes down
every integration test that builds an ``ApplicationService``.

These tests turn that runtime landmine into an immediate, readable failure.
"""

from __future__ import annotations

from app.backend.core.config import DEFAULT_SETTINGS
from app.backend.security.redaction import is_sensitive_key
from app.backend.services.application_service import _flatten_settings

# ``_required_text(key, "setting key", maximum=200)`` in the repository.
MAX_SETTING_KEY_CHARS = 200


def test_no_default_setting_uses_a_credential_like_name() -> None:
    refused = sorted(
        key for key in _flatten_settings(DEFAULT_SETTINGS) if is_sensitive_key(key)
    )
    assert refused == [], (
        "These settings keys would be refused by SQLiteRepository.set_setting "
        "because is_sensitive_key() reads them as credentials. Rename them and "
        "avoid the words session, token, secret, cookie, password, credential, "
        f"authorization and api_key: {refused}"
    )


def test_default_setting_keys_fit_the_repository_limit() -> None:
    too_long = sorted(
        key
        for key in _flatten_settings(DEFAULT_SETTINGS)
        if len(key) > MAX_SETTING_KEY_CHARS
    )
    assert too_long == []


def test_the_guard_would_notice_a_credential_like_name() -> None:
    # Without this the guard above could pass simply because the classifier
    # stopped classifying anything.  It also pins the exact regression: the
    # rule engine used to ship ``rules.session_max_hours``.
    assert is_sensitive_key("rules.session_max_hours")
    assert is_sensitive_key("api.auth_token")
    assert not is_sensitive_key("rules.max_runtime_hours")
