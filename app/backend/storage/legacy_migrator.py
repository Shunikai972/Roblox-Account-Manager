"""Non-destructive migration of legacy Roblox Account Manager data.

The migrator never runs automatically against an account store.  It first makes
an immutable backup, then requires an explicit `import_account_metadata=True`
opt-in before it decrypts or parses ``AccountData.json``.  Sessions and saved
passwords remain excluded unless separately confirmed for DPAPI-vault import.
"""

from __future__ import annotations

from configparser import ConfigParser, Error as ConfigError
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit, urlunsplit

from app.backend.models.domain import Account, Game, Group, legacy_group_order_key
from app.backend.repositories.sqlite_repository import RepositoryError, SQLiteRepository
from app.backend.security.dpapi import CurrentUserDPAPI, DPAPIError, DPAPIUnavailableError
from app.backend.security.redaction import is_sensitive_key
from app.backend.security.vault import DPAPISecretVault, SecretVaultError

from .backups import BackupError, BackupRecord, VersionedBackupManager


# Exact byte identifiers used by the historical 3.7.x serializer.  Their use
# here is detection/compatibility only; no payload is inspected until explicit
# account-metadata import has been requested.
LEGACY_RAM_HEADER = b"Roblox Account Manager created by ic3w0lf22 @ github.com ......."
LEGACY_DPAPI_ENTROPY = (
    b"ROBLOX ACCOUNT MANAGER | :) | BROUGHT TO YOU BUY ic3w0lf"
)
_DPAPI_BLOB_PREFIX = bytes.fromhex("01000000d08c9ddf0115d1118c7a00c04fc297eb")
_ACCOUNT_DATA_NAME = "AccountData.json"
_ACCOUNT_BACKUP_NAME = "AccountData.json.backup"
_LEGACY_AUXILIARY_FILES = ("RAMSettings.ini", "RAMTheme.ini", "RecentGames.json")
_MAX_LEGACY_INI_BYTES = 1_000_000

# ``RAMSettings.ini`` contains several controls whose historical behavior was
# tied to browser-session handling, client patching, remote control, or forced
# process termination.  The migration keeps the ordinary local preferences,
# but it never resurrects those controls merely because their old checkbox was
# enabled.  Sensitive keys are also filtered separately by ``is_sensitive_key``.
_UNSAFE_LEGACY_GENERAL_KEYS = frozenset(
    {
        "enablemultirbx",
        "autocookierefresh",
        "usecefsharpbrowser",
        "unlockfps",
        "maxfpsvalue",
        "customclientsettings",
        "nopechakey",
    }
)
_SAFE_LEGACY_DEVELOPER_KEYS = frozenset({"devmode"})
_SAFE_LEGACY_WEBSERVER_KEYS = frozenset({"webserverport"})
_SAFE_LEGACY_WATCHER_KEYS = frozenset(
    {
        "enabled",
        "scaninterval",
        "expectedwindowtitle",
        "savewindowpositions",
        "ignoreexistingprocesses",
    }
)
_THEME_COLOR_KEYS = frozenset(
    {
        "accountsbg",
        "accountsfg",
        "buttonsbg",
        "buttonsfg",
        "buttonsbc",
        "formsbg",
        "formsfg",
        "textboxesbg",
        "textboxesfg",
        "textboxesbc",
        "labelsbc",
        "labelsfc",
    }
)
_THEME_BOOLEAN_KEYS = frozenset(
    {"darktopbar", "showheaders", "labelstransparent", "lightimages"}
)
_THEME_BUTTON_STYLES = frozenset({"standard", "flat", "popup", "system"})
_CANONICAL_LEGACY_THEME_SECTIONS = frozenset(
    {"robloxaccountmanager", "rbxaltmanager"}
)


class LegacyFormat(str, Enum):
    MISSING = "missing"
    EMPTY = "empty"
    PLAINTEXT_JSON = "plaintext_json"
    DPAPI = "dpapi"
    PASSWORD_ENCRYPTED = "password_encrypted"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class LegacyDetection:
    """A header-only classification; it contains no legacy payload values."""

    path: Path
    format: LegacyFormat
    size_bytes: int
    fingerprint: str | None = None

    @property
    def requires_password(self) -> bool:
        return self.format is LegacyFormat.PASSWORD_ENCRYPTED

    @property
    def requires_windows_user(self) -> bool:
        return self.format is LegacyFormat.DPAPI

    @property
    def can_import_metadata(self) -> bool:
        return self.format in {
            LegacyFormat.PLAINTEXT_JSON,
            LegacyFormat.DPAPI,
            LegacyFormat.PASSWORD_ENCRYPTED,
        }


