"""Application use cases composed from storage, Roblox and process services."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import sys
import threading
import time
from typing import Any

from app.backend.core.config import APP_VERSION, AppPaths, DEFAULT_SETTINGS, merge_settings
from app.backend.core.windows_startup import StartupRegistrationError, WindowsStartupManager
from app.backend.core.errors import (
    AppError,
    ConflictError,
    ExternalServiceError,
    MigrationError,
    NotFoundError,
    SecurityError,
    StorageError,
    ValidationError,
)
from app.backend.models.domain import Account, Activity, Game, Group, Notification
from app.backend.repositories.sqlite_repository import (
    ConflictError as RepositoryConflictError,
    NotFoundError as RepositoryNotFoundError,
    RepositoryError,
    SQLiteRepository,
)
from app.backend.roblox import (
    BatchLauncher,
    ClientSettingsPatcher,
    LaunchTarget,
    OAuthClientConfiguration,
    OAuthConfigurationError,
    OAuthGrant,
    OAuthGrantVault,
    OAuthIdentity,
    OAuthLoginCompletion,
    OAuthLoginCoordinator,
    RobloxAuthTools,
    RobloxClient,
    WindowsMultiInstanceController,
    WindowsRobloxLauncher,
    WindowsUwpRobloxManager,
)
from app.backend.roblox.errors import RobloxLaunchError, RobloxServiceError, RobloxUwpError
from app.backend.security.dpapi import CurrentUserDPAPI, DPAPIError, DPAPIUnavailableError
from app.backend.core.updater import UpdateChecker
from app.backend.roblox.account_utils import AccountUtils
from app.backend.roblox.player_search import PlayerSearchService
from app.backend.roblox.private_servers import PrivateServerHelper
from app.backend.roblox.random_server import RandomServerSelector
from app.backend.storage.backups import BackupError, VersionedBackupManager
from app.backend.storage.bulk_import import BulkAccountImporter
from app.backend.storage.metadata_transfer import MetadataTransfer, MetadataTransferError
from app.backend.watchers.beta_home_cleaner import BetaHomeCleaner
from app.backend.watchers import (
    MonitorPollingLoop,
    RestartPolicy,
    RestartRequest,
    RobloxPlayerLogRuntime,
    RobloxProcessMonitor,
    TerminationStatus,
)


_SETTING_ALIASES = {
    "theme": "appearance.theme",
    "accent": "appearance.accent",
    "density": "appearance.density",
    "reduce_motion": "appearance.reduced_motion",
    "launch_behavior": "general.launch_behavior",
    "close_when_empty": "instances.close_when_empty",
    "watcher_enabled": "watcher.enabled",
    "watcher_termination_enabled": "watcher.termination_enabled",
    "watcher_auto_relaunch_enabled": "watcher.auto_relaunch_enabled",
    "auto_backup": "general.auto_backup",
    "notifications": "notifications.desktop_notifications",
    "diagnostics": "developer.verbose_logs",
}

_AVATAR_COLOR_TOKENS = frozenset({"violet", "mint", "coral", "blue", "amber"})
_GROUP_COLOR_TOKENS = _AVATAR_COLOR_TOKENS | frozenset({"neutral"})
_LEGACY_GROUP_COLOR_TOKENS = {
    "#7c5cff": "violet",
    "#9c85ff": "violet",
    "#47cfa1": "mint",
    "#f58283": "coral",
    "#73a9ff": "blue",
    "#efb55d": "amber",
}


class ApplicationService:
    """A small service façade consumed by pywebview and optional local APIs.

    The class is deliberately synchronous at its boundary because pywebview
    invokes exposed methods on background workers.  Network providers still
    have strict timeouts and all public results are redacted dictionaries.
    """

    def __init__(
        self,
        *,
        paths: AppPaths | None = None,
        repository: SQLiteRepository | None = None,
        vault: CurrentUserDPAPI | None = None,
        roblox: RobloxClient | None = None,
        launcher: WindowsRobloxLauncher | None = None,
        uwp_manager: WindowsUwpRobloxManager | None = None,
        startup_manager: WindowsStartupManager | Any | None = None,
        runtime_is_frozen: bool | None = None,
        runtime_executable: Path | str | None = None,
        monitor: RobloxProcessMonitor | None = None,
        log_runtime: RobloxPlayerLogRuntime | Any | None = None,
        oauth_login: OAuthLoginCoordinator | None = None,
        client_settings: ClientSettingsPatcher | None = None,
        logger: logging.Logger | logging.LoggerAdapter[logging.Logger] | None = None,
    ) -> None:
        self.paths = paths or AppPaths.for_current_user()
        self.paths.ensure_exists()
        self.repository = repository or SQLiteRepository(self.paths.database)
        self.vault = vault or CurrentUserDPAPI()
        self.roblox = roblox or RobloxClient(
            timeout_seconds=float(DEFAULT_SETTINGS["network"]["request_timeout_seconds"])
        )
        self.launcher = launcher or WindowsRobloxLauncher()
        self.uwp_manager = uwp_manager or WindowsUwpRobloxManager()
        self._windows_startup_manager = startup_manager
        self._windows_startup_unavailable_reason: str | None = None
        if self._windows_startup_manager is None:
            frozen = bool(getattr(sys, "frozen", False)) if runtime_is_frozen is None else runtime_is_frozen
            if frozen:
                executable = runtime_executable if runtime_executable is not None else Path(sys.executable)
                try:
                    self._windows_startup_manager = WindowsStartupManager(executable)
                except ValidationError:
                    self._windows_startup_unavailable_reason = (
                        "The distributed executable required for auto-startup is unavailable."
                    )
            else:
                self._windows_startup_unavailable_reason = (
                    "Auto-startup is available in the distributed Windows executable, "
                    "not in the Python development environment."
                )
        self.monitor = monitor or RobloxProcessMonitor()
        # This observer is intentionally separate from the process monitor.
        # Typed log events are exposed for diagnostics/UI only; they are never
        # fed into close, bind, account-status, or relaunch decisions.
        self._log_runtime = log_runtime or RobloxPlayerLogRuntime()
        self.oauth_login = oauth_login or OAuthLoginCoordinator()
        self.backups = VersionedBackupManager(self.paths.backups, app_version=APP_VERSION)
        self.logger = logger or logging.getLogger("astro_account_manager.service")
        self._restore_lock = threading.RLock()
        self._watch_loop_lock = threading.RLock()
        self._launch_lock = threading.RLock()
        self._watch_loop: MonitorPollingLoop | None = None
        self._watcher_requested = False
        self._oauth_results: dict[str, dict[str, Any]] = {}
        self._nexus_server: Any = None
        self.multi_instance = WindowsMultiInstanceController()
        self.client_settings = client_settings or ClientSettingsPatcher()
        self.batch_launcher = BatchLauncher(launch_single_fn=self._batch_launch_single_adapter)
        self.auth_tools = RobloxAuthTools(roblox_client=self.roblox)
        self.account_utils = AccountUtils()
        self.player_search = PlayerSearchService(self.roblox)
        self.random_server = RandomServerSelector(self.roblox)
        self._ensure_default_settings()
        self._configure_monitor_from_settings()

    def close(self) -> None:
        """Release owned external resources on application shutdown."""

        self.stop_nexus_server()
        self.stop_watcher()
        close_client = getattr(self.roblox, "close", None)
        if callable(close_client):
            close_client()
        self.oauth_login.close()
        self.repository.close()

    # Bootstrap -------------------------------------------------------------
    def bootstrap(self) -> dict[str, Any]:
        """Return a compact, secret-free initial UI state."""

        scan = self._scan_instances(allow_restarts=True)
        return {
            "mode": "desktop",
            "version": APP_VERSION,
            "accounts": [self._account_payload(item) for item in self.repository.list_accounts()],
            "groups": [self._group_payload(item) for item in self.repository.list_groups()],
            "games": [self._game_payload(item) for item in self.repository.list_games(limit=30)],
            "instances": [self._instance_payload(item) for item in scan.instances],
            "settings": self.get_settings(),
            "nexus": self.get_nexus_status(),
            "activity": self.get_activity(),
            "notifications": self.get_notifications(),
            "diagnostics": self.get_diagnostics(include_logs=False),
        }

    # Accounts --------------------------------------------------------------
    def list_accounts(self, query: str | None = None) -> list[dict[str, Any]]:
        return [self._account_payload(item) for item in self.repository.list_accounts(search=query)]

    def create_account(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = self._require_mapping(payload, "Account data")
        username = self._required_text(data.get("username"), "Username")
        if self.repository.get_account_by_username(username) is not None:
            raise ConflictError("This username already exists in your workspace.")

        group_id = self._optional_id(data.get("group_id"))
        if group_id:
            self._get_group(group_id)

        account = Account(
            username=username,
            user_id=self._optional_int(data.get("user_id")),
            display_name=self._optional_text(data.get("display_name")) or username,
            alias=self._optional_text(data.get("alias")) or "",
            description=self._optional_text(data.get("notes") or data.get("description")) or "",
            group_id=group_id,
            is_favorite=bool(data.get("favorite", data.get("is_favorite", False))),
            status="ready",
            saved_place_id=self._optional_int(data.get("saved_place_id") or data.get("place_id")),
            saved_job_id=self._optional_text(data.get("saved_job_id") or data.get("job_id")),
            metadata={"ui": {"avatar_color": self._avatar_color(data.get("avatar_color"))}},
        )

        try:
            saved = self.repository.save_account(account)
        except RepositoryConflictError as exc:
            raise ConflictError("This username or group is already in use.") from exc
        except RepositoryError as exc:
            raise StorageError("Account could not be saved.") from exc

        # The metadata row must exist before its vault entry can satisfy the
        # foreign-key constraint.  A failed vault write leaves a valid account
        # without a session rather than a half-written secret reference.
        session = data.get("session")
        if session is not None:
            self._store_session(saved, session)
            saved.has_session = True
            try:
                saved = self.repository.save_account(saved)
            except RepositoryError as exc:
                self.repository.delete_protected_secret(saved.id, "session")
                raise StorageError("Session status could not be saved.") from exc

        self._activity("account", f"{saved.username} was added", account_id=saved.id)
        self._notice("success", "Account Added", f"{saved.username} is ready in your workspace.")
        return self._account_payload(saved)

    def update_account(self, account_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        existing = self._get_account(account_id)
        data = self._require_mapping(payload, "Account data")
        group_id = self._optional_id(data.get("group_id", existing.group_id))
        if group_id:
            self._get_group(group_id)

        mutable = existing.to_dict()
        aliases = {
            "favorite": "is_favorite",
            "notes": "description",
            "last_used": "last_used_at",
        }
        for source, target in aliases.items():
            if source in data:
                mutable[target] = data[source]
        for key in (
            "username",
            "display_name",
            "alias",
            "description",
            "avatar_url",
            "status",
            "is_favorite",
            "saved_place_id",
            "saved_job_id",
            "custom_fields",
            "metadata",
        ):
            if key in data:
                mutable[key] = data[key]
        if "user_id" in data:
            mutable["user_id"] = self._optional_int(data["user_id"])
        if "avatar_color" in data:
            metadata = dict(mutable.get("metadata") or {})
            ui_metadata = dict(metadata.get("ui") or {})
            ui_metadata["avatar_color"] = self._avatar_color(data["avatar_color"])
            metadata["ui"] = ui_metadata
            mutable["metadata"] = metadata
        if "launch_options" in data and isinstance(data["launch_options"], Mapping):
            metadata = dict(mutable.get("metadata") or {})
            metadata["launch_options"] = dict(data["launch_options"])
            mutable["metadata"] = metadata
        mutable["group_id"] = group_id
        mutable["id"] = existing.id
        mutable["has_session"] = existing.has_session
        if "session" in data:
            self._store_session(existing, data["session"])
            mutable["has_session"] = True

        try:
            saved = self.repository.save_account(mutable)
        except RepositoryConflictError as exc:
            raise ConflictError("Another account is already using this username.") from exc
        except RepositoryError as exc:
            raise StorageError("Account could not be updated.") from exc
        self._activity("account", f"{saved.username} was updated", account_id=saved.id)
        return self._account_payload(saved)

    def delete_accounts(self, account_ids: list[str] | tuple[str, ...]) -> dict[str, Any]:
        if not isinstance(account_ids, (list, tuple)) or not account_ids:
            raise ValidationError("Select at least one account to remove.")
        deleted: list[str] = []
        for account_id in dict.fromkeys(str(item) for item in account_ids if str(item).strip()):
            account = self._get_account(account_id)
            try:
                self.repository.delete_protected_secret(account.id, "session")
                if self.repository.delete_account(account.id):
                    self._forget_account_in_monitor(account.id)
                    deleted.append(account.id)
            except RepositoryError as exc:
                raise StorageError("An account could not be removed.") from exc
        self._activity("account", f"{len(deleted)} account(s) removed")
        self._notice("info", "Accounts Removed", f"{len(deleted)} account(s) were removed from this device.")
        return {"deleted": deleted}

    def reorder_accounts(self, account_ids: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
        """Persist one complete, user-chosen account order atomically."""

        if not isinstance(account_ids, (list, tuple)):
            raise ValidationError("Account order must be a complete list.")
        normalized_ids = [self._required_text(account_id, "An account ID") for account_id in account_ids]
        if len(normalized_ids) != len(set(normalized_ids)):
            raise ValidationError("Account order contains duplicates.")
        try:
            ordered = self.repository.reorder_accounts(normalized_ids)
        except RepositoryError as exc:
            raise ValidationError("Complete account order is invalid.") from exc
        self._activity("account", f"Order updated for {len(ordered)} account(s)")
        return [self._account_payload(account) for account in ordered]

    # Public Roblox profile, avatar and presence --------------------------
    def get_public_profile(self, user_id: int | str) -> dict[str, Any]:
        """Retrieve a credential-free public Roblox profile by numeric UserId."""

        normalized = self._positive_int(user_id, "User ID")
        try:
            profile = self.roblox.get_public_profile(normalized)
        except RobloxServiceError as exc:
            raise ExternalServiceError(str(exc), retryable=getattr(exc, "retryable", False)) from exc
        exporter = getattr(profile, "to_dict", None)
        if not callable(exporter):
            raise ExternalServiceError("Roblox public profile is invalid.")
        payload = exporter()
        if not isinstance(payload, Mapping):
            raise ExternalServiceError("Roblox public profile is invalid.")
        return dict(payload)

    def refresh_account_public_profile(self, account_id: str) -> dict[str, Any]:
        """Persist current public identity and avatar data for one local account.

        This mirrors the legacy ``Account.GetUserInfo`` plus avatar display
        behavior.  It never reads a session from the vault and deliberately
        keeps the user-chosen local username stable if Roblox renamed it.
        """

        account = self._get_account(account_id)
        if account.user_id is None:
            raise ValidationError("Associate a Roblox User ID with this account before refreshing its profile.")
        profile = self.get_public_profile(account.user_id)
        metadata = dict(account.metadata)
        metadata["public_profile"] = {
            key: profile.get(key)
            for key in (
                "user_id",
                "username",
                "display_name",
                "description",
                "created_at",
                "is_banned",
                "has_verified_badge",
                "profile_url",
                "avatar_state",
            )
        }
        metadata["public_profile"]["refreshed_at"] = _utc_now()
        account.metadata = metadata
        account.display_name = self._optional_text(profile.get("display_name")) or account.display_name or account.username
        avatar_url = profile.get("avatar_url")
        if isinstance(avatar_url, str):
            account.avatar_url = avatar_url
        account.last_refreshed_at = _utc_now()
        try:
            saved = self.repository.save_account(account)
        except RepositoryError as exc:
            raise StorageError("Le profil public n'a pas pu etre enregistre.") from exc
        self._activity("profile", f"Profil public actualise pour {saved.username}", account_id=saved.id)
        return {"account": self._account_payload(saved), "profile": profile}

    def get_public_presence(self, user_ids: list[int | str] | tuple[int | str, ...]) -> list[dict[str, Any]]:
        """Return a bounded, cached public presence lookup for explicit users."""

        if not isinstance(user_ids, (list, tuple)) or not user_ids:
            raise ValidationError("Selectionnez au moins un UserId pour la presence.")
        normalized = list(dict.fromkeys(self._positive_int(value, "Le UserId") for value in user_ids))
        if len(normalized) > 50:
            raise ValidationError("La presence est limitee a 50 utilisateurs par requete.")
        try:
            presence = self.roblox.get_public_presence(normalized)
        except RobloxServiceError as exc:
            raise ExternalServiceError(str(exc), retryable=getattr(exc, "retryable", False)) from exc
        payload: list[dict[str, Any]] = []
        for entry in presence:
            exporter = getattr(entry, "to_dict", None)
            if not callable(exporter):
                continue
            item = exporter()
            if isinstance(item, Mapping):
                payload.append(dict(item))
        return payload

    def refresh_account_presence(self, account_ids: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
        """Refresh public presence metadata for up to 50 selected local accounts.

        Presence is intentionally kept separate from the process/watcher's
        ``status`` field: a remote ``in_game`` indication must not overwrite a
        verified local process state.
        """

        if not isinstance(account_ids, (list, tuple)) or not account_ids:
            raise ValidationError("Select at least one account for presence.")
        unique_ids = list(dict.fromkeys(self._optional_id(value) for value in account_ids))
        if any(value is None for value in unique_ids):
            raise ValidationError("An account ID is invalid.")
        if len(unique_ids) > 50:
            raise ValidationError("Presence is limited to 50 accounts per request.")
        accounts = [self._get_account(str(account_id)) for account_id in unique_ids]
        if any(account.user_id is None for account in accounts):
            raise ValidationError("Each selected account must have a Roblox User ID.")
        records = self.get_public_presence([int(account.user_id) for account in accounts if account.user_id is not None])
        by_user_id = {item.get("user_id"): item for item in records if isinstance(item.get("user_id"), int)}
        refreshed_at = _utc_now()
        result: list[dict[str, Any]] = []
        for account in accounts:
            snapshot = by_user_id.get(account.user_id)
            metadata = dict(account.metadata)
            metadata["public_presence"] = {
                **(snapshot or {"state": "unavailable", "user_id": account.user_id}),
                "refreshed_at": refreshed_at,
            }
            account.metadata = metadata
            account.last_refreshed_at = refreshed_at
            try:
                saved = self.repository.save_account(account)
            except RepositoryError as exc:
                raise StorageError("La presence publique n'a pas pu etre enregistree.") from exc
            result.append({"account_id": saved.id, "user_id": saved.user_id, "presence": snapshot})
        return result

    # Groups ----------------------------------------------------------------
    def list_groups(self) -> list[dict[str, Any]]:
        return [self._group_payload(item) for item in self.repository.list_groups()]

    def create_group(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = self._require_mapping(payload, "Group data")
        name = self._required_text(data.get("name"), "Group name")
        groups = self.repository.list_groups()
        order_value = data.get("order", data.get("sort_order", len(groups)))
        try:
            sort_order = int(order_value)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Group sort order must be an integer.") from exc
        group = Group(
            name=name,
            color=self._group_color(data.get("color")),
            icon=self._optional_text(data.get("icon")) or "folder",
            sort_order=sort_order,
        )
        try:
            saved = self.repository.save_group(group)
        except RepositoryError as exc:
            raise StorageError("Group could not be saved.") from exc
        self._activity("group", f"Group {saved.name} created")
        return self._group_payload(saved)

    def update_group(self, group_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Update persistent group presentation/state without touching members."""

        existing = self._get_group(group_id)
        data = self._require_mapping(payload, "Group data")
        mutable = existing.to_dict()
        aliases = {
            "favorite": "is_favorite",
            "collapsed": "is_collapsed",
            "order": "sort_order",
        }
        for source, target in aliases.items():
            if source in data:
                mutable[target] = data[source]
        for key in ("name", "color", "icon", "sort_order", "is_favorite", "is_collapsed"):
            if key in data:
                mutable[key] = data[key]
        if "name" in mutable:
            mutable["name"] = self._required_text(mutable["name"], "Group name")
        if "color" in mutable:
            mutable["color"] = self._group_color(mutable["color"])
        if "icon" in mutable:
            mutable["icon"] = self._optional_text(mutable["icon"]) or "folder"
        if not isinstance(mutable.get("sort_order"), int):
            try:
                mutable["sort_order"] = int(mutable["sort_order"])
            except (TypeError, ValueError) as exc:
                raise ValidationError("Group sort order must be an integer.") from exc
        mutable["id"] = existing.id
        try:
            saved = self.repository.save_group(mutable)
        except RepositoryConflictError as exc:
            raise ConflictError("A group with this name already exists.") from exc
        except RepositoryError as exc:
            raise StorageError("Group could not be updated.") from exc
        self._activity("group", f"Group {saved.name} updated")
        return self._group_payload(saved)

    def delete_group(self, group_id: str) -> dict[str, Any]:
        """Remove a group and safely leave its accounts ungrouped."""

        group = self._get_group(group_id)
        try:
            deleted = self.repository.delete_group(group_id)
        except RepositoryError as exc:
            raise StorageError("Group could not be deleted.") from exc
        if not deleted:
            raise NotFoundError("Group not found.")
        self._activity("group", f"Group {group.name} deleted")
        self._notice("info", "Group Removed", "Associated accounts are now ungrouped.")
        return {"deleted": group_id}

    def move_accounts(self, account_ids: list[str] | tuple[str, ...], group_id: str | None) -> dict[str, Any]:
        if not isinstance(account_ids, (list, tuple)) or not account_ids:
            raise ValidationError("Select at least one account to move.")
        if group_id:
            self._get_group(group_id)
        try:
            moved = self.repository.move_accounts(account_ids, group_id)
        except RepositoryError as exc:
            raise StorageError("Accounts could not be moved.") from exc
        self._activity("group", f"{moved} account(s) moved")
        return {"moved": list(account_ids), "count": moved, "group_id": group_id}

    # Games and servers -----------------------------------------------------
    def list_games(self) -> list[dict[str, Any]]:
        return [self._game_payload(item) for item in self.repository.list_games(limit=100)]

    def list_recent_games(self) -> list[dict[str, Any]]:
        """Return the bounded most-recent game history, newest first."""

        return [
            self._game_payload(item)
            for item in self.repository.list_games(recent_only=True, limit=self._max_recent_games())
        ]

    def list_favorite_games(self) -> list[dict[str, Any]]:
        """Return persisted game favourites independently from recency."""

        return [self._game_payload(item) for item in self.repository.list_games(favorites_only=True, limit=100)]

    def get_game(self, place_id: int | str) -> dict[str, Any]:
        normalized = self._positive_int(place_id, "Place ID")
        cached = self.repository.get_game_by_place_id(normalized)
        try:
            game = self.roblox.get_game_details(normalized)
            game.is_favorite = cached.is_favorite if cached else False
            game.last_used_at = _utc_now()
            game = self._save_recent_game(game)
        except RobloxServiceError as exc:
            if cached:
                try:
                    cached = self._save_recent_game(cached)
                except RepositoryError as storage_error:
                    raise StorageError("Recent game could not be saved.") from storage_error
                return self._game_payload(cached, stale=True)
            raise ExternalServiceError(str(exc), retryable=getattr(exc, "retryable", False)) from exc
        except RepositoryError as exc:
            raise StorageError("Game details could not be saved.") from exc
        return self._game_payload(game)

    def set_game_favorite(self, place_id: int | str, favorite: bool) -> dict[str, Any]:
        """Mark or unmark a persisted game favourite without touching recency."""

        normalized = self._positive_int(place_id, "Place ID")
        if not isinstance(favorite, bool):
            raise ValidationError("Game favorite state is invalid.")
        try:
            game = self.repository.get_game_by_place_id(normalized)
        except RepositoryError as exc:
            raise StorageError("Local game record could not be read.") from exc
        if game is None:
            if not favorite:
                raise NotFoundError("This game is not saved locally.")
            try:
                game = self.roblox.get_game_details(normalized)
            except RobloxServiceError as exc:
                raise ExternalServiceError(str(exc), retryable=getattr(exc, "retryable", False)) from exc
            game.is_favorite = True
            game.last_used_at = None
            try:
                saved = self.repository.save_game(game)
            except RepositoryError as exc:
                raise StorageError("Game favorite could not be saved.") from exc
        else:
            try:
                saved = self.repository.set_game_favorite(normalized, favorite)
            except RepositoryError as exc:
                raise StorageError("Game favorite could not be updated.") from exc
        self._activity("game", "Game added to favorites" if favorite else "Game removed from favorites", metadata={"place_id": normalized})
        return self._game_payload(saved)

    def remove_game(self, place_id: int | str) -> dict[str, Any]:
        """Remove one locally stored game record and its favourite marker."""

        normalized = self._positive_int(place_id, "Place ID")
        try:
            deleted = self.repository.delete_game_by_place_id(normalized)
        except RepositoryError as exc:
            raise StorageError("Game could not be removed.") from exc
        if not deleted:
            raise NotFoundError("This game is not saved locally.")
        self._activity("game", "Game removed from local library", metadata={"place_id": normalized})
        return {"deleted": normalized}

    def list_servers(self, place_id: int | str) -> list[dict[str, Any]]:
        normalized = self._positive_int(place_id, "Le PlaceId")
        try:
            page = self.roblox.list_public_servers(normalized)
        except RobloxServiceError as exc:
            raise ExternalServiceError(str(exc), retryable=getattr(exc, "retryable", False)) from exc
        return [self._server_payload(server) for server in page.servers]

    def launch_account(self, account_id: str, target: Mapping[str, Any] | None = None) -> dict[str, Any]:
        account = self._get_account(account_id)
        target_data = dict(target or {})
        place_id = target_data.get("place_id") or target_data.get("placeId") or account.saved_place_id
        if place_id is None:
            raise ValidationError("Choose a Place ID before launching Roblox.")
        launch_target = LaunchTarget(
            place_id=self._positive_int(place_id, "Place ID"),
            job_id=self._optional_text(target_data.get("job_id") or target_data.get("jobId")),
        )

        with self._launch_lock:
            multi_instance_enabled = bool(
                self.get_settings()["categories"].get("instances", {}).get("allow_multiple_launches", False)
                or self.multi_instance.is_enabled
            )
            if multi_instance_enabled:
                self.multi_instance.enable_multi_instance()

            # Apply per-account or per-launch FPS Cap & Potato Graphics settings
            launch_opts = account.metadata.get("launch_options", {}) if isinstance(account.metadata, dict) else {}
            fps_target = target_data.get("fps") or target_data.get("fps_cap") or launch_opts.get("max_fps") or self.client_settings.get_fps_cap()
            potato_mode = target_data.get("potato") if "potato" in target_data else (target_data.get("potato_graphics") if "potato_graphics" in target_data else launch_opts.get("potato_graphics", self.get_settings()["categories"].get("performance", {}).get("potato_graphics", False)))
            try:
                self.client_settings.patch_launch_settings(fps=int(fps_target) if fps_target else 0, potato_graphics=bool(potato_mode))
            except Exception as patch_exc:
                self.logger.warning(f"Could not apply launch ClientSettings: {patch_exc}")

            try:
                result = self.launcher.launch(launch_target)
            except RobloxLaunchError as exc:
                raise ExternalServiceError(str(exc), retryable=False) from exc

            # Bounded flag initialization hold window (e.g. 1.2s max) to prevent FastFlags collision
            # during rapid consecutive or parallel multi-account launches
            if result.launched:
                time.sleep(1.2)

        watcher_request_id = self._register_launch_intent(account, launch_target)

        account.status = "launching"
        account.last_used_at = _utc_now()
        account.saved_place_id = launch_target.place_id
        account.saved_job_id = launch_target.job_id
        try:
            self.repository.save_account(account)
        except RepositoryError:
            self._notice("warning", "Launch Sent", "Roblox was opened, but metadata could not be updated.")
        if result.launched:
            try:
                self._record_recent_game(launch_target.place_id)
            except RepositoryError:
                self._notice("warning", "Launch Sent", "Roblox was opened, but recent game history could not be saved.")
        self._activity("launch", f"Launch requested for {account.username}", account_id=account.id, metadata={"place_id": launch_target.place_id})
        self._notice("success", "Launch Requested", f"Windows is launching Roblox for {account.username}.")
        return {
            "accepted": bool(result.launched),
            "account_id": account.id,
            "target": {"place_id": launch_target.place_id, "job_id": launch_target.job_id},
            "watcher_request_id": watcher_request_id,
        }

    # UWP packages ---------------------------------------------------------
    def list_uwp_packages(self) -> dict[str, Any]:
        """Discover current-user Roblox UWP registrations without mutating them.

        A non-Windows host or a temporarily unavailable AppX subsystem is a
        capability state rather than an application failure.  The response is
        deliberately metadata-only: no package install path, session, account
        association, or manifest content crosses the bridge.
        """

        try:
            packages = self.uwp_manager.list_packages()
        except RobloxUwpError as exc:
            return {"available": False, "reason": exc.message, "packages": []}
        return {
            "available": True,
            "reason": None,
            "packages": [package.to_dict() for package in packages],
        }

    def launch_uwp_package(self, package_full_name: str) -> dict[str, Any]:
        """Ask Windows to launch a Roblox app already registered for this user."""

        result = self.uwp_manager.launch_package(package_full_name)
        self._activity("launch", "Roblox UWP launch requested", metadata={"uwp": True})
        self._notice("success", "UWP Launch Requested", "Windows is launching the selected Roblox app.")
        return result.to_dict()

    # Process monitor -------------------------------------------------------
    def list_instances(self) -> list[dict[str, Any]]:
        return [self._instance_payload(item) for item in self.monitor.current_instances()]

    def refresh_instances(self) -> list[dict[str, Any]]:
        scan = self._scan_instances(allow_restarts=True)
        return [self._instance_payload(item) for item in scan.instances]

    def get_instance_monitor(self) -> dict[str, Any]:
        """Return current local process state and bounded redacted history."""

        history_method = getattr(self.monitor, "history", None)
        history = history_method() if callable(history_method) else ()
        pending_method = getattr(self.monitor, "pending_restarts", None)
        pending = pending_method() if callable(pending_method) else ()
        return {
            "instances": self.list_instances(),
            "events": [item.to_dict() if hasattr(item, "to_dict") else {"kind": getattr(item, "kind", "instance"), "pid": getattr(item, "pid", 0), "occurred_at": getattr(item, "occurred_at", None)} for item in history],
            "log_watcher": self._log_watcher_payload(),
            "log_events": self._log_event_payloads(),
            "pending_restarts": [self._restart_payload(item) for item in pending],
            "last_scan_complete": bool(getattr(self.monitor, "last_scan_complete", True)),
            "termination_enabled": bool(getattr(self.monitor, "termination_enabled", False)),
        }

    def close_instance(self, pid: int, *, confirm: bool = False) -> dict[str, Any]:
        """Gracefully close one verified process after explicit user confirmation."""

        terminator = getattr(self.monitor, "terminate_known_process", None)
        if not callable(terminator):
            raise ValidationError("Instance closing is unavailable.")
        before = next((item for item in self.monitor.current_instances() if item.pid == pid), None)
        result = terminator(pid, confirm=confirm)
        if result.status is TerminationStatus.TERMINATED and before is not None and before.account_id:
            self._set_account_runtime_status(before.account_id, "ready")
        self._activity(
            "instance",
            f"Roblox instance closing: {result.status.value}",
            account_id=before.account_id if before is not None else None,
            metadata={"pid": result.pid, "status": result.status.value},
        )
        return {"pid": result.pid, "status": result.status.value, "message": result.message}

    def bind_instance(
        self,
        pid: int,
        account_id: str,
        target: Mapping[str, Any] | None = None,
        *,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Explicitly associate an orphaned local client with an account record."""

        account = self._get_account(account_id)
        target_data = dict(target or {})
        place_id = target_data.get("place_id") or target_data.get("placeId") or account.saved_place_id
        if place_id is None:
            raise ValidationError("Choose a Place ID before associating this instance.")
        binder = getattr(self.monitor, "bind_orphan", None)
        if not callable(binder):
            raise ValidationError("Instance association is unavailable.")
        instance = binder(
            self._positive_int(pid, "PID"),
            account_id=account.id,
            account_username=account.username,
            place_id=self._positive_int(place_id, "Place ID"),
            job_id=self._optional_text(target_data.get("job_id") or target_data.get("jobId")),
            restart_policy=self._restart_policy_for(account),
            confirm=confirm,
        )
        self._set_account_runtime_status(account.id, "in_game")
        self._activity(
            "instance",
            f"Instance associated with {account.username}",
            account_id=account.id,
            metadata={"pid": instance.pid, "place_id": instance.place_id},
        )
        return self._instance_payload(instance)

    def configure_account_watcher(self, account_id: str, rule: Mapping[str, Any]) -> dict[str, Any]:
        """Persist an explicit, bounded per-account automatic relaunch rule."""

        account = self._get_account(account_id)
        normalized = self._validated_account_watcher_rule(rule, existing=account.metadata.get("watcher"))
        metadata = dict(account.metadata)
        metadata["watcher"] = normalized
        account.metadata = metadata
        try:
            saved = self.repository.save_account(account)
        except RepositoryError as exc:
            raise StorageError("Watcher rule could not be saved.") from exc
        self._activity(
            "watcher",
            f"Relaunch rule updated for {saved.username}",
            account_id=saved.id,
            metadata={"auto_relaunch": normalized["auto_relaunch"]},
        )
        return {"account_id": saved.id, **normalized}

    # Official Roblox OAuth identity linking --------------------------------
    def start_oauth_login(self) -> dict[str, Any]:
        """Open the system browser for an opt-in Roblox OAuth PKCE flow.

        This links a public Roblox identity and stores Open Cloud tokens in the
        Windows vault after consent.  It deliberately does not obtain or
        modify a game-client cookie/session.
        """

        config = self._oauth_configuration()
        if not self.vault.available:
            raise SecurityError("Windows Vault is required before connecting a Roblox account.")
        snapshot = self.oauth_login.start(config)
        self._oauth_results.pop(snapshot.operation_id, None)
        self._activity("oauth", "Roblox OAuth login started")
        return snapshot.as_public_dict()

    def poll_oauth_login(self, operation_id: str) -> dict[str, Any]:
        """Return safe pending/completed OAuth state without exposing tokens."""

        identifier = self._oauth_operation_id(operation_id)
        remembered = self._oauth_results.get(identifier)
        if remembered is not None:
            return deepcopy(remembered)

        result = self.oauth_login.poll(identifier)
        if not isinstance(result, OAuthLoginCompletion):
            return result.as_public_dict()

        account = self._persist_oauth_connection(result.identity, result.grant)
        payload = {**result.snapshot.as_public_dict(), "account": account}
        self._oauth_results[identifier] = payload
        self._activity("oauth", f"{account['username']} was connected via OAuth", account_id=account["id"])
        self._notice("success", "Account Connected", f"{account['username']} was linked via Roblox OAuth.")
        return deepcopy(payload)

    def cancel_oauth_login(self, operation_id: str) -> dict[str, Any]:
        """Stop a pending local callback receiver and discard its PKCE state."""

        identifier = self._oauth_operation_id(operation_id)
        self._oauth_results.pop(identifier, None)
        snapshot = self.oauth_login.cancel(identifier)
        self._activity("oauth", "Roblox OAuth login cancelled")
        return snapshot.as_public_dict()

    def refresh_oauth_account(self, account_id: str) -> dict[str, Any]:
        """Rotate an OAuth refresh grant and refresh the linked public profile."""

        config = self._oauth_configuration()
        account = self._get_account(account_id)
        grants = self._oauth_grant_vault()
        current_grant = grants.load(account.id)
        if current_grant is None:
            raise NotFoundError("This account is not connected via Roblox OAuth.")
        refreshed_grant, identity = self.oauth_login.refresh(config, current_grant)
        if account.user_id is not None and account.user_id != identity.user_id:
            raise SecurityError("The received OAuth profile does not match the selected account.")
        saved = self._persist_oauth_connection(
            identity,
            refreshed_grant,
            expected_account_id=account.id,
            previous_grant=current_grant,
        )
        self._activity("oauth", f"{saved['username']} was refreshed via OAuth", account_id=saved["id"])
        return saved

    def disconnect_oauth_account(self, account_id: str) -> dict[str, Any]:
        """Forget the local OAuth grant while preserving the local account profile.

        This is a local disconnect.  It neither reads a browser cookie nor
        invents a game-client logout operation.
        """

        account = self._get_account(account_id)
        grants = self._oauth_grant_vault()
        grants.delete(account.id)
        metadata = dict(account.metadata)
        metadata.pop("oauth", None)
        account.metadata = metadata
        try:
            saved = self.repository.save_account(account)
        except RepositoryError as exc:
            raise StorageError("OAuth connection status could not be updated.") from exc
        payload = self._account_payload(saved)
        self._activity("oauth", f"{payload['username']} was disconnected locally", account_id=saved.id)
        self._notice("info", "Connection Removed", "Local OAuth tokens for this account were removed.")
        return payload

    # Settings --------------------------------------------------------------
    def get_settings(self) -> dict[str, Any]:
        nested = deepcopy(DEFAULT_SETTINGS)
        stored = self.repository.list_settings()
        for path, value in stored.items():
            self._set_path(nested, path, value)
        flat = {
            "theme": nested["appearance"]["theme"],
            "accent": nested["appearance"]["accent"],
            "density": nested["appearance"]["density"],
            "reduce_motion": nested["appearance"]["reduced_motion"],
            "watcher_enabled": nested["watcher"]["enabled"],
            "watcher_termination_enabled": nested["watcher"].get("termination_enabled", False),
            "watcher_auto_relaunch_enabled": nested["watcher"].get("auto_relaunch_enabled", False),
            "auto_backup": nested["general"]["auto_backup"],
            "notifications": nested["notifications"]["desktop_notifications"],
            "diagnostics": nested["developer"]["verbose_logs"],
            "launch_behavior": nested["general"].get("launch_behavior", "confirm"),
            "close_when_empty": nested["instances"].get("close_when_empty", False),
            "categories": nested,
        }
        return flat

    def update_settings(self, values: Mapping[str, Any]) -> dict[str, Any]:
        data = self._require_mapping(values, "Settings parameters")
        nested_updates: dict[str, Any] = {}
        for key, value in data.items():
            if key == "categories" and isinstance(value, Mapping):
                nested_updates = merge_settings(nested_updates, dict(value))
                continue
            path = _SETTING_ALIASES.get(key, key if "." in key else None)
            if path:
                self._set_path(nested_updates, path, value)
        if not nested_updates:
            raise ValidationError("No recognized settings parameters provided.")
        general_updates = nested_updates.get("general")
        if isinstance(general_updates, Mapping) and "start_with_windows" in general_updates:
            raise ValidationError(
                "Use the dedicated Windows startup action with explicit confirmation."
            )
        candidate = merge_settings(self.get_settings()["categories"], nested_updates)
        self._validate_settings(candidate)
        for path, value in _flatten_settings(nested_updates).items():
            self.repository.set_setting(path, value)
        if "general.max_recent_games" in _flatten_settings(nested_updates):
            try:
                self.repository.prune_recent_games(self._max_recent_games())
            except RepositoryError as exc:
                raise StorageError("Recent games limit could not be applied.") from exc
        self._configure_monitor_from_settings()
        self._sync_watcher_loop()
        self._activity("settings", "Settings updated")
        return self.get_settings()

    def get_windows_startup_status(self) -> dict[str, Any]:
        """Return the real current-user Run capability without exposing a path.

        Development runs intentionally report an unavailable capability instead
        of registering ``python.exe``.  A frozen Windows build creates the
        manager from its own executable, while tests can inject a manager.
        """

        configured = self._windows_startup_configured()
        manager = self._windows_startup_manager
        if manager is None:
            return {
                "available": False,
                "supported": False,
                "accessible": False,
                "registered": False,
                "enabled": False,
                "needs_repair": False,
                "configured": configured,
                "reason": self._windows_startup_unavailable_reason
                or "Automatic startup is unavailable.",
            }
        try:
            status = manager.inspect()
        except StartupRegistrationError:
            return {
                "available": False,
                "supported": True,
                "accessible": False,
                "registered": False,
                "enabled": False,
                "needs_repair": False,
                "configured": configured,
                "reason": "Windows startup registration is inaccessible.",
            }
        payload = status.to_dict()
        payload["available"] = bool(payload.get("supported") and payload.get("accessible"))
        payload["configured"] = configured
        return payload

    def set_windows_startup(self, enabled: bool, confirm: bool = False) -> dict[str, Any]:
        """Explicitly enable or disable Astro's own current-user Run value."""

        if not isinstance(enabled, bool):
            raise ValidationError("Windows startup state must be boolean.")
        if confirm is not True:
            raise ValidationError("Confirm the Windows startup modification.")
        manager = self._windows_startup_manager
        if manager is None:
            raise ValidationError(
                self._windows_startup_unavailable_reason
                or "Automatic startup is unavailable."
            )
        try:
            status = manager.enable() if enabled else manager.disable()
        except StartupRegistrationError as exc:
            raise StorageError("Windows could not modify automatic startup.") from exc

        status_payload = status.to_dict()
        if bool(status_payload.get("enabled")) is not enabled:
            raise StorageError("Windows did not confirm automatic startup modification.")
        try:
            self.repository.set_setting("general.start_with_windows", enabled)
        except RepositoryError as exc:
            # Persist only after Windows has confirmed the requested state.  A
            # best-effort compensation prevents a stale preference whenever
            # the local database happens to fail afterwards.
            try:
                manager.disable() if enabled else manager.enable()
            except StartupRegistrationError:
                self.logger.error("Could not compensate Windows startup after a settings write failure.")
            raise StorageError("Windows startup setting could not be saved.") from exc

        self._activity("settings", "Windows startup enabled" if enabled else "Windows startup disabled")
        self._notice(
            "success" if enabled else "info",
            "Windows Startup Updated",
            "Astro Account Manager will start with your Windows session."
            if enabled
            else "Astro Account Manager will no longer start automatically.",
        )
        status_payload["available"] = bool(
            status_payload.get("supported") and status_payload.get("accessible")
        )
        status_payload["configured"] = enabled
        return status_payload

    # Activity, notifications, backup and migration ------------------------
    def get_activity(self) -> list[dict[str, Any]]:
        return [self._activity_payload(item) for item in self.repository.list_activity(limit=100)]

    def get_notifications(self) -> list[dict[str, Any]]:
        return [self._notification_payload(item) for item in self.repository.list_notifications(limit=100)]

    def dismiss_notification(self, notification_id: str) -> dict[str, Any]:
        try:
            dismissed = self.repository.dismiss_notification(notification_id)
        except RepositoryError as exc:
            raise StorageError("Notification could not be dismissed.") from exc
        if not dismissed:
            raise NotFoundError("Notification not found.")
        return {"dismissed": notification_id}

    def backup_data(self) -> dict[str, Any]:
        if self.repository.database_path is None:
            raise StorageError("Backups are not available for in-memory database.")
        try:
            record = self.backups.create_sqlite_backup(self.repository.database_path, label="manual")
        except BackupError as exc:
            raise StorageError("Backup could not be created.") from exc
        self._activity("backup", "Verified local backup created", metadata={"backup_id": record.backup_id})
        self._notice("success", "Backup Completed", "A verified copy of your workspace metadata has been created.")
        return {
            "id": record.backup_id,
            "path": str(self.paths.backups),
            "size": record.size_bytes,
            "created_at": record.created_at,
            "verified": self.backups.verify(record),
        }

    def list_backups(self) -> list[dict[str, Any]]:
        """List only verified backup manifests, newest first."""

        try:
            records = self.backups.list_backups(verify=True)
        except BackupError as exc:
            raise StorageError("Backups could not be read.") from exc
        return [
            {
                "id": record.backup_id,
                "created_at": record.created_at,
                "size": record.size_bytes,
                "label": record.label,
                "source_name": record.source_name,
                "verified": True,
            }
            for record in records
        ]

    def export_metadata(self) -> dict[str, Any]:
        """Create a portable, checksummed export containing no credentials."""

        filename = f"astro-metadata-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}.json"
        destination = self.paths.exports / filename
        try:
            exported = MetadataTransfer(self.repository).export_to(destination)
            size = exported.stat().st_size
        except (MetadataTransferError, OSError) as exc:
            raise StorageError("Metadata could not be exported.") from exc
        self._activity("export", "Metadata exported", metadata={"filename": exported.name})
        self._notice("success", "Export Completed", "A secret-free metadata export was created.")
        return {"path": str(exported), "filename": exported.name, "size": size, "classification": "public_metadata_only"}

    def import_metadata(self, path: str, *, confirm: bool = False) -> dict[str, Any]:
        """Import a portable public-metadata file after a verified safety backup."""

        if not confirm:
            raise ValidationError("Import requires explicit confirmation.")
        if not isinstance(path, str) or not path.strip():
            raise ValidationError("Metadata file path is required.")
        if self.repository.database_path is None:
            raise StorageError("Import is not available for in-memory database.")
        try:
            safety = self.backups.create_sqlite_backup(self.paths.database, label="pre-metadata-import")
            report = MetadataTransfer(self.repository).import_from(path)
        except MetadataTransferError as exc:
            raise ValidationError("Metadata file is invalid or contains unauthorized data.") from exc
        except BackupError as exc:
            raise StorageError("Pre-import safety backup could not be created.") from exc
        except RepositoryError as exc:
            raise StorageError("Metadata could not be imported.") from exc
        report_data = report.to_dict()
        self._activity("import", "Metadata imported", metadata={"filename": Path(path).name, **report_data})
        self._notice("success", "Import Completed", "Compatible metadata was added without importing secrets.")
        return {**report_data, "pre_import_backup": safety.backup_id, "classification": "public_metadata_only"}

    def restore_backup(self, backup_id: str, *, confirm: bool = False) -> dict[str, Any]:
        """Restore a verified database snapshot after an explicit confirmation.

        A pre-restore snapshot is created first. The repository is deliberately
        reopened only after the atomic file replacement succeeds, preventing an
        in-memory connection from continuing against a replaced SQLite file on
        Windows.
        """

        if not confirm:
            raise ValidationError("Restore requires explicit confirmation.")
        if not isinstance(backup_id, str) or not backup_id.strip():
            raise ValidationError("Backup ID to restore is invalid.")
        if self.repository.database_path is None:
            raise StorageError("Restore is not available for in-memory database.")
        watcher_was_requested = self._watcher_requested
        self._stop_watcher_worker()
        with self._restore_lock:
            try:
                record = self.backups.get_backup(backup_id)
                if record.source_name != self.paths.database.name or not self.backups.verify(record):
                    raise BackupError("This backup is not a verified Astro Account Manager backup.")
                safety = self.backups.create_sqlite_backup(self.paths.database, label="pre-restore")
                self.repository.checkpoint()
                self.repository.close()
                self._remove_sqlite_sidecars()
                self.backups.restore(record, self.paths.database, overwrite=True)
                self.repository = SQLiteRepository(self.paths.database)
                self._ensure_default_settings()
            except BackupError as exc:
                self._reopen_repository_after_failed_restore()
                raise StorageError("Backup could not be restored.") from exc
            except RepositoryError as exc:
                self._reopen_repository_after_failed_restore()
                raise StorageError("Restored database could not be opened.") from exc
            except StorageError:
                self._reopen_repository_after_failed_restore()
                raise
            except OSError as exc:
                self._reopen_repository_after_failed_restore()
                raise StorageError("Backup could not be restored.") from exc
            finally:
                self._configure_monitor_from_settings()
                if watcher_was_requested:
                    self._sync_watcher_loop()
        self._activity("restore", "Backup restored", metadata={"backup_id": backup_id, "safety_backup_id": safety.backup_id})
        self._notice("info", "Restore Completed", "Backup was restored; a pre-restore backup copy is available.")
        return {
            "restored": backup_id,
            "pre_restore_backup": safety.backup_id,
            "verified": True,
        }

    def migrate_legacy(self, path: str, *, include_sessions: bool = False, password: str | None = None) -> dict[str, Any]:
        """Run the explicit importer without ever altering the selected source.

        The implementation is imported lazily so a desktop build can still show
        a useful compatibility error if an optional legacy crypto dependency is
        unavailable.
        """

        candidate = Path(path).expanduser()
        if not candidate.exists():
            raise ValidationError("Selected legacy directory was not found.")
        try:
            from app.backend.storage.legacy_migrator import LegacyDataMigrator
        except ImportError as exc:
            raise MigrationError("Legacy migration module is not available.") from exc
        migrator = LegacyDataMigrator(
            repository=self.repository,
            backup_manager=self.backups,
            dpapi=self.vault,
        )
        try:
            report = migrator.migrate(
                candidate,
                import_account_metadata=True,
                include_sessions=include_sessions,
                include_saved_passwords=False,
                confirm_secret_import=include_sessions,
                password=password,
            )
        except (RepositoryError, DPAPIError, BackupError, ValueError) as exc:
            raise MigrationError("Legacy migration could not be completed.") from exc
        report_data = _migration_payload(report)
        self._activity("migration", "Legacy migration analyzed", metadata=report_data)
        self._notice("info", "Migration Completed", "Review the report for imported or skipped items.")
        return report_data

    def get_diagnostics(self, *, include_logs: bool = True) -> dict[str, Any]:
        dpapi_status = self.vault.status
        logs = self._read_recent_log_lines() if include_logs else []
        services = [
            {"name": "Storage vault", "status": "healthy", "detail": f"Schema v{self.repository.schema_version}"},
            {"name": "Windows DPAPI", "status": "healthy" if dpapi_status.available else "degraded", "detail": dpapi_status.reason or "CurrentUser vault available"},
            {"name": "Instance watcher", "status": "healthy", "detail": f"{len(self.monitor.current_instances())} instance(s) observed"},
            {"name": "Roblox gateway", "status": "healthy", "detail": "Public client ready"},
        ]
        return {
            "status": "degraded" if any(item["status"] == "degraded" for item in services) else "healthy",
            "checked_at": _utc_now(),
            "services": services,
            "logs": logs,
            "data_root": str(self.paths.root),
        }

    # Private helpers -------------------------------------------------------
    def _ensure_default_settings(self) -> None:
        stored = self.repository.list_settings()
        for path, value in _flatten_settings(DEFAULT_SETTINGS).items():
            if path not in stored:
                self.repository.set_setting(path, value)

    def _max_recent_games(self) -> int:
        """Return the validated local recent-game limit with a safe fallback."""

        try:
            value = self.get_settings()["categories"]["general"]["max_recent_games"]
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1_000:
                raise ValueError("invalid max recent games")
            return value
        except (KeyError, TypeError, ValueError, RepositoryError):
            return int(DEFAULT_SETTINGS["general"]["max_recent_games"])

    def _windows_startup_configured(self) -> bool:
        """Read the persisted intent separately from the actual Registry state."""

        try:
            value = self.get_settings()["categories"]["general"].get("start_with_windows", False)
            return bool(value) if isinstance(value, bool) else False
        except (KeyError, TypeError, RepositoryError):
            return False

    def _save_recent_game(self, game: Game) -> Game:
        """Persist a game as recent and trim only the excess recent history."""

        game.last_used_at = game.last_used_at or _utc_now()
        saved = self.repository.save_game(game)
        self.repository.prune_recent_games(self._max_recent_games())
        refreshed = self.repository.get_game_by_place_id(saved.place_id)
        # The just-used game is newest, so it cannot be pruned by a positive
        # maximum. The fallback preserves a deterministic result if storage is
        # altered by another local operation between the two reads.
        return refreshed or saved

    def _record_recent_game(self, place_id: int) -> Game:
        """Record a successful local launch without adding a network dependency."""

        existing = self.repository.get_game_by_place_id(place_id)
        game = existing or Game(place_id=place_id, name=f"Roblox place {place_id}")
        game.last_used_at = _utc_now()
        return self._save_recent_game(game)

    def _reopen_repository_after_failed_restore(self) -> None:
        """Best-effort recovery of a usable repository after a restore error."""

        try:
            if self.repository.is_closed:
                self.repository = SQLiteRepository(self.paths.database)
                self._ensure_default_settings()
        except Exception:
            self.logger.exception("Could not reopen repository after failed restore")

    def _remove_sqlite_sidecars(self) -> None:
        """Remove stale WAL/SHM files only after a successful checkpoint/close."""

        database = self.paths.database.resolve()
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{database}{suffix}")
            try:
                sidecar.relative_to(self.paths.root.resolve())
            except ValueError as exc:
                raise StorageError("SQLite restore path is invalid.") from exc
            try:
                sidecar.unlink(missing_ok=True)
            except OSError as exc:
                raise StorageError("SQLite temporary files could not be prepared.") from exc

    def _oauth_configuration(self) -> OAuthClientConfiguration:
        oauth = self.get_settings()["categories"].get("oauth", {})
        if not isinstance(oauth, Mapping) or not bool(oauth.get("enabled")):
            raise ValidationError(
                "Roblox OAuth connection is not configured. Enable it with a client ID and registered callback."
            )
        try:
            return OAuthClientConfiguration(
                client_id=str(oauth.get("client_id") or ""),
                redirect_uri=str(oauth.get("redirect_uri") or ""),
                callback_timeout_seconds=oauth.get("callback_timeout_seconds", 300),
            )
        except OAuthConfigurationError as exc:
            raise ValidationError(exc.message) from exc

    def _oauth_grant_vault(self) -> OAuthGrantVault:
        """Bind the current repository after a possible backup restoration."""

        return OAuthGrantVault(self.repository, self.vault)

    def _persist_oauth_connection(
        self,
        identity: OAuthIdentity,
        grant: OAuthGrant,
        *,
        expected_account_id: str | None = None,
        previous_grant: OAuthGrant | None = None,
    ) -> dict[str, Any]:
        """Persist a public identity plus a DPAPI-protected OAuth grant.

        The linked public profile is intentionally saved separately from the
        grant.  An account therefore never advertises an OAuth connection
        until its encrypted vault write succeeds.
        """

        existing = self._find_oauth_account(identity)
        if expected_account_id is not None:
            target = self._get_account(expected_account_id)
            if target.user_id is not None and target.user_id != identity.user_id:
                raise SecurityError("The received OAuth profile does not match the selected account.")
            if existing is not None and existing.id != target.id:
                raise ConflictError("This Roblox profile is already linked to another local account.")
            existing = target

        created = existing is None
        if existing is None:
            account = Account(
                username=identity.username,
                user_id=identity.user_id,
                display_name=identity.display_name or identity.username,
                avatar_url=identity.avatar_url,
                status="ready",
                has_session=False,
            )
            try:
                existing = self.repository.save_account(account)
            except RepositoryConflictError as exc:
                raise ConflictError("This Roblox profile is already in your workspace.") from exc
            except RepositoryError as exc:
                raise StorageError("Roblox profile could not be saved.") from exc

        grants = self._oauth_grant_vault()
        if not created and previous_grant is None:
            try:
                previous_grant = grants.load(existing.id)
            except AppError:
                # A newly consented OAuth flow may repair an expired/corrupt
                # local grant.  The new verified grant can safely replace it.
                previous_grant = None
        try:
            grants.store(existing.id, grant)
        except AppError:
            if created:
                try:
                    self.repository.delete_account(existing.id)
                except RepositoryError:
                    self.logger.warning("Could not remove incomplete OAuth account")
            raise

        account = existing
        account.user_id = identity.user_id
        account.username = identity.username
        account.display_name = identity.display_name or identity.username
        if identity.avatar_url is not None:
            account.avatar_url = identity.avatar_url
        if account.status in {"", "unknown"}:
            account.status = "ready"
        account.last_refreshed_at = _utc_now()
        metadata = dict(account.metadata)
        metadata["oauth"] = {
            "connected": True,
            "scopes": list(grant.scopes),
            "expires_at": grant.expires_at.astimezone(UTC).isoformat(),
            "linked_at": _utc_now(),
        }
        account.metadata = metadata
        try:
            saved = self.repository.save_account(account)
        except RepositoryConflictError as exc:
            self._restore_or_remove_oauth_grant(existing.id, previous_grant)
            if created:
                try:
                    self.repository.delete_account(existing.id)
                except RepositoryError:
                    self.logger.warning("Could not remove incomplete OAuth account")
            raise ConflictError("This Roblox username is already linked to another local account.") from exc
        except RepositoryError as exc:
            self._restore_or_remove_oauth_grant(existing.id, previous_grant)
            if created:
                try:
                    self.repository.delete_account(existing.id)
                except RepositoryError:
                    self.logger.warning("Could not remove incomplete OAuth account")
            raise StorageError("OAuth profile could not be finalized.") from exc
        return self._account_payload(saved)

    def _restore_or_remove_oauth_grant(self, account_id: str, previous_grant: OAuthGrant | None) -> None:
        """Best-effort vault rollback if updating public account data fails."""

        try:
            grants = self._oauth_grant_vault()
            if previous_grant is None:
                grants.delete(account_id)
            else:
                grants.store(account_id, previous_grant)
        except AppError:
            self.logger.warning("Could not roll back OAuth grant state")

    def _find_oauth_account(self, identity: OAuthIdentity) -> Account | None:
        try:
            by_identity = [
                account
                for account in self.repository.list_accounts()
                if account.user_id == identity.user_id
            ]
            by_username = self.repository.get_account_by_username(identity.username)
        except RepositoryError as exc:
            raise StorageError("OAuth account could not be searched.") from exc
        if len(by_identity) > 1:
            raise ConflictError("Multiple local accounts use this same Roblox user ID.")
        account = by_identity[0] if by_identity else by_username
        if by_identity and by_username is not None and by_username.id != by_identity[0].id:
            raise ConflictError("This Roblox username is already linked to another local account.")
        return account

    @staticmethod
    def _oauth_operation_id(value: Any) -> str:
        if (
            not isinstance(value, str)
            or not 12 <= len(value) <= 128
            or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for character in value)
        ):
            raise ValidationError("OAuth operation is invalid.")
        return value

    def _store_session(self, account: Account, value: Any) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("Provided session is invalid.")
        if len(value) > 8_192:
            raise ValidationError("Provided session is invalid.")
        try:
            protected = self.vault.protect(value.encode("utf-8"), description="Astro Account Manager Roblox session")
        except DPAPIUnavailableError as exc:
            raise SecurityError("Windows vault is not available to protect this session.") from exc
        except DPAPIError as exc:
            raise SecurityError("Session could not be protected by Windows.") from exc
        try:
            self.repository.save_protected_secret(account.id, "session", protected)
        except RepositoryError as exc:
            raise StorageError("Session could not be saved.") from exc
        account.has_session = True

    def _get_account(self, account_id: str) -> Account:
        try:
            return self.repository.get_account(account_id)
        except RepositoryNotFoundError as exc:
            raise NotFoundError("Account not found.") from exc
        except RepositoryError as exc:
            raise StorageError("Account could not be read.") from exc

    def _get_group(self, group_id: str) -> Group:
        try:
            return self.repository.get_group(group_id)
        except RepositoryNotFoundError as exc:
            raise NotFoundError("Group not found.") from exc
        except RepositoryError as exc:
            raise StorageError("Group could not be read.") from exc

    def _activity(self, kind: str, summary: str, *, account_id: str | None = None, metadata: Mapping[str, Any] | None = None) -> None:
        try:
            self.repository.record_activity(Activity(kind=kind, summary=summary, account_id=account_id, metadata=dict(metadata or {})))
        except RepositoryError:
            self.logger.warning("Could not record activity: %s", kind)

    def _notice(self, level: str, title: str, message: str) -> None:
        try:
            self.repository.save_notification(Notification(level=level, title=title, message=message))
        except RepositoryError:
            self.logger.warning("Could not persist notification: %s", title)

    # Watcher runtime ------------------------------------------------------
    def start_watcher(self) -> bool:
        """Start the opt-in local polling worker when watcher.enabled is true.

        The worker only observes processes and consumes explicitly enabled,
        bounded relaunch requests.  It owns no credential and has no way to
        modify a Roblox client.
        """

        self._watcher_requested = True
        self._configure_monitor_from_settings()
        if not self._watcher_is_enabled():
            return False
        with self._watch_loop_lock:
            if self._watch_loop is None:
                scan_method = getattr(self.monitor, "scan", None)
                if not callable(scan_method):
                    return False
                self._watch_loop = MonitorPollingLoop(
                    self._watcher_tick,
                    interval_seconds=self._watcher_interval,
                    on_error=self._watcher_background_failure,
                )
            return self._watch_loop.start()

    def stop_watcher(self) -> None:
        """Stop the owned polling worker before storage or services close."""

        self._watcher_requested = False
        self._stop_watcher_worker()

    def _sync_watcher_loop(self) -> None:
        if not self._watcher_requested:
            return
        if self._watcher_is_enabled():
            self.start_watcher()
        else:
            self._stop_watcher_worker()

    def _stop_watcher_worker(self) -> None:
        with self._watch_loop_lock:
            loop = self._watch_loop
            self._watch_loop = None
        if loop is not None:
            loop.stop()

    def _watcher_tick(self) -> Any:
        return self._scan_instances(allow_restarts=True)

    def _watcher_interval(self) -> float:
        try:
            value = self.get_settings()["categories"]["watcher"]["scan_interval_seconds"]
            return float(value)
        except (KeyError, TypeError, ValueError, RepositoryError):
            return 6.0

    def _watcher_background_failure(self) -> None:
        # Keep the log message independent of an arbitrary psutil adapter's
        # exception text; process command lines can contain private data.
        self.logger.warning("Roblox watcher scan failed; it will retry on the next interval.")

    def _watcher_is_enabled(self) -> bool:
        try:
            return bool(self.get_settings()["categories"]["watcher"].get("enabled", False))
        except (KeyError, TypeError, RepositoryError):
            return False

    def _configure_monitor_from_settings(self) -> None:
        configure = getattr(self.monitor, "configure", None)
        if not callable(configure):
            return
        try:
            watcher = self.get_settings()["categories"]["watcher"]
            configure(
                termination_enabled=bool(watcher.get("termination_enabled", False)),
                launch_match_timeout_seconds=watcher.get("launch_match_timeout_seconds", 45),
                crash_window_seconds=watcher.get("crash_window_seconds", 120),
            )
        except (KeyError, TypeError, ValueError, ValidationError, RepositoryError):
            self.logger.warning("Watcher configuration is invalid; existing local watcher options were kept.")

    def _scan_instances(self, *, allow_restarts: bool) -> Any:
        scan = self.monitor.scan()
        self._record_process_events(getattr(scan, "events", ()))
        self._poll_instance_logs(
            getattr(scan, "instances", ()),
            process_scan_complete=bool(getattr(scan, "complete", True)),
        )
        if allow_restarts:
            self._dispatch_due_restarts()
        return scan

    def _poll_instance_logs(self, instances: Any, *, process_scan_complete: bool) -> None:
        """Update the read-only Player-log observer independently of control.

        Parsed log events are never passed to ``RobloxProcessMonitor`` or the
        restart dispatcher.  A transient file-system failure therefore cannot
        change account state, close a process, or request a relaunch.
        """

        poll = getattr(self._log_runtime, "poll", None)
        if not callable(poll):
            return
        try:
            poll(instances, process_scan_complete=process_scan_complete)
        except (OSError, TypeError, ValueError, ValidationError):
            # Keep this deliberately free of exception text: it may otherwise
            # contain a local path that has no place in application logs/UI.
            self.logger.warning("Roblox Player log observation failed; process monitoring remains unchanged.")

    def _log_watcher_payload(self) -> dict[str, Any]:
        """Return a fixed, path-free observer state for the desktop bridge."""

        snapshot_method = getattr(self._log_runtime, "snapshot", None)
        snapshot = snapshot_method() if callable(snapshot_method) else None
        return {
            "directory_available": bool(getattr(snapshot, "directory_available", False)),
            "discovery_complete": bool(getattr(snapshot, "discovery_complete", True)),
            "candidate_count": self._nonnegative_int(getattr(snapshot, "candidate_count", 0)),
            "observed_instance_count": self._nonnegative_int(
                getattr(snapshot, "observed_instance_count", 0)
            ),
            "association_state": self._log_association_state(
                getattr(snapshot, "association_state", "directory_unavailable")
            ),
            "associated_pid": self._optional_pid(getattr(snapshot, "associated_pid", None)),
        }

    def _log_event_payloads(self) -> list[dict[str, Any]]:
        """Return only the whitelist of typed, redacted log-event fields."""

        history_method = getattr(self._log_runtime, "history", None)
        history = history_method() if callable(history_method) else ()
        payloads: list[dict[str, Any]] = []
        for event in history:
            kind = getattr(event, "kind", None)
            kind_value = getattr(kind, "value", kind)
            if not isinstance(kind_value, str) or not kind_value:
                continue
            payloads.append(
                {
                    "kind": kind_value,
                    "occurred_at": getattr(event, "occurred_at", None),
                    "pid": self._optional_pid(getattr(event, "pid", None)),
                    "place_id": self._safe_positive_int(getattr(event, "place_id", None)),
                    "job_id": self._safe_job_id(getattr(event, "job_id", None)),
                    "disconnect_code": self._safe_positive_int(getattr(event, "disconnect_code", None)),
                }
            )
        return payloads

    @staticmethod
    def _nonnegative_int(value: Any) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    @staticmethod
    def _optional_pid(value: Any) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None

    @staticmethod
    def _safe_positive_int(value: Any) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None

    @staticmethod
    def _safe_job_id(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized if 0 < len(normalized) <= 128 else None

    @staticmethod
    def _log_association_state(value: Any) -> str:
        allowed = {
            "directory_unavailable",
            "process_scan_incomplete",
            "discovery_truncated",
            "no_instance",
            "no_log",
            "ambiguous",
            "associated",
        }
        return value if isinstance(value, str) and value in allowed else "directory_unavailable"

    def _register_launch_intent(
        self,
        account: Account,
        target: LaunchTarget,
        *,
        restart_policy: RestartPolicy | None = None,
        restart_attempt: int = 0,
    ) -> str | None:
        if not self._watcher_is_enabled():
            return None
        register = getattr(self.monitor, "register_launch_intent", None)
        if not callable(register):
            return None
        try:
            return register(
                account_id=account.id,
                account_username=account.username,
                place_id=target.place_id,
                job_id=target.job_id,
                restart_policy=restart_policy or self._restart_policy_for(account),
                restart_attempt=restart_attempt,
            )
        except (TypeError, ValueError, ValidationError):
            # A successful Windows hand-off remains valid if only its optional
            # local watcher registration fails.
            self.logger.warning("A Roblox launch could not be registered with the local watcher.")
            return None

    def _dispatch_due_restarts(self) -> None:
        claim = getattr(self.monitor, "claim_due_restarts", None)
        record_result = getattr(self.monitor, "record_restart_result", None)
        if not callable(claim):
            return
        try:
            requests = claim()
        except (TypeError, ValueError, ValidationError):
            self.logger.warning("The local watcher could not claim pending relaunches.")
            return
        for request in requests:
            if not isinstance(request, RestartRequest):
                continue
            launched = False
            try:
                account = self._get_account(request.account_id)
                target = LaunchTarget(place_id=request.place_id, job_id=request.job_id)
                result = self.launcher.launch(target)
                launched = bool(result.launched)
                if launched:
                    self._register_launch_intent(
                        account,
                        target,
                        restart_policy=request.restart_policy,
                        restart_attempt=request.restart_attempt,
                    )
                    self._set_account_runtime_status(account.id, "launching")
                    self._activity(
                        "relaunch",
                        f"Local relaunch requested for {account.username}",
                        account_id=account.id,
                        metadata={"place_id": target.place_id, "attempt": request.restart_attempt},
                    )
            except (AppError, RobloxLaunchError):
                self._notice(
                    "warning",
                    "Local Relaunch Failed",
                    "Relaunch rule was consumed without starting a process. Check Diagnostics.",
                )
            finally:
                if callable(record_result):
                    try:
                        record_result(request, launched=launched)
                    except (TypeError, ValueError, ValidationError):
                        self.logger.warning("The watcher could not record a relaunch result.")

    def _restart_policy_for(self, account: Account) -> RestartPolicy:
        watcher = self.get_settings()["categories"].get("watcher", {})
        fallback = {
            "auto_relaunch": False,
            "relaunch_delay_seconds": watcher.get("relaunch_delay_seconds", 15),
            "relaunch_max_attempts": watcher.get("relaunch_max_attempts", 2),
            "relaunch_on_crash": watcher.get("relaunch_on_crash", True),
            "relaunch_on_exit": watcher.get("relaunch_on_exit", False),
        }
        try:
            rule = self._validated_account_watcher_rule(
                account.metadata.get("watcher", {}), existing=fallback
            )
        except ValidationError:
            rule = fallback
        return RestartPolicy(
            enabled=bool(watcher.get("auto_relaunch_enabled", False)) and rule["auto_relaunch"],
            delay_seconds=rule["relaunch_delay_seconds"],
            max_attempts=rule["relaunch_max_attempts"],
            restart_on_crash=rule["relaunch_on_crash"],
            restart_on_exit=rule["relaunch_on_exit"],
        )

    @staticmethod
    def _validated_account_watcher_rule(
        value: Any, *, existing: Any = None
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise ValidationError("Account watcher rule is invalid.")
        baseline = {
            "auto_relaunch": False,
            "relaunch_delay_seconds": 15,
            "relaunch_max_attempts": 2,
            "relaunch_on_crash": True,
            "relaunch_on_exit": False,
        }
        if isinstance(existing, Mapping):
            for key in baseline:
                if key in existing:
                    baseline[key] = existing[key]
        unknown = set(value) - set(baseline)
        if unknown:
            raise ValidationError("Account watcher rule contains an unknown field.")
        baseline.update(dict(value))
        if not isinstance(baseline["auto_relaunch"], bool):
            raise ValidationError("Account relaunch option is invalid.")
        if not isinstance(baseline["relaunch_on_crash"], bool) or not isinstance(baseline["relaunch_on_exit"], bool):
            raise ValidationError("Account relaunch triggers are invalid.")
        delay = baseline["relaunch_delay_seconds"]
        if isinstance(delay, bool) or not isinstance(delay, (int, float)) or not 1 <= float(delay) <= 3_600:
            raise ValidationError("Account relaunch delay must be between 1 and 3600 seconds.")
        attempts = baseline["relaunch_max_attempts"]
        if isinstance(attempts, bool) or not isinstance(attempts, int) or not 0 <= attempts <= 20:
            raise ValidationError("Account relaunch attempt count must be between 0 and 20.")
        return {
            "auto_relaunch": baseline["auto_relaunch"],
            "relaunch_delay_seconds": float(delay),
            "relaunch_max_attempts": attempts,
            "relaunch_on_crash": baseline["relaunch_on_crash"],
            "relaunch_on_exit": baseline["relaunch_on_exit"],
        }

    @staticmethod
    def _restart_payload(request: RestartRequest) -> dict[str, Any]:
        return {
            "id": request.request_id,
            "account_id": request.account_id,
            "place_id": request.place_id,
            "job_id": request.job_id,
            "due_at": _iso_to_epoch_ms(datetime.fromtimestamp(request.due_at, tz=UTC).isoformat()),
            "attempt": request.restart_attempt,
        }

    def _set_account_runtime_status(self, account_id: str, status: str) -> None:
        if status not in {"ready", "launching", "in_game", "offline"}:
            return
        try:
            account = self.repository.get_account(account_id)
            if account.status != status:
                account.status = status
                self.repository.save_account(account)
        except RepositoryError:
            self.logger.warning("Could not update account status from local watcher.")

    def _forget_account_in_monitor(self, account_id: str) -> None:
        forget = getattr(self.monitor, "forget_account", None)
        if callable(forget):
            try:
                forget(account_id)
            except (TypeError, ValueError, ValidationError):
                self.logger.warning("Could not detach a deleted account from the local watcher.")

    def _record_process_events(self, events: Any) -> None:
        for event in events:
            kind = getattr(event, "kind", "instance")
            account_id = getattr(event, "account_id", None)
            metadata = {
                "pid": getattr(event, "pid", 0),
                "occurred_at": getattr(event, "occurred_at", None),
                "state": getattr(event, "state", None),
                "reason": getattr(event, "reason", None),
                "restart_attempt": getattr(event, "restart_attempt", None),
            }
            self._activity("instance", f"Instance Roblox {kind}", account_id=account_id, metadata=metadata)
            if not account_id:
                continue
            if kind in {"launch_matched", "orphan_bound"}:
                self._set_account_runtime_status(account_id, "in_game")
            elif kind in {"exited", "crashed", "terminated", "launch_expired"}:
                self._set_account_runtime_status(account_id, "ready")

    @staticmethod
    def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise ValidationError(f"{label} sont invalides.")
        return value

    @staticmethod
    def _required_text(value: Any, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"{label} est requis.")
        normalized = " ".join(value.split())
        if len(normalized) > 120:
            raise ValidationError(f"{label} est trop long.")
        return normalized

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValidationError("Text is invalid.")
        return value.strip() or None

    @staticmethod
    def _optional_id(value: Any) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str) or len(value) > 100:
            raise ValidationError("ID is invalid.")
        return value

    @staticmethod
    def _avatar_color(value: Any) -> str:
        if value is None or value == "":
            return "violet"
        if not isinstance(value, str) or value not in _AVATAR_COLOR_TOKENS:
            raise ValidationError("Avatar color is invalid.")
        return value

    @staticmethod
    def _group_color(value: Any) -> str:
        if value is None or value == "":
            return "violet"
        if not isinstance(value, str):
            raise ValidationError("Group color is invalid.")
        normalized = value.strip().lower()
        if normalized in _LEGACY_GROUP_COLOR_TOKENS:
            return _LEGACY_GROUP_COLOR_TOKENS[normalized]
        if _is_hex_color(normalized):
            return normalized
        if normalized not in _GROUP_COLOR_TOKENS:
            raise ValidationError("Group color is invalid.")
        return normalized

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        return ApplicationService._positive_int(value, "The value")

    @staticmethod
    def _positive_int(value: Any, label: str) -> int:
        if isinstance(value, bool):
            raise ValidationError(f"{label} is invalid.")
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{label} must be a positive integer.") from exc
        if result <= 0:
            raise ValidationError(f"{label} must be a positive integer.")
        return result

    @staticmethod
    def _set_path(target: dict[str, Any], path: str, value: Any) -> None:
        cursor = target
        parts = path.split(".")
        for part in parts[:-1]:
            existing = cursor.get(part)
            if not isinstance(existing, dict):
                existing = {}
                cursor[part] = existing
            cursor = existing
        cursor[parts[-1]] = value

    @staticmethod
    def _validate_settings(values: Mapping[str, Any]) -> None:
        general = values.get("general", {})
        max_recent_games = general.get("max_recent_games") if isinstance(general, Mapping) else None
        if isinstance(max_recent_games, bool) or not isinstance(max_recent_games, int) or not 1 <= max_recent_games <= 1_000:
            raise ValidationError("Recent games limit must be between 1 and 1000.")
        if not isinstance(general.get("start_with_windows"), bool):
            raise ValidationError("Windows startup state is invalid.")
        appearance = values.get("appearance", {})
        if appearance.get("theme") not in {"dark", "light", "system"}:
            raise ValidationError("Theme is invalid.")
        accent = appearance.get("accent")
        if not isinstance(accent, str) or not _is_hex_color(accent.lower()):
            raise ValidationError("Accent color is invalid.")
        if appearance.get("density") not in {"comfortable", "compact"}:
            raise ValidationError("Interface density is invalid.")
        if not isinstance(appearance.get("reduced_motion"), bool):
            raise ValidationError("Reduced motion preference is invalid.")
        watcher = values.get("watcher", {})
        interval = watcher.get("scan_interval_seconds")
        if not isinstance(interval, int) or not 1 <= interval <= 300:
            raise ValidationError("Watcher interval must be between 1 and 300 seconds.")
        if not isinstance(watcher.get("enabled"), bool):
            raise ValidationError("Watcher state is invalid.")
        if not isinstance(watcher.get("termination_enabled"), bool):
            raise ValidationError("Instance termination option is invalid.")
        if not isinstance(watcher.get("auto_relaunch_enabled"), bool):
            raise ValidationError("Global relaunch option is invalid.")
        if not isinstance(watcher.get("relaunch_on_crash"), bool) or not isinstance(watcher.get("relaunch_on_exit"), bool):
            raise ValidationError("Global relaunch triggers are invalid.")
        for key, minimum, maximum, label in (
            ("launch_match_timeout_seconds", 5, 300, "Launch match timeout"),
            ("crash_window_seconds", 5, 3_600, "Crash window"),
            ("relaunch_delay_seconds", 1, 3_600, "Relaunch delay"),
        ):
            numeric = watcher.get(key)
            if isinstance(numeric, bool) or not isinstance(numeric, (int, float)) or not minimum <= float(numeric) <= maximum:
                raise ValidationError(f"{label} is invalid.")
        attempts = watcher.get("relaunch_max_attempts")
        if isinstance(attempts, bool) or not isinstance(attempts, int) or not 0 <= attempts <= 20:
            raise ValidationError("Maximum relaunch attempt count is invalid.")
        oauth = values.get("oauth", {})
        if not isinstance(oauth, Mapping) or not isinstance(oauth.get("enabled"), bool):
            raise ValidationError("OAuth connection state is invalid.")
        client_id = oauth.get("client_id")
        redirect_uri = oauth.get("redirect_uri")
        callback_timeout = oauth.get("callback_timeout_seconds")
        if not isinstance(client_id, str) or len(client_id) > 80:
            raise ValidationError("OAuth client ID is invalid.")
        if not isinstance(redirect_uri, str):
            raise ValidationError("OAuth redirect URI is invalid.")
        try:
            OAuthClientConfiguration(
                client_id=client_id or "1",
                redirect_uri=redirect_uri,
                callback_timeout_seconds=callback_timeout,
            )
        except OAuthConfigurationError as exc:
            raise ValidationError(exc.message) from exc
        if bool(oauth.get("enabled")) and not client_id.strip():
            raise ValidationError("A Roblox OAuth client ID is required when login is enabled.")
        api = values.get("api", {})
        if not isinstance(api.get("enabled"), bool):
            raise ValidationError("Local API state is invalid.")
        if api.get("host") != "127.0.0.1":
            raise ValidationError("Local API must be bound to 127.0.0.1.")
        port = api.get("port")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValidationError("Local API port is invalid.")

    @staticmethod
    def _account_payload(account: Account) -> dict[str, Any]:
        payload = account.to_dict()
        oauth = account.metadata.get("oauth") if isinstance(account.metadata, Mapping) else None
        oauth_connected = bool(oauth.get("connected")) if isinstance(oauth, Mapping) else False
        oauth_expires_at = oauth.get("expires_at") if isinstance(oauth, Mapping) else None
        watcher = account.metadata.get("watcher") if isinstance(account.metadata, Mapping) else None
        watcher_rule = (
            {
                key: watcher[key]
                for key in (
                    "auto_relaunch",
                    "relaunch_delay_seconds",
                    "relaunch_max_attempts",
                    "relaunch_on_crash",
                    "relaunch_on_exit",
                )
                if key in watcher
            }
            if isinstance(watcher, Mapping)
            else {}
        )
        payload.update(
            {
                "favorite": account.is_favorite,
                "notes": account.description,
                "last_used": _iso_to_epoch_ms(account.last_used_at),
                "avatar_color": _avatar_color_from_metadata(account.metadata),
                "oauth_connected": oauth_connected,
                "oauth_expires_at": oauth_expires_at if isinstance(oauth_expires_at, str) else None,
                "watcher": watcher_rule,
            }
        )
        return payload

    @staticmethod
    def _group_payload(group: Group) -> dict[str, Any]:
        payload = group.to_dict()
        payload.update(
            {
                "color": _group_color_token(group.color),
                "favorite": group.is_favorite,
                "collapsed": group.is_collapsed,
                "order": group.sort_order,
            }
        )
        return payload

    @staticmethod
    def _game_payload(game: Game, *, stale: bool = False) -> dict[str, Any]:
        payload = game.to_dict()
        payload.update(
            {
                "title": game.name,
                "creator": game.creator_name or "Roblox",
                "players": game.playing or 0,
                "favorite": game.is_favorite,
                "last_opened": _iso_to_epoch_ms(game.last_used_at),
                "stale": stale,
            }
        )
        return payload

    @staticmethod
    def _server_payload(server: Any) -> dict[str, Any]:
        payload = server.to_dict()
        payload.update(
            {
                "id": server.job_id,
                "players": server.playing,
                "capacity": server.max_players,
                "vip": server.server_type.casefold() != "public",
            }
        )
        return payload

    @staticmethod
    def _instance_payload(instance: Any) -> dict[str, Any]:
        payload = instance.to_dict()
        payload.update(
            {
                "id": f"pid_{instance.pid}",
                "state": instance.status,
                "memory_mb": round((instance.memory_bytes or 0) / (1024 * 1024)),
                "game": "Roblox",
                "server": "—",
            }
        )
        return payload

    @staticmethod
    def _activity_payload(activity: Activity) -> dict[str, Any]:
        payload = activity.to_dict()
        payload.update(
            {
                "type": activity.kind,
                "title": activity.summary,
                "detail": _activity_detail(activity.metadata),
                "at": _iso_to_epoch_ms(activity.created_at),
            }
        )
        return payload

    @staticmethod
    def _notification_payload(notification: Notification) -> dict[str, Any]:
        payload = notification.to_dict()
        payload.update(
            {
                "kind": notification.level,
                "body": notification.message,
                "read": notification.is_dismissed,
                "at": _iso_to_epoch_ms(notification.created_at),
            }
        )
        return payload

    def _read_recent_log_lines(self) -> list[dict[str, Any]]:
        # The current logger writes the Astro filename. Keep the legacy read
        # fallback so an existing Asteria workspace remains diagnosable until
        # its first post-rebrand application launch.
        for log_path in (
            self.paths.logs / "astro-account-manager.log",
            self.paths.logs / "asteria.log",
        ):
            if not log_path.is_file():
                continue
            try:
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
            except OSError:
                continue
            return [{"level": _line_level(line), "at": None, "message": _redact_log_line(line)} for line in lines]
        return []

    # Nexus Account Control --------------------------------------------------
    def _handle_nexus_client_log(self, username: str, message: str) -> None:
        self.logger.info(f"[Nexus Client Log] {username}: {message}")
        self._activity("nexus", f"Client Roblox ({username}) print: {message}", metadata={"username": username, "message": message})

    def start_nexus_server(self, host: str | None = None, port: int | None = None) -> dict[str, Any]:
        nexus_settings = self.get_settings()["categories"].get("nexus", {})
        target_host = host or nexus_settings.get("host", "127.0.0.1")
        target_port = int(port or nexus_settings.get("port", 5242))

        if self._nexus_server is None:
            from app.backend.nexus.server import NexusServer
            self._nexus_server = NexusServer(
                host=target_host,
                port=target_port,
                on_auto_relaunch_trigger=self._handle_nexus_auto_relaunch,
            )
            self._nexus_server.on_log_callback = self._handle_nexus_client_log
        self._nexus_server.start()
        self._activity("nexus", f"Nexus Server started on ws://{target_host}:{target_port}/Nexus")
        return self.get_nexus_status()

    def stop_nexus_server(self) -> dict[str, Any]:
        if self._nexus_server is not None:
            self._nexus_server.stop()
            self._nexus_server = None
            self._activity("nexus", "Nexus Server stopped")
        return self.get_nexus_status()

    def get_nexus_status(self) -> dict[str, Any]:
        if self._nexus_server is not None and self._nexus_server.is_running:
            return {
                "running": True,
                "host": self._nexus_server.host,
                "port": self._nexus_server.port,
                "url": f"ws://{self._nexus_server.host}:{self._nexus_server.port}/Nexus",
                "accounts": self._nexus_server.get_connected_accounts(),
            }
        nexus_settings = self.get_settings()["categories"].get("nexus", {})
        return {
            "running": False,
            "host": nexus_settings.get("host", "127.0.0.1"),
            "port": int(nexus_settings.get("port", 5242)),
            "url": f"ws://{nexus_settings.get('host', '127.0.0.1')}:{nexus_settings.get('port', 5242)}/Nexus",
            "accounts": [],
        }

    def send_nexus_command(self, target_account: str, command_name: str, payload: Any = None) -> bool:
        if self._nexus_server is None or not self._nexus_server.is_running:
            self.start_nexus_server()
        if self._nexus_server is None or not self._nexus_server.is_running:
            raise ValidationError("Nexus Server could not be started.")
        success = self._nexus_server.send_command(target_account, command_name, payload)
        self._activity("nexus", f"Nexus command '{command_name}' sent to '{target_account}'")
        return success

    def get_nexus_lua_script(self, host: str = "127.0.0.1", port: int = 5242) -> str:
        from app.backend.nexus.lua_script import get_nexus_lua_script
        return get_nexus_lua_script(host=host, port=port)

    def _handle_nexus_auto_relaunch(self, username: str) -> None:
        """Called by Nexus server when an auto-relaunch account disconnects."""
        accounts = self.repository.list_accounts()
        matching = [acc for acc in accounts if acc.username.lower() == username.lower()]
        if matching:
            account = matching[0]
            try:
                self.logger.info(f"Nexus auto-relaunching account {account.username}")
                self.launch_account(account.id)
                self._activity("nexus", f"Auto-relaunch triggered for {account.username}", account_id=account.id)
            except Exception as exc:
                self.logger.error(f"Nexus auto-relaunch failed for {account.username}: {exc}")

    # Multi-Instance ---------------------------------------------------------
    def get_multi_instance_status(self) -> dict[str, Any]:
        return self.multi_instance.get_status()

    def set_multi_instance(self, enabled: bool) -> dict[str, Any]:
        if enabled:
            success = self.multi_instance.enable_multi_instance()
            if success:
                self._activity("multi_instance", "Roblox Multi-instance enabled (singleton handles held)")
        else:
            self.multi_instance.disable_multi_instance()
            self._activity("multi_instance", "Roblox Multi-instance disabled")
        return self.get_multi_instance_status()

    # FPS Cap & ClientSettings ------------------------------------------------
    def get_fps_cap(self) -> dict[str, Any]:
        fps = self.client_settings.get_fps_cap()
        return {"fps": fps, "file": str(self.client_settings.settings_file)}

    def set_fps_cap(self, fps: int) -> dict[str, Any]:
        success = self.client_settings.set_fps_cap(fps)
        if success:
            self._activity("client_settings", f"Roblox client FPS cap set to {fps}")
        return {"success": success, "fps": fps}

    def remove_fps_cap(self) -> dict[str, Any]:
        success = self.client_settings.remove_fps_cap()
        if success:
            self._activity("client_settings", "Roblox client FPS cap removed")
        return {"success": success}

    # Batch Launcher ---------------------------------------------------------
    def _batch_launch_single_adapter(self, account_id: str, target: dict[str, Any] | None) -> dict[str, Any]:
        return self.launch_account(account_id, target)

    def start_batch_launch(self, account_ids: list[str], target: dict[str, Any] | None = None, delay_seconds: float = 2.5) -> dict[str, Any]:
        res = self.batch_launcher.start_batch(account_ids, target, delay_seconds)
        self._activity("batch_launch", f"Batch launch started for {len(account_ids)} account(s) (delay: {delay_seconds}s)")
        return res

    def cancel_batch_launch(self) -> dict[str, Any]:
        res = self.batch_launcher.cancel_batch()
        self._activity("batch_launch", "Batch launch cancelled by user")
        return res

    def get_batch_launch_status(self) -> dict[str, Any]:
        return self.batch_launcher.get_status()

    # Authenticated Tools ----------------------------------------------------
    def _get_account_cookie_raw(self, account_id: str) -> str:
        account = self._get_account(account_id)
        protected_blob = self.repository.load_protected_secret(account.id, "session")
        if not protected_blob:
            raise ValidationError(f"Account {account.username} has no stored session.")
        try:
            raw_bytes = self.vault.unprotect(protected_blob)
            return raw_bytes.decode("utf-8").strip()
        except Exception as exc:
            raise SecurityError("Could not decrypt stored session.") from exc

    def generate_auth_ticket(self, account_id: str) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        ticket = self.auth_tools.generate_auth_ticket(cookie)
        self._activity("auth_tools", "Auth ticket generated", account_id=account_id)
        return {"account_id": account_id, "ticket": ticket}

    def generate_rbx_player_link(self, account_id: str, place_id: int, job_id: str | None = None) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        ticket = self.auth_tools.generate_auth_ticket(cookie)
        link = self.auth_tools.generate_rbx_player_uri(ticket, place_id, job_id)
        self._activity("auth_tools", "rbx-player link generated", account_id=account_id, metadata={"place_id": place_id})
        return {"account_id": account_id, "ticket": ticket, "link": link}

    def get_account_cookie(self, account_id: str) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        account = self._get_account(account_id)
        self._activity("auth_tools", "Session/cookie extracted for copy", account_id=account_id)
        return {"account_id": account_id, "username": account.username, "cookie": cookie}

    def add_account_from_cookie(self, cookie: str, group_id: str | None = None) -> dict[str, Any]:
        """Validates a raw .ROBLOSECURITY cookie, resolves Roblox user profile, and persists to vault & SQLite."""
        if not cookie or not isinstance(cookie, str):
            raise ValidationError(".ROBLOSECURITY cookie is required.")
        clean_cookie = cookie.strip()

        from app.backend.roblox.client import SessionRobloxClient
        session_client = SessionRobloxClient(clean_cookie)
        try:
            user = session_client.authenticated_user()
        except Exception as exc:
            raise ValidationError(f"Roblox session validation failed: {exc}")
        finally:
            session_client.close()

        existing = self.repository.get_account_by_username(user.username)
        account_id = existing.id if existing else None

        avatar_url = None
        try:
            profile = self.roblox.get_public_profile(user.user_id)
            avatar_url = profile.avatar_url
        except Exception:
            pass

        account_kwargs: dict[str, Any] = {
            "user_id": user.user_id,
            "username": user.username,
            "display_name": user.display_name or user.username,
            "avatar_url": avatar_url,
            "group_id": group_id,
            "last_used_at": datetime.now(UTC).isoformat(),
            "has_session": True,
        }
        if account_id:
            account_kwargs["id"] = account_id

        account = Account(**account_kwargs)

        saved = self.repository.save_account(account)
        protected_blob = self.vault.protect(clean_cookie.encode("utf-8"))
        self.repository.save_protected_secret(saved.id, "session", protected_blob)
        self._activity("account", f"Account {saved.username} logged in with cookie", account_id=saved.id)
        return saved.to_dict()

    def start_manual_browser_login(self, group_id: str | None = None) -> dict[str, Any]:
        """Opens a browser window for manual Roblox login and intercepts the cookie."""
        from app.backend.roblox.browser_login import BrowserLoginService, EdgeCDPLoginService

        def _on_captured(cookie_str: str) -> None:
            try:
                self.add_account_from_cookie(cookie_str, group_id=group_id)
            except Exception as exc:
                self.logger.error(f"Error saving account from captured cookie: {exc}")

        # Try Edge CDP Service first (guaranteed 100% HttpOnly cookie extraction via DevTools Protocol)
        try:
            edge_service = EdgeCDPLoginService()
            if edge_service.start_login(_on_captured):
                return {"started": True, "engine": "edge_cdp"}
        except Exception as cdp_exc:
            self.logger.debug(f"Edge CDP login unavailable, falling back to PyWebView: {cdp_exc}")

        # Fallback to PyWebView BrowserLoginService
        if not hasattr(self, "_browser_login_service") or self._browser_login_service is None:
            self._browser_login_service = BrowserLoginService()

        started = self._browser_login_service.start_manual_login(_on_captured)
        return {"started": started, "engine": "pywebview"}

    # Bulk Import ------------------------------------------------------------
    def import_bulk_accounts(self, raw_text: str, group_id: str | None = None) -> dict[str, Any]:
        parsed = BulkAccountImporter.parse_text(raw_text)
        imported_count = 0
        imported_accounts = []

        for item in parsed:
            cookie = item.get("cookie")
            username = item.get("username")
            if cookie and "_|WARNING" in cookie:
                try:
                    acc = self.add_account_from_cookie(cookie, group_id=group_id)
                    imported_count += 1
                    imported_accounts.append(acc)
                    continue
                except Exception as exc:
                    self.logger.debug(f"Direct cookie add failed, falling back to profile stub: {exc}")

            fallback_name = username or f"Account_{len(self.repository.list_accounts()) + 1}"
            try:
                acc_payload = {
                    "username": fallback_name,
                    "group_id": group_id,
                }
                created = self.create_account(acc_payload)
                if cookie:
                    protected_blob = self.vault.protect(cookie.encode("utf-8"))
                    self.repository.save_protected_secret(created["id"], "session", protected_blob)
                imported_count += 1
                imported_accounts.append(created)
            except Exception as exc:
                self.logger.warning(f"Failed to bulk import account {fallback_name}: {exc}")

        self._activity("bulk_import", f"{imported_count} account(s) bulk imported")
        return {"imported": imported_count, "total_parsed": len(parsed), "accounts": imported_accounts}

    # Window Positioner ------------------------------------------------------
    def position_instance_window(self, pid: int, x: int, y: int, width: int = 800, height: int = 600) -> dict[str, Any]:
        from app.backend.watchers.window_positioner import RobloxWindowPositioner
        success = RobloxWindowPositioner.position_window(pid, x, y, width, height)
        self._activity("window", f"Positioned window PID {pid} at ({x}, {y})")
        return {"pid": pid, "success": success, "x": x, "y": y, "width": width, "height": height}

    # Extended Account Utilities & Features ----------------------------------
    def change_account_password(self, account_id: str, current_pass: str, new_pass: str) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        success = self.account_utils.change_password(cookie, current_pass, new_pass)
        self._activity("account_utils", "Password changed", account_id=account_id)
        return {"account_id": account_id, "success": success}

    def change_account_email(self, account_id: str, password: str, new_email: str) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        success = self.account_utils.change_email(cookie, password, new_email)
        self._activity("account_utils", f"Email changed to {new_email}", account_id=account_id)
        return {"account_id": account_id, "success": success}

    def logout_all_account_sessions(self, account_id: str) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        success = self.account_utils.logout_all_sessions(cookie)
        self._activity("account_utils", "Logged out all other sessions", account_id=account_id)
        return {"account_id": account_id, "success": success}

    def set_account_display_name(self, account_id: str, new_display_name: str) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        account = self._get_account(account_id)
        if not account.user_id:
            raise ValidationError("UserId required to update display name.")
        success = self.account_utils.set_display_name(cookie, account.user_id, new_display_name)
        account.display_name = new_display_name
        self.repository.save_account(account)
        self._activity("account_utils", f"Display name updated: {new_display_name}", account_id=account_id)
        return {"account_id": account_id, "display_name": new_display_name, "success": success}

    def send_account_friend_request(self, account_id: str, target_user_id: int) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        success = self.account_utils.send_friend_request(cookie, target_user_id)
        self._activity("account_utils", f"Friend request sent to {target_user_id}", account_id=account_id)
        return {"account_id": account_id, "target_user_id": target_user_id, "success": success}

    def block_account_user(self, account_id: str, target_user_id: int) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        success = self.account_utils.block_user(cookie, target_user_id)
        self._activity("account_utils", f"Blocked user {target_user_id}", account_id=account_id)
        return {"account_id": account_id, "target_user_id": target_user_id, "success": success}

    def unblock_account_user(self, account_id: str, target_user_id: int) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        success = self.account_utils.unblock_user(cookie, target_user_id)
        self._activity("account_utils", f"Unblocked user {target_user_id}", account_id=account_id)
        return {"account_id": account_id, "target_user_id": target_user_id, "success": success}

    def quick_log_in_account(self, account_id: str, code: str) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        success = self.account_utils.quick_log_in(cookie, code)
        self._activity("account_utils", "Quick Log In code submitted", account_id=account_id)
        return {"account_id": account_id, "code": code, "success": success}

    def get_account_blocked_list(self, account_id: str) -> list[dict[str, Any]]:
        cookie = self._get_account_cookie_raw(account_id)
        return self.account_utils.get_blocked_users(cookie)

    def unblock_all_account_users(self, account_id: str) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        count = self.account_utils.unblock_everyone(cookie)
        self._activity("account_utils", f"Unblocked all users ({count})", account_id=account_id)
        return {"account_id": account_id, "unblocked_count": count}

    def set_account_avatar(self, account_id: str, asset_ids: list[int]) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        success = self.account_utils.set_avatar(cookie, asset_ids)
        self._activity("account_utils", "Avatar outfit updated", account_id=account_id)
        return {"account_id": account_id, "asset_ids": asset_ids, "success": success}

    def parse_vip_link(self, link: str) -> dict[str, Any] | None:
        return PrivateServerHelper.parse_vip_link(link)

    def search_players(self, keyword: str, limit: int = 10) -> list[dict[str, Any]]:
        return self.player_search.search_players(keyword, limit)

    def get_player_presence(self, user_id: int) -> dict[str, Any]:
        return self.player_search.get_player_presence(user_id)

    def get_random_server(self, place_id: int) -> dict[str, Any] | None:
        return self.random_server.get_random_server(place_id)

    def close_beta_home_windows(self) -> dict[str, Any]:
        closed = BetaHomeCleaner.close_beta_home_windows()
        if closed:
            self._activity("watcher", f"{closed} Beta Home window(s) closed")
        return {"closed_count": closed}

    def check_for_updates(self) -> dict[str, Any]:
        return UpdateChecker.check_for_updates()


def _flatten_settings(values: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, value in values.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            flattened.update(_flatten_settings(value, path))
        else:
            flattened[path] = value
    return flattened


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _iso_to_epoch_ms(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _activity_detail(metadata: Mapping[str, Any]) -> str:
    if not metadata:
        return ""
    from app.backend.security.redaction import is_sensitive_key

    safe = {key: value for key, value in metadata.items() if not is_sensitive_key(key)}
    return ", ".join(f"{key}: {value}" for key, value in safe.items())[:180]


def _line_level(line: str) -> str:
    upper = line.upper()
    if " ERROR " in upper or " CRITICAL " in upper:
        return "ERROR"
    if " WARNING " in upper or " WARN " in upper:
        return "WARN"
    return "INFO"


def _redact_log_line(line: str) -> str:
    # Import lazily to keep all secret treatment in one auditable place.
    from app.backend.core.logging import redact

    return redact(line)


def _migration_payload(report: Any) -> dict[str, Any]:
    """Convert a migration report to bridge-safe primitives without file data."""

    detections = [
        {
            "filename": item.path.name,
            "format": item.format.value,
            "size_bytes": item.size_bytes,
            "requires_password": item.requires_password,
            "requires_windows_user": item.requires_windows_user,
        }
        for item in report.detections
    ]
    backups = [
        {
            "id": item.backup_id,
            "created_at": item.created_at,
            "size": item.size_bytes,
            "verified": True,
        }
        for item in report.backup_records
    ]
    return {
        "source_directory": str(report.source_directory),
        "detections": detections,
        "backups": backups,
        "settings_imported": report.settings_imported,
        "games_imported": report.games_imported,
        "groups_imported": report.groups_imported,
        "accounts_imported": report.accounts_imported,
        "sessions_imported": report.sessions_imported,
        "saved_passwords_imported": report.saved_passwords_imported,
        "account_metadata_imported": report.account_metadata_imported,
        "secret_import_requires_consent": report.secret_import_requires_consent,
        "warnings": list(report.warnings),
    }


def _avatar_color_from_metadata(metadata: Mapping[str, Any]) -> str:
    """Return a safe UI token without making the domain model UI-specific."""

    ui = metadata.get("ui") if isinstance(metadata, Mapping) else None
    candidate = ui.get("avatar_color") if isinstance(ui, Mapping) else None
    return candidate if isinstance(candidate, str) and candidate in _AVATAR_COLOR_TOKENS else "violet"


def _group_color_token(value: str) -> str:
    normalized = value.strip().lower() if isinstance(value, str) else ""
    return _LEGACY_GROUP_COLOR_TOKENS.get(
        normalized,
        normalized if normalized in _GROUP_COLOR_TOKENS else "violet",
    )


def _is_hex_color(value: str) -> bool:
    return (
        len(value) in {4, 7}
        and value.startswith("#")
        and all(character in "0123456789abcdef" for character in value[1:])
    )


__all__ = ["ApplicationService"]
