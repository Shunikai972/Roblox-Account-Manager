from __future__ import annotations

from app.backend.core.config import (
    APP_NAME,
    APP_SLUG,
    LEGACY_APP_SLUG,
    AppPaths,
    DEFAULT_SETTINGS,
    merge_settings,
)
from app.backend.core.logging import redact
from app.backend.models.domain import Account


def test_merge_settings_recursively_preserves_defaults() -> None:
    result = merge_settings(DEFAULT_SETTINGS, {"appearance": {"theme": "light"}})

    assert result["appearance"]["theme"] == "light"
    assert result["appearance"]["accent"] == DEFAULT_SETTINGS["appearance"]["accent"]
    assert DEFAULT_SETTINGS["appearance"]["theme"] == "dark"


def test_redaction_hides_common_session_material() -> None:
    message = ".ROBLOSECURITY=super-secret csrf-token: csrf-value password=abc"

    redacted = redact(message)

    assert "super-secret" not in redacted
    assert "csrf-value" not in redacted
    assert "password=abc" not in redacted
    assert "[REDACTED]" in redacted


def test_account_public_model_has_no_session_value() -> None:
    account = Account(username="example", has_session=True)

    assert "session" not in account.to_dict()
    assert account.to_dict()["has_session"] is True


def test_rebrand_uses_astro_for_new_data_and_preserves_legacy_workspace(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    new_paths = AppPaths.for_current_user()

    assert APP_NAME == "Astro Account Manager"
    assert new_paths.root.name == APP_SLUG
    assert new_paths.database.name == "astro.db"

    legacy_root = tmp_path / LEGACY_APP_SLUG
    legacy_root.mkdir()
    (legacy_root / "asteria.db").write_bytes(b"legacy-placeholder")

    migrated_paths = AppPaths.for_current_user()

    assert migrated_paths.root == legacy_root
    assert migrated_paths.database == legacy_root / "asteria.db"