@dataclass(frozen=True, slots=True)
class MigrationReport:
    """Safe migration result that intentionally contains counts, never secrets."""

    source_directory: Path
    detections: tuple[LegacyDetection, ...]
    backup_records: tuple[BackupRecord, ...] = ()
    settings_imported: int = 0
    games_imported: int = 0
    groups_imported: int = 0
    accounts_imported: int = 0
    sessions_imported: int = 0
    saved_passwords_imported: int = 0
    account_metadata_imported: bool = False
    secret_import_requires_consent: bool = False
    warnings: tuple[str, ...] = ()

    @property
    def account_data_detected(self) -> bool:
        return any(item.format not in {LegacyFormat.MISSING, LegacyFormat.EMPTY} for item in self.detections)


class LegacyMigrationError(RuntimeError):
    """A migration failure that never embeds legacy account or secret content."""


class LegacyDataMigrator:
    """Import safe legacy metadata only after a user-visible confirmation flow.

    A UI should call :meth:`scan` to show classifications first.  It can then
    call :meth:`migrate` with account metadata consent; a password is requested
    only for the password-encrypted format.  The caller must also explicitly
    confirm any import of session or saved-password material.
    """

    def __init__(
        self,
        repository: SQLiteRepository,
        backup_manager: VersionedBackupManager,
        *,
        dpapi: CurrentUserDPAPI | None = None,
        vault: DPAPISecretVault | None = None,
    ) -> None:
        self.repository = repository
        self.backup_manager = backup_manager
        self.dpapi = dpapi or CurrentUserDPAPI()
        self.vault = vault or DPAPISecretVault(repository, self.dpapi)

    def scan(self, source_directory: str | Path) -> tuple[LegacyDetection, ...]:
        """Classify account files from short headers without decrypting/parsing."""

        source = _resolve_legacy_directory(source_directory)
        return tuple(
            self.detect_account_data(source / filename)
            for filename in (_ACCOUNT_DATA_NAME, _ACCOUNT_BACKUP_NAME)
        )

    def detect_account_data(self, path: str | Path) -> LegacyDetection:
        """Classify a legacy account store using only its identifier/header bytes."""

        candidate = Path(path).expanduser()
        if not candidate.is_file():
            return LegacyDetection(candidate, LegacyFormat.MISSING, 0, None)
        try:
            size = candidate.stat().st_size
            if size == 0:
                return LegacyDetection(candidate, LegacyFormat.EMPTY, 0, _header_fingerprint(b"", 0))
            # A small prefix is ample for the historic header/BOM while keeping
            # consent-free scanning strictly header-only.
            with candidate.open("rb") as stream:
                header = stream.read(max(512, len(LEGACY_RAM_HEADER), len(_DPAPI_BLOB_PREFIX)))
            if header.startswith(LEGACY_RAM_HEADER):
                detected = LegacyFormat.PASSWORD_ENCRYPTED
            elif header.startswith(_DPAPI_BLOB_PREFIX):
                detected = LegacyFormat.DPAPI
            elif header.lstrip(b"\xef\xbb\xbf\x20\t\r\n").startswith((b"[", b"{")):
                detected = LegacyFormat.PLAINTEXT_JSON
            else:
                detected = LegacyFormat.UNKNOWN
            return LegacyDetection(candidate, detected, size, _header_fingerprint(header, size))
        except OSError as exc:
            raise LegacyMigrationError("Legacy account data could not be inspected safely.") from exc

    def migrate(
        self,
        source_directory: str | Path,
        *,
        import_account_metadata: bool = False,
        include_sessions: bool = False,
        include_saved_passwords: bool = False,
        confirm_secret_import: bool = False,
        password: str | bytes | bytearray | memoryview | None = None,
    ) -> MigrationReport:
        """Run the explicit migration without modifying any legacy file.

        ``include_sessions`` defaults to ``False`` by design.  Setting either
        secret flag without ``confirm_secret_import=True`` never imports a
        secret; the report tells the caller that confirmation is still needed.
        """

        source = _resolve_legacy_directory(source_directory)
        detections = self.scan(source)
        backup_records, warnings = self._backup_legacy_files(source)
        counts = {
            "settings_imported": 0,
            "games_imported": 0,
            "groups_imported": 0,
            "accounts_imported": 0,
            "sessions_imported": 0,
            "saved_passwords_imported": 0,
        }

        with self.repository.transaction():
            counts["settings_imported"] = self._import_ini_files(source)
            counts["games_imported"] = self._import_recent_games(source / "RecentGames.json")
            # RAM's list order is its only recency information: the newest
            # game is appended last by ``AddRecentGame``.  The importer turns
            # that order into local timestamps and then applies the migrated
            # MaxRecentGames setting exactly once, after every row is present.
            if counts["games_imported"]:
                self._prune_imported_recent_games()

            metadata_imported = False
            account_warning: str | None = None
            if import_account_metadata:
                account_file = _select_account_file(detections)
                if account_file is None:
                    account_warning = "No supported legacy account file was available for metadata import."
                else:
                    try:
                        payload = self._load_account_payload(account_file, password=password)
                        result = self._import_account_payload(
                            payload,
                            include_sessions=include_sessions and confirm_secret_import,
                            include_saved_passwords=include_saved_passwords and confirm_secret_import,
                        )
                        counts.update(result)
                        metadata_imported = True
                    except _PasswordRequired:
                        account_warning = "This legacy account file is password-encrypted; a password is required."
                    except _PasswordRejected:
                        account_warning = "The legacy account password could not unlock the data."
                    except DPAPIUnavailableError:
                        account_warning = "Windows CurrentUser DPAPI is unavailable for this account file."
                    except DPAPIError:
                        account_warning = "The legacy DPAPI data could not be unlocked for the active Windows user."
                    except LegacyMigrationError:
                        account_warning = "Legacy account metadata could not be imported safely."
            else:
                account_warning = (
                    "Account metadata was not imported. Explicit consent is required before legacy "
                    "AccountData is decrypted or parsed."
                )

            if account_warning:
                warnings.append(account_warning)
            secret_consent_needed = (include_sessions or include_saved_passwords) and not confirm_secret_import
            if secret_consent_needed:
                warnings.append("Secret import was requested but requires a separate explicit confirmation.")

            fingerprint = _directory_fingerprint(source, detections)
            self.repository.record_migration_run(
                source_path=str(source),
                source_fingerprint=fingerprint,
                status="completed" if metadata_imported or not import_account_metadata else "needs_attention",
                details={
                    "account_format": _primary_format(detections).value,
                    "account_metadata_imported": metadata_imported,
                    "settings_imported": counts["settings_imported"],
                    "games_imported": counts["games_imported"],
                    "accounts_imported": counts["accounts_imported"],
                    "sessions_imported": counts["sessions_imported"],
                    "saved_passwords_imported": counts["saved_passwords_imported"],
                    "secret_import_requires_consent": secret_consent_needed,
                },
                completed=metadata_imported or not import_account_metadata,
            )

        return MigrationReport(
            source_directory=source,
            detections=detections,
            backup_records=tuple(backup_records),
            account_metadata_imported=metadata_imported,
            secret_import_requires_consent=secret_consent_needed,
            warnings=tuple(warnings),
            **counts,
        )

    def _backup_legacy_files(self, source: Path) -> tuple[list[BackupRecord], list[str]]:
        records: list[BackupRecord] = []
        warnings: list[str] = []
        for filename in (_ACCOUNT_DATA_NAME, _ACCOUNT_BACKUP_NAME, *_LEGACY_AUXILIARY_FILES):
            candidate = source / filename
            if not candidate.is_file() or candidate.stat().st_size == 0:
                continue
            try:
                records.append(
                    self.backup_manager.create_backup(
                        candidate,
                        label="legacy migration preflight",
                        metadata={"source_kind": "legacy", "filename": candidate.name},
                    )
                )
            except (BackupError, OSError):
                # A migration can still import non-secret settings if a backup
                # destination is temporarily unavailable, but never parses
                # AccountData without an intact preflight backup.
                if candidate.name in {_ACCOUNT_DATA_NAME, _ACCOUNT_BACKUP_NAME}:
                    raise LegacyMigrationError("Could not create the required legacy account-data backup.")
                warnings.append(f"A backup for {candidate.name} could not be created.")
        return records, warnings

    def _import_ini_files(self, source: Path) -> int:
        """Port validated local preferences and retain their safe legacy form.

        The previous migration treated both INI files as untyped bags of text.
        That preserved some values under ``legacy.*`` but did not actually
        apply the compatible preferences in the new architecture.  We now map
        the small, well-defined overlap while retaining a sanitized legacy
        record for fields that do not yet have a visual equivalent.
        """

        imported = 0
        settings = _read_legacy_ini(source / "RAMSettings.ini")
        if settings is not None:
            imported += self._import_legacy_settings(settings)

        theme = _read_legacy_ini(source / "RAMTheme.ini")
        if theme is not None:
            imported += self._import_legacy_theme(theme)
        return imported

    def _import_legacy_settings(self, parser: ConfigParser) -> int:
        imported = 0
        for section in parser.sections():
            normalized_section = _legacy_identifier(section)
            for key, raw_value in parser.items(section):
                normalized_key = _legacy_identifier(key)
                if not _is_safe_legacy_setting(normalized_section, normalized_key):
                    continue
                retained_value = _coerce_ini_value(raw_value)
                if retained_value is None:
                    continue
                imported += self._store_setting(
                    f"legacy.settings.{_normalize_setting_key(section)}.{_normalize_setting_key(key)}",
                    retained_value,
                )
                mapped = _map_legacy_setting(normalized_section, normalized_key, raw_value)
                if mapped is not None:
                    destination, value = mapped
                    imported += self._store_setting(destination, value)
        return imported

    def _import_legacy_theme(self, parser: ConfigParser) -> int:
        imported = 0
        palette_by_section: list[tuple[int, dict[str, str]]] = []
        for section_index, section in enumerate(parser.sections()):
            palette: dict[str, str] = {}
            for key, raw_value in parser.items(section):
                normalized_key = _legacy_identifier(key)
                sanitized = _sanitize_theme_value(normalized_key, raw_value)
                if sanitized is None:
                    continue
                imported += self._store_setting(
                    f"legacy.theme.{_normalize_setting_key(section)}.{_normalize_setting_key(key)}",
                    sanitized,
                )
                if normalized_key in _THEME_COLOR_KEYS:
                    palette[normalized_key] = sanitized
            if palette:
                priority = 0 if _legacy_identifier(section) in _CANONICAL_LEGACY_THEME_SECTIONS else section_index + 1
                palette_by_section.append((priority, palette))

        # The legacy editor used the Forms background to decide whether light
        # images were required.  The closest Astro equivalent is the global
        # light/dark canvas.  ButtonsBG is its single custom accent slot; the
        # complete validated palette remains available under ``legacy.theme``.
        if not palette_by_section:
            return imported
        _, palette = min(palette_by_section, key=lambda item: item[0])
        forms_background = palette.get("formsbg")
        if forms_background is not None:
            imported += self._store_setting(
                "appearance.theme",
                "dark" if _legacy_color_is_dark(forms_background) else "light",
            )
        buttons_background = palette.get("buttonsbg")
        if buttons_background is not None:
            imported += self._store_setting("appearance.accent", buttons_background)
        return imported

    def _store_setting(self, key: str, value: Any) -> int:
        try:
            self.repository.set_setting(key, value)
        except RepositoryError:
            # A malformed legacy item must not abort unrelated local settings.
            return 0
        return 1

    def _prune_imported_recent_games(self) -> None:
        raw_maximum = self.repository.get_setting("general.max_recent_games", 8)
        maximum = raw_maximum if isinstance(raw_maximum, int) and not isinstance(raw_maximum, bool) else 8
        if not 1 <= maximum <= 1_000:
            maximum = 8
        try:
            self.repository.prune_recent_games(maximum)
        except RepositoryError:
            # The imported rows are still valid metadata if a best-effort trim
            # fails (for example with an externally closed in-memory database).
            return

    def _import_recent_games(self, path: Path) -> int:
        if not path.is_file():
            return 0
        try:
            parsed = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return 0
        if not isinstance(parsed, list):
            return 0
        imported = 0
        # ``RecentGames`` was persisted oldest-to-newest.  It carried no
        # timestamp, so use a migration-time sequence solely to retain that
        # ordering in the SQLite recent-games query.  A later real launch will
        # naturally replace this synthetic timestamp with its actual time.
        started_at = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=max(len(parsed) - 1, 0))
        for index, item in enumerate(parsed):
            if not isinstance(item, Mapping):
                continue
            details = item.get("Details") or item.get("details")
            if not isinstance(details, Mapping):
                continue
            place_id = _as_positive_int(details.get("placeId") or details.get("PlaceID"))
            if place_id is None:
                continue
            name = _safe_text(details.get("name") or details.get("Name"), maximum=300) or "Unknown"
            existing = self.repository.get_game_by_place_id(place_id)
            legacy_metadata = {
                "url": _safe_http_url(details.get("url")),
                "source_name": _safe_text(details.get("sourceName"), maximum=300),
                "source_description": _safe_text(details.get("sourceDescription")),
                "is_playable": _parse_legacy_bool(details.get("isPlayable"), default=True),
                "has_verified_badge": _parse_legacy_bool(details.get("hasVerifiedBadge"), default=False),
                "universe_root_place_id": _as_positive_int(details.get("universeRootPlaceId")),
                "reason_prohibited": _safe_text(details.get("reasonProhibited"), maximum=1_000),
                "price": _as_non_negative_int(details.get("price")),
                "recent_order": index,
            }
            metadata = dict(existing.metadata) if existing is not None else {}
            metadata["legacy"] = {
                **(metadata.get("legacy") if isinstance(metadata.get("legacy"), Mapping) else {}),
                **{key: value for key, value in legacy_metadata.items() if value is not None},
            }
            try:
                self.repository.save_game(
                    Game(
                        place_id=place_id,
                        name=name,
                        universe_id=_as_positive_int(details.get("universeId")),
                        description=_safe_text(details.get("description")) or "",
                        creator_name=_safe_text(details.get("builder") or details.get("sourceName"), maximum=300),
                        creator_id=_as_positive_int(details.get("builderId")),
                        icon_url=_safe_http_url(item.get("ImageUrl") or item.get("imageUrl")),
                        is_favorite=existing.is_favorite if existing is not None else False,
                        last_used_at=(started_at + timedelta(seconds=index)).isoformat(),
                        metadata=metadata,
                    )
                )
                imported += 1
            except RepositoryError:
                continue
        return imported

    def _load_account_payload(
        self,
        detection: LegacyDetection,
        *,
        password: str | bytes | bytearray | memoryview | None,
    ) -> list[Mapping[str, Any]]:
        """Decode one explicitly consented store and validate its JSON shape."""

        try:
            encrypted = detection.path.read_bytes()
            if detection.format is LegacyFormat.PLAINTEXT_JSON:
                decoded = encrypted
            elif detection.format is LegacyFormat.DPAPI:
                decoded = self.dpapi.unprotect(encrypted, entropy=LEGACY_DPAPI_ENTROPY)
            elif detection.format is LegacyFormat.PASSWORD_ENCRYPTED:
                if password is None:
                    raise _PasswordRequired()
                decoded = _decrypt_password_payload(encrypted, password)
            else:
                raise LegacyMigrationError("Unsupported legacy account-data format.")
            return _parse_account_json(decoded)
        except (_PasswordRequired, _PasswordRejected, DPAPIError, DPAPIUnavailableError):
            raise
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
            raise LegacyMigrationError("Legacy account data is invalid or unreadable.") from exc

    def _import_account_payload(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        include_sessions: bool,
        include_saved_passwords: bool,
    ) -> dict[str, int]:
        counts = {"groups_imported": 0, "accounts_imported": 0, "sessions_imported": 0, "saved_passwords_imported": 0}
        groups_by_name = {group.name.casefold(): group for group in self.repository.list_groups()}
        normalized_records = tuple(records)

        # RAM 3.7.2 sorted group headers through a hidden leading numeric
        # prefix on their names.  Create all new groups before accounts so the
        # persistent v3 order reflects that historic presentation regardless
        # of the account-record order in AccountData.json.  Existing local
        # groups are deliberately left in their user-chosen order.
        new_group_names: dict[str, str] = {}
        for record in normalized_records:
            username = _safe_text(record.get("Username") or record.get("username"))
            if not username:
                continue
            group_name = _safe_text(record.get("Group") or record.get("group")) or "Default"
            group_key = group_name.casefold()
            if group_key not in groups_by_name:
                new_group_names.setdefault(group_key, group_name)
        for group_name in sorted(new_group_names.values(), key=legacy_group_order_key):
            group_key = group_name.casefold()
            try:
                group = self.repository.save_group(Group(name=group_name))
            except RepositoryError:
                continue
            groups_by_name[group_key] = group
            counts["groups_imported"] += 1

        for record in normalized_records:
            username = _safe_text(record.get("Username") or record.get("username"))
            if not username:
                continue
            group_name = _safe_text(record.get("Group") or record.get("group")) or "Default"
            group = groups_by_name.get(group_name.casefold())
            if group is None:
                # A malformed/conflicting group was skipped during the
                # precreation phase, so retain the old per-record failure
                # behaviour without assigning the account somewhere else.
                continue

            fields = _safe_string_mapping(record.get("Fields") or record.get("fields") or {})
            existing = self.repository.get_account_by_username(username)
            account = Account(
                id=existing.id if existing else Account(username=username).id,
                username=username,
                user_id=_as_positive_int(record.get("UserID") or record.get("user_id")),
                alias=_safe_text(record.get("Alias") or record.get("alias")) or "",
                description=_safe_text(record.get("Description") or record.get("description")) or "",
                group_id=group.id,
                status="valid" if bool(record.get("Valid") or record.get("valid")) else "unknown",
                last_used_at=_legacy_date(record.get("LastUse") or record.get("last_use")),
                last_refreshed_at=_legacy_date(record.get("LastAttemptedRefresh") or record.get("last_attempted_refresh")),
                saved_place_id=_field_int(fields, "SavedPlaceId"),
                saved_job_id=_field_text(fields, "SavedJobId") or _field_text(fields, "SavedJobID"),
                # Browser trackers were tied to the historical embedded-login
                # flow.  They are neither needed nor meaningful for the new
                # OAuth/system-browser flow, so migration deliberately leaves
                # them behind with the legacy source data.
                browser_tracker_id=None,
                custom_fields=fields,
                metadata={"legacy": {"valid": bool(record.get("Valid") or record.get("valid"))}},
                has_session=False,
            )
            try:
                saved = self.repository.save_account(account)
            except RepositoryError:
                continue
            counts["accounts_imported"] += 1

            if include_sessions:
                session = _safe_text(record.get("SecurityToken") or record.get("security_token"))
                if session:
                    try:
                        self.vault.store(saved.id, "session", session.encode("utf-8"))
                        # Update public marker only after the vault write succeeds.
                        saved.has_session = True
                        self.repository.save_account(saved)
                        counts["sessions_imported"] += 1
                    except (DPAPIUnavailableError, SecretVaultError, RepositoryError):
                        pass
            if include_saved_passwords:
                saved_password = _safe_text(record.get("Password") or record.get("password"))
                if saved_password:
                    try:
                        self.vault.store(saved.id, "saved_password", saved_password.encode("utf-8"))
                        counts["saved_passwords_imported"] += 1
                    except (DPAPIUnavailableError, SecretVaultError, RepositoryError):
                        pass
        return counts


