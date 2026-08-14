"""Transactional SQLite persistence for non-secret application state.

Sessions, cookies, passwords and tokens are intentionally absent from this
schema.  They belong in an opt-in OS-protected vault, never the general account
repository or frontend-facing domain model.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, TypeVar
from uuid import uuid4

from app.backend.models.domain import Account, Activity, Game, Group, Notification, legacy_group_order_key
from app.backend.security.redaction import is_sensitive_key, redact_mapping


SCHEMA_VERSION = 4
_T = TypeVar("_T")
_MISSING = object()


class RepositoryError(RuntimeError):
    """A storage failure safe to surface through the application's error layer."""


class NotFoundError(RepositoryError):
    """Raised when an expected entity cannot be found."""


class ConflictError(RepositoryError):
    """Raised when a unique or relational storage constraint is violated."""


class SQLiteRepository:
    """Thread-safe unit of persistence for account-management metadata.

    Repository methods return typed domain objects and copy structured values,
    preventing a caller from mutating cached SQLite data accidentally.  Every
    multi-row operation uses an explicit transaction; SQLite WAL mode keeps
    readers responsive while the desktop process persists changes.
    """

    def __init__(self, database: str | Path) -> None:
        self.database_path = Path(database).expanduser() if str(database) != ":memory:" else None
        if self.database_path is not None:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            target = str(self.database_path.resolve())
        else:
            target = ":memory:"
        self._connection = sqlite3.connect(
            target,
            timeout=15,
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._transaction_depth = 0
        self._closed = False
        self._configure_connection()
        self._apply_schema()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True

    def checkpoint(self) -> None:
        """Checkpoint WAL data before a confirmed whole-file replacement."""

        with self._lock:
            self._ensure_open()
            try:
                self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error as exc:
                raise RepositoryError("Database checkpoint failed.") from exc

    def __enter__(self) -> "SQLiteRepository":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    @property
    def schema_version(self) -> int:
        row = self._fetchone("SELECT MAX(version) AS version FROM schema_migrations")
        return int(row["version"] or 0) if row else 0

    @property
    def is_closed(self) -> bool:
        with self._lock:
            return self._closed

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Run statements atomically, with savepoints for nested repository calls."""

        with self._lock:
            self._ensure_open()
            depth = self._transaction_depth
            savepoint = f"repository_savepoint_{depth}"
            try:
                if depth == 0:
                    self._connection.execute("BEGIN IMMEDIATE")
                else:
                    self._connection.execute(f"SAVEPOINT {savepoint}")
                self._transaction_depth += 1
                yield
            except Exception:
                self._transaction_depth -= 1
                if depth == 0:
                    self._connection.execute("ROLLBACK")
                else:
                    self._connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    self._connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            else:
                self._transaction_depth -= 1
                if depth == 0:
                    self._connection.execute("COMMIT")
                else:
                    self._connection.execute(f"RELEASE SAVEPOINT {savepoint}")

    # Groups -----------------------------------------------------------------
    def save_group(self, group: Group | Mapping[str, Any] | str) -> Group:
        """Insert or update a group and return its persisted representation."""

        if isinstance(group, str):
            group = Group(name=group)
        data = _object_data(group)
        identifier = _text(data.get("id") or uuid4())
        name = _required_text(data.get("name"), "group name", maximum=120)
        now = _utc_now()
        created_at = _optional_text(data.get("created_at")) or now
        updated_at = now
        payload = {
            "id": identifier,
            "name": name,
            "color": _optional_text(data.get("color")) or "#7c5cff",
            "icon": _optional_text(data.get("icon")) or "folder",
            "sort_order": None,
            "is_favorite": _boolean(data.get("is_favorite")),
            "is_collapsed": _boolean(data.get("is_collapsed")),
            "created_at": created_at,
            "updated_at": updated_at,
        }
        statement = """
            INSERT INTO groups (id, name, color, icon, sort_order, is_favorite, is_collapsed, created_at, updated_at)
            VALUES (:id, :name, :color, :icon, :sort_order, :is_favorite, :is_collapsed, :created_at, :updated_at)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                color = excluded.color,
                icon = excluded.icon,
                is_favorite = excluded.is_favorite,
                is_collapsed = excluded.is_collapsed,
                updated_at = excluded.updated_at
        """
        with self.transaction():
            existing = self._fetchone("SELECT sort_order FROM groups WHERE id = ?", (identifier,))
            # Like account ordering, an already-persisted group order is a
            # snapshot on a Group object.  Saving a stale object after a
            # drag/drop must not undo the atomic group reorder.
            payload["sort_order"] = (
                int(existing["sort_order"])
                if existing is not None
                else self._next_group_sort_order()
            )
            self._execute(statement, payload)
        return self.get_group(identifier)

    def get_group(self, group_id: str) -> Group:
        row = self._fetchone("SELECT * FROM groups WHERE id = ?", (group_id,))
        if row is None:
            raise NotFoundError("Group was not found.")
        return _group_from_row(row)

    def list_groups(self) -> list[Group]:
        rows = self._fetchall("SELECT * FROM groups ORDER BY sort_order ASC, id")
        return [_group_from_row(row) for row in rows]

    def delete_group(self, group_id: str) -> bool:
        with self.transaction():
            result = self._execute("DELETE FROM groups WHERE id = ?", (group_id,))
        return result.rowcount > 0

    def reorder_groups(self, group_ids: Iterable[str]) -> list[Group]:
        """Persist one complete group order as a single atomic operation.

        Legacy RAM used the hidden numeric prefix in a group name as its
        visible ordering mechanism.  The new model freezes that imported order
        in ``sort_order`` and accepts later user-driven moves only as a full
        sequence, so a filtered or stale UI payload cannot drop a group.
        """

        identifiers = _ordered_group_ids(group_ids)
        with self.transaction():
            rows = self._fetchall("SELECT id FROM groups ORDER BY sort_order ASC, id")
            existing_ids = {str(row["id"]) for row in rows}
            supplied_ids = set(identifiers)
            unknown_ids = supplied_ids - existing_ids
            if unknown_ids:
                raise NotFoundError("One or more groups selected for reordering were not found.")
            if supplied_ids != existing_ids:
                raise RepositoryError("A complete group ID order is required.")
            now = _utc_now()
            for position, group_id in enumerate(identifiers):
                self._execute(
                    "UPDATE groups SET sort_order = ?, updated_at = ? WHERE id = ?",
                    (position, now, group_id),
                )
        return self.list_groups()

    def _next_group_sort_order(self) -> int:
        row = self._fetchone("SELECT COALESCE(MAX(sort_order), -1) AS maximum FROM groups")
        maximum = int(row["maximum"] if row is not None else -1)
        if maximum >= 2_147_483_647:
            raise RepositoryError("Group sort_order capacity has been reached; reorder groups first.")
        return maximum + 1

    # Accounts ---------------------------------------------------------------
    def save_account(self, account: Account | Mapping[str, Any]) -> Account:
        """Persist public account metadata only; secret-looking fields are dropped."""

        data = _object_data(account)
        identifier = _text(data.get("id") or uuid4())
        username = _required_text(data.get("username"), "username", maximum=120)
        group_id = _optional_text(data.get("group_id"))
        now = _utc_now()
        created_at = _optional_text(data.get("created_at")) or now
        fields = _strip_sensitive_values(data.get("custom_fields", {}))
        metadata = _strip_sensitive_values(data.get("metadata", {}))
        payload = {
            "id": identifier,
            "username": username,
            "user_id": _optional_integer(data.get("user_id")),
            "display_name": _optional_text(data.get("display_name"), maximum=120),
            "alias": _optional_text(data.get("alias"), maximum=120) or "",
            "description": _optional_text(data.get("description"), maximum=5000) or "",
            "group_id": group_id,
            "avatar_url": _optional_text(data.get("avatar_url"), maximum=2048),
            "status": _optional_text(data.get("status"), maximum=40) or "unknown",
            "is_favorite": _boolean(data.get("is_favorite")),
            "sort_order": None,
            "last_used_at": _optional_text(data.get("last_used_at")),
            "last_refreshed_at": _optional_text(data.get("last_refreshed_at")),
            "saved_place_id": _optional_integer(data.get("saved_place_id")),
            "saved_job_id": _optional_text(data.get("saved_job_id"), maximum=256),
            "browser_tracker_id": _optional_text(data.get("browser_tracker_id"), maximum=128),
            "custom_fields_json": _json_dump(fields),
            "metadata_json": _json_dump(metadata),
            "has_session": _boolean(data.get("has_session")),
            "created_at": created_at,
            "updated_at": now,
        }
        statement = """
            INSERT INTO accounts (
                id, username, user_id, display_name, alias, description, group_id, avatar_url, status,
                is_favorite, sort_order, last_used_at, last_refreshed_at, saved_place_id, saved_job_id,
                browser_tracker_id, custom_fields_json, metadata_json, has_session, created_at, updated_at
            ) VALUES (
                :id, :username, :user_id, :display_name, :alias, :description, :group_id, :avatar_url, :status,
                :is_favorite, :sort_order, :last_used_at, :last_refreshed_at, :saved_place_id, :saved_job_id,
                :browser_tracker_id, :custom_fields_json, :metadata_json, :has_session, :created_at, :updated_at
            ) ON CONFLICT(id) DO UPDATE SET
                username = excluded.username,
                user_id = excluded.user_id,
                display_name = excluded.display_name,
                alias = excluded.alias,
                description = excluded.description,
                group_id = excluded.group_id,
                avatar_url = excluded.avatar_url,
                status = excluded.status,
                is_favorite = excluded.is_favorite,
                last_used_at = excluded.last_used_at,
                last_refreshed_at = excluded.last_refreshed_at,
                saved_place_id = excluded.saved_place_id,
                saved_job_id = excluded.saved_job_id,
                browser_tracker_id = excluded.browser_tracker_id,
                custom_fields_json = excluded.custom_fields_json,
                metadata_json = excluded.metadata_json,
                has_session = excluded.has_session,
                updated_at = excluded.updated_at
        """
        try:
            with self.transaction():
                existing = self._fetchone("SELECT sort_order FROM accounts WHERE id = ?", (identifier,))
                # ``sort_order`` on Account is a persisted snapshot, not an
                # update request.  A caller may hold an account object from
                # before a drag/drop reorder, so accepting its stale value
                # here would silently undo that atomic reorder.  New accounts
                # always append; ``reorder_accounts`` is the only operation
                # allowed to change an established order.
                payload["sort_order"] = (
                    int(existing["sort_order"])
                    if existing is not None
                    else self._next_account_sort_order()
                )
                self._execute(statement, payload)
        except sqlite3.IntegrityError as exc:
            raise ConflictError("Account username or group reference conflicts with existing data.") from exc
        return self.get_account(identifier)

    def get_account(self, account_id: str) -> Account:
        row = self._fetchone("SELECT * FROM accounts WHERE id = ?", (account_id,))
        if row is None:
            raise NotFoundError("Account was not found.")
        return _account_from_row(row)

    def get_account_by_username(self, username: str) -> Account | None:
        row = self._fetchone("SELECT * FROM accounts WHERE username = ? COLLATE NOCASE", (username,))
        return _account_from_row(row) if row else None

    def list_accounts(
        self,
        *,
        group_id: str | None | object = _MISSING,
        search: str | None = None,
        limit: int | None = None,
    ) -> list[Account]:
        clauses: list[str] = []
        params: list[Any] = []
        if group_id is not _MISSING:
            if group_id is None:
                clauses.append("group_id IS NULL")
            else:
                clauses.append("group_id = ?")
                params.append(group_id)
        if search:
            clauses.append("(username LIKE ? ESCAPE '\\' OR display_name LIKE ? ESCAPE '\\' OR alias LIKE ? ESCAPE '\\')")
            pattern = f"%{_escape_like(search.strip())}%"
            params.extend([pattern, pattern, pattern])
        query = "SELECT * FROM accounts"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY sort_order ASC, id"
        if limit is not None:
            query += " LIMIT ?"
            params.append(_positive_limit(limit))
        return [_account_from_row(row) for row in self._fetchall(query, params)]

    def delete_account(self, account_id: str) -> bool:
        with self.transaction():
            result = self._execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        return result.rowcount > 0

    def move_accounts(self, account_ids: Iterable[str], group_id: str | None) -> int:
        identifiers = tuple(dict.fromkeys(str(identifier) for identifier in account_ids if identifier))
        if not identifiers:
            return 0
        if group_id is not None:
            self.get_group(group_id)
        placeholders = ", ".join("?" for _ in identifiers)
        with self.transaction():
            result = self._execute(
                f"UPDATE accounts SET group_id = ?, updated_at = ? WHERE id IN ({placeholders})",
                (group_id, _utc_now(), *identifiers),
            )
        return result.rowcount

    def reorder_accounts(self, account_ids: Iterable[str]) -> list[Account]:
        """Persist one complete account order as a single atomic operation.

        The legacy ObjectListView drag/drop handler removed each dragged model
        from the backing list, inserted it at the target index, then serialized
        that list.  The desktop UI can recreate the same result by sending the
        complete resulting ID sequence here.  Requiring every local account
        prevents a partial drag payload from silently scrambling accounts that
        were not visible in a filtered view.
        """

        identifiers = _ordered_account_ids(account_ids)
        with self.transaction():
            rows = self._fetchall("SELECT id FROM accounts ORDER BY sort_order ASC, id")
            existing_ids = {str(row["id"]) for row in rows}
            supplied_ids = set(identifiers)
            unknown_ids = supplied_ids - existing_ids
            if unknown_ids:
                raise NotFoundError("One or more accounts selected for reordering were not found.")
            if supplied_ids != existing_ids:
                raise RepositoryError("A complete account ID order is required.")
            now = _utc_now()
            for position, account_id in enumerate(identifiers):
                self._execute(
                    "UPDATE accounts SET sort_order = ?, updated_at = ? WHERE id = ?",
                    (position, now, account_id),
                )
        return self.list_accounts()

    def _next_account_sort_order(self) -> int:
        row = self._fetchone("SELECT COALESCE(MAX(sort_order), -1) AS maximum FROM accounts")
        maximum = int(row["maximum"] if row is not None else -1)
        if maximum >= 2_147_483_647:
            raise RepositoryError("Account sort_order capacity has been reached; reorder accounts first.")
        return maximum + 1

    # Protected vault blobs --------------------------------------------------
    def save_protected_secret(self, account_id: str, secret_kind: str, protected_blob: bytes) -> None:
        """Store an already DPAPI-protected blob without ever handling plaintext.

        Only security services should call this method.  The repository exposes
        bytes here because SQLite must persist the opaque blob, not because the
        general application API is allowed to read credentials.
        """

        kind = _required_text(secret_kind, "secret kind", maximum=80)
        if not isinstance(protected_blob, (bytes, bytearray, memoryview)) or not protected_blob:
            raise RepositoryError("Protected secret data must be a non-empty bytes-like value.")
        # Verify the account reference early to give callers an actionable
        # error before SQLite's foreign-key constraint is evaluated.
        self.get_account(account_id)
        now = _utc_now()
        with self.transaction():
            self._execute(
                """
                INSERT INTO secret_vault_entries (account_id, secret_kind, protected_blob, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(account_id, secret_kind) DO UPDATE SET
                    protected_blob = excluded.protected_blob, updated_at = excluded.updated_at
                """,
                (account_id, kind, sqlite3.Binary(bytes(protected_blob)), now, now),
            )

    def load_protected_secret(self, account_id: str, secret_kind: str) -> bytes | None:
        """Return only an opaque protected blob for a trusted security service."""

        row = self._fetchone(
            "SELECT protected_blob FROM secret_vault_entries WHERE account_id = ? AND secret_kind = ?",
            (account_id, secret_kind),
        )
        return bytes(row["protected_blob"]) if row is not None else None

    def has_protected_secret(self, account_id: str, secret_kind: str = "session") -> bool:
        row = self._fetchone(
            "SELECT 1 FROM secret_vault_entries WHERE account_id = ? AND secret_kind = ?",
            (account_id, secret_kind),
        )
        return row is not None

    def delete_protected_secret(self, account_id: str, secret_kind: str) -> bool:
        with self.transaction():
            result = self._execute(
                "DELETE FROM secret_vault_entries WHERE account_id = ? AND secret_kind = ?",
                (account_id, secret_kind),
            )
        return result.rowcount > 0

    # Games ------------------------------------------------------------------
    def save_game(self, game: Game | Mapping[str, Any]) -> Game:
        data = _object_data(game)
        place_id = _integer(data.get("place_id"), default=None)
        if place_id is None or place_id <= 0:
            raise RepositoryError("A positive game place_id is required.")
        identifier = _text(data.get("id") or uuid4())
        now = _utc_now()
        payload = {
            "id": identifier,
            "place_id": place_id,
            "universe_id": _optional_integer(data.get("universe_id")),
            "name": _required_text(data.get("name"), "game name", maximum=300),
            "description": _optional_text(data.get("description"), maximum=10000) or "",
            "creator_name": _optional_text(data.get("creator_name"), maximum=300),
            "creator_id": _optional_integer(data.get("creator_id")),
            "icon_url": _optional_text(data.get("icon_url"), maximum=2048),
            "playing": _optional_integer(data.get("playing")),
            "max_players": _optional_integer(data.get("max_players")),
            "is_favorite": _boolean(data.get("is_favorite")),
            "last_used_at": _optional_text(data.get("last_used_at")),
            "metadata_json": _json_dump(_strip_sensitive_values(data.get("metadata", {}))),
            "created_at": _optional_text(data.get("created_at")) or now,
            "updated_at": now,
        }
        statement = """
            INSERT INTO games (
                id, place_id, universe_id, name, description, creator_name, creator_id, icon_url, playing,
                max_players, is_favorite, last_used_at, metadata_json, created_at, updated_at
            ) VALUES (
                :id, :place_id, :universe_id, :name, :description, :creator_name, :creator_id, :icon_url, :playing,
                :max_players, :is_favorite, :last_used_at, :metadata_json, :created_at, :updated_at
            ) ON CONFLICT(place_id) DO UPDATE SET
                universe_id = excluded.universe_id,
                name = excluded.name,
                description = excluded.description,
                creator_name = excluded.creator_name,
                creator_id = excluded.creator_id,
                icon_url = excluded.icon_url,
                playing = excluded.playing,
                max_players = excluded.max_players,
                is_favorite = excluded.is_favorite,
                last_used_at = excluded.last_used_at,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
        """
        with self.transaction():
            self._execute(statement, payload)
        row = self._fetchone("SELECT * FROM games WHERE place_id = ?", (place_id,))
        assert row is not None
        return _game_from_row(row)

    def get_game_by_place_id(self, place_id: int) -> Game | None:
        row = self._fetchone("SELECT * FROM games WHERE place_id = ?", (place_id,))
        return _game_from_row(row) if row else None

    def list_games(
        self,
        *,
        favorites_only: bool = False,
        recent_only: bool = False,
        limit: int | None = None,
    ) -> list[Game]:
        query = "SELECT * FROM games"
        params: list[Any] = []
        clauses: list[str] = []
        if favorites_only:
            clauses.append("is_favorite = 1")
        if recent_only:
            clauses.append("last_used_at IS NOT NULL")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        if recent_only:
            # Windows clocks can return the same timestamp for rapid launches.
            # rowid is a deterministic newest-insert tie-breaker instead of
            # letting SQLite return an arbitrary order in that sub-millisecond
            # window.
            query += " ORDER BY last_used_at DESC, updated_at DESC, rowid DESC, name COLLATE NOCASE, place_id"
        else:
            query += " ORDER BY is_favorite DESC, last_used_at DESC, name COLLATE NOCASE, place_id"
        if limit is not None:
            query += " LIMIT ?"
            params.append(_positive_limit(limit))
        return [_game_from_row(row) for row in self._fetchall(query, params)]

    def set_game_favorite(self, place_id: int, is_favorite: bool) -> Game:
        """Persist the favourite flag without altering recency metadata."""

        normalized_place_id = _positive_game_place_id(place_id)
        if not isinstance(is_favorite, bool):
            raise RepositoryError("Game favorite state must be a boolean.")
        with self.transaction():
            result = self._execute(
                "UPDATE games SET is_favorite = ?, updated_at = ? WHERE place_id = ?",
                (_boolean(is_favorite), _utc_now(), normalized_place_id),
            )
        if result.rowcount == 0:
            raise NotFoundError("Game was not found.")
        row = self._fetchone("SELECT * FROM games WHERE place_id = ?", (normalized_place_id,))
        assert row is not None
        return _game_from_row(row)

    def delete_game_by_place_id(self, place_id: int) -> bool:
        """Remove a stored game record, including any local favourite marker."""

        normalized_place_id = _positive_game_place_id(place_id)
        with self.transaction():
            result = self._execute("DELETE FROM games WHERE place_id = ?", (normalized_place_id,))
        return result.rowcount > 0

    def prune_recent_games(self, maximum: int) -> list[int]:
        """Keep at most ``maximum`` recent games without losing favourites.

        Legacy RAM kept `RecentGames.json` and `FavoriteGames.json` apart. The
        SQLite port shares a game record, so pruning a recent favourite clears
        only ``last_used_at`` while a non-favourite record is removed entirely.
        The returned PlaceIds describe entries removed from the recent list,
        not necessarily deleted from the database.
        """

        normalized_maximum = _positive_limit(maximum)
        with self.transaction():
            stale = self._fetchall(
                """
                SELECT place_id, is_favorite
                FROM games
                WHERE last_used_at IS NOT NULL
                ORDER BY last_used_at DESC, updated_at DESC, rowid DESC, place_id DESC
                LIMIT -1 OFFSET ?
                """,
                (normalized_maximum,),
            )
            removed: list[int] = []
            now = _utc_now()
            for row in stale:
                place_id = int(row["place_id"])
                if bool(row["is_favorite"]):
                    self._execute(
                        "UPDATE games SET last_used_at = NULL, updated_at = ? WHERE place_id = ?",
                        (now, place_id),
                    )
                else:
                    self._execute("DELETE FROM games WHERE place_id = ?", (place_id,))
                removed.append(place_id)
        return removed

    # Settings ---------------------------------------------------------------
    def set_setting(self, key: str, value: Any) -> None:
        setting_key = _required_text(key, "setting key", maximum=200)
        if is_sensitive_key(setting_key):
            raise RepositoryError("Sensitive settings must use OS-protected storage.")
        payload = (setting_key, _json_dump(_strip_sensitive_values(value)), _utc_now())
        with self.transaction():
            self._execute(
                """
                INSERT INTO settings (key, value_json, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
                """,
                payload,
            )

    def get_setting(self, key: str, default: _T | None = None) -> Any | _T | None:
        row = self._fetchone("SELECT value_json FROM settings WHERE key = ?", (key,))
        return default if row is None else _json_load(row["value_json"], default={})

    def list_settings(self, *, prefix: str | None = None) -> dict[str, Any]:
        if prefix:
            pattern = f"{_escape_like(prefix)}%"
            rows = self._fetchall("SELECT key, value_json FROM settings WHERE key LIKE ? ESCAPE '\\' ORDER BY key", (pattern,))
        else:
            rows = self._fetchall("SELECT key, value_json FROM settings ORDER BY key")
        return {row["key"]: _json_load(row["value_json"], default=None) for row in rows}

    def delete_setting(self, key: str) -> bool:
        with self.transaction():
            result = self._execute("DELETE FROM settings WHERE key = ?", (key,))
        return result.rowcount > 0

    # Macros -----------------------------------------------------------------
    def save_macro(self, values: Mapping[str, Any]) -> dict[str, Any]:
        """Persist one secret-free macro definition."""

        identifier = _text(values.get("id") or uuid4())
        name = _required_text(values.get("name"), "macro name", maximum=120)
        description = _optional_text(values.get("description")) or ""
        if len(description) > 500:
            raise RepositoryError("Macro description is too long.")
        mode = _required_text(values.get("mode") or "blocks", "macro mode", maximum=20)
        if mode not in {"blocks", "dsl"}:
            raise RepositoryError("Macro mode is invalid.")
        source = str(values.get("source") or "")
        if len(source) > 32_000:
            raise RepositoryError("Macro source is too large.")
        actions = values.get("actions")
        if not isinstance(actions, list):
            raise RepositoryError("Macro actions must be a list.")
        account_id = _optional_text(values.get("account_id"))
        now = _utc_now()
        existing = self._fetchone("SELECT created_at FROM macros WHERE id = ?", (identifier,))
        payload = {
            "id": identifier,
            "name": name,
            "description": description,
            "account_id": account_id,
            "mode": mode,
            "source": source,
            "actions_json": _json_dump(actions),
            "created_at": str(existing["created_at"]) if existing else now,
            "updated_at": now,
        }
        with self.transaction():
            self._execute(
                """
                INSERT INTO macros (id, name, description, account_id, mode, source, actions_json, created_at, updated_at)
                VALUES (:id, :name, :description, :account_id, :mode, :source, :actions_json, :created_at, :updated_at)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    account_id = excluded.account_id,
                    mode = excluded.mode,
                    source = excluded.source,
                    actions_json = excluded.actions_json,
                    updated_at = excluded.updated_at
                """,
                payload,
            )
        return self.get_macro(identifier)

    def get_macro(self, macro_id: str) -> dict[str, Any]:
        row = self._fetchone("SELECT * FROM macros WHERE id = ?", (_text(macro_id),))
        if row is None:
            raise NotFoundError("Macro was not found.")
        return _macro_from_row(row)

    def list_macros(self) -> list[dict[str, Any]]:
        rows = self._fetchall("SELECT * FROM macros ORDER BY name COLLATE NOCASE, id")
        return [_macro_from_row(row) for row in rows]

    def delete_macro(self, macro_id: str) -> bool:
        with self.transaction():
            result = self._execute("DELETE FROM macros WHERE id = ?", (_text(macro_id),))
        return result.rowcount > 0

    # Activity ---------------------------------------------------------------
    def record_activity(self, activity: Activity | Mapping[str, Any]) -> Activity:
        data = _object_data(activity)
        payload = {
            "id": _text(data.get("id") or uuid4()),
            "kind": _required_text(data.get("kind"), "activity kind", maximum=80),
            "summary": _required_text(data.get("summary"), "activity summary", maximum=2000),
            "account_id": _optional_text(data.get("account_id")),
            "metadata_json": _json_dump(_strip_sensitive_values(data.get("metadata", {}))),
            "created_at": _optional_text(data.get("created_at")) or _utc_now(),
        }
        with self.transaction():
            self._execute(
                """
                INSERT INTO activity (id, kind, summary, account_id, metadata_json, created_at)
                VALUES (:id, :kind, :summary, :account_id, :metadata_json, :created_at)
                """,
                payload,
            )
        return self.get_activity(payload["id"])

    def get_activity(self, activity_id: str) -> Activity:
        row = self._fetchone("SELECT * FROM activity WHERE id = ?", (activity_id,))
        if row is None:
            raise NotFoundError("Activity entry was not found.")
        return _activity_from_row(row)

    def list_activity(self, *, limit: int = 100, account_id: str | None = None) -> list[Activity]:
        if account_id is None:
            rows = self._fetchall(
                "SELECT * FROM activity ORDER BY created_at DESC, id DESC LIMIT ?", (_positive_limit(limit),)
            )
        else:
            rows = self._fetchall(
                "SELECT * FROM activity WHERE account_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                (account_id, _positive_limit(limit)),
            )
        return [_activity_from_row(row) for row in rows]

    # Notifications ----------------------------------------------------------
    def save_notification(self, notification: Notification | Mapping[str, Any]) -> Notification:
        data = _object_data(notification)
        action = _strip_sensitive_values(data.get("action")) if data.get("action") else None
        payload = {
            "id": _text(data.get("id") or uuid4()),
            "level": _required_text(data.get("level"), "notification level", maximum=30),
            "title": _required_text(data.get("title"), "notification title", maximum=300),
            "message": _required_text(data.get("message"), "notification message", maximum=5000),
            "is_dismissed": _boolean(data.get("is_dismissed")),
            "action_json": _json_dump(action) if action is not None else None,
            "created_at": _optional_text(data.get("created_at")) or _utc_now(),
        }
        with self.transaction():
            self._execute(
                """
                INSERT INTO notifications (id, level, title, message, is_dismissed, action_json, created_at)
                VALUES (:id, :level, :title, :message, :is_dismissed, :action_json, :created_at)
                ON CONFLICT(id) DO UPDATE SET
                    level = excluded.level, title = excluded.title, message = excluded.message,
                    is_dismissed = excluded.is_dismissed, action_json = excluded.action_json
                """,
                payload,
            )
        return self.get_notification(payload["id"])

    def get_notification(self, notification_id: str) -> Notification:
        row = self._fetchone("SELECT * FROM notifications WHERE id = ?", (notification_id,))
        if row is None:
            raise NotFoundError("Notification was not found.")
        return _notification_from_row(row)

    def list_notifications(self, *, include_dismissed: bool = False, limit: int = 100) -> list[Notification]:
        if include_dismissed:
            rows = self._fetchall(
                "SELECT * FROM notifications ORDER BY created_at DESC, id DESC LIMIT ?", (_positive_limit(limit),)
            )
        else:
            rows = self._fetchall(
                "SELECT * FROM notifications WHERE is_dismissed = 0 ORDER BY created_at DESC, id DESC LIMIT ?",
                (_positive_limit(limit),),
            )
        return [_notification_from_row(row) for row in rows]

    def dismiss_notification(self, notification_id: str) -> bool:
        with self.transaction():
            result = self._execute("UPDATE notifications SET is_dismissed = 1 WHERE id = ?", (notification_id,))
        return result.rowcount > 0

    # Schema / query helpers -------------------------------------------------
    def _configure_connection(self) -> None:
        with self._lock:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA busy_timeout = 15000")
            # WAL is not useful for in-memory databases and reports a different
            # journal mode there, so set it only for file-backed app data.
            if self.database_path is not None:
                self._connection.execute("PRAGMA journal_mode = WAL")
                self._connection.execute("PRAGMA synchronous = FULL")

    def _apply_schema(self) -> None:
        with self.transaction():
            self._execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            current = self._fetchone("SELECT MAX(version) AS version FROM schema_migrations")
            version = int(current["version"] or 0) if current else 0
            if version > SCHEMA_VERSION:
                raise RepositoryError("Database was created by a newer version of the application.")
            if version < 1:
                self._create_v1_schema()
                self._execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (1, _utc_now()),
                )
                version = 1
            if version < 2:
                self._migrate_v2_account_sort_order()
                self._execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (2, _utc_now()),
                )
                version = 2
            if version < 3:
                self._migrate_v3_group_sort_order()
                self._execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (3, _utc_now()),
                )
                version = 3
            if version < 4:
                self._migrate_v4_macros()
                self._execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (4, _utc_now()),
                )

    def _create_v1_schema(self) -> None:
        schema = """
            CREATE TABLE IF NOT EXISTS groups (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE,
                color TEXT NOT NULL,
                icon TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                is_favorite INTEGER NOT NULL DEFAULT 0 CHECK (is_favorite IN (0, 1)),
                is_collapsed INTEGER NOT NULL DEFAULT 0 CHECK (is_collapsed IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_groups_name ON groups(name COLLATE NOCASE);

            CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL COLLATE NOCASE,
                user_id INTEGER,
                display_name TEXT,
                alias TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                group_id TEXT REFERENCES groups(id) ON DELETE SET NULL,
                avatar_url TEXT,
                status TEXT NOT NULL DEFAULT 'unknown',
                is_favorite INTEGER NOT NULL DEFAULT 0 CHECK (is_favorite IN (0, 1)),
                last_used_at TEXT,
                last_refreshed_at TEXT,
                saved_place_id INTEGER,
                saved_job_id TEXT,
                browser_tracker_id TEXT,
                custom_fields_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                has_session INTEGER NOT NULL DEFAULT 0 CHECK (has_session IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_username ON accounts(username COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_accounts_group ON accounts(group_id);
            CREATE INDEX IF NOT EXISTS idx_accounts_last_used ON accounts(last_used_at DESC);

            CREATE TABLE IF NOT EXISTS games (
                id TEXT PRIMARY KEY,
                place_id INTEGER NOT NULL UNIQUE,
                universe_id INTEGER,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                creator_name TEXT,
                creator_id INTEGER,
                icon_url TEXT,
                playing INTEGER,
                max_players INTEGER,
                is_favorite INTEGER NOT NULL DEFAULT 0 CHECK (is_favorite IN (0, 1)),
                last_used_at TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_games_recent ON games(last_used_at DESC);

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS activity (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                summary TEXT NOT NULL,
                account_id TEXT REFERENCES accounts(id) ON DELETE SET NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_activity_created ON activity(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_activity_account ON activity(account_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS notifications (
                id TEXT PRIMARY KEY,
                level TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                is_dismissed INTEGER NOT NULL DEFAULT 0 CHECK (is_dismissed IN (0, 1)),
                action_json TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_notifications_active ON notifications(is_dismissed, created_at DESC);

            CREATE TABLE IF NOT EXISTS secret_vault_entries (
                account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                secret_kind TEXT NOT NULL,
                protected_blob BLOB NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (account_id, secret_kind)
            );

            CREATE TABLE IF NOT EXISTS migration_runs (
                id TEXT PRIMARY KEY,
                source_path TEXT NOT NULL,
                source_fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_migration_source_fingerprint
                ON migration_runs(source_fingerprint);
        """
        for statement in (part.strip() for part in schema.split(";") if part.strip()):
            self._execute(statement)

    def _migrate_v2_account_sort_order(self) -> None:
        """Add a stable persisted account order without disturbing old rows.

        Version 1 had no manual account ordering; its observable order was the
        repository's old favourite/recent/username query.  Backfilling from
        that exact query makes the first v2 opening stable for existing local
        workspaces before a user performs their first drag/drop reorder.
        """

        columns = self._fetchall("PRAGMA table_info(accounts)")
        column_names = {str(column["name"]) for column in columns}
        if "sort_order" not in column_names:
            self._execute("ALTER TABLE accounts ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
            rows = self._fetchall(
                "SELECT id FROM accounts ORDER BY is_favorite DESC, last_used_at DESC, username COLLATE NOCASE, id"
            )
            for position, row in enumerate(rows):
                self._execute("UPDATE accounts SET sort_order = ? WHERE id = ?", (position, row["id"]))
        self._execute("CREATE INDEX IF NOT EXISTS idx_accounts_sort_order ON accounts(sort_order, id)")

    def _migrate_v3_group_sort_order(self) -> None:
        """Freeze the legacy numeric group-prefix display order in SQLite.

        Legacy managers used the group name as ObjectListView's key and stripped a
        leading one-to-three digit prefix only when rendering the group title.
        Users therefore named groups such as ``001 Apple`` or ``1Apple`` to
        place them before other headers.  The explicit v3 order captures that
        behaviour once, while later drag/drop moves use ``reorder_groups``.
        """

        rows = self._fetchall("SELECT id, name, sort_order FROM groups")
        ordered_rows = sorted(
            rows,
            key=lambda row: legacy_group_order_key(
                row["name"],
                previous_order=row["sort_order"],
                identifier=row["id"],
            ),
        )
        for position, row in enumerate(ordered_rows):
            self._execute("UPDATE groups SET sort_order = ? WHERE id = ?", (position, row["id"]))
        self._execute("CREATE INDEX IF NOT EXISTS idx_groups_sort_order ON groups(sort_order, id)")

    def _migrate_v4_macros(self) -> None:
        """Add secret-free, account-scoped macro definitions."""

        self._execute(
            """
            CREATE TABLE IF NOT EXISTS macros (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE,
                description TEXT NOT NULL DEFAULT '',
                account_id TEXT REFERENCES accounts(id) ON DELETE SET NULL,
                mode TEXT NOT NULL CHECK (mode IN ('blocks', 'dsl')),
                source TEXT NOT NULL DEFAULT '',
                actions_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._execute("CREATE INDEX IF NOT EXISTS idx_macros_account ON macros(account_id, name COLLATE NOCASE)")

    def record_migration_run(
        self,
        *,
        source_path: str,
        source_fingerprint: str,
        status: str,
        details: Mapping[str, Any] | None = None,
        completed: bool = False,
    ) -> str:
        """Persist redacted migration status without recording raw legacy data."""

        run_id = str(uuid4())
        now = _utc_now()
        payload = (
            run_id,
            source_path,
            source_fingerprint,
            status,
            _json_dump(_strip_sensitive_values(dict(details or {}))),
            now,
            now if completed else None,
        )
        with self.transaction():
            self._execute(
                """
                INSERT INTO migration_runs (
                    id, source_path, source_fingerprint, status, details_json, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_fingerprint) DO UPDATE SET
                    status = excluded.status, details_json = excluded.details_json,
                    completed_at = excluded.completed_at
                """,
                payload,
            )
        return run_id

    def _execute(self, statement: str, parameters: Any = ()) -> sqlite3.Cursor:
        self._ensure_open()
        try:
            return self._connection.execute(statement, parameters)
        except sqlite3.IntegrityError:
            raise
        except sqlite3.Error as exc:
            raise RepositoryError(f"Database operation failed: {exc}") from exc

    def _fetchone(self, statement: str, parameters: Sequence[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._execute(statement, parameters).fetchone()

    def _fetchall(self, statement: str, parameters: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._execute(statement, parameters).fetchall()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RepositoryError("Database repository is closed.")


def _object_data(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict"):
        candidate = value.to_dict()
        if isinstance(candidate, Mapping):
            return dict(candidate)
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError("Expected a domain object or mapping.")


def _group_from_row(row: sqlite3.Row) -> Group:
    return Group(
        id=row["id"],
        name=row["name"],
        color=row["color"],
        icon=row["icon"],
        sort_order=row["sort_order"],
        is_favorite=bool(row["is_favorite"]),
        is_collapsed=bool(row["is_collapsed"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _account_from_row(row: sqlite3.Row) -> Account:
    return Account(
        id=row["id"],
        username=row["username"],
        user_id=row["user_id"],
        display_name=row["display_name"],
        alias=row["alias"],
        description=row["description"],
        group_id=row["group_id"],
        avatar_url=row["avatar_url"],
        status=row["status"],
        is_favorite=bool(row["is_favorite"]),
        sort_order=int(row["sort_order"]),
        last_used_at=row["last_used_at"],
        last_refreshed_at=row["last_refreshed_at"],
        saved_place_id=row["saved_place_id"],
        saved_job_id=row["saved_job_id"],
        browser_tracker_id=row["browser_tracker_id"],
        custom_fields=_json_load(row["custom_fields_json"], default={}),
        metadata=_json_load(row["metadata_json"], default={}),
        has_session=bool(row["has_session"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _game_from_row(row: sqlite3.Row) -> Game:
    return Game(
        id=row["id"],
        place_id=row["place_id"],
        universe_id=row["universe_id"],
        name=row["name"],
        description=row["description"],
        creator_name=row["creator_name"],
        creator_id=row["creator_id"],
        icon_url=row["icon_url"],
        playing=row["playing"],
        max_players=row["max_players"],
        is_favorite=bool(row["is_favorite"]),
        last_used_at=row["last_used_at"],
        metadata=_json_load(row["metadata_json"], default={}),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _activity_from_row(row: sqlite3.Row) -> Activity:
    return Activity(
        id=row["id"],
        kind=row["kind"],
        summary=row["summary"],
        account_id=row["account_id"],
        metadata=_json_load(row["metadata_json"], default={}),
        created_at=row["created_at"],
    )


def _notification_from_row(row: sqlite3.Row) -> Notification:
    action = _json_load(row["action_json"], default=None) if row["action_json"] else None
    return Notification(
        id=row["id"],
        level=row["level"],
        title=row["title"],
        message=row["message"],
        is_dismissed=bool(row["is_dismissed"]),
        action=action,
        created_at=row["created_at"],
    )


def _macro_from_row(row: sqlite3.Row) -> dict[str, Any]:
    actions = _json_load(row["actions_json"], default=[])
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "account_id": row["account_id"],
        "mode": row["mode"],
        "source": row["source"],
        "actions": actions if isinstance(actions, list) else [],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _text(value: Any) -> str:
    return str(value)


def _required_text(value: Any, label: str, *, maximum: int) -> str:
    if value is None:
        raise RepositoryError(f"{label.capitalize()} is required.")
    normalized = str(value).strip()
    if not normalized:
        raise RepositoryError(f"{label.capitalize()} is required.")
    if len(normalized) > maximum:
        raise RepositoryError(f"{label.capitalize()} exceeds {maximum} characters.")
    return normalized


def _optional_text(value: Any, *, maximum: int | None = None) -> str | None:
    if value is None:
        return None
    normalized = str(value)
    if maximum is not None and len(normalized) > maximum:
        raise RepositoryError(f"Text exceeds {maximum} characters.")
    return normalized


def _integer(value: Any, *, default: int | None) -> int | None:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise RepositoryError("Boolean values are not valid integer identifiers.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise RepositoryError("Expected an integer value.") from exc


def _positive_game_place_id(value: Any) -> int:
    parsed = _integer(value, default=None)
    if parsed is None or parsed <= 0:
        raise RepositoryError("A positive game place_id is required.")
    return parsed


def _optional_integer(value: Any) -> int | None:
    return _integer(value, default=None)


def _ordered_account_ids(values: Iterable[str]) -> tuple[str, ...]:
    return _ordered_entity_ids(values, entity_name="Account")


def _ordered_group_ids(values: Iterable[str]) -> tuple[str, ...]:
    return _ordered_entity_ids(values, entity_name="Group")


def _ordered_entity_ids(values: Iterable[str], *, entity_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray, Mapping)):
        raise RepositoryError(f"{entity_name} IDs for reordering must be an ordered iterable of non-empty strings.")
    identifiers: list[str] = []
    seen: set[str] = set()
    try:
        iterator = iter(values)
    except TypeError as exc:
        raise RepositoryError(
            f"{entity_name} IDs for reordering must be an ordered iterable of non-empty strings."
        ) from exc
    for value in iterator:
        if not isinstance(value, str):
            raise RepositoryError(f"{entity_name} IDs for reordering must be non-empty strings.")
        identifier = value.strip()
        if not identifier:
            raise RepositoryError(f"{entity_name} IDs for reordering must be non-empty strings.")
        if identifier in seen:
            raise RepositoryError(f"{entity_name} IDs for reordering must not contain duplicates.")
        seen.add(identifier)
        identifiers.append(identifier)
    return tuple(identifiers)


def _boolean(value: Any) -> int:
    return 1 if bool(value) else 0


def _positive_limit(value: int) -> int:
    parsed = _integer(value, default=None)
    if parsed is None or parsed < 1 or parsed > 10000:
        raise RepositoryError("Limit must be between 1 and 10000.")
    return parsed


def _json_dump(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise RepositoryError("Structured data is not JSON serializable.") from exc


def _json_load(value: str | None, *, default: _T) -> Any | _T:
    if value is None:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _strip_sensitive_values(value: Any) -> Any:
    """Drop sensitive-keyed data before it can enter the metadata database."""

    if isinstance(value, Mapping):
        cleaned: dict[Any, Any] = {}
        for key, item in value.items():
            if not is_sensitive_key(key):
                cleaned[key] = _strip_sensitive_values(item)
        return cleaned
    if isinstance(value, list):
        return [_strip_sensitive_values(item) for item in value]
    if isinstance(value, tuple):
        return [_strip_sensitive_values(item) for item in value]
    # Redact embedded labelled secrets in free text while retaining harmless
    # activity context such as a failed operation name.
    return redact_mapping(value)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


__all__ = [
    "ConflictError",
    "NotFoundError",
    "RepositoryError",
    "SCHEMA_VERSION",
    "SQLiteRepository",
]
