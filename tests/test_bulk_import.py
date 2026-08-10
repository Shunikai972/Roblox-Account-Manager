"""Tests for bulk account importing."""

from pathlib import Path

from app.backend.api.bridge import DesktopBridge
from app.backend.core.config import AppPaths
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

    service.close()