class _PasswordRequired(Exception):
    pass


class _PasswordRejected(Exception):
    pass


def _decrypt_password_payload(
    encrypted: bytes,
    password: str | bytes | bytearray | memoryview,
) -> bytes:
    """Decode the historical Argon2 + XSalsa20-Poly1305 payload via PyNaCl."""

    if not encrypted.startswith(LEGACY_RAM_HEADER):
        raise LegacyMigrationError("Password-encrypted data is missing its legacy header.")
    offset = len(LEGACY_RAM_HEADER)
    salt_length, nonce_length = 16, 24
    if len(encrypted) <= offset + salt_length + nonce_length:
        raise _PasswordRejected()
    try:
        from nacl import pwhash, secret
        from nacl.exceptions import CryptoError
    except ImportError as exc:  # pragma: no cover - PyNaCl is an application dependency.
        raise LegacyMigrationError("Legacy password migration support is not installed.") from exc

    password_bytes = _password_bytes(password)
    salt = encrypted[offset : offset + salt_length]
    nonce_start = offset + salt_length
    nonce = encrypted[nonce_start : nonce_start + nonce_length]
    ciphertext = encrypted[nonce_start + nonce_length :]
    # Sodium.Core historically delegated to libsodium's Argon password hash.
    # Try argon2id first (the contemporary default), then argon2i for older
    # compatibility.  Neither plaintext nor an authentication error is logged.
    algorithms = [pwhash.argon2id]
    if hasattr(pwhash, "argon2i"):
        algorithms.append(pwhash.argon2i)
    for algorithm in algorithms:
        try:
            key = algorithm.kdf(
                secret.SecretBox.KEY_SIZE,
                password_bytes,
                salt,
                opslimit=algorithm.OPSLIMIT_MODERATE,
                memlimit=algorithm.MEMLIMIT_MODERATE,
            )
            return secret.SecretBox(key).decrypt(ciphertext, nonce)
        except CryptoError:
            continue
        except (TypeError, ValueError):
            continue
    raise _PasswordRejected()


