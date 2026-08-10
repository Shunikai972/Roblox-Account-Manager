from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from app.backend.models.domain import Account, Activity, Game, Group, Notification
from app.backend.repositories.sqlite_repository import RepositoryError, SQLiteRepository
from app.backend.security.dpapi import CurrentUserDPAPI, DPAPIUnavailableError
from app.backend.security.redaction import redact_mapping, redact_text
from app.backend.security.vault import DPAPISecretVault
from app.backend.storage.backups import BackupError, VersionedBackupManager


def test_repository_persists_public_domain_objects_and_excludes_sensitive_metadata(tmp_path: Path) -> None:
    with SQLiteRepository(tmp_path / "app.db") as repository:
        group = repository.save_group(Group(name="Primary", is_favorite=True))
        account = repository.save_account(
            Account(
                username="ExampleUser",
                group_id=group.id,
                custom_fields={"favorite_color": "violet", "password": "must-not-persist"},
                metadata={"source": "legacy", "token": "must-not-persist"},
            )
        )
        game = repository.save_game(Game(place_id=12345, name="Example Game", is_favorite=True))
        activity = repository.record_activity(Activity(kind="launch", summary="Started Example Game", account_id=account.id))
        notification = repository.save_notification(
            Notification(level="info", title="Ready", message="Everything is local.")
        )
        repository.set_setting("appearance.theme", "dark")

        loaded = repository.get_account(account.id)
        assert loaded.username == "ExampleUser"
        assert loaded.group_id == group.id
        assert loaded.custom_fields == {"favorite_color": "violet"}
        assert loaded.metadata == {"source": "legacy"}
        assert repository.list_games(favorites_only=True) == [game]
        assert repository.list_activity(account_id=account.id) == [activity]
        assert repository.list_notifications() == [notification]
        assert repository.get_setting("appearance.theme") == "dark"


def test_recent_game_pruning_preserves_a_favorite_record(tmp_path: Path) -> None:
    with SQLiteRepository(tmp_path / "app.db") as repository:
        favorite = repository.save_game(
            Game(
                place_id=10,
                name="Favorite recent",
                is_favorite=True,
                last_used_at="2026-08-10T10:00:00+00:00",
            )
        )
        repository.save_game(
            Game(place_id=20, name="Old recent", last_used_at="2026-08-10T11:00:00+00:00")
        )
        repository.save_game(
            Game(place_id=30, name="New recent", last_used_at="2026-08-10T12:00:00+00:00")
        )

        removed = repository.prune_recent_games(2)

        assert removed == [10]
        assert [game.place_id for game in repository.list_games(recent_only=True)] == [30, 20]
        retained = repository.get_game_by_place_id(favorite.place_id)
        assert retained is not None
        assert retained.is_favorite is True
        assert retained.last_used_at is None


def test_repository_can_toggle_and_delete_a_persisted_game(tmp_path: Path) -> None:
    with SQLiteRepository(tmp_path / "app.db") as repository:
        repository.save_game(Game(place_id=456, name="Toggle game", last_used_at="2026-08-10T12:00:00+00:00"))

        favorite = repository.set_game_favorite(456, True)
        assert favorite.is_favorite is True
        assert repository.list_games(favorites_only=True) == [favorite]
        assert repository.delete_game_by_place_id(456) is True
        assert repository.get_game_by_place_id(456) is None
        assert repository.delete_game_by_place_id(456) is False


def test_repository_transactions_rollback_as_a_unit(tmp_path: Path) -> None:
    with SQLiteRepository(tmp_path / "app.db") as repository:
        with pytest.raises(RuntimeError):
            with repository.transaction():
                repository.save_group(Group(name="Will Roll Back"))
                raise RuntimeError("intentional test rollback")
        assert repository.list_groups() == []


def test_account_order_is_persisted_reordered_atomically_and_appends_new_accounts(tmp_path: Path) -> None:
    database = tmp_path / "ordered-accounts.db"
    with SQLiteRepository(database) as repository:
        first = repository.save_account(Account(username="First"))
        second = repository.save_account(Account(username="Second"))
        third = repository.save_account(Account(username="Third"))
        assert [account.sort_order for account in repository.list_accounts()] == [0, 1, 2]

        reordered = repository.reorder_accounts([third.id, first.id, second.id])
        assert [account.id for account in reordered] == [third.id, first.id, second.id]
        assert [account.sort_order for account in reordered] == [0, 1, 2]

        with pytest.raises(RepositoryError, match="duplicates"):
            repository.reorder_accounts([third.id, third.id, first.id])
        with pytest.raises(RepositoryError, match="complete account ID order"):
            repository.reorder_accounts([third.id, first.id])
        with pytest.raises(RepositoryError, match="not found"):
            repository.reorder_accounts([third.id, first.id, second.id, "missing-account"])
        with pytest.raises(RepositoryError, match="ordered iterable"):
            repository.reorder_accounts(third.id)
        assert [account.id for account in repository.list_accounts()] == [third.id, first.id, second.id]

        second.description = "Edited without resetting position"
        assert repository.save_account(second).sort_order == 2
        appended = repository.save_account(Account(username="Appended"))
        assert appended.sort_order == 3

    with SQLiteRepository(database) as reopened:
        assert [account.username for account in reopened.list_accounts()] == ["Third", "First", "Second", "Appended"]
        assert [account.sort_order for account in reopened.list_accounts()] == [0, 1, 2, 3]


