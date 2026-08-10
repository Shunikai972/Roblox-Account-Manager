"""Credential-free JSON import and export for portable Astro metadata.

This module deliberately transfers a small, explicit public-data schema rather
than serialising the SQLite database.  The database also contains local audit
data and DPAPI-protected vault blobs; neither belongs in a portable file.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.backend.models.domain import Account, Game, Group
from app.backend.repositories.sqlite_repository import RepositoryError, SQLiteRepository
from app.backend.security.redaction import is_sensitive_key, redact_text


METADATA_TRANSFER_FORMAT = "astro-account-manager.metadata"
# Files from the immediately preceding product name use the same schema and
# checksum rules.  Accept them explicitly so a rebrand never strands an
# otherwise valid public-metadata export.
LEGACY_METADATA_TRANSFER_FORMAT = "asteria-account-manager.metadata"
ACCEPTED_METADATA_TRANSFER_FORMATS = frozenset(
    {METADATA_TRANSFER_FORMAT, LEGACY_METADATA_TRANSFER_FORMAT}
)
METADATA_TRANSFER_VERSION = 1
MAX_TRANSFER_BYTES = 8 * 1024 * 1024
MAX_ENTITIES_PER_COLLECTION = 10_000
MAX_JSON_DEPTH = 12

_TOP_LEVEL_FIELDS = frozenset({"format", "version", "manifest", "groups", "accounts", "games"})
_MANIFEST_FIELDS = frozenset({"exported_at", "entity_counts", "data_classification", "content_sha256"})
_GROUP_FIELDS = frozenset({"name", "color", "icon", "sort_order", "is_favorite", "is_collapsed"})
_ACCOUNT_FIELDS = frozenset(
    {
        "username",
        "user_id",
        "display_name",
        "alias",
        "description",
        "group_name",
        "avatar_url",
        "status",
        "is_favorite",
        "last_used_at",
        "last_refreshed_at",
        "saved_place_id",
        "saved_job_id",
        "custom_fields",
        "metadata",
    }
)
_GAME_FIELDS = frozenset(
    {
        "place_id",
        "universe_id",
        "name",
        "description",
        "creator_name",
        "creator_id",
        "icon_url",
        "playing",
        "max_players",
        "is_favorite",
        "last_used_at",
        "metadata",
    }
)


class MetadataTransferError(RuntimeError):
    """A portable-metadata file was invalid or could not be written safely."""


@dataclass(frozen=True, slots=True)
class MetadataImportReport:
    """Counts and non-sensitive warnings produced by :meth:`import_from`."""

    source_path: Path
    groups_imported: int = 0
    groups_ignored: int = 0
    accounts_imported: int = 0
    accounts_ignored: int = 0
    games_imported: int = 0
    games_ignored: int = 0
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": str(self.source_path),
            "groups": {"imported": self.groups_imported, "ignored": self.groups_ignored},
            "accounts": {"imported": self.accounts_imported, "ignored": self.accounts_ignored},
            "games": {"imported": self.games_imported, "ignored": self.games_ignored},
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class _ParsedTransfer:
    groups: tuple[dict[str, Any], ...]
    accounts: tuple[dict[str, Any], ...]
    games: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]


class MetadataTransfer:
    """Export and import only explicitly allowlisted public metadata.

    ``export_to`` never reads ``secret_vault_entries`` and omits the public
    ``has_session`` marker as well.  ``import_from`` has no vault dependency,
    rejects credential-looking keys before writing anything, and always writes
    accounts with ``has_session=False``.
    """

    def __init__(self, repository: SQLiteRepository) -> None:
        self.repository = repository

    def export_to(self, path: str | Path, *, overwrite: bool = False) -> Path:
        """Write a versioned, checksummed public-metadata JSON document.

        The target is replaced atomically only after the complete JSON payload
        has reached a temporary file in the target directory.  Existing files
        require the explicit ``overwrite=True`` acknowledgement.
        """

        destination = _resolve_destination(path)
        repository_groups = self.repository.list_groups()
        groups = [_export_group(group) for group in repository_groups]
        groups_by_id = {group.id: group.name for group in repository_groups}
        accounts = [_export_account(account, groups_by_id) for account in self.repository.list_accounts()]
        games = [_export_game(game) for game in self.repository.list_games()]
        content = {"groups": groups, "accounts": accounts, "games": games}
        document = {
            "format": METADATA_TRANSFER_FORMAT,
            "version": METADATA_TRANSFER_VERSION,
            "manifest": {
                "exported_at": _utc_now(),
                "entity_counts": {key: len(value) for key, value in content.items()},
                "data_classification": "public_metadata_only",
                "content_sha256": _content_checksum(content),
            },
            **content,
        }
        encoded = _canonical_json(document).encode("utf-8") + b"\n"
        if len(encoded) > MAX_TRANSFER_BYTES:
            raise MetadataTransferError("Metadata export exceeds the portable file size limit.")
        _write_atomically(destination, encoded, overwrite=overwrite)
        return destination

    def import_from(self, path: str | Path) -> MetadataImportReport:
        """Validate and best-effort import a credential-free metadata file.

        Existing groups are mapped by case-insensitive name.  Existing accounts
        (username) and games (place ID) are never overwritten; they are counted
        as ignored.  An invalid document causes no database write at all.
        """

        source = _resolve_source(path)
        document = _read_document(source)
        parsed = _validate_document(document)
        warnings = list(parsed.warnings)
        counts = {
            "groups_imported": 0,
            "groups_ignored": 0,
            "accounts_imported": 0,
            "accounts_ignored": 0,
            "games_imported": 0,
            "games_ignored": 0,
        }

        # The entire import uses a single outer transaction.  Repository save
        # calls use nested savepoints, so an individual conflict can be skipped
        # while the rest of the validated transfer remains atomic as a unit.
        with self.repository.transaction():
            groups_by_name = {
                _group_key(group.name): group
                for group in self.repository.list_groups()
            }
            imported_group_names: set[str] = set()
            for index, item in enumerate(parsed.groups):
                group_key = _group_key(item["name"])
                if group_key in imported_group_names:
                    counts["groups_ignored"] += 1
                    warnings.append(f"Duplicate group entry at index {index + 1} was ignored.")
                    continue
                if group_key in groups_by_name:
                    counts["groups_ignored"] += 1
                    continue
                try:
                    group = self.repository.save_group(
                        Group(
                            name=item["name"],
                            color=item["color"],
                            icon=item["icon"],
                            sort_order=item["sort_order"],
                            is_favorite=item["is_favorite"],
                            is_collapsed=item["is_collapsed"],
                        )
                    )
                except RepositoryError:
                    counts["groups_ignored"] += 1
                    warnings.append(f"Group entry at index {index + 1} could not be imported.")
                    continue
                groups_by_name[group_key] = group
                imported_group_names.add(group_key)
                counts["groups_imported"] += 1

            imported_usernames: set[str] = set()
            for index, item in enumerate(parsed.accounts):
                username_key = item["username"].casefold()
                if username_key in imported_usernames or self.repository.get_account_by_username(item["username"]):
                    counts["accounts_ignored"] += 1
                    if username_key in imported_usernames:
                        warnings.append(f"Duplicate account entry at index {index + 1} was ignored.")
                    continue
                imported_usernames.add(username_key)
                group = groups_by_name.get(_group_key(item["group_name"])) if item["group_name"] else None
                if item["group_name"] and group is None:
                    warnings.append(
                        f"Account entry at index {index + 1} references an unknown group and was imported ungrouped."
                    )
                try:
                    self.repository.save_account(
                        Account(
                            username=item["username"],
                            user_id=item["user_id"],
                            display_name=item["display_name"],
                            alias=item["alias"],
                            description=item["description"],
                            group_id=group.id if group else None,
                            avatar_url=item["avatar_url"],
                            status=item["status"],
                            is_favorite=item["is_favorite"],
                            last_used_at=item["last_used_at"],
                            last_refreshed_at=item["last_refreshed_at"],
                            saved_place_id=item["saved_place_id"],
                            saved_job_id=item["saved_job_id"],
                            custom_fields=item["custom_fields"],
                            metadata=item["metadata"],
                            has_session=False,
                        )
                    )
                except RepositoryError:
                    counts["accounts_ignored"] += 1
                    warnings.append(f"Account entry at index {index + 1} could not be imported.")
                    continue
                counts["accounts_imported"] += 1

            imported_places: set[int] = set()
            for index, item in enumerate(parsed.games):
                place_id = item["place_id"]
                if place_id in imported_places or self.repository.get_game_by_place_id(place_id):
                    counts["games_ignored"] += 1
                    if place_id in imported_places:
                        warnings.append(f"Duplicate game entry at index {index + 1} was ignored.")
                    continue
                imported_places.add(place_id)
                try:
                    self.repository.save_game(
                        Game(
                            place_id=place_id,
                            universe_id=item["universe_id"],
                            name=item["name"],
                            description=item["description"],
                            creator_name=item["creator_name"],
                            creator_id=item["creator_id"],
                            icon_url=item["icon_url"],
                            playing=item["playing"],
                            max_players=item["max_players"],
                            is_favorite=item["is_favorite"],
                            last_used_at=item["last_used_at"],
                            metadata=item["metadata"],
                        )
                    )
                except RepositoryError:
                    counts["games_ignored"] += 1
                    warnings.append(f"Game entry at index {index + 1} could not be imported.")
                    continue
                counts["games_imported"] += 1

        return MetadataImportReport(source_path=source, warnings=tuple(warnings), **counts)


def _export_group(group: Group) -> dict[str, Any]:
    return {
        "name": _safe_text(group.name, maximum=120, default=""),
        "color": _safe_text(group.color, maximum=64, default="#7c5cff"),
        "icon": _safe_text(group.icon, maximum=128, default="folder"),
        "sort_order": _safe_int(group.sort_order, default=0),
        "is_favorite": bool(group.is_favorite),
        "is_collapsed": bool(group.is_collapsed),
    }


def _export_account(account: Account, groups_by_id: Mapping[str, str]) -> dict[str, Any]:
    # OAuth link state is meaningful only beside the local DPAPI grant.  A
    # portable export has no grant, so copying this marker would falsely imply
    # that an imported account is still connected.
    metadata = dict(account.metadata)
    metadata.pop("oauth", None)
    return {
        "username": _safe_text(account.username, maximum=120, default=""),
        "user_id": _safe_optional_int(account.user_id),
        "display_name": _safe_optional_text(account.display_name, maximum=120),
        "alias": _safe_text(account.alias, maximum=120, default=""),
        "description": _safe_text(account.description, maximum=5000, default=""),
        "group_name": _safe_optional_text(groups_by_id.get(account.group_id or ""), maximum=120),
        "avatar_url": _safe_optional_text(account.avatar_url, maximum=2048),
        "status": _safe_text(account.status, maximum=40, default="unknown"),
        "is_favorite": bool(account.is_favorite),
        "last_used_at": _safe_optional_text(account.last_used_at, maximum=128),
        "last_refreshed_at": _safe_optional_text(account.last_refreshed_at, maximum=128),
        "saved_place_id": _safe_optional_int(account.saved_place_id),
        "saved_job_id": _safe_optional_text(account.saved_job_id, maximum=256),
        "custom_fields": _sanitize_public_value(account.custom_fields)[0],
        "metadata": _sanitize_public_value(metadata)[0],
    }


def _export_game(game: Game) -> dict[str, Any]:
    return {
        "place_id": _safe_int(game.place_id, default=0),
        "universe_id": _safe_optional_int(game.universe_id),
        "name": _safe_text(game.name, maximum=300, default=""),
        "description": _safe_text(game.description, maximum=10000, default=""),
        "creator_name": _safe_optional_text(game.creator_name, maximum=300),
        "creator_id": _safe_optional_int(game.creator_id),
        "icon_url": _safe_optional_text(game.icon_url, maximum=2048),
        "playing": _safe_optional_int(game.playing),
        "max_players": _safe_optional_int(game.max_players),
        "is_favorite": bool(game.is_favorite),
        "last_used_at": _safe_optional_text(game.last_used_at, maximum=128),
        "metadata": _sanitize_public_value(game.metadata)[0],
    }


def _read_document(source: Path) -> Any:
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise MetadataTransferError("Metadata transfer file could not be inspected.") from exc
    if size > MAX_TRANSFER_BYTES:
        raise MetadataTransferError("Metadata transfer file exceeds the supported size limit.")
    try:
        with source.open("rb") as stream:
            raw = stream.read(MAX_TRANSFER_BYTES + 1)
    except OSError as exc:
        raise MetadataTransferError("Metadata transfer file could not be read.") from exc
    if len(raw) > MAX_TRANSFER_BYTES:
        raise MetadataTransferError("Metadata transfer file exceeds the supported size limit.")
    try:
        return json.loads(raw.decode("utf-8"), parse_constant=_reject_non_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise MetadataTransferError("Metadata transfer file is not valid UTF-8 JSON.") from exc


def _validate_document(document: Any) -> _ParsedTransfer:
    if not isinstance(document, Mapping):
        raise MetadataTransferError("Metadata transfer root must be an object.")
    _require_exact_keys(document, _TOP_LEVEL_FIELDS, "transfer root")
    if document.get("format") not in ACCEPTED_METADATA_TRANSFER_FORMATS:
        raise MetadataTransferError("Unsupported metadata transfer format.")
    if document.get("version") != METADATA_TRANSFER_VERSION or isinstance(document.get("version"), bool):
        raise MetadataTransferError("Unsupported metadata transfer version.")

    manifest = document.get("manifest")
    if not isinstance(manifest, Mapping):
        raise MetadataTransferError("Metadata transfer manifest must be an object.")
    _require_exact_keys(manifest, _MANIFEST_FIELDS, "transfer manifest")
    if manifest.get("data_classification") != "public_metadata_only":
        raise MetadataTransferError("Metadata transfer is not marked as public metadata only.")
    _validate_timestamp(manifest.get("exported_at"))

    # Check the bytes' canonical JSON representation before adding internal
    # validation markers such as ``_redacted_text`` below.
    raw_content = {key: document.get(key) for key in ("groups", "accounts", "games")}
    checksum = manifest.get("content_sha256")
    if not isinstance(checksum, str) or len(checksum) != 64 or checksum != _content_checksum(raw_content):
        raise MetadataTransferError("Metadata transfer checksum does not match its data.")

    groups = _validate_collection(document.get("groups"), _GROUP_FIELDS, "group", _normalise_group)
    accounts = _validate_collection(document.get("accounts"), _ACCOUNT_FIELDS, "account", _normalise_account)
    games = _validate_collection(document.get("games"), _GAME_FIELDS, "game", _normalise_game)
    content = {"groups": groups, "accounts": accounts, "games": games}
    expected_counts = manifest.get("entity_counts")
    if not isinstance(expected_counts, Mapping) or set(expected_counts) != {"groups", "accounts", "games"}:
        raise MetadataTransferError("Metadata transfer manifest has invalid entity counts.")
    for key, values in content.items():
        count = expected_counts.get(key)
        if not isinstance(count, int) or isinstance(count, bool) or count != len(values):
            raise MetadataTransferError("Metadata transfer manifest count does not match its data.")
    warnings: list[str] = []
    for collection in content.values():
        for item in collection:
            if item.pop("_redacted_text", False):
                warnings.append("Credential-like text was redacted from imported public metadata.")
    return _ParsedTransfer(
        groups=tuple(groups),
        accounts=tuple(accounts),
        games=tuple(games),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _validate_collection(
    value: Any,
    allowed_fields: frozenset[str],
    label: str,
    normaliser: Any,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise MetadataTransferError(f"Metadata transfer {label}s must be an array.")
    if len(value) > MAX_ENTITIES_PER_COLLECTION:
        raise MetadataTransferError(f"Metadata transfer contains too many {label} entries.")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise MetadataTransferError(f"Each metadata transfer {label} must be an object.")
        _require_exact_keys(item, allowed_fields, f"{label} entry")
        _assert_no_sensitive_keys(item)
        result.append(normaliser(item))
    return result


def _normalise_group(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": _required_text(item.get("name"), "group name", maximum=120),
        "color": _required_text(item.get("color"), "group color", maximum=64),
        "icon": _required_text(item.get("icon"), "group icon", maximum=128),
        "sort_order": _integer(item.get("sort_order"), "group sort order", default=0),
        "is_favorite": _boolean(item.get("is_favorite"), "group favorite"),
        "is_collapsed": _boolean(item.get("is_collapsed"), "group collapsed"),
    }


def _normalise_account(item: Mapping[str, Any]) -> dict[str, Any]:
    custom_fields, fields_redacted = _normalise_public_mapping(item.get("custom_fields"), "account custom fields")
    metadata, metadata_redacted = _normalise_public_mapping(item.get("metadata"), "account metadata")
    # Backward-compatible handling for exports created before OAuth linking was
    # added: the identity can be imported, but the link marker cannot survive
    # without its local DPAPI grant.
    metadata.pop("oauth", None)
    return {
        "username": _required_text(item.get("username"), "account username", maximum=120),
        "user_id": _optional_integer(item.get("user_id"), "account user id"),
        "display_name": _optional_text(item.get("display_name"), maximum=120),
        "alias": _required_text(item.get("alias"), "account alias", maximum=120, allow_empty=True),
        "description": _required_text(item.get("description"), "account description", maximum=5000, allow_empty=True),
        "group_name": _optional_text(item.get("group_name"), maximum=120),
        "avatar_url": _optional_text(item.get("avatar_url"), maximum=2048),
        "status": _required_text(item.get("status"), "account status", maximum=40),
        "is_favorite": _boolean(item.get("is_favorite"), "account favorite"),
        "last_used_at": _optional_text(item.get("last_used_at"), maximum=128),
        "last_refreshed_at": _optional_text(item.get("last_refreshed_at"), maximum=128),
        "saved_place_id": _optional_positive_integer(item.get("saved_place_id"), "saved place id"),
        "saved_job_id": _optional_text(item.get("saved_job_id"), maximum=256),
        "custom_fields": custom_fields,
        "metadata": metadata,
        "_redacted_text": fields_redacted or metadata_redacted,
    }


def _normalise_game(item: Mapping[str, Any]) -> dict[str, Any]:
    metadata, metadata_redacted = _normalise_public_mapping(item.get("metadata"), "game metadata")
    return {
        "place_id": _positive_integer(item.get("place_id"), "game place id"),
        "universe_id": _optional_integer(item.get("universe_id"), "game universe id"),
        "name": _required_text(item.get("name"), "game name", maximum=300),
        "description": _required_text(item.get("description"), "game description", maximum=10000, allow_empty=True),
        "creator_name": _optional_text(item.get("creator_name"), maximum=300),
        "creator_id": _optional_integer(item.get("creator_id"), "game creator id"),
        "icon_url": _optional_text(item.get("icon_url"), maximum=2048),
        "playing": _optional_integer(item.get("playing"), "game player count"),
        "max_players": _optional_integer(item.get("max_players"), "game maximum player count"),
        "is_favorite": _boolean(item.get("is_favorite"), "game favorite"),
        "last_used_at": _optional_text(item.get("last_used_at"), maximum=128),
        "metadata": metadata,
        "_redacted_text": metadata_redacted,
    }


def _normalise_public_mapping(value: Any, label: str) -> tuple[dict[str, Any], bool]:
    if not isinstance(value, Mapping):
        raise MetadataTransferError(f"{label.capitalize()} must be an object.")
    cleaned, was_redacted = _sanitize_public_value(value, reject_sensitive=True)
    assert isinstance(cleaned, dict)
    return cleaned, was_redacted


def _sanitize_public_value(value: Any, *, reject_sensitive: bool = False, depth: int = 0) -> tuple[Any, bool]:
    if depth > MAX_JSON_DEPTH:
        raise MetadataTransferError("Metadata transfer contains data nested too deeply.")
    if isinstance(value, Mapping):
        if len(value) > 1_000:
            raise MetadataTransferError("Metadata transfer contains an oversized metadata object.")
        result: dict[str, Any] = {}
        redacted = False
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 200:
                raise MetadataTransferError("Metadata transfer contains an invalid metadata key.")
            if is_sensitive_key(key):
                if reject_sensitive:
                    raise MetadataTransferError("Metadata transfer contains a credential-like field.")
                continue
            normalized, changed = _sanitize_public_value(item, reject_sensitive=reject_sensitive, depth=depth + 1)
            result[key] = normalized
            redacted = redacted or changed
        return result, redacted
    if isinstance(value, list):
        if len(value) > 1_000:
            raise MetadataTransferError("Metadata transfer contains an oversized metadata list.")
        result_list: list[Any] = []
        redacted = False
        for item in value:
            normalized, changed = _sanitize_public_value(item, reject_sensitive=reject_sensitive, depth=depth + 1)
            result_list.append(normalized)
            redacted = redacted or changed
        return result_list, redacted
    if value is None or isinstance(value, bool):
        return value, False
    if isinstance(value, int):
        if abs(value) > 9_223_372_036_854_775_807:
            raise MetadataTransferError("Metadata transfer integer is out of range.")
        return value, False
    if isinstance(value, float):
        if not math.isfinite(value):
            raise MetadataTransferError("Metadata transfer contains an invalid number.")
        return value, False
    if isinstance(value, str):
        if len(value) > 10_000:
            raise MetadataTransferError("Metadata transfer text value exceeds the size limit.")
        redacted = redact_text(value)
        return redacted, redacted != value
    raise MetadataTransferError("Metadata transfer contains an unsupported value type.")


def _assert_no_sensitive_keys(value: Mapping[str, Any]) -> None:
    for key in value:
        if is_sensitive_key(key):
            raise MetadataTransferError("Metadata transfer contains a credential-like field.")


def _require_exact_keys(value: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    if set(value) != expected:
        raise MetadataTransferError(f"Metadata transfer {label} has unsupported or missing fields.")


def _required_text(value: Any, label: str, *, maximum: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise MetadataTransferError(f"Metadata transfer {label} must be text.")
    if len(value) > maximum:
        raise MetadataTransferError(f"Metadata transfer {label} exceeds its length limit.")
    normalized = redact_text(value).strip()
    if not normalized and not allow_empty:
        raise MetadataTransferError(f"Metadata transfer {label} is required.")
    return normalized


def _optional_text(value: Any, *, maximum: int) -> str | None:
    if value is None:
        return None
    return _required_text(value, "text value", maximum=maximum, allow_empty=True)


def _integer(value: Any, label: str, *, default: int | None = None) -> int | None:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or abs(value) > 9_223_372_036_854_775_807:
        raise MetadataTransferError(f"Metadata transfer {label} must be an integer.")
    return value


def _positive_integer(value: Any, label: str) -> int:
    number = _integer(value, label)
    if number is None or number <= 0:
        raise MetadataTransferError(f"Metadata transfer {label} must be positive.")
    return number


def _optional_positive_integer(value: Any, label: str) -> int | None:
    if value is None:
        return None
    return _positive_integer(value, label)


def _optional_integer(value: Any, label: str) -> int | None:
    return _integer(value, label)


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise MetadataTransferError(f"Metadata transfer {label} must be true or false.")
    return value


def _validate_timestamp(value: Any) -> None:
    if not isinstance(value, str) or len(value) > 128:
        raise MetadataTransferError("Metadata transfer manifest timestamp is invalid.")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MetadataTransferError("Metadata transfer manifest timestamp is invalid.") from exc


def _safe_text(value: Any, *, maximum: int, default: str) -> str:
    if not isinstance(value, str):
        return default
    return redact_text(value[:maximum])


def _safe_optional_text(value: Any, *, maximum: int) -> str | None:
    return _safe_text(value, maximum=maximum, default="") if isinstance(value, str) else None


def _safe_int(value: Any, *, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _safe_optional_int(value: Any) -> int | None:
    return _safe_int(value, default=0) if isinstance(value, int) and not isinstance(value, bool) else None


def _group_key(name: str) -> str:
    return name.strip().casefold()


def _content_checksum(content: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(content).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _resolve_destination(path: str | Path) -> Path:
    destination = Path(path).expanduser()
    if not destination.name:
        raise MetadataTransferError("Metadata export destination must be a file path.")
    return destination.resolve()


def _resolve_source(path: str | Path) -> Path:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise MetadataTransferError("Metadata transfer source is not a regular file.")
    return source


def _write_atomically(destination: Path, payload: bytes, *, overwrite: bool) -> None:
    if destination.exists() and not overwrite:
        raise MetadataTransferError("Metadata export destination already exists; overwrite was not confirmed.")
    temporary: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if destination.exists() and not overwrite:
            raise MetadataTransferError("Metadata export destination was created during export.")
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    except MetadataTransferError:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    except OSError as exc:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise MetadataTransferError("Metadata export could not be written atomically.") from exc


def _fsync_directory(directory: Path) -> None:
    """Best-effort directory sync; Windows does not expose directory handles."""

    if os.name == "nt":
        return
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _reject_non_json_constant(value: str) -> None:
    raise ValueError(f"Non-JSON value is not accepted: {value}")


__all__ = [
    "ACCEPTED_METADATA_TRANSFER_FORMATS",
    "LEGACY_METADATA_TRANSFER_FORMAT",
    "MAX_TRANSFER_BYTES",
    "METADATA_TRANSFER_FORMAT",
    "METADATA_TRANSFER_VERSION",
    "MetadataImportReport",
    "MetadataTransfer",
    "MetadataTransferError",
]