def _password_bytes(value: str | bytes | bytearray | memoryview) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    raise TypeError("Password must be text or bytes-like.")


def _parse_account_json(payload: bytes) -> list[Mapping[str, Any]]:
    text = payload.decode("utf-8-sig")
    parsed = json.loads(text)
    if not isinstance(parsed, list):
        raise LegacyMigrationError("Legacy account data does not contain an account list.")
    records: list[Mapping[str, Any]] = []
    for item in parsed:
        if isinstance(item, Mapping):
            records.append(item)
    return records


def _select_account_file(detections: Iterable[LegacyDetection]) -> LegacyDetection | None:
    # The primary is preferred.  A historical backup is considered only when it
    # is itself recognizable; data is never moved or renamed in either case.
    candidates = [item for item in detections if item.can_import_metadata]
    if not candidates:
        return None
    candidates.sort(key=lambda item: 0 if item.path.name == _ACCOUNT_DATA_NAME else 1)
    return candidates[0]


def _resolve_legacy_directory(path: str | Path) -> Path:
    source = Path(path).expanduser().resolve()
    if not source.is_dir():
        raise LegacyMigrationError("Legacy source directory does not exist.")
    return source


def _directory_fingerprint(source: Path, detections: Iterable[LegacyDetection]) -> str:
    digest = hashlib.sha256(str(source).encode("utf-8"))
    for detection in detections:
        digest.update(detection.path.name.encode("utf-8"))
        digest.update((detection.fingerprint or "").encode("ascii"))
    return digest.hexdigest()


