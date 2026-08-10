from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.backend.models.domain import Account, Game, Group
from app.backend.repositories.sqlite_repository import SQLiteRepository
from app.backend.storage.metadata_transfer import (
    LEGACY_METADATA_TRANSFER_FORMAT,
    METADATA_TRANSFER_FORMAT,
    METADATA_TRANSFER_VERSION,
    MetadataTransfer,
    MetadataTransferError,
)


def _checksum(document: dict[str, object]) -> str:
    content = {key: document[key] for key in ("groups", "accounts", "games")}
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_export_is_atomic_and_contains_only_redacted_public_metadata(tmp_path: Path) -> None:
    destination = tmp_path / "exports" / "portable.json"
    with SQLiteRepository(tmp_path / "source.db") as repository:
        group = repository.save_group(Group(name="Main crew", color="violet"))
        account = repository.save_account(
            Account(
                username="PublicUser",
                group_id=group.id,
                description=".ROBLOSECURITY=export-only-placeholder",
                custom_fields={"label": "safe", "session_token": "must-never-export"},
                metadata={"origin": "test", "api_key": "must-never-export"},
                has_session=True,
                browser_tracker_id="private-browser-marker",
            )
        )
        repository.save_protected_secret(account.id, "session", b"opaque-non-production-blob")
        repository.save_game(Game(place_id=12345, name="Public game", metadata={"genre": "adventure"}))

        exported = MetadataTransfer(repository).export_to(destination)
        assert exported == destination.resolve()
        with pytest.raises(MetadataTransferError):
            MetadataTransfer(repository).export_to(destination)

    document = json.loads(destination.read_text(encoding="utf-8"))
    assert document["format"] == METADATA_TRANSFER_FORMAT
    assert document["version"] == METADATA_TRANSFER_VERSION
    assert document["manifest"]["data_classification"] == "public_metadata_only"
    assert document["manifest"]["entity_counts"] == {"accounts": 1, "games": 1, "groups": 1}
    exported_account = document["accounts"][0]
    assert exported_account["custom_fields"] == {"label": "safe"}
    assert exported_account["metadata"] == {"origin": "test"}
    assert "has_session" not in exported_account
    assert "browser_tracker_id" not in exported_account
    serialized = destination.read_text(encoding="utf-8")
    assert "export-only-placeholder" not in serialized
    assert "must-never-export" not in serialized
    assert "opaque-non-production-blob" not in serialized


def test_import_maps_groups_by_name_and_never_restores_sessions(tmp_path: Path) -> None:
    source_path = tmp_path / "source.json"
    with SQLiteRepository(tmp_path / "source.db") as source:
        source_group = source.save_group(Group(name="Builders", color="coral"))
        source.save_account(
            Account(
                username="PortableUser",
                group_id=source_group.id,
                alias="P",
                custom_fields={"role": "tester"},
                has_session=True,
            )
        )
        source.save_game(Game(place_id=98765, name="Portable game", is_favorite=True))
        MetadataTransfer(source).export_to(source_path)

    with SQLiteRepository(tmp_path / "target.db") as target:
        existing_group = target.save_group(Group(name="builders", color="existing"))
        report = MetadataTransfer(target).import_from(source_path)

        assert report.groups_imported == 0
        assert report.groups_ignored == 1
        assert report.accounts_imported == 1
        assert report.accounts_ignored == 0
        assert report.games_imported == 1
        account = target.get_account_by_username("portableuser")
        assert account is not None
        assert account.group_id == existing_group.id
        assert account.has_session is False
        assert target.load_protected_secret(account.id, "session") is None
        assert target.get_game_by_place_id(98765) is not None


def test_import_accepts_legacy_asteria_metadata_format(tmp_path: Path) -> None:
    source_path = tmp_path / "legacy-asteria.json"
    with SQLiteRepository(tmp_path / "source.db") as source:
        source.save_account(Account(username="LegacyPortable"))
        MetadataTransfer(source).export_to(source_path)

    document = json.loads(source_path.read_text(encoding="utf-8"))
    document["format"] = LEGACY_METADATA_TRANSFER_FORMAT
    source_path.write_text(json.dumps(document), encoding="utf-8")

    with SQLiteRepository(tmp_path / "target.db") as target:
        report = MetadataTransfer(target).import_from(source_path)

    assert report.accounts_imported == 1


def test_import_rejects_malformed_or_sensitive_files_without_writing(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{ definitely not JSON", encoding="utf-8")
    with SQLiteRepository(tmp_path / "target.db") as repository:
        transfer = MetadataTransfer(repository)
        with pytest.raises(MetadataTransferError):
            transfer.import_from(malformed)
        assert repository.list_accounts() == []

        sensitive = {
            "format": METADATA_TRANSFER_FORMAT,
            "version": METADATA_TRANSFER_VERSION,
            "manifest": {
                "exported_at": "2026-08-10T12:00:00+00:00",
                "entity_counts": {"groups": 0, "accounts": 1, "games": 0},
                "data_classification": "public_metadata_only",
                "content_sha256": "",
            },
            "groups": [],
            "accounts": [
                {
                    "username": "UnsafeImport",
                    "user_id": None,
                    "display_name": None,
                    "alias": "",
                    "description": "",
                    "group_name": None,
                    "avatar_url": None,
                    "status": "unknown",
                    "is_favorite": False,
                    "last_used_at": None,
                    "last_refreshed_at": None,
                    "saved_place_id": None,
                    "saved_job_id": None,
                    "custom_fields": {"cookie": "never-import"},
                    "metadata": {},
                }
            ],
            "games": [],
        }
        sensitive["manifest"]["content_sha256"] = _checksum(sensitive)  # type: ignore[index]
        sensitive_path = tmp_path / "sensitive.json"
        sensitive_path.write_text(json.dumps(sensitive), encoding="utf-8")
        with pytest.raises(MetadataTransferError, match="credential-like"):
            transfer.import_from(sensitive_path)
        assert repository.list_accounts() == []
