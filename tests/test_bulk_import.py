"""Tests for bulk account importing."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.backend.api.bridge import DesktopBridge
from app.backend.core.config import AppPaths
from app.backend.core.errors import ValidationError
from app.backend.repositories.sqlite_repository import SQLiteRepository
from app.backend.services.application_service import ApplicationService
from app.backend.storage.bulk_import import BulkAccountImporter


def _paths(tmp_path: Path) -> AppPaths:
    return AppPaths(
        root=tmp_path,
        database=tmp_path / "astro.db",
        logs=tmp_path / "logs",
        backups=tmp_path / "backups",
        cache=tmp_path / "cache",
        exports=tmp_path / "exports",
    )


def test_bulk_importer_parser():
    text = """
    # Comment line
    UserOne:Pass123
    UserTwo:Pass456:_|WARNING:-DO-NOT-SHARE-THIS.cookie_data_here
    _|WARNING:-DO-NOT-SHARE-THIS.raw_cookie_line
    """

    parsed = BulkAccountImporter.parse_text(text)
    assert len(parsed) == 3
    assert parsed[0]["username"] == "UserOne"
    assert parsed[0]["password"] == "Pass123"

    assert parsed[1]["username"] == "UserTwo"
    assert "cookie_data_here" in parsed[1]["cookie"]

    assert parsed[2]["username"] == ""
    assert "raw_cookie_line" in parsed[2]["cookie"]


def test_bulk_import_service_and_bridge(tmp_path: Path):
    paths = _paths(tmp_path)
    repo = SQLiteRepository(paths.database)
    service = ApplicationService(paths=paths, repository=repo)
    bridge = DesktopBridge(service)
    service.add_account_from_cookie = MagicMock(side_effect=ValidationError("invalid test cookie"))

    raw_text = "BulkUserA:PassAAA\nBulkUserB:PassBBB:_|WARNING:-DO-NOT-SHARE-THIS.cookieB"
    res = bridge.import_bulk_accounts(raw_text)

    assert res["imported"] == 2
    assert res["total_parsed"] == 2
    assert len(res["accounts"]) == 2

    # Check database
    accounts = repo.list_accounts()
    usernames = [acc.username for acc in accounts]
    assert "BulkUserA" in usernames
    assert "BulkUserB" in usernames

    # Invalid cookies are never promoted to usable sessions, while an
    # explicitly supplied saved password remains encrypted outside SQLite.
    imported_b = next(account for account in accounts if account.username == "BulkUserB")
    assert imported_b.has_session is False
    assert repo.load_protected_secret(imported_b.id, "session") is None
    protected_password = repo.load_protected_secret(imported_b.id, "saved_password")
    assert protected_password is not None
    assert service.vault.unprotect(protected_password) == b"PassBBB"
    assert res["warnings"]

    service.close()


WARNING_PREFIX = "_|WARNING:-DO-NOT-SHARE-THIS."


def test_parser_recovers_a_record_with_a_trailing_field():
    parsed = BulkAccountImporter.parse_text("UserOne:Pass123:someone@example.test")
    assert parsed == [{"username": "UserOne", "password": "Pass123", "cookie": None}]


def test_parser_collapses_duplicates_case_insensitively_and_keeps_richest():
    parsed = BulkAccountImporter.parse_text("UserOne\nUserOne:Pass123\nuserone")
    assert len(parsed) == 1
    assert parsed[0]["password"] == "Pass123"


def test_cookie_wins_over_password_only_duplicate():
    parsed = BulkAccountImporter.parse_text(
        "UserOne:Pass123\nUserOne:" + WARNING_PREFIX + "cookie_value"
    )
    assert len(parsed) == 1
    assert parsed[0]["cookie"].startswith(WARNING_PREFIX)


def test_comma_cookie_format_keeps_cookie_associated_with_username():
    parsed = BulkAccountImporter.parse_text(
        "UserOne,Pass123," + WARNING_PREFIX + "cookie_value"
    )
    assert len(parsed) == 1
    assert parsed[0]["username"] == "UserOne"
    assert parsed[0]["password"] == "Pass123"
    assert parsed[0]["cookie"].startswith(WARNING_PREFIX)


def test_parser_keeps_distinct_anonymous_cookies_and_collapses_repeats():
    first = WARNING_PREFIX + "cookie_a"
    second = WARNING_PREFIX + "cookie_b"
    assert len(BulkAccountImporter.parse_text(first + "\n" + second)) == 2
    assert len(BulkAccountImporter.parse_text(first + "\n" + first)) == 1


def test_parser_ignores_empty_comments_and_invalid_usernames():
    assert BulkAccountImporter.parse_text("") == []
    assert BulkAccountImporter.parse_text(None) == []  # type: ignore[arg-type]
    assert BulkAccountImporter.parse_text("# comment\n// comment\nab:Pass123") == []


def test_bulk_import_deduplicates_before_database_write(tmp_path: Path):
    paths = _paths(tmp_path)
    repo = SQLiteRepository(paths.database)
    service = ApplicationService(paths=paths, repository=repo)
    try:
        result = service.import_bulk_accounts("DupUser:PassAAA\nDupUser:PassAAA")
        assert result["total_parsed"] == 1
        assert result["imported"] == 1
        assert len([account for account in repo.list_accounts() if account.username == "DupUser"]) == 1
    finally:
        service.close()


def test_bulk_import_rejects_comment_only_input(tmp_path: Path):
    paths = _paths(tmp_path)
    repo = SQLiteRepository(paths.database)
    service = ApplicationService(paths=paths, repository=repo)
    try:
        with pytest.raises(ValidationError):
            service.import_bulk_accounts("# only a comment")
        assert repo.list_accounts() == []
    finally:
        service.close()


def test_bulk_import_never_stores_plaintext_password_in_sqlite(tmp_path: Path):
    paths = _paths(tmp_path)
    repo = SQLiteRepository(paths.database)
    service = ApplicationService(paths=paths, repository=repo)
    try:
        service.import_bulk_accounts("VaultUser:SuperSecretValue")
        account = next(item for item in repo.list_accounts() if item.username == "VaultUser")
        protected = repo.load_protected_secret(account.id, "saved_password")
        assert protected is not None
        assert service.vault.unprotect(protected) == b"SuperSecretValue"
        assert b"SuperSecretValue" not in paths.database.read_bytes()
    finally:
        service.close()