def _primary_format(detections: Iterable[LegacyDetection]) -> LegacyFormat:
    for detection in detections:
        if detection.path.name == _ACCOUNT_DATA_NAME:
            return detection.format
    return LegacyFormat.MISSING


def _read_legacy_ini(path: Path) -> ConfigParser | None:
    """Read a bounded UTF-8 INI file without accepting partial configuration."""

    try:
        if not path.is_file() or path.stat().st_size > _MAX_LEGACY_INI_BYTES:
            return None
        text = path.read_text(encoding="utf-8-sig")
        parser = ConfigParser(interpolation=None)
        parser.optionxform = str
        parser.read_string(text)
        return parser
    except (ConfigError, OSError, UnicodeError):
        return None


def _legacy_identifier(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())


def _is_safe_legacy_setting(section: str, key: str) -> bool:
    if not section or not key or is_sensitive_key(key) or "browsertracker" in key:
        return False
    if section == "general":
        return key not in _UNSAFE_LEGACY_GENERAL_KEYS
    if section == "developer":
        return key in _SAFE_LEGACY_DEVELOPER_KEYS
    if section == "webserver":
        return key in _SAFE_LEGACY_WEBSERVER_KEYS
    if section == "watcher":
        return key in _SAFE_LEGACY_WATCHER_KEYS
    # Prompts only controlled local confirmations in RAM.  Unknown sections
    # are likewise retained as bounded, non-sensitive legacy metadata so this
    # stricter importer does not discard an extension setting that the older
    # generic migration preserved.  Neither form gains active behavior here.
    return section != "accountcontrol"