def test_group_order_is_persisted_reordered_atomically_and_stable_on_save(tmp_path: Path) -> None:
    database = tmp_path / "ordered-groups.db"
    with SQLiteRepository(database) as repository:
        first = repository.save_group(Group(name="First"))
        second = repository.save_group(Group(name="Second"))
        third = repository.save_group(Group(name="Third"))
        assert [group.sort_order for group in repository.list_groups()] == [0, 1, 2]

        reordered = repository.reorder_groups([third.id, first.id, second.id])
        assert [group.id for group in reordered] == [third.id, first.id, second.id]
        assert [group.sort_order for group in reordered] == [0, 1, 2]

        with pytest.raises(RepositoryError, match="duplicates"):
            repository.reorder_groups([third.id, third.id, first.id])
        with pytest.raises(RepositoryError, match="complete group ID order"):
            repository.reorder_groups([third.id, first.id])
        with pytest.raises(RepositoryError, match="not found"):
            repository.reorder_groups([third.id, first.id, second.id, "missing-group"])
        with pytest.raises(RepositoryError, match="ordered iterable"):
            repository.reorder_groups(third.id)
        assert [group.id for group in repository.list_groups()] == [third.id, first.id, second.id]

        second.color = "#4f46e5"
        assert repository.save_group(second).sort_order == 2
        appended = repository.save_group(Group(name="Appended"))
        assert appended.sort_order == 3

    with SQLiteRepository(database) as reopened:
        assert [group.name for group in reopened.list_groups()] == ["Third", "First", "Second", "Appended"]
        assert [group.sort_order for group in reopened.list_groups()] == [0, 1, 2, 3]


def test_v1_account_database_migrates_to_a_stable_persisted_order(tmp_path: Path) -> None:
    database = tmp_path / "v1-accounts.db"
    _create_v1_accounts_database(database)

    with SQLiteRepository(database) as repository:
        assert repository.schema_version == 3
        migrated = repository.list_accounts()
        # This is the v1 observable default order: favourite, then latest
        # usage, then case-insensitive username and ID.  Version 2 freezes it
        # as explicit positions before the first user-driven reorder.
        assert [account.username for account in migrated] == ["Favorite", "Recent", "Alphabetical"]
        assert [account.sort_order for account in migrated] == [0, 1, 2]

    with SQLiteRepository(database) as reopened:
        assert [account.username for account in reopened.list_accounts()] == ["Favorite", "Recent", "Alphabetical"]
        assert [account.sort_order for account in reopened.list_accounts()] == [0, 1, 2]


def test_v2_group_database_migrates_legacy_numeric_prefix_order(tmp_path: Path) -> None:
    database = tmp_path / "v2-groups.db"
    _create_v2_groups_database(database)

    with SQLiteRepository(database) as repository:
        assert repository.schema_version == 3
        migrated = repository.list_groups()
        # RAM 3.7.2 grouped by the raw name, then hid a leading 1-3 digit
        # prefix from the group header.  Version 3 freezes that old ordering.
        assert [group.name for group in migrated] == ["001 Apple", "2 Banana", "10 Tangerine", "Zebra"]
        assert [group.sort_order for group in migrated] == [0, 1, 2, 3]

    with SQLiteRepository(database) as reopened:
        assert [group.name for group in reopened.list_groups()] == ["001 Apple", "2 Banana", "10 Tangerine", "Zebra"]
        assert [group.sort_order for group in reopened.list_groups()] == [0, 1, 2, 3]


def test_settings_refuse_secret_named_values(tmp_path: Path) -> None:
    with SQLiteRepository(tmp_path / "app.db") as repository:
        with pytest.raises(RepositoryError):
            repository.set_setting("api.token", "not-a-real-secret")


def test_redaction_masks_structured_and_unstructured_credentials() -> None:
    redacted = redact_mapping(
        {"token": "example", "nested": {"password": "example"}, "safe": "keep"}
    )
    assert redacted == {"token": "[REDACTED]", "nested": {"password": "[REDACTED]"}, "safe": "keep"}
    assert "example" not in redact_text("Authorization: Bearer example-token")
    assert "example" not in redact_text(".ROBLOSECURITY=example-cookie")