def _map_legacy_setting(section: str, key: str, raw_value: str) -> tuple[str, Any] | None:
    if section == "general":
        if key == "maxrecentgames":
            maximum = _bounded_legacy_int(raw_value, minimum=1, maximum=1_000)
            return ("general.max_recent_games", maximum) if maximum is not None else None
        if key == "accountjoindelay":
            seconds = _bounded_legacy_int(raw_value, minimum=0, maximum=60)
            return ("general.launch_delay_ms", seconds * 1_000) if seconds is not None else None
        if key == "showpresence":
            value = _parse_legacy_bool(raw_value)
            return ("accounts.show_presence", value) if value is not None else None
        if key == "presenceupdaterate":
            minutes = _bounded_legacy_int(raw_value, minimum=1, maximum=9_999)
            return ("accounts.presence_update_seconds", minutes * 60) if minutes is not None else None
    elif section == "developer" and key == "devmode":
        value = _parse_legacy_bool(raw_value)
        return ("developer.enabled", value) if value is not None else None
    elif section == "webserver" and key == "webserverport":
        port = _bounded_legacy_int(raw_value, minimum=1, maximum=65_535)
        return ("api.port", port) if port is not None else None
    elif section == "watcher":
        if key == "enabled":
            value = _parse_legacy_bool(raw_value)
            return ("watcher.enabled", value) if value is not None else None
        if key == "scaninterval":
            # RAM exposed 2–600 seconds; the new monitor accepts 1–300.  Do
            # not silently clamp an unsupported old value into a new behavior.
            seconds = _bounded_legacy_int(raw_value, minimum=2, maximum=300)
            return ("watcher.scan_interval_seconds", seconds) if seconds is not None else None
        if key == "expectedwindowtitle":
            title = _safe_window_title(raw_value)
            return ("watcher.expected_window_title", title) if title is not None else None
        if key == "savewindowpositions":
            value = _parse_legacy_bool(raw_value)
            return ("instances.remember_window_positions", value) if value is not None else None
    return None


def _sanitize_theme_value(key: str, value: str) -> str | bool | None:
    if key in _THEME_COLOR_KEYS:
        return _normalize_legacy_hex_color(value)
    if key in _THEME_BOOLEAN_KEYS:
        return _parse_legacy_bool(value)
    if key == "buttonstyle":
        style = value.strip().casefold()
        return style if style in _THEME_BUTTON_STYLES else None
    return None


def _normalize_legacy_hex_color(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if len(normalized) == 4 and normalized.startswith("#") and all(
        character in "0123456789abcdef" for character in normalized[1:]
    ):
        return "#" + "".join(character * 2 for character in normalized[1:])
    if len(normalized) == 7 and normalized.startswith("#") and all(
        character in "0123456789abcdef" for character in normalized[1:]
    ):
        return normalized
    return None


def _legacy_color_is_dark(value: str) -> bool:
    """Match ``System.Drawing.Color.GetBrightness`` for an RGB hex colour."""

    red = int(value[1:3], 16)
    green = int(value[3:5], 16)
    blue = int(value[5:7], 16)
    return (max(red, green, blue) + min(red, green, blue)) / 510 < 0.5


def _parse_legacy_bool(value: Any, *, default: bool | None = None) -> bool | None:
    if isinstance(value, bool):
        return value
    if not isinstance(value, str):
        return default
    normalized = value.strip().casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return default


def _bounded_legacy_int(value: Any, *, minimum: int, maximum: int) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if minimum <= number <= maximum else None


def _safe_window_title(value: Any) -> str | None:
    title = _safe_text(value, maximum=120)
    if title is None:
        return None
    title = title.strip()
    if not title or any(ord(character) < 32 for character in title):
        return None
    return title


def _safe_http_url(value: Any) -> str | None:
    candidate = _safe_text(value, maximum=2_048)
    if candidate is None:
        return None
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    # Legacy game/image URLs do not require a credential-bearing query string.
    # Dropping query/fragment preserves the stable public location only.
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc, parsed.path, "", ""))