def test_atomic_backup_verifies_and_requires_restore_confirmation(tmp_path: Path) -> None:
    source = tmp_path / "source.dat"
    source.write_bytes(b"test backup payload")
    manager = VersionedBackupManager(tmp_path / "backups", app_version="test")

    record = manager.create_backup(source, label="test")
    assert manager.verify(record)
    assert manager.list_backups(verify=True) == [record]

    destination = tmp_path / "restored.dat"
    assert manager.restore(record, destination) == destination
    assert destination.read_bytes() == source.read_bytes()
    with pytest.raises(BackupError):
        manager.restore(record, destination)


def test_dpapi_current_user_round_trip_or_safe_unavailable_fallback() -> None:
    dpapi = CurrentUserDPAPI()
    if not dpapi.available:
        assert dpapi.try_protect(b"non-production-test-data") is None
        with pytest.raises(DPAPIUnavailableError):
            dpapi.protect(b"non-production-test-data")
        return
    protected = dpapi.protect(b"non-production-test-data", entropy=b"test-entropy")
    assert protected != b"non-production-test-data"
    assert dpapi.unprotect(protected, entropy=b"test-entropy") == b"non-production-test-data"


def test_dpapi_vault_stores_only_protected_blobs(tmp_path: Path) -> None:
    dpapi = CurrentUserDPAPI()
    if not dpapi.available:
        pytest.skip("Windows DPAPI is unavailable")
    with SQLiteRepository(tmp_path / "app.db") as repository:
        account = repository.save_account(Account(username="vault-user"))
        vault = DPAPISecretVault(repository, dpapi)
        vault.store(account.id, "session", b"non-production-test-data")
        blob = repository.load_protected_secret(account.id, "session")
        assert blob is not None
        assert b"non-production-test-data" not in blob
        assert vault.retrieve(account.id, "session") == b"non-production-test-data"


def _create_v1_accounts_database(path: Path) -> None:
    """Create the pre-sort-order shape to exercise the real SQLite migration."""

    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            INSERT INTO schema_migrations (version, applied_at) VALUES (1, '2026-08-10T00:00:00+00:00');
            CREATE TABLE groups (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE,
                color TEXT NOT NULL DEFAULT '#7c5cff',
                icon TEXT NOT NULL DEFAULT 'folder',
                sort_order INTEGER NOT NULL DEFAULT 0,
                is_favorite INTEGER NOT NULL DEFAULT 0,
                is_collapsed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE accounts (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL COLLATE NOCASE,
                user_id INTEGER,
                display_name TEXT,
                alias TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                group_id TEXT,
                avatar_url TEXT,
                status TEXT NOT NULL DEFAULT 'unknown',
                is_favorite INTEGER NOT NULL DEFAULT 0,
                last_used_at TEXT,
                last_refreshed_at TEXT,
                saved_place_id INTEGER,
                saved_job_id TEXT,
                browser_tracker_id TEXT,
                custom_fields_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                has_session INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        rows = [
            (
                "account-alpha",
                "Alphabetical",
                0,
                None,
            ),
            (
                "account-recent",
                "Recent",
                0,
                "2026-08-10T11:00:00+00:00",
            ),
            (
                "account-favorite",
                "Favorite",
                1,
                "2026-08-10T01:00:00+00:00",
            ),
        ]
        connection.executemany(
            """
            INSERT INTO accounts (
                id, username, is_favorite, last_used_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, '2026-08-10T00:00:00+00:00', '2026-08-10T00:00:00+00:00')
            """,
            rows,
        )
        connection.commit()
    finally:
        connection.close()


def _create_v2_groups_database(path: Path) -> None:
    """Create the pre-persisted-group-order shape for the v3 migration."""

    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            INSERT INTO schema_migrations (version, applied_at) VALUES (2, '2026-08-10T00:00:00+00:00');
            CREATE TABLE groups (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE,
                color TEXT NOT NULL,
                icon TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                is_favorite INTEGER NOT NULL DEFAULT 0,
                is_collapsed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        connection.executemany(
            """
            INSERT INTO groups (id, name, color, icon, sort_order, is_favorite, is_collapsed, created_at, updated_at)
            VALUES (?, ?, '#7c5cff', 'folder', ?, 0, 0, '2026-08-10T00:00:00+00:00', '2026-08-10T00:00:00+00:00')
            """,
            [
                ("group-zebra", "Zebra", 0),
                ("group-ten", "10 Tangerine", 1),
                ("group-first", "001 Apple", 2),
                ("group-second", "2 Banana", 3),
            ],
        )
        connection.commit()
    finally:
        connection.close()