def _header_fingerprint(header: bytes, size: int) -> str:
    digest = hashlib.sha256()
    digest.update(size.to_bytes(16, byteorder="big", signed=False))
    digest.update(header)
    return digest.hexdigest()


def _normalize_setting_key(value: str) -> str:
    collapsed = "".join(character.lower() if character.isalnum() else "_" for character in value)
    return collapsed.strip("_")[:80] or "unknown"


def _coerce_ini_value(value: str) -> Any | None:
    stripped = value.strip()
    if len(stripped) > 10_000:
        return None
    if stripped.casefold() in {"true", "false"}:
        return stripped.casefold() == "true"
    try:
        integer = int(stripped)
        if -1_000_000_000_000 <= integer <= 1_000_000_000_000:
            return integer
        return None
    except ValueError:
        pass
    try:
        number = float(stripped)
        if math.isfinite(number) and abs(number) <= 1_000_000_000_000:
            return number
        return None
    except ValueError:
        return stripped


def _safe_text(value: Any, *, maximum: int = 10_000) -> str | None:
    if value is None or not isinstance(value, (str, int, float, bool)):
        return None
    text = str(value)
    return text[:maximum] if text else None


def _safe_string_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for key, item in value.items():
        key_text = _safe_text(key)
        item_text = _safe_text(item)
        if (
            key_text
            and item_text is not None
            and not is_sensitive_key(key_text)
            and "browsertracker" not in _legacy_identifier(key_text)
        ):
            result[key_text[:200]] = item_text[:5000]
    return result


def _field_text(values: Mapping[str, str], target: str) -> str | None:
    target_folded = target.casefold()
    for key, value in values.items():
        if key.casefold() == target_folded:
            return value
    return None


def _field_int(values: Mapping[str, str], target: str) -> int | None:
    return _as_positive_int(_field_text(values, target))


def _as_positive_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _as_non_negative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 0 <= number <= 1_000_000_000 else None


def _legacy_date(value: Any) -> str | None:
    # Keep the historical timestamp opaque-but-serializable.  The new UI can
    # normalize valid ISO values later; we avoid locale-sensitive parsing here.
    return _safe_text(value)


__all__ = [
    "LEGACY_DPAPI_ENTROPY",
    "LEGACY_RAM_HEADER",
    "LegacyDataMigrator",
    "LegacyDetection",
    "LegacyFormat",
    "LegacyMigrationError",
    "MigrationReport",
]
