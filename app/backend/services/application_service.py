"""Application use cases composed from storage, Roblox and process services."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
import json
import logging
import os
from pathlib import Path
import re
import secrets
import socket
import sys
import threading
import time
from typing import Any

import psutil

from app.backend.core.config import (
    APP_VERSION,
    AppPaths,
    DEFAULT_SETTINGS,
    feature_enabled,
    feature_flags,
    merge_settings,
)
from app.backend.automations import (
    MacroEngine,
    MacroParseError,
    MacroRunNotFound,
    parse_macro_dsl,
    validate_macro_actions,
)
from app.backend.core.crash_reporting import SupportBundleBuilder
from app.backend.integrations import DiscordPresenceManager, DiscordRpcError
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
from app.backend.services.fleet_features import FleetFeaturesMixin, ServiceMacroController
from app.backend.repositories.sqlite_repository import (
    ConflictError as RepositoryConflictError,
    NotFoundError as RepositoryNotFoundError,
    RepositoryError,
    SQLiteRepository,
)
from app.backend.roblox import (
    BatchLauncher,
    AuthenticatedBrowserService,
    ClientSettingsPatcher,
    LaunchTarget,
    OAuthClientConfiguration,
    OAuthConfigurationError,
    OAuthGrant,
    OAuthGrantVault,
    OAuthIdentity,
    OAuthLoginCompletion,
    OAuthLoginCoordinator,
    RegionLookupSettings,
    RequestsRegionTransport,
    RobloxAuthTools,
    RobloxClient,
    ServerRegionResolver,
    WindowsMultiInstanceController,
    WindowsRobloxLauncher,
    WindowsUwpRobloxManager,
)
from app.backend.roblox.errors import RobloxLaunchError, RobloxServiceError, RobloxUwpError
from app.backend.security.dpapi import CurrentUserDPAPI, DPAPIError, DPAPIUnavailableError
from app.backend.core.updater import UpdateChecker, UpdateError, UpdateManager
from app.backend.roblox.background import RobloxBackgroundManager
from app.backend.roblox.account_utils import AccountUtils
from app.backend.roblox.player_search import PlayerSearchService
from app.backend.roblox.private_servers import PrivateServerHelper
from app.backend.roblox.random_server import RandomServerSelector
from app.backend.storage.backups import BackupError, VersionedBackupManager
from app.backend.storage.bulk_import import BulkAccountImporter
from app.backend.storage.metadata_transfer import MetadataTransfer, MetadataTransferError
from app.backend.watchers.beta_home_cleaner import BetaHomeCleaner
from app.backend.watchers.rejoin_rules import (
    MAX_REJOIN_ATTEMPTS,
    RejoinPlan,
    classify_disconnect,
    plan_rejoin,
)
from app.backend.watchers.rule_engine import (
    ACTION_PAUSE_MACRO,
    ACTION_RESTART_MACRO,
    ACTION_RESUME_MACRO,
    AccountFacts,
    RuleDecision,
    SystemFacts,
    automatic_decisions,
    evaluate_rules,
    normalized_priority,
    recommendations,
    validated_rule_settings,
)
from app.backend.core.config import feature_enabled as _feature_enabled
from app.backend.watchers.launch_planner import (
    LaunchPlan,
    plan_launches,
    validated_launcher_settings,
)
from app.backend.watchers.resource_plan import (
    ACTION_PAUSE_LAUNCHES,
    ACTION_RECOMMEND_CLOSE,
    InstanceFacts,
    MachineFacts,
    ResourcePlan,
    plan_resources,
    validated_resource_settings,
)
from app.backend.watchers.window_positioner import RobloxWindowPositioner
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
    "allow_multiple_launches": "instances.allow_multiple_launches",
    "watcher_enabled": "watcher.enabled",
    "global_max_fps": "performance.global_max_fps",
    "potato_graphics": "performance.potato_graphics",
    "watcher_termination_enabled": "watcher.termination_enabled",
    "watcher_auto_relaunch_enabled": "watcher.auto_relaunch_enabled",
    "watcher_close_unconnected": "watcher.close_unconnected",
    "watcher_close_if_memory_low": "watcher.close_if_memory_low",
    "watcher_close_if_title_mismatch": "watcher.close_if_title_mismatch",
    "remember_window_positions": "instances.remember_window_positions",
    "auto_backup": "general.auto_backup",
    "notifications": "notifications.desktop_notifications",
    "diagnostics": "developer.verbose_logs",
    "warn_if_roblox_running": "general.warn_if_roblox_running",
    "discord_enabled": "discord.enabled",
    "discord_client_id": "discord.client_id",
    "discord_strategy": "discord.strategy",
    "discord_show_account": "discord.show_account",
    "updates_auto_check": "updates.auto_check",
    "updates_auto_download": "updates.auto_download",
    "updates_install_on_exit": "updates.install_on_exit",
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


class ApplicationService(FleetFeaturesMixin):
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
        window_positioner: Any | None = None,
        oauth_login: OAuthLoginCoordinator | None = None,
        client_settings: ClientSettingsPatcher | None = None,
        region_resolver: ServerRegionResolver | None = None,
        macro_engine: MacroEngine | Any | None = None,
        discord_presence: DiscordPresenceManager | Any | None = None,
        update_manager: UpdateManager | Any | None = None,
        background_manager: RobloxBackgroundManager | Any | None = None,
        support_bundle_builder: SupportBundleBuilder | Any | None = None,
        authenticated_browser: AuthenticatedBrowserService | Any | None = None,
        logger: logging.Logger | logging.LoggerAdapter[logging.Logger] | None = None,
    ) -> None:
        self._region_resolver = region_resolver or ServerRegionResolver(
            fetch_json=RequestsRegionTransport()
        )
        self.paths = paths or AppPaths.for_current_user()
        self.paths.ensure_exists()
        self.repository = repository or SQLiteRepository(self.paths.database)
        self.vault = vault or CurrentUserDPAPI()
        self.roblox = roblox or RobloxClient(
            timeout_seconds=float(DEFAULT_SETTINGS["network"]["request_timeout_seconds"])
        )
        self.launcher = launcher or WindowsRobloxLauncher()
        self.uwp_manager = uwp_manager or WindowsUwpRobloxManager(
            instance_root=self.paths.root / "UWP_Instances"
        )
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
        # The log observer stays separate from close/relaunch decisions. Its
        # typed lifecycle events may refine the *display* state of an already
        # bound account, so a kicked client is not incorrectly shown in-game.
        self._log_runtime = log_runtime or RobloxPlayerLogRuntime()
        self._seen_log_event_keys: set[tuple[Any, ...]] = set()
        self._log_disconnected_pids: set[int] = set()
        # Last observed disconnect code per account.  It only ever refines a
        # relaunch the process watcher already granted; it never grants one.
        self._log_disconnect_codes: dict[str, int] = {}
        # Rule engine bookkeeping.  Macro progress is tracked per run from the
        # outside, so a wedged macro is detected without asking that macro to
        # report its own health.
        self._macro_progress: dict[str, tuple[Any, float]] = {}
        self._rule_paused_runs: set[str] = set()
        self._rule_notified: set[tuple[str, str]] = set()
        self._rule_decisions: tuple[dict[str, Any], ...] = ()
        self._cpu_primed = False
        self.window_positioner = window_positioner or RobloxWindowPositioner
        self.oauth_login = oauth_login or OAuthLoginCoordinator()
        self.backups = VersionedBackupManager(self.paths.backups, app_version=APP_VERSION)
        self.logger = logger or logging.getLogger("astro_account_manager.service")
        self._restore_lock = threading.RLock()
        self._watch_loop_lock = threading.RLock()
        self._launch_lock = threading.RLock()
        self._watch_loop: MonitorPollingLoop | None = None
        self._watcher_requested = False
        self._oauth_results: dict[str, dict[str, Any]] = {}
        self._browser_login_results: dict[str, dict[str, Any]] = {}
        self._browser_login_lock = threading.RLock()
        self._discord_instance_signature: tuple[tuple[Any, ...], ...] | None = None
        self._pending_window_restores: dict[int, tuple[str, float]] = {}
        self._nexus_server: Any = None
        self._nexus_token: str | None = None
        self.multi_instance = WindowsMultiInstanceController()
        self.client_settings = client_settings or ClientSettingsPatcher()
        self.batch_launcher = BatchLauncher(launch_single_fn=self._batch_launch_single_adapter)
        self.auth_tools = RobloxAuthTools(roblox_client=self.roblox)
        self.account_utils = AccountUtils()
        self.player_search = PlayerSearchService(self.roblox)
        self.random_server = RandomServerSelector(self.roblox)
        self.macro_engine = macro_engine or MacroEngine()
        # LAUNCH, TELEPORT and RESTART blocks need the application, not the
        # input backend, so the engine borrows the same launch path as the UI.
        if hasattr(self.macro_engine, "set_controller"):
            self.macro_engine.set_controller(ServiceMacroController(self))
        self.discord_presence = discord_presence or DiscordPresenceManager()
        frozen_runtime = bool(getattr(sys, "frozen", False)) if runtime_is_frozen is None else bool(runtime_is_frozen)
        executable_runtime = runtime_executable if runtime_executable is not None else Path(sys.executable)
        self.update_manager = update_manager or UpdateManager(
            self.paths.cache / "updates",
            runtime_executable=executable_runtime,
            runtime_is_frozen=frozen_runtime,
        )
        self.background_manager = background_manager or RobloxBackgroundManager()
        self.support_bundle_builder = support_bundle_builder or SupportBundleBuilder(
            self.paths.logs, self.paths.exports
        )
        self.authenticated_browser = authenticated_browser or AuthenticatedBrowserService()
        self._ensure_default_settings()
        self._configure_multi_instance_from_settings()
        self._configure_monitor_from_settings()

    def close(self) -> None:
        """Release owned external resources on application shutdown."""

        update_preferences = self.get_settings()["categories"].get("updates", {})
        self._stop_nexus_server_unchecked()
        self.stop_watcher()
        self.macro_engine.stop_all()
        self.discord_presence.close()
        self.multi_instance.disable_multi_instance()
        close_client = getattr(self.roblox, "close", None)
        if callable(close_client):
            close_client()
        self.oauth_login.close()
        self.repository.close()
        close_updater = getattr(self.update_manager, "close", None)
        apply_update = getattr(self.update_manager, "apply_pending_on_exit", None)
        if bool(update_preferences.get("install_on_exit", False)) and callable(apply_update):
            apply_update()
        if callable(close_updater):
            close_updater()

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
            "multi_instance": self.get_multi_instance_status(),
            "features": feature_flags(),
            "nexus": self.get_nexus_status() if feature_enabled("nexus") else {"available": False},
            "activity": self.get_activity(),
            "notifications": self.get_notifications(),
            "diagnostics": self.get_diagnostics(include_logs=False),
            "macros": self.list_macros(),
            "macro_runs": self.list_macro_runs(),
            "discord_presence": self.get_discord_presence_status(),
            "updater": self.get_update_status(),
            "roblox_background": self.get_roblox_background_status(),
        }

    # Accounts --------------------------------------------------------------
    def list_accounts(self, query: str | None = None) -> list[dict[str, Any]]:
        return [self._account_payload(item) for item in self.repository.list_accounts(search=query)]

    def create_account(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = self._require_mapping(payload, "Account data")
        supplied_session = data.get("session")
        if isinstance(supplied_session, str) and supplied_session.strip():
            return self.add_account_from_cookie(
                supplied_session,
                group_id=self._optional_id(data.get("group_id")),
            )
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
        if "session" in data:
            raise ValidationError("Use the authenticated cookie import flow to replace a Roblox session.")
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

    def search_games(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search Roblox experiences through the omni-search endpoint.

        The Roblox client already implemented this call, but nothing exposed it,
        which left the Games & servers page unable to discover any experience.
        Locally saved games are still matched first so the page keeps working
        when the network is unavailable.
        """

        phrase = str(query or "").strip()
        if not phrase:
            return self.list_games()
        if len(phrase) > 120:
            raise ValidationError("A game search phrase must be 120 characters or fewer.")
        bounded = self._positive_int(limit, "The search limit")
        if bounded > 50:
            bounded = 50

        lowered = phrase.lower()
        local = [
            payload
            for payload in self.list_games()
            if lowered in str(payload.get("title", "")).lower()
            or lowered in str(payload.get("creator", "")).lower()
        ]
        try:
            remote = self.roblox.search_games(phrase, limit=bounded)
        except RobloxServiceError as exc:
            if local:
                return local[:bounded]
            raise ExternalServiceError(str(exc), retryable=getattr(exc, "retryable", False)) from exc

        merged = list(local)
        seen = {str(item.get("place_id")) for item in merged}
        for game in remote:
            payload = self._game_payload(game)
            key = str(payload.get("place_id"))
            if key in seen:
                continue
            seen.add(key)
            merged.append(payload)
        return merged[:bounded]

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
        rows = [self._server_payload(server) for server in page.servers]
        return self._region_resolver_for_settings().annotate_servers(rows)

    def _region_resolver_for_settings(self) -> ServerRegionResolver:
        try:
            network = self.get_settings()["categories"].get("network", {})
        except Exception:
            network = {}
        self._region_resolver.update_settings(RegionLookupSettings.from_mapping(network))
        return self._region_resolver

    def resolve_server_region(self, address: str) -> dict[str, Any]:
        resolver = self._region_resolver_for_settings()
        if not resolver.enabled:
            return {
                "region": None,
                "enabled": False,
                "reason": "Region lookup is disabled in Settings > Network.",
            }
        region = resolver.resolve(address)
        return {
            "region": region,
            "enabled": True,
            "reason": None if region else "No region resolved for this server.",
        }

    def probe_server_regions(
        self,
        account_id: str,
        place_id: int | str,
        job_ids: list[str],
    ) -> dict[str, Any]:
        """Port RAM's explicit 16-server authenticated region probe."""

        account = self._get_account(account_id)
        normalized_place_id = self._positive_int(place_id, "Place ID")
        if not isinstance(job_ids, list) or not 1 <= len(job_ids) <= 16:
            raise ValidationError("Select between 1 and 16 public servers for region probing.")
        if len(set(job_ids)) != len(job_ids):
            raise ValidationError("Server region probe contains duplicate Job IDs.")
        resolver = self._region_resolver_for_settings()
        if not resolver.enabled:
            raise ValidationError("Enable server region lookup in Settings > Network first.")
        cookie = self._get_account_cookie_raw(account.id)
        rows: list[dict[str, Any]] = []
        for job_id in job_ids:
            try:
                probed = self.auth_tools.probe_server_instance(cookie, normalized_place_id, job_id)
                region = resolver.resolve(probed.get("address"))
                latency_ms: int | None = None
                if probed.get("port"):
                    started = time.monotonic()
                    try:
                        with socket.create_connection(
                            (str(probed["address"]), int(probed["port"])), timeout=0.4
                        ):
                            latency_ms = max(0, int((time.monotonic() - started) * 1000))
                    except OSError:
                        latency_ms = None
                rows.append({"job_id": job_id, "region": region, "ping": latency_ms, "resolved": region is not None})
            except RobloxServiceError as exc:
                rows.append({"job_id": job_id, "region": None, "ping": None, "resolved": False, "reason": str(exc)})
        self._activity(
            "server_region",
            f"Region probe completed for {len(rows)} public server(s)",
            account_id=account.id,
            metadata={"place_id": normalized_place_id},
        )
        return {
            "place_id": normalized_place_id,
            "account_id": account.id,
            "servers": rows,
            "resolved": sum(1 for row in rows if row["resolved"]),
        }

    def launch_account(
        self,
        account_id: str,
        target: Mapping[str, Any] | None = None,
        *,
        _restart_policy: RestartPolicy | None = None,
        _restart_attempt: int = 0,
    ) -> dict[str, Any]:
        account = self._get_account(account_id)
        target_data = dict(target or {})
        place_id = target_data.get("place_id") or target_data.get("placeId") or account.saved_place_id
        if place_id is None:
            raise ValidationError("Choose a Place ID before launching Roblox.")
        launch_target = LaunchTarget(
            place_id=self._positive_int(place_id, "Place ID"),
            job_id=self._optional_text(target_data.get("job_id") or target_data.get("jobId")),
        )

        categories = self.get_settings()["categories"]
        instance_settings = categories.get("instances", {})
        if bool(instance_settings.get("prevent_duplicate_accounts", True)):
            duplicate_check = getattr(self.monitor, "has_active_or_pending_account", None)
            if callable(duplicate_check):
                duplicate = bool(duplicate_check(account.id))
            else:
                duplicate = any(
                    getattr(instance, "account_id", None) == account.id
                    for instance in self.monitor.current_instances()
                )
            if duplicate:
                raise ConflictError("This account already has an active or pending Roblox launch.")

        watcher_request_id: str | None = None
        with self._launch_lock:
            multi_instance_enabled = bool(
                instance_settings.get("allow_multiple_launches", False)
                or self.multi_instance.is_enabled
            )
            if multi_instance_enabled and not self.multi_instance.enable_multi_instance():
                raise ConflictError(
                    "Multi Roblox is enabled but Astro could not acquire its mutex. "
                    "Close every Roblox client, restart Astro, then launch the accounts from Astro."
                )
            if multi_instance_enabled:
                prepare_for_launch = getattr(self.multi_instance, "prepare_for_launch", None)
                preparation = prepare_for_launch() if callable(prepare_for_launch) else {}
                if preparation.get("error"):
                    self.logger.warning(
                        "Multi Roblox could not detach the modern singleton event: %s",
                        preparation["error"],
                    )
                    self._notice(
                        "warning",
                        "Multi Roblox compatibility warning",
                        "Astro kept the historic mutex, but Windows refused the modern event detachment. "
                        "A previous Roblox window may close when the next account starts.",
                    )

            # Apply per-account or per-launch FPS Cap & Potato Graphics settings
            launch_opts = account.metadata.get("launch_options", {}) if isinstance(account.metadata, dict) else {}
            performance = categories.get("performance", {}) if isinstance(categories, Mapping) else {}

            # Resolution order, most specific first: an explicit launch target,
            # then the account's own launch options, then the global
            # performance preference.  The value currently written in
            # ClientAppSettings.json is only a last resort so a launch never
            # silently drops a cap the user already asked for.
            fps_target = None
            for candidate in (
                target_data.get("fps"),
                target_data.get("fps_cap"),
                launch_opts.get("max_fps"),
                performance.get("global_max_fps"),
            ):
                if candidate not in (None, "", 0, "0"):
                    fps_target = candidate
                    break
            if fps_target is None:
                fps_target = self.client_settings.get_fps_cap()

            if "potato" in target_data:
                potato_mode = target_data.get("potato")
            elif "potato_graphics" in target_data:
                potato_mode = target_data.get("potato_graphics")
            elif "potato_graphics" in launch_opts:
                potato_mode = launch_opts.get("potato_graphics")
            else:
                potato_mode = performance.get("potato_graphics", False)

            try:
                patched = self.client_settings.patch_launch_settings(
                    fps=int(fps_target) if fps_target else 0,
                    potato_graphics=bool(potato_mode),
                )
                if not patched:
                    raise ValidationError(
                        "Roblox ClientSettings could not be written. Check the installation path and file permissions."
                    )
            except Exception as patch_exc:
                # A silent warning hid a completely non-working FPS unlocker.
                # Surface it where the user can see it, without aborting the
                # launch the user explicitly asked for.
                self.logger.warning(f"Could not apply launch ClientSettings: {patch_exc}")
                self._activity(
                    "performance",
                    "FPS cap and graphics flags could not be applied for this launch",
                    account_id=account.id,
                )
                self._notice(
                    "warning",
                    "FPS unlocker not applied",
                    str(getattr(patch_exc, "message", None) or patch_exc),
                )

            try:
                # A stored account session must select that account in the
                # Roblox client. The generic roblox:// URI only opens the
                # machine's current browser/client identity, so use RAM's
                # authentication-ticket hand-off whenever a vault session is
                # available.
                launch_authenticated = getattr(self.launcher, "launch_authenticated_uri", None)
                if account.has_session and callable(launch_authenticated):
                    cookie = self._get_account_cookie_raw(account.id)
                    ticket = self.auth_tools.generate_auth_ticket(cookie)
                    link_code = self._optional_text(
                        target_data.get("private_server_link_code") or target_data.get("link_code")
                    )
                    if link_code:
                        uri = PrivateServerHelper.format_private_server_uri(
                            auth_ticket=ticket,
                            place_id=launch_target.place_id,
                            link_code=link_code,
                        )
                    else:
                        uri = self.auth_tools.generate_rbx_player_uri(
                            ticket,
                            launch_target.place_id,
                            launch_target.job_id,
                        )
                    # The watcher intent must exist before Windows receives the
                    # protocol hand-off.  Registering it afterwards creates a
                    # race where a fast Roblox process is permanently treated
                    # as an unrelated orphan.
                    watcher_request_id = self._register_launch_intent(
                        account,
                        launch_target,
                        restart_policy=_restart_policy,
                        restart_attempt=_restart_attempt,
                    )
                    result = launch_authenticated(uri)
                else:
                    watcher_request_id = self._register_launch_intent(
                        account,
                        launch_target,
                        restart_policy=_restart_policy,
                        restart_attempt=_restart_attempt,
                    )
                    result = self.launcher.launch(launch_target)
            except RobloxServiceError as exc:
                self._cancel_launch_intent(watcher_request_id)
                raise ExternalServiceError(str(exc), retryable=getattr(exc, "retryable", False)) from exc
            except RobloxLaunchError as exc:
                self._cancel_launch_intent(watcher_request_id)
                raise ExternalServiceError(str(exc), retryable=False) from exc

            if not result.launched:
                self._cancel_launch_intent(watcher_request_id)
                self._activity(
                    "launch",
                    f"Launch rejected for {account.username}",
                    account_id=account.id,
                    metadata={"place_id": launch_target.place_id},
                )
                return {
                    "accepted": False,
                    "account_id": account.id,
                    "target": {"place_id": launch_target.place_id, "job_id": launch_target.job_id},
                    "watcher_request_id": None,
                }

            account.status = "launching"
            account.last_used_at = _utc_now()
            # ``saved_place_id`` is the account's configured default, not a
            # last-launched field.  A one-off game/server launch must never
            # overwrite that per-account preference.
            try:
                self.repository.save_account(account)
            except RepositoryError:
                self._notice("warning", "Launch Sent", "Roblox was opened, but metadata could not be updated.")

            # Serialise only until the watcher has observed this account.  In
            # the common case this replaces the old unconditional 1.2 second
            # sleep with a couple of short polls, while preventing two rapid
            # launches from becoming an ambiguous pair of orphan processes.
            if watcher_request_id:
                self._await_launch_observation(account.id, timeout_seconds=1.2)
            else:
                time.sleep(0.2)

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

    def create_uwp_account_clone(
        self,
        account_id: str,
        *,
        confirm: bool = False,
        supports_multiple_instances: bool = True,
    ) -> dict[str, Any]:
        if confirm is not True:
            raise SecurityError("Creating a Windows UWP clone requires explicit confirmation.")
        account = self._get_account(account_id)
        result = self.uwp_manager.create_account_clone(
            account.username,
            supports_multiple_instances=bool(supports_multiple_instances),
        )
        self._activity("uwp", f"UWP clone created for {account.username}", account_id=account.id)
        self._notice("success", "UWP Clone Registered", f"Windows registered Roblox {account.username}.")
        return result

    def unregister_uwp_account_clone(
        self, account_id: str, *, confirm: bool = False
    ) -> dict[str, Any]:
        if confirm is not True:
            raise SecurityError("Unregistering a Windows UWP clone requires explicit confirmation.")
        account = self._get_account(account_id)
        result = self.uwp_manager.unregister_account_clone(account.username)
        self._activity("uwp", f"UWP clone unregistered for {account.username}", account_id=account.id)
        self._notice("success", "UWP Clone Unregistered", "The clone files were preserved locally.")
        return result

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
            "accounts": [self._account_payload(item) for item in self.repository.list_accounts()],
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
        try:
            watcher_settings = self.get_settings()["categories"].get("watcher", {})
        except (KeyError, TypeError, RepositoryError):
            watcher_settings = {}
        effective = self._relaunch_arming_state(saved, watcher_settings, normalized)
        return {"account_id": saved.id, **normalized, "effective": effective}

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
        # The dashboard, the watcher tick and every fleet screen read settings.
        # Rebuilding the tree per call meant a SQLite scan plus a deep copy each
        # time, so the snapshot is reused until a write bumps the repository
        # revision. Callers still receive a private copy they may mutate.
        revision = getattr(self.repository, "settings_revision", None)
        cached = getattr(self, "_settings_snapshot", None)
        if revision is not None and cached is not None and cached[0] == revision:
            return deepcopy(cached[1])
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
            "watcher_close_unconnected": nested["watcher"].get("close_unconnected", False),
            "watcher_close_if_memory_low": nested["watcher"].get("close_if_memory_low", False),
            "watcher_close_if_title_mismatch": nested["watcher"].get("close_if_title_mismatch", False),
            "remember_window_positions": nested["instances"].get("remember_window_positions", False),
            "auto_backup": nested["general"]["auto_backup"],
            "notifications": nested["notifications"]["desktop_notifications"],
            "diagnostics": nested["developer"]["verbose_logs"],
            "launch_behavior": nested["general"].get("launch_behavior", "confirm"),
            "close_when_empty": nested["instances"].get("close_when_empty", False),
            "allow_multiple_launches": nested["instances"].get("allow_multiple_launches", False),
            "global_max_fps": nested.get("performance", {}).get("global_max_fps", 0),
            "potato_graphics": nested.get("performance", {}).get("potato_graphics", False),
            "categories": nested,
        }
        if revision is not None:
            self._settings_snapshot = (revision, deepcopy(flat))
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
        performance_updates = nested_updates.get("performance")
        if isinstance(performance_updates, dict) and "global_max_fps" in performance_updates:
            raw_fps = performance_updates["global_max_fps"]
            if isinstance(raw_fps, bool):
                raise ValidationError("Global FPS target must be a whole number.")
            try:
                performance_updates["global_max_fps"] = int(raw_fps)
            except (TypeError, ValueError) as exc:
                raise ValidationError("Global FPS target must be a whole number.") from exc
        general_updates = nested_updates.get("general")
        if isinstance(general_updates, Mapping) and "start_with_windows" in general_updates:
            raise ValidationError(
                "Use the dedicated Windows startup action with explicit confirmation."
            )
        candidate = merge_settings(self.get_settings()["categories"], nested_updates)
        self._validate_settings(candidate)
        flattened_updates = _flatten_settings(nested_updates)
        previous_performance = self.get_settings()["categories"].get("performance", {})
        next_performance = candidate.get("performance", {})
        performance_changed = bool(
            {"performance.global_max_fps", "performance.potato_graphics"}
            & set(flattened_updates)
        )
        performance_applied = False
        if performance_changed:
            try:
                performance_applied = bool(
                    self.client_settings.patch_launch_settings(
                        fps=int(next_performance.get("global_max_fps") or 0),
                        potato_graphics=bool(next_performance.get("potato_graphics", False)),
                    )
                )
            except Exception as exc:
                raise StorageError("Roblox FPS and graphics settings could not be applied.") from exc
            if not performance_applied:
                raise StorageError("Roblox FPS and graphics settings could not be applied.")
        try:
            for path, value in flattened_updates.items():
                self.repository.set_setting(path, value)
        except RepositoryError as exc:
            if performance_applied:
                try:
                    self.client_settings.patch_launch_settings(
                        fps=int(previous_performance.get("global_max_fps") or 0),
                        potato_graphics=bool(previous_performance.get("potato_graphics", False)),
                    )
                except Exception:
                    self.logger.error("Could not restore ClientSettings after a settings write failure.")
            raise StorageError("Settings could not be saved.") from exc
        if "general.max_recent_games" in flattened_updates:
            try:
                self.repository.prune_recent_games(self._max_recent_games())
            except RepositoryError as exc:
                raise StorageError("Recent games limit could not be applied.") from exc
        self._configure_monitor_from_settings()
        self._sync_watcher_loop()
        if "instances.allow_multiple_launches" in _flatten_settings(nested_updates):
            self._configure_multi_instance_from_settings()
        self._activity("settings", "Settings updated")
        return self.get_settings()

    def reset_settings(
        self, category: str | None = None, confirm: bool = False
    ) -> dict[str, Any]:
        """Restore one canonical category, or every category, to defaults."""

        if confirm is not True:
            raise ValidationError("Confirm the settings reset.")
        normalized = str(category or "").strip().lower()
        if normalized and normalized not in DEFAULT_SETTINGS:
            raise ValidationError("Choose a valid settings category.")

        current = self.get_settings()["categories"]
        if not normalized or normalized == "general":
            startup_enabled = bool(current.get("general", {}).get("start_with_windows"))
            if startup_enabled:
                self.set_windows_startup(False, confirm=True)

        defaults = (
            {normalized: deepcopy(DEFAULT_SETTINGS[normalized])}
            if normalized
            else deepcopy(DEFAULT_SETTINGS)
        )
        # The registry-backed startup flag is owned by its dedicated confirmed
        # action above, never by the generic settings writer.
        general = defaults.get("general")
        if isinstance(general, dict):
            general.pop("start_with_windows", None)

        output = self.update_settings({"categories": defaults})
        expected_paths = set(_flatten_settings(defaults))
        prefix = f"{normalized}." if normalized else None
        for path in tuple(self.repository.list_settings(prefix=prefix)):
            if path == "general.start_with_windows":
                continue
            if path not in expected_paths:
                self.repository.delete_setting(path)

        scope = normalized or "all categories"
        self._activity("settings", f"Settings reset: {scope}")
        return self.get_settings() if output is not None else output

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
        scan = self._scan_instances(allow_restarts=True)
        self._refresh_discord_for_scan(scan)
        # RAM's Beta Home cleaner ran automatically after a short grace
        # period.  Only a verified Roblox process with one of the exact Home
        # titles can receive WM_CLOSE; normal game windows are untouched.
        closed = BetaHomeCleaner.close_beta_home_windows(min_age_seconds=30.0)
        if closed:
            self._activity("watcher", f"{closed} Beta Home window(s) closed automatically")
        # Session history, macro resumes and the clock-driven schedule all ride
        # on this one tick: a single process poll, one consistent set of facts.
        self._update_fleet_ledgers(scan)
        self._dispatch_macro_resumes()
        try:
            self.run_due_scheduled_tasks(silent=True)
        except AppError:
            self.logger.warning("A scheduled task could not run on this tick.")
        return scan

    def _refresh_discord_for_scan(self, scan: Any) -> None:
        instances = tuple(getattr(scan, "instances", ()) or ())
        signature = tuple(
            sorted(
                (
                    getattr(item, "pid", None),
                    getattr(item, "account_id", None),
                    getattr(item, "place_id", None),
                    getattr(item, "status", None),
                )
                for item in instances
            )
        )
        if signature == self._discord_instance_signature:
            return
        self._discord_instance_signature = signature
        try:
            settings = self.get_settings()["categories"].get("discord", {})
            if bool(settings.get("enabled")):
                self.refresh_discord_presence()
            else:
                self.discord_presence.close()
        except (AppError, DiscordRpcError, RepositoryError):
            self.logger.info("Discord Rich Presence could not be refreshed.")

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
        self._reconcile_account_runtime_statuses(scan)
        self._poll_instance_logs(
            getattr(scan, "instances", ()),
            process_scan_complete=bool(getattr(scan, "complete", True)),
        )
        self._apply_instance_window_runtime(scan)
        if allow_restarts:
            self._dispatch_due_restarts()
            self._apply_rules(scan)
        return scan

    def _await_launch_observation(self, account_id: str, *, timeout_seconds: float) -> bool:
        """Wait briefly for one launched process without a fixed launch delay."""

        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        while True:
            scan = self._scan_instances(allow_restarts=False)
            if any(getattr(instance, "account_id", None) == account_id for instance in scan.instances):
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.1, remaining))

    def _reconcile_account_runtime_statuses(self, scan: Any) -> None:
        """Repair persisted runtime labels after a complete process snapshot.

        Runtime labels live in SQLite so the UI can render them cheaply, but a
        process may disappear while Astro is closed.  A new monitor has no old
        PID from which to emit an ``exited`` event, so complete scans must also
        reconcile stale ``launching``/``in_game`` values against the monitor's
        current associated instances and unexpired launch intentions.
        """

        if not bool(getattr(scan, "complete", True)):
            return
        live_account_ids = {
            account_id
            for instance in (getattr(scan, "instances", ()) or ())
            if isinstance((account_id := getattr(instance, "account_id", None)), str)
            and account_id
        }
        live_pids = {
            pid
            for instance in (getattr(scan, "instances", ()) or ())
            if isinstance((pid := getattr(instance, "pid", None)), int) and pid > 0
        }
        self._log_disconnected_pids.intersection_update(live_pids)
        duplicate_check = getattr(self.monitor, "has_active_or_pending_account", None)
        try:
            accounts = self.repository.list_accounts()
        except RepositoryError:
            self.logger.warning("Could not reconcile account status from the local watcher.")
            return
        for account in accounts:
            if account.status not in {"launching", "in_game"}:
                continue
            matching_instances = tuple(
                instance
                for instance in (getattr(scan, "instances", ()) or ())
                if getattr(instance, "account_id", None) == account.id
            )
            disconnected = any(
                getattr(instance, "pid", None) in self._log_disconnected_pids
                for instance in matching_instances
            )
            if account.id in live_account_ids:
                desired = "ready" if disconnected else "in_game"
            else:
                pending = False
                if callable(duplicate_check):
                    try:
                        pending = bool(duplicate_check(account.id))
                    except (TypeError, ValueError, ValidationError):
                        pending = False
                desired = "launching" if pending else "ready"
            if account.status != desired:
                self._set_account_runtime_status(account.id, desired)

    def _apply_instance_window_runtime(self, scan: Any) -> None:
        """Apply opt-in RAM-compatible window capture/restore and health rules."""

        try:
            categories = self.get_settings()["categories"]
            instance_settings = categories.get("instances", {})
            watcher = categories.get("watcher", {})
        except (KeyError, TypeError, RepositoryError):
            return
        instances = tuple(getattr(scan, "instances", ()) or ())
        started = tuple(getattr(scan, "started", ()) or ())
        if bool(instance_settings.get("remember_window_positions", False)):
            self._queue_window_restores(started)
            self._attempt_window_restores()
            self._capture_bound_window_positions(instances)
        else:
            self._pending_window_restores.clear()
        self._apply_automatic_close_rules(instances, watcher)

    def _queue_window_restores(self, started: tuple[Any, ...]) -> None:
        now = time.time()
        for instance in started:
            account_id = getattr(instance, "account_id", None)
            pid = getattr(instance, "pid", None)
            if not isinstance(account_id, str) or not isinstance(pid, int) or pid <= 0:
                continue
            try:
                account = self._get_account(account_id)
            except AppError:
                continue
            if self._window_layout(account.metadata) is not None:
                self._pending_window_restores[pid] = (account_id, now + 45.0)

    def _attempt_window_restores(self) -> None:
        now = time.time()
        for pid, (account_id, deadline) in tuple(self._pending_window_restores.items()):
            if now > deadline:
                self._pending_window_restores.pop(pid, None)
                continue
            try:
                account = self._get_account(account_id)
            except AppError:
                self._pending_window_restores.pop(pid, None)
                continue
            layout = self._window_layout(account.metadata)
            if layout is None:
                self._pending_window_restores.pop(pid, None)
                continue
            if self.window_positioner.position_window(pid, **layout):
                self._pending_window_restores.pop(pid, None)
                self._activity(
                    "window",
                    f"Restored saved Roblox window for {account.username}",
                    account_id=account.id,
                    metadata={"pid": pid},
                )

    def _capture_bound_window_positions(self, instances: tuple[Any, ...]) -> None:
        for instance in instances:
            account_id = getattr(instance, "account_id", None)
            pid = getattr(instance, "pid", None)
            if (
                not isinstance(account_id, str)
                or not isinstance(pid, int)
                or pid <= 0
                or pid in self._pending_window_restores
                or self._instance_age_seconds(instance) < 30.0
            ):
                continue
            snapshot = self.window_positioner.inspect_window(pid)
            if not isinstance(snapshot, Mapping) or bool(snapshot.get("focused", False)):
                continue
            layout = self._window_layout(snapshot)
            if layout is None:
                continue
            try:
                account = self._get_account(account_id)
                if self._window_layout(account.metadata) == layout:
                    continue
                metadata = dict(account.metadata)
                metadata["window_layout"] = layout
                account.metadata = metadata
                self.repository.save_account(account)
            except (AppError, RepositoryError):
                self.logger.warning("A Roblox window layout could not be persisted.")

    def _apply_automatic_close_rules(self, instances: tuple[Any, ...], watcher: Mapping[str, Any]) -> None:
        if not bool(watcher.get("termination_enabled", False)):
            return
        memory_rule = bool(watcher.get("close_if_memory_low", False))
        title_rule = bool(watcher.get("close_if_title_mismatch", False))
        unconnected_rule = bool(watcher.get("close_unconnected", False))
        if not (memory_rule or title_rule or unconnected_rule):
            return
        terminator = getattr(self.monitor, "terminate_known_process", None)
        if not callable(terminator):
            return
        grace = float(watcher.get("health_grace_seconds", 30))
        unconnected_timeout = float(watcher.get("unconnected_timeout_seconds", 60))
        threshold_bytes = int(watcher.get("memory_low_mb", 200)) * 1024 * 1024
        expected_title = str(watcher.get("expected_window_title", "Roblox"))
        for instance in instances:
            if getattr(instance, "status", "") not in {"running", "orphaned"}:
                continue
            age = self._instance_age_seconds(instance)
            pid = getattr(instance, "pid", None)
            if not isinstance(pid, int) or pid <= 0:
                continue
            snapshot = self.window_positioner.inspect_window(pid)
            # RAM ignored the focused Roblox window. Astro also requires a
            # verified visible window, avoiding similarly named helpers.
            if not isinstance(snapshot, Mapping) or bool(snapshot.get("focused", False)):
                continue
            reason: str | None = None
            memory_bytes = getattr(instance, "memory_bytes", None)
            if memory_rule and age >= grace and isinstance(memory_bytes, int) and memory_bytes < threshold_bytes:
                reason = "memory_below_threshold"
            elif title_rule and age >= grace and snapshot.get("title") != expected_title:
                reason = "window_title_mismatch"
            elif unconnected_rule and age >= unconnected_timeout and not getattr(instance, "account_id", None):
                reason = "unconnected_timeout"
            if reason is None:
                continue
            try:
                result = terminator(pid, confirm=True, wait_timeout_seconds=0.5)
            except (TypeError, ValueError, ValidationError, RobloxServiceError):
                self.logger.warning("An automatic Roblox close rule could not be applied.")
                continue
            status = getattr(getattr(result, "status", None), "value", None)
            self._activity(
                "watcher",
                f"Automatic Roblox close rule: {status or 'failed'}",
                account_id=getattr(instance, "account_id", None),
                metadata={"pid": pid, "reason": reason},
            )

    @staticmethod
    def _instance_age_seconds(instance: Any) -> float:
        started_at = getattr(instance, "started_at", None)
        if not isinstance(started_at, str):
            return 0.0
        try:
            started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            return max(0.0, (datetime.now(UTC) - started.astimezone(UTC)).total_seconds())
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _window_layout(value: Any) -> dict[str, int] | None:
        source = value.get("window_layout") if isinstance(value, Mapping) and "window_layout" in value else value
        if not isinstance(source, Mapping):
            return None
        values = {key: source.get(key) for key in ("x", "y", "width", "height")}
        if any(isinstance(item, bool) or not isinstance(item, int) for item in values.values()):
            return None
        if not -32_768 <= values["x"] <= 32_767 or not -32_768 <= values["y"] <= 32_767:
            return None
        if not 160 <= values["width"] <= 16_384 or not 120 <= values["height"] <= 16_384:
            return None
        return values

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
            self._apply_log_runtime_account_states(instances)
        except (OSError, TypeError, ValueError, ValidationError):
            # Keep this deliberately free of exception text: it may otherwise
            # contain a local path that has no place in application logs/UI.
            self.logger.warning("Roblox Player log observation failed; process monitoring remains unchanged.")

    def _apply_log_runtime_account_states(self, instances: Any) -> None:
        """Refine bound account labels from new, typed Player-log events only.

        This never closes or relaunches a process. A process can remain alive
        on Roblox's Error 267/279 dialog; the process watcher alone therefore
        cannot truthfully decide whether the account is still in a game.
        """

        history_method = getattr(self._log_runtime, "history", None)
        history = tuple(history_method() or ()) if callable(history_method) else ()
        account_by_pid = {
            getattr(instance, "pid", None): getattr(instance, "account_id", None)
            for instance in (instances or ())
        }
        current_keys: set[tuple[Any, ...]] = set()
        for event in history:
            kind = getattr(event, "kind", None)
            kind_value = getattr(kind, "value", kind)
            pid = getattr(event, "pid", None)
            key = (
                kind_value,
                getattr(event, "occurred_at", None),
                pid,
                getattr(event, "place_id", None),
                getattr(event, "job_id", None),
                getattr(event, "disconnect_code", None),
            )
            current_keys.add(key)
            if key in self._seen_log_event_keys:
                continue
            account_id = account_by_pid.get(pid)
            if not isinstance(pid, int) or not isinstance(account_id, str) or not account_id:
                continue
            if kind_value in {"disconnected", "returned_to_app", "data_model_stopped"}:
                self._log_disconnected_pids.add(pid)
                observed = classify_disconnect(getattr(event, "disconnect_code", None)).code
                if observed is not None:
                    self._log_disconnect_codes[account_id] = observed
                self._set_account_runtime_status(account_id, "ready")
            elif kind_value in {"game_joined", "data_model_started"}:
                self._log_disconnected_pids.discard(pid)
                self._log_disconnect_codes.pop(account_id, None)
                self._set_account_runtime_status(account_id, "in_game")
        self._seen_log_event_keys = current_keys

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
                restart_policy=restart_policy or self._restart_policy_for(account, attempt=restart_attempt),
                restart_attempt=restart_attempt,
            )
        except (TypeError, ValueError, ValidationError):
            # A successful Windows hand-off remains valid if only its optional
            # local watcher registration fails.
            self.logger.warning("A Roblox launch could not be registered with the local watcher.")
            return None

    def _cancel_launch_intent(self, request_id: str | None) -> None:
        if not request_id:
            return
        cancel = getattr(self.monitor, "cancel_launch_intent", None)
        if not callable(cancel):
            return
        try:
            cancel(request_id)
        except (TypeError, ValueError, ValidationError):
            self.logger.warning("A failed Roblox launch could not be removed from the local watcher.")

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
                plan = self._rejoin_plan_for(request)
                # Reusing a server that shut down or dropped the connection
                # just fails again, so a server-side failure joins a fresh one.
                target_job = None if plan.change_server else request.job_id
                result = self.launch_account(
                    account.id,
                    {"place_id": request.place_id, "job_id": target_job},
                    _restart_policy=request.restart_policy,
                    _restart_attempt=request.restart_attempt,
                )
                launched = bool(result.get("accepted"))
                if launched:
                    self._activity(
                        "relaunch",
                        f"Local relaunch requested for {account.username}",
                        account_id=account.id,
                        metadata={
                            "place_id": request.place_id,
                            "attempt": request.restart_attempt,
                            "changed_server": plan.change_server,
                            "reason": plan.reason.label,
                        },
                    )
                    # A client that comes back should come back doing what it
                    # was doing.  The macro is queued, then started once the
                    # new process is verified, never blind-fired here.
                    self._queue_macro_resume(account.id, reason=plan.reason.label)
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

    @staticmethod
    def _relaunch_arming_state(
        account: Account, watcher: Mapping[str, Any], rule: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Explain, in one place, whether an automatic relaunch is really armed.

        The watchdog is deliberately gated by several explicit switches.  When
        any of them is off the relaunch must stay inactive, but the caller has
        to be able to say *which* one is off instead of failing silently.
        """

        if not bool(watcher.get("enabled", True)):
            return {"armed": False, "reason": "the local process monitor is disabled"}
        if not bool(rule.get("enabled", True)):
            return {"armed": False, "reason": "this account is not watched"}
        if not bool(rule.get("auto_relaunch", False)):
            return {"armed": False, "reason": "automatic relaunch is off for this account"}
        if not bool(watcher.get("auto_relaunch_enabled", False)):
            return {"armed": False, "reason": "account relaunch rules are disabled globally"}
        if not (bool(rule.get("relaunch_on_crash", True)) or bool(rule.get("relaunch_on_exit", False))):
            return {"armed": False, "reason": "no relaunch trigger is selected"}
        if int(rule.get("relaunch_max_attempts", 0) or 0) <= 0:
            return {"armed": False, "reason": "the maximum relaunch attempts is zero"}
        return {"armed": True, "reason": "armed"}

    def get_rule_decisions(self) -> list[dict[str, Any]]:
        """Return the decisions taken on the most recent watcher tick.

        Read-only on purpose: the UI shows what the rules did, and what they
        refuse to do without a human, instead of re-deriving the logic itself.
        """

        return [dict(item) for item in self._rule_decisions]

    # Dashboard, smart launcher and resources --------------------------------

    def get_dashboard(self, watched_pid: Any = None) -> dict[str, Any]:
        """One read-only snapshot joining accounts, windows, macros and rules.

        The UI used to ask five different questions to fill one screen, which
        made every poll inconsistent: an account could look offline while its
        macro was listed as running.  One join, one answer.
        """

        windows = list(self.monitor.current_instances())
        instances: list[dict[str, Any]] = []
        instance_by_account: dict[str, dict[str, Any]] = {}
        for window in windows:
            payload = self._instance_payload(window)
            payload["runtime_seconds"] = self._instance_runtime_seconds(window)
            instances.append(payload)
            account_id = str(payload.get("account_id") or "")
            if account_id:
                instance_by_account.setdefault(account_id, payload)

        runs = [run for run in self.list_macro_runs() if not run.get("finished_at")]
        macro_by_account: dict[str, dict[str, Any]] = {}
        for run in runs:
            account_id = str(run.get("account_id") or "")
            if account_id:
                macro_by_account.setdefault(account_id, run)

        comfort_settings = self.get_settings()["categories"].get("comfort", {})
        idle_after_seconds = max(0.0, float(comfort_settings.get("sleep_after_minutes") or 0) * 60.0)
        cards: list[dict[str, Any]] = []
        for account in self.repository.list_accounts():
            payload = self._account_payload(account)
            account_id = str(payload.get("id") or "")
            instance = instance_by_account.get(account_id)
            macro = macro_by_account.get(account_id)
            metadata = getattr(account, "metadata", None) or {}
            cards.append(
                {
                    **payload,
                    "instance": instance,
                    "macro": macro,
                    "pid": (instance or {}).get("pid"),
                    "memory_mb": (instance or {}).get("memory_mb"),
                    "runtime_seconds": (instance or {}).get("runtime_seconds"),
                    "place_id": (instance or {}).get("place_id"),
                    "live_state": self._dashboard_state(
                        instance, macro, idle_after_seconds=idle_after_seconds
                    ),
                    "priority": normalized_priority(metadata.get("priority")),
                }
            )

        groups = self.list_groups()
        resources = self._resource_plan(
            watched_pid=self._clean_pid(watched_pid), windows=windows, runs=runs
        )
        return {
            "generated_at": _utc_now(),
            "accounts": cards,
            "instances": instances,
            "groups": groups,
            "macro_runs": runs,
            "rule_decisions": self.get_rule_decisions(),
            "resources": resources.to_dict(),
            "launcher": self._launcher_settings().to_dict(),
            "batch": self.batch_launcher.get_status(),
            "totals": {
                "accounts": len(cards),
                "running": len(instances),
                "macros": len(runs),
                "groups": len(groups),
            },
            # Macros serve one window at a time in this build; the concurrent
            # path is set aside behind ASTRO_ENABLE_MULTI_WINDOW_MACROS.
            "single_window_macros": not _feature_enabled("multi_window_macros"),
        }

    @staticmethod
    def _dashboard_state(
        instance: Mapping[str, Any] | None,
        macro: Mapping[str, Any] | None,
        *,
        idle_after_seconds: float = 0.0,
    ) -> str:
        """Return the single word the dashboard shows for this account.

        ``afk`` is reported honestly: the client sits in a game, no macro is
        driving it, and it has been that way for longer than the sleep
        threshold.  Astro cannot read a player's own idle timer, so it reports
        only what it really knows -- nothing is automating this window.
        """

        if instance is None:
            return "offline"
        if str(instance.get("state") or "") in {"crashed", "exited", "terminated"}:
            return "error"
        if macro is not None:
            if macro.get("paused"):
                return "macro_paused"
            if macro.get("state") == "running":
                return "farming"
        if instance.get("place_id"):
            runtime = float(instance.get("runtime_seconds") or 0.0)
            if idle_after_seconds > 0 and runtime >= idle_after_seconds:
                return "afk"
            return "in_game"
        return "launching"

    @staticmethod
    def _clean_pid(value: Any) -> int | None:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            return None
        try:
            number = int(str(value).strip())
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    def _launcher_settings(self) -> Any:
        return validated_launcher_settings(
            self.get_settings()["categories"].get("launcher", {})
        )

    def _resource_settings(self) -> Any:
        return validated_resource_settings(
            self.get_settings()["categories"].get("resources", {})
        )

    def _machine_facts(self) -> MachineFacts:
        """Sample the machine without ever blocking a UI call."""

        cpu: float | None = None
        memory: float | None = None
        total: int | None = None
        available: int | None = None
        try:
            if not self._cpu_primed:
                psutil.cpu_percent(interval=None)
                self._cpu_primed = True
            else:
                cpu = float(psutil.cpu_percent(interval=None))
            virtual = psutil.virtual_memory()
            memory = float(virtual.percent)
            total = int(virtual.total)
            available = int(virtual.available)
        except Exception:
            self.logger.debug("System pressure sampling is unavailable on this machine.")
        return MachineFacts(
            cpu_percent=cpu,
            memory_percent=memory,
            total_bytes=total,
            available_bytes=available,
        )

    def _resource_plan(
        self,
        *,
        watched_pid: int | None = None,
        windows: list[Any] | None = None,
        runs: list[Any] | None = None,
    ) -> ResourcePlan:
        """Plan frame rates, reusing a snapshot the caller already paid for.

        ``get_dashboard`` has already scanned the processes and listed the
        macro runs.  Scanning again for the resource verdict doubled the cost
        of the one screen that polls the most, so the caller may hand both
        lists over instead.
        """

        active = list(runs) if runs is not None else self.list_macro_runs()
        macro_pids = {
            run.get("pid")
            for run in active
            if not run.get("finished_at")
        }
        observed = (
            list(windows)
            if windows is not None
            else list(self.monitor.current_instances())
        )
        facts = [
            InstanceFacts(
                pid=int(window.pid),
                account_id=window.account_id,
                username=str(window.account_username or ""),
                watched=watched_pid is not None and int(window.pid) == int(watched_pid),
                macro_running=window.pid in macro_pids,
                memory_bytes=window.memory_bytes,
            )
            for window in observed
        ]
        return plan_resources(
            instances=facts,
            machine=self._machine_facts(),
            settings=self._resource_settings(),
        )

    def get_resource_plan(self, watched_pid: Any = None) -> dict[str, Any]:
        """Return the frame-rate plan, watchdog verdict and remaining capacity."""

        return self._resource_plan(watched_pid=self._clean_pid(watched_pid)).to_dict()

    def apply_resource_plan(self, watched_pid: Any = None) -> dict[str, Any]:
        """Apply the only cap Roblox exposes: the global client FPS cap.

        Per-window frame rates are not achievable through the client settings
        file, so this applies the most demanding window's target and reports
        exactly what it did.
        """

        plan = self._resource_plan(watched_pid=self._clean_pid(watched_pid))
        payload = plan.to_dict()
        if plan.applied_fps is None:
            return {"applied": False, "reason": plan.applied_reason, "plan": payload}
        try:
            result = self.set_fps_cap(int(plan.applied_fps))
        except ValidationError as exc:
            return {"applied": False, "reason": str(exc), "plan": payload}
        return {
            "applied": bool(result.get("success")),
            "fps": plan.applied_fps,
            "reason": plan.applied_reason,
            "plan": payload,
        }

    def _smart_launch_plan(self, account_ids: Any, group_id: Any) -> LaunchPlan:
        accounts = [self._account_payload(item) for item in self.repository.list_accounts()]
        selected: list[dict[str, Any]] = []
        if account_ids is not None:
            if not isinstance(account_ids, (list, tuple)) or not account_ids:
                raise ValidationError("Select at least one account to launch.")
            index = {str(item.get("id")): item for item in accounts}
            for identifier in account_ids:
                item = index.get(str(identifier).strip())
                if item is None:
                    raise NotFoundError("Account was not found.")
                selected.append(item)
        elif group_id:
            group = str(group_id).strip()
            self._get_group(group)
            selected = [
                item for item in accounts if str(item.get("group_id") or "") == group
            ]
            if not selected:
                raise ValidationError("This group has no account to launch.")
        else:
            raise ValidationError("Choose a group or a list of accounts to launch.")
        running = {
            str(window.account_id)
            for window in self.monitor.current_instances()
            if window.account_id
        }
        return plan_launches(
            accounts=[
                {"account_id": item.get("id"), "username": item.get("username")}
                for item in selected
            ],
            running_account_ids=running,
            settings=self._launcher_settings(),
        )

    def plan_smart_launch(
        self, account_ids: Any = None, group_id: Any = None
    ) -> dict[str, Any]:
        """Preview a smart launch. Launches nothing."""

        plan = self._smart_launch_plan(account_ids, group_id)
        resources = self._resource_plan()
        payload = plan.to_dict()
        payload["resources"] = resources.to_dict()
        payload["blocked"] = resources.action == ACTION_RECOMMEND_CLOSE
        payload["warning"] = (
            resources.message
            if resources.action in (ACTION_PAUSE_LAUNCHES, ACTION_RECOMMEND_CLOSE)
            else ""
        )
        return payload

    def start_smart_launch(
        self, account_ids: Any = None, group_id: Any = None, target: Any = None
    ) -> dict[str, Any]:
        """Launch a selection or a whole group in staggered waves."""

        plan = self._smart_launch_plan(account_ids, group_id)
        if not plan.steps:
            raise ConflictError("Every selected account is already running.")
        resources = self._resource_plan()
        # Adding clients to a saturated machine is how a farm freezes, so the
        # watchdog gets a veto here.
        if resources.action == ACTION_RECOMMEND_CLOSE:
            raise ConflictError(resources.message)
        ordered = [step.account_id for step in plan.steps]
        status = self.batch_launcher.start_batch(
            ordered,
            dict(target) if isinstance(target, Mapping) else None,
            plan.delay_seconds,
        )
        self._activity(
            "batch_launch",
            (
                f"Smart launch queued {len(ordered)} account(s) in {plan.waves} wave(s), "
                f"{plan.delay_seconds:g}s apart"
            ),
            metadata={
                "waves": plan.waves,
                "max_concurrent": plan.max_concurrent,
                "skipped": len(plan.skipped),
            },
        )
        return {
            "plan": plan.to_dict(),
            "status": status,
            "resources": resources.to_dict(),
        }

    def stop_all_macros(self) -> dict[str, Any]:
        """Stop every live macro run. Stopping needs no confirmation."""

        stopped: list[str] = []
        for run in self.macro_engine.list_runs():
            if run.get("finished_at"):
                continue
            run_id = str(run.get("run_id") or "")
            if not run_id:
                continue
            try:
                self.macro_engine.stop(run_id)
            except MacroParseError:
                continue
            stopped.append(run_id)
        if stopped:
            self._activity("macro", f"Stopped {len(stopped)} macro run(s)")
        return {"stopped": stopped, "count": len(stopped)}

    def close_instances(self, pids: Any, *, confirm: bool = False) -> dict[str, Any]:
        """Close several clients, reusing the single confirmed path.

        This loops over ``close_instance`` on purpose instead of talking to the
        monitor directly, so closing stays explicit and never escalates to a
        forced kill.
        """

        if not isinstance(pids, (list, tuple)) or not pids:
            raise ValidationError("Select at least one instance to close.")
        if len(pids) > 32:
            raise ValidationError("Close at most 32 instances at once.")
        results: list[dict[str, Any]] = []
        for pid in pids:
            number = self._clean_pid(pid)
            if number is None:
                raise ValidationError("Instance process id is invalid.")
            results.append(self.close_instance(number, confirm=confirm))
        return {"results": results, "count": len(results)}

    def _rule_settings(self) -> Any:
        return validated_rule_settings(self.get_settings()["categories"].get("rules", {}))

    def _system_facts(self) -> SystemFacts:
        """Sample machine-wide pressure without ever blocking the watcher tick.

        The first non-blocking psutil CPU reading is always 0.0, so it is primed
        once and reported as "not measured".  An unmeasured sample can never
        pause an account, which is the safe direction to fail in.
        """

        cpu: float | None = None
        memory: float | None = None
        try:
            if not self._cpu_primed:
                psutil.cpu_percent(interval=None)
                self._cpu_primed = True
            else:
                cpu = float(psutil.cpu_percent(interval=None))
            memory = float(psutil.virtual_memory().percent)
        except Exception:
            self.logger.debug("System pressure sampling is unavailable on this machine.")
        return SystemFacts(cpu_percent=cpu, memory_percent=memory)

    @staticmethod
    def _instance_runtime_seconds(instance: Any) -> float:
        """Return how long one instance has been alive, or 0.0 when unknown."""

        started = getattr(instance, "started_at", None)
        if not isinstance(started, str) or not started:
            return 0.0
        try:
            moment = datetime.fromisoformat(started.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return max(0.0, (datetime.now(UTC) - moment).total_seconds())

    def _account_facts(self, scan: Any) -> list[AccountFacts]:
        """Build one fact row per associated instance for the rule engine."""

        now = time.monotonic()
        runs_by_account: dict[str, Mapping[str, Any]] = {}
        live_run_ids: set[str] = set()
        try:
            runs = self.list_macro_runs()
        except (AppError, RuntimeError):
            runs = []
        for run in runs:
            if not isinstance(run, Mapping):
                continue
            run_id = str(run.get("run_id") or "")
            state = str(run.get("state") or "").strip().lower()
            if not run_id or state not in {"starting", "running", "paused"}:
                continue
            live_run_ids.add(run_id)
            step = run.get("current_step")
            previous = self._macro_progress.get(run_id)
            if previous is None or previous[0] != step:
                self._macro_progress[run_id] = (step, now)
            account_id = str(run.get("account_id") or "")
            if account_id:
                runs_by_account[account_id] = run
        for stale in tuple(self._macro_progress):
            if stale not in live_run_ids:
                self._macro_progress.pop(stale, None)
                self._rule_paused_runs.discard(stale)
        facts: list[AccountFacts] = []
        for instance in getattr(scan, "instances", ()) or ():
            account_id = getattr(instance, "account_id", None)
            if not isinstance(account_id, str) or not account_id:
                continue
            try:
                account = self._get_account(account_id)
            except AppError:
                continue
            run = runs_by_account.get(account_id, {})
            run_id = str(run.get("run_id") or "") or None
            metadata = account.metadata if isinstance(account.metadata, Mapping) else {}
            seen = self._macro_progress.get(run_id or "")
            state = str(run.get("state") or "").strip().lower() or None
            facts.append(
                AccountFacts(
                    account_id=account_id,
                    username=account.username or account_id,
                    group_id=account.group_id,
                    priority=normalized_priority(metadata.get("priority")),
                    running=True,
                    runtime_seconds=self._instance_runtime_seconds(instance),
                    disconnected=getattr(instance, "pid", None) in self._log_disconnected_pids,
                    macro_run_id=run_id,
                    macro_id=str(run.get("macro_id") or "") or None,
                    macro_state="paused" if run.get("paused") else state,
                    macro_idle_seconds=max(0.0, now - seen[1]) if seen else 0.0,
                    macro_paused_by_rule=bool(run_id and run_id in self._rule_paused_runs),
                )
            )
        return facts

    def _apply_rules(self, scan: Any) -> None:
        """Evaluate the bounded rules and apply only the half that is allowed.

        Anything that would close or relaunch a live client is recorded as an
        activity entry instead of executed: this codebase requires explicit
        confirmation before terminating a Roblox process, and an automation
        rule does not get to be the exception.
        """

        try:
            settings = self._rule_settings()
        except ValidationError:
            self.logger.warning("Rule settings are invalid; the rule engine stayed idle.")
            return
        if not settings.enabled:
            self._rule_decisions = ()
            self._rule_notified.clear()
            return
        try:
            decisions = evaluate_rules(
                accounts=self._account_facts(scan),
                system=self._system_facts(),
                settings=settings,
            )
        except (ValidationError, TypeError, ValueError):
            self.logger.warning("Rule evaluation failed; no rule action was taken.")
            return
        self._rule_decisions = tuple(item.to_dict() for item in decisions)
        for decision in automatic_decisions(decisions):
            self._apply_rule_decision(decision)
        pending: set[tuple[str, str]] = set()
        for decision in recommendations(decisions):
            key = (decision.account_id, decision.rule)
            pending.add(key)
            if key in self._rule_notified:
                continue
            self._rule_notified.add(key)
            self._activity(
                "rule",
                decision.explanation,
                account_id=decision.account_id,
                metadata={"rule": decision.rule, "action": decision.action, "automatic": False},
            )
        self._rule_notified.intersection_update(pending)

    def _apply_rule_decision(self, decision: RuleDecision) -> None:
        """Apply one automatic decision through the normal validated surface."""

        run_id = decision.run_id
        if not run_id:
            return
        try:
            if decision.action == ACTION_PAUSE_MACRO:
                self.pause_macro(run_id)
                self._rule_paused_runs.add(run_id)
            elif decision.action == ACTION_RESUME_MACRO:
                self.resume_macro(run_id)
                self._rule_paused_runs.discard(run_id)
            elif decision.action == ACTION_RESTART_MACRO:
                pid = self._macro_run_pid(run_id)
                self.stop_macro(run_id)
                self._macro_progress.pop(run_id, None)
                self._rule_paused_runs.discard(run_id)
                if decision.macro_id and pid:
                    self.start_macro(decision.macro_id, pid)
            else:
                return
        except (AppError, RuntimeError, TypeError, ValueError):
            self.logger.info("A rule action could not be applied to run %s.", run_id)
            return
        self._activity(
            "rule",
            decision.explanation,
            account_id=decision.account_id,
            metadata={"rule": decision.rule, "action": decision.action, "automatic": True},
        )

    def _macro_run_pid(self, run_id: str) -> int | None:
        """Return the verified PID of one live macro run, when still present."""

        try:
            runs = self.list_macro_runs()
        except (AppError, RuntimeError):
            return None
        for run in runs:
            if isinstance(run, Mapping) and str(run.get("run_id") or "") == run_id:
                pid = run.get("pid")
                if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
                    return pid
        return None

    def _restart_policy_for(
        self,
        account: Account,
        *,
        attempt: int = 0,
        disconnect_code: int | None = None,
    ) -> RestartPolicy:
        """Build the bounded restart policy, including the rejoin backoff.

        A flat delay used to retry a dead client every N seconds no matter how
        many attempts had already failed.  The rejoin rules grow that delay per
        attempt, so a genuinely broken account backs off instead of hammering
        Roblox, while the very first attempt stays exactly as fast as before.
        """

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
        delay = rule["relaunch_delay_seconds"]
        try:
            delay = plan_rejoin(
                attempt=min(max(self._nonnegative_int(attempt), 0), MAX_REJOIN_ATTEMPTS),
                max_attempts=MAX_REJOIN_ATTEMPTS,
                base_delay_seconds=rule["relaunch_delay_seconds"],
                disconnect_code=disconnect_code,
                change_server_after=watcher.get("rejoin_change_server_after", 2),
                backoff_factor=watcher.get("rejoin_backoff_factor", 2.0),
                max_delay_seconds=watcher.get("rejoin_max_delay_seconds", 300),
                require_place=False,
            ).delay_seconds
        except (ValidationError, TypeError, ValueError):
            # A malformed rejoin setting must never disarm a relaunch the
            # operator already enabled: keep the flat delay instead.
            self.logger.warning("Rejoin backoff settings are invalid; the flat relaunch delay is used.")
        return RestartPolicy(
            # The restart policy must read the *same* arming decision the
            # watcher screen shows.  Recomputing it anywhere else is exactly
            # how the two used to disagree.
            enabled=self._relaunch_arming_state(account, watcher, rule)["armed"],
            delay_seconds=delay,
            max_attempts=rule["relaunch_max_attempts"],
            restart_on_crash=rule["relaunch_on_crash"],
            restart_on_exit=rule["relaunch_on_exit"],
        )

    def _rejoin_plan_for(self, request: RestartRequest) -> RejoinPlan:
        """Choose which server one already-granted relaunch should target.

        The process watcher owns *whether* a relaunch happens.  This only
        answers *where* to reconnect, using the last disconnect code observed
        for that account by the read-only Player-log observer.
        """

        watcher = self.get_settings()["categories"].get("watcher", {})
        try:
            return plan_rejoin(
                attempt=min(
                    max(self._nonnegative_int(getattr(request, "restart_attempt", 0)), 0),
                    MAX_REJOIN_ATTEMPTS,
                ),
                max_attempts=MAX_REJOIN_ATTEMPTS,
                base_delay_seconds=watcher.get("relaunch_delay_seconds", 15),
                disconnect_code=self._log_disconnect_codes.get(request.account_id),
                place_id=request.place_id,
                job_id=request.job_id,
                change_server_after=watcher.get("rejoin_change_server_after", 2),
                backoff_factor=watcher.get("rejoin_backoff_factor", 2.0),
                max_delay_seconds=watcher.get("rejoin_max_delay_seconds", 300),
                require_place=False,
            )
        except (ValidationError, TypeError, ValueError):
            # Never cancel a granted relaunch because a knob is malformed: keep
            # the original target by refusing to change server.
            self.logger.warning("Rejoin settings are invalid; the previous server is reused.")
            return plan_rejoin(
                attempt=0,
                change_server_after=MAX_REJOIN_ATTEMPTS,
                require_place=False,
            )

    @staticmethod
    def _validated_account_watcher_rule(
        value: Any, *, existing: Any = None
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise ValidationError("Account watcher rule is invalid.")
        baseline = {
            "enabled": True,
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
        if not isinstance(baseline["enabled"], bool):
            raise ValidationError("Account watcher enablement is invalid.")
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
            "enabled": baseline["enabled"],
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
        if not isinstance(general.get("warn_if_roblox_running"), bool):
            raise ValidationError("Roblox background warning preference is invalid.")
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
        for key in ("close_unconnected", "close_if_memory_low", "close_if_title_mismatch"):
            if not isinstance(watcher.get(key), bool):
                raise ValidationError(f"Watcher option {key} is invalid.")
        if not isinstance(watcher.get("relaunch_on_crash"), bool) or not isinstance(watcher.get("relaunch_on_exit"), bool):
            raise ValidationError("Global relaunch triggers are invalid.")
        for key, minimum, maximum, label in (
            ("launch_match_timeout_seconds", 5, 300, "Launch match timeout"),
            ("crash_window_seconds", 5, 3_600, "Crash window"),
            ("relaunch_delay_seconds", 1, 3_600, "Relaunch delay"),
            ("unconnected_timeout_seconds", 5, 3_600, "Unconnected timeout"),
            ("health_grace_seconds", 5, 600, "Watcher health grace"),
            ("rejoin_backoff_factor", 1, 10, "Rejoin backoff factor"),
            ("rejoin_max_delay_seconds", 1, 3_600, "Maximum rejoin delay"),
        ):
            numeric = watcher.get(key)
            if isinstance(numeric, bool) or not isinstance(numeric, (int, float)) or not minimum <= float(numeric) <= maximum:
                raise ValidationError(f"{label} is invalid.")
        attempts = watcher.get("relaunch_max_attempts")
        if isinstance(attempts, bool) or not isinstance(attempts, int) or not 0 <= attempts <= 20:
            raise ValidationError("Maximum relaunch attempt count is invalid.")
        change_server_after = watcher.get("rejoin_change_server_after")
        if (
            isinstance(change_server_after, bool)
            or not isinstance(change_server_after, int)
            or not 0 <= change_server_after <= 20
        ):
            raise ValidationError("The rejoin server change threshold is invalid.")
        memory_low = watcher.get("memory_low_mb")
        if isinstance(memory_low, bool) or not isinstance(memory_low, int) or not 50 <= memory_low <= 4_096:
            raise ValidationError("Low-memory threshold must be between 50 and 4096 MB.")
        expected_title = watcher.get("expected_window_title")
        if not isinstance(expected_title, str) or not 1 <= len(expected_title.strip()) <= 128:
            raise ValidationError("Expected Roblox window title is invalid.")
        validated_rule_settings(values.get("rules", {}))
        validated_launcher_settings(values.get("launcher", {}))
        validated_resource_settings(values.get("resources", {}))
        instances = values.get("instances", {})
        if not isinstance(instances, Mapping) or not isinstance(instances.get("remember_window_positions"), bool):
            raise ValidationError("Window position preference is invalid.")
        if not isinstance(instances.get("allow_multiple_launches"), bool):
            raise ValidationError("Multi-instance preference is invalid.")
        macros = values.get("macros", {})
        if not isinstance(macros, Mapping) or not all(
            isinstance(macros.get(key), bool) for key in ("enabled", "allow_background_delivery")
        ):
            raise ValidationError("Macro preferences are invalid.")
        discord = values.get("discord", {})
        if not isinstance(discord, Mapping) or not isinstance(discord.get("enabled"), bool):
            raise ValidationError("Discord Rich Presence preference is invalid.")
        discord_id = discord.get("client_id")
        if not isinstance(discord_id, str) or len(discord_id) > 32 or (discord_id and not discord_id.isdigit()):
            raise ValidationError("Discord Application ID is invalid.")
        if discord.get("strategy") not in {"latest", "aggregate"} or not isinstance(discord.get("show_account"), bool):
            raise ValidationError("Discord Rich Presence strategy is invalid.")
        if discord.get("enabled") and len(discord_id) < 5:
            raise ValidationError("A Discord Application ID is required when Rich Presence is enabled.")
        updates = values.get("updates", {})
        if not isinstance(updates, Mapping) or not all(
            isinstance(updates.get(key), bool) for key in ("auto_check", "auto_download", "install_on_exit")
        ):
            raise ValidationError("Update preferences are invalid.")
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
        network = values.get("network", {})
        if not isinstance(network, Mapping) or not isinstance(
            network.get("region_lookup_enabled"), bool
        ):
            raise ValidationError("Server region lookup state is invalid.")
        provider = network.get("region_lookup_provider")
        region_format = network.get("region_lookup_format")
        if not isinstance(provider, str) or len(provider) > 300:
            raise ValidationError("Server region provider is invalid.")
        if not isinstance(region_format, str) or not 1 <= len(region_format.strip()) <= 120:
            raise ValidationError("Server region format is invalid.")
        for key, minimum, maximum, label in (
            ("region_lookup_timeout_seconds", 0.5, 30, "Region lookup timeout"),
            ("region_cache_ttl_seconds", 30, 86_400, "Region cache lifetime"),
        ):
            numeric = network.get(key)
            if isinstance(numeric, bool) or not isinstance(numeric, (int, float)):
                raise ValidationError(f"{label} is invalid.")
            if not minimum <= float(numeric) <= maximum:
                raise ValidationError(f"{label} is invalid.")
        api = values.get("api", {})
        if not isinstance(api.get("enabled"), bool):
            raise ValidationError("Local API state is invalid.")
        if not isinstance(api.get("allow_external"), bool):
            raise ValidationError("External API access state is invalid.")
        expected_api_host = "0.0.0.0" if api.get("allow_external") else "127.0.0.1"
        if api.get("host") != expected_api_host:
            raise ValidationError("Local API host does not match its external access setting.")
        port = api.get("port")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValidationError("Local API port is invalid.")
        for permission in (
            "allow_get_cookie",
            "allow_launch_account",
            "allow_account_editing",
            "allow_import_cookie",
            "allow_get_accounts",
            "legacy_password_auth_enabled",
        ):
            if not isinstance(api.get(permission), bool):
                raise ValidationError(f"Local API permission {permission} is invalid.")

    def _account_payload(self, account: Account) -> dict[str, Any]:
        payload = account.to_dict()
        oauth = account.metadata.get("oauth") if isinstance(account.metadata, Mapping) else None
        oauth_connected = bool(oauth.get("connected")) if isinstance(oauth, Mapping) else False
        oauth_expires_at = oauth.get("expires_at") if isinstance(oauth, Mapping) else None
        watcher = account.metadata.get("watcher") if isinstance(account.metadata, Mapping) else None
        watcher_rule = (
            {
                key: watcher[key]
                for key in (
                    "enabled",
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
                "has_saved_password": self.repository.has_protected_secret(
                    account.id, "saved_password"
                ),
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
    # The whole Nexus surface is kept in the tree but hidden from the product.
    # Every public entry point below refuses to run unless ASTRO_ENABLE_NEXUS is
    # set, so no UI, palette entry, bridge call or LAN request can reach it.
    # Nothing here was deleted: setting the variable restores the feature.
    def _require_nexus_feature(self) -> None:
        if not feature_enabled("nexus"):
            raise ConflictError(
                "The Nexus surface is hidden in this build. "
                "Set ASTRO_ENABLE_NEXUS=1 before starting Astro Account Manager to restore it."
            )

    def _handle_nexus_client_log(self, username: str, message: str) -> None:
        safe_message = _redact_log_line(str(message)[:2000])
        self.logger.info("[Nexus Client Log] %s", safe_message)
        self._activity("nexus", "Roblox client log", metadata={"message": safe_message})

    def start_nexus_server(self, host: str | None = None, port: int | None = None) -> dict[str, Any]:
        self._require_nexus_feature()
        nexus_settings = self.get_settings()["categories"].get("nexus", {})
        target_host = host or nexus_settings.get("host", "127.0.0.1")
        target_port = int(port or nexus_settings.get("port", 5242))
        if target_host not in ("127.0.0.1", "localhost") and not bool(nexus_settings.get("allow_external", False)):
            raise ValidationError("External Nexus listeners require the explicit allow_external setting.")

        if self._nexus_server is None:
            from app.backend.nexus.server import NexusServer
            self._nexus_token = secrets.token_urlsafe(32)
            self._nexus_server = NexusServer(
                host=target_host,
                port=target_port,
                authentication_token=self._nexus_token,
                on_auto_relaunch_trigger=self._handle_nexus_auto_relaunch,
            )
            self._nexus_server.on_log_callback = self._handle_nexus_client_log
        self._nexus_server.start()
        self._activity("nexus", f"Nexus Server started on ws://{target_host}:{target_port}/Nexus")
        return self.get_nexus_status()

    def stop_nexus_server(self) -> dict[str, Any]:
        self._require_nexus_feature()
        return self._stop_nexus_server_unchecked()

    def _stop_nexus_server_unchecked(self) -> dict[str, Any]:
        """Stop a listener that an earlier enabled run may have left behind."""

        if self._nexus_server is not None:
            self._nexus_server.stop()
            self._nexus_server = None
            self._nexus_token = None
            self._activity("nexus", "Nexus Server stopped")
        return self.get_nexus_status()

    def get_nexus_status(self) -> dict[str, Any]:
        if not feature_enabled("nexus"):
            return {"available": False, "running": False, "accounts": []}
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
        self._require_nexus_feature()
        if self._nexus_server is None or not self._nexus_server.is_running:
            self.start_nexus_server()
        if self._nexus_server is None or not self._nexus_server.is_running:
            raise ValidationError("Nexus Server could not be started.")
        success = self._nexus_server.send_command(target_account, command_name, payload)
        self._activity("nexus", f"Nexus command '{command_name}' sent to '{target_account}'")
        return success

    def get_nexus_lua_script(self, host: str = "127.0.0.1", port: int = 5242) -> str:
        self._require_nexus_feature()
        from app.backend.nexus.lua_script import get_nexus_lua_script
        if self._nexus_server is None or not self._nexus_server.is_running:
            self.start_nexus_server(host=host, port=port)
        if self._nexus_server is None:
            raise ValidationError("Nexus Server could not be started.")
        return get_nexus_lua_script(
            host=self._nexus_server.host,
            port=self._nexus_server.port,
            token=self._nexus_token or "",
        )

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
        status = dict(self.multi_instance.get_status())
        configured = bool(
            self.get_settings()["categories"].get("instances", {}).get("allow_multiple_launches", False)
        )
        status.update(
            {
                "configured": configured,
                "restart_required": bool(configured and status.get("supported") and not status.get("enabled")),
            }
        )
        return status

    def set_multi_instance(self, enabled: bool) -> dict[str, Any]:
        if not isinstance(enabled, bool):
            raise ValidationError("Multi-instance state is invalid.")
        self.repository.set_setting("instances.allow_multiple_launches", enabled)
        if enabled:
            success = self.multi_instance.enable_multi_instance()
            if success:
                self._activity("multi_instance", "Roblox Multi-instance enabled (singleton handles held)")
            else:
                self._activity(
                    "multi_instance",
                    "Roblox Multi-instance saved; restart Astro before Roblox to activate it",
                )
        else:
            self.multi_instance.disable_multi_instance()
            self._activity("multi_instance", "Roblox Multi-instance disabled")
        return self.get_multi_instance_status()

    def _configure_multi_instance_from_settings(self) -> None:
        """Apply the persisted one-click preference to the process mutex."""

        configured = bool(
            self.get_settings()["categories"].get("instances", {}).get("allow_multiple_launches", False)
        )
        if configured:
            self.multi_instance.enable_multi_instance()
        else:
            self.multi_instance.disable_multi_instance()

    # FPS Cap & ClientSettings ------------------------------------------------
    def get_fps_cap(self) -> dict[str, Any]:
        fps = self.client_settings.get_fps_cap()
        status = self.client_settings.status()
        return {
            "fps": fps,
            "file": str(self.client_settings.settings_file),
            "verified": self.client_settings.verify_fps_targets(),
            **status,
        }

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
        ticket = self._account_utility_call(self.auth_tools.generate_auth_ticket, cookie)
        self._activity("auth_tools", "Auth ticket generated", account_id=account_id)
        return {"account_id": account_id, "ticket": ticket}

    def get_account_csrf_token(self, account_id: str) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        token = self._account_utility_call(self.auth_tools.get_csrf_token, cookie)
        self._activity("auth_tools", "X-CSRF token generated", account_id=account_id)
        return {"account_id": account_id, "csrf_token": token}

    def generate_rbx_player_link(self, account_id: str, place_id: int, job_id: str | None = None) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        ticket = self._account_utility_call(self.auth_tools.generate_auth_ticket, cookie)
        link = self._account_utility_call(self.auth_tools.generate_rbx_player_uri, ticket, place_id, job_id)
        self._activity("auth_tools", "rbx-player link generated", account_id=account_id, metadata={"place_id": place_id})
        return {"account_id": account_id, "ticket": ticket, "link": link}

    def get_account_cookie(self, account_id: str) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        account = self._get_account(account_id)
        self._activity("auth_tools", "Session/cookie extracted for copy", account_id=account_id)
        return {"account_id": account_id, "username": account.username, "cookie": cookie}

    def refresh_account_session(self, account_id: str) -> dict[str, Any]:
        """Validate the stored session and refresh its authenticated identity."""

        from app.backend.roblox import SessionRobloxClient

        account = self._get_account(account_id)
        cookie = self._get_account_cookie_raw(account.id)
        try:
            with SessionRobloxClient(cookie) as client:
                identity = client.authenticated_user()
        except RobloxServiceError as exc:
            raise ExternalServiceError("The stored Roblox session is invalid or unavailable.") from exc
        if account.user_id and int(account.user_id) != int(identity.user_id):
            raise SecurityError("The stored session belongs to a different Roblox account.")
        account.user_id = identity.user_id
        account.username = identity.username
        account.display_name = identity.display_name or account.display_name or identity.username
        account.has_session = True
        account.status = "ready"
        metadata = dict(account.metadata)
        metadata["session_last_validated_at"] = _utc_now()
        account.metadata = metadata
        try:
            saved = self.repository.save_account(account)
        except RepositoryError as exc:
            raise StorageError("The refreshed session identity could not be saved.") from exc
        self._activity("account", "Stored Roblox session validated", account_id=saved.id)
        return self._account_payload(saved)

    def export_account_sessions(self, account_ids: list[str], *, confirm: bool = False) -> dict[str, Any]:
        """Explicitly export selected raw sessions in RAM-compatible text form."""

        if confirm is not True:
            raise SecurityError("Raw session export requires explicit confirmation.")
        if not isinstance(account_ids, list) or not 1 <= len(account_ids) <= 500:
            raise ValidationError("Select between 1 and 500 accounts for session export.")
        normalized_ids = [self._required_text(value, "Account ID") for value in account_ids]
        if len(set(normalized_ids)) != len(normalized_ids):
            raise ValidationError("Session export contains duplicate accounts.")
        lines: list[str] = []
        for account_id in normalized_ids:
            account = self._get_account(account_id)
            lines.append(f"{account.username}:{self._get_account_cookie_raw(account.id)}")
        self.paths.exports.mkdir(parents=True, exist_ok=True)
        filename = f"astro-sessions-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}.txt"
        destination = (self.paths.exports / filename).resolve()
        try:
            destination.relative_to(self.paths.exports.resolve())
        except ValueError as exc:
            raise SecurityError("Session export destination is invalid.") from exc
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        try:
            descriptor = os.open(destination, flags, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("\n".join(lines) + "\n")
            try:
                os.chmod(destination, 0o600)
            except OSError:
                pass
        except OSError as exc:
            raise StorageError("Raw session export could not be written.") from exc
        self._activity("auth_tools", f"Raw sessions explicitly exported ({len(lines)} account(s))")
        return {"path": str(destination), "filename": filename, "count": len(lines), "plaintext": True}

    def add_account_from_cookie(self, cookie: str, group_id: str | None = None) -> dict[str, Any]:
        """Validates a raw .ROBLOSECURITY cookie, resolves Roblox user profile, and persists to vault & SQLite."""
        if not cookie or not isinstance(cookie, str):
            raise ValidationError(".ROBLOSECURITY cookie is required.")
        clean_cookie = cookie.strip()
        normalized_group_id = self._optional_id(group_id)
        if normalized_group_id:
            self._get_group(normalized_group_id)

        from app.backend.roblox.client import SessionRobloxClient
        session_client = SessionRobloxClient(clean_cookie)
        try:
            user = session_client.authenticated_user()
        except Exception as exc:
            raise ValidationError("Roblox rejected this session or could not be reached.") from exc
        finally:
            session_client.close()

        existing = self.repository.get_account_by_username(user.username)

        avatar_url = None
        try:
            profile = self.roblox.get_public_profile(user.user_id)
            avatar_url = profile.avatar_url
        except Exception:
            pass

        account = existing or Account(username=user.username)
        account.user_id = user.user_id
        account.username = user.username
        account.display_name = user.display_name or account.display_name or user.username
        account.avatar_url = avatar_url or account.avatar_url
        if normalized_group_id is not None:
            account.group_id = normalized_group_id
        account.last_used_at = datetime.now(UTC).isoformat()

        try:
            protected_blob = self.vault.protect(clean_cookie.encode("utf-8"))
        except Exception as exc:
            raise SecurityError("The Roblox session could not be protected by Windows.") from exc

        created_new = existing is None
        try:
            saved = self.repository.save_account(account)
            self.repository.save_protected_secret(saved.id, "session", protected_blob)
            saved.has_session = True
            saved = self.repository.save_account(saved)
        except RepositoryError as exc:
            if created_new:
                try:
                    self.repository.delete_account(account.id)
                except RepositoryError:
                    pass
            raise StorageError("The authenticated account could not be saved.") from exc
        self._activity("account", f"Account {saved.username} logged in with cookie", account_id=saved.id)
        return self._account_payload(saved)

    def start_manual_browser_login(self, group_id: str | None = None) -> dict[str, Any]:
        """Open an isolated browser for a manually entered Roblox login."""

        return self._start_browser_login(group_id=group_id)

    def start_saved_password_browser_login(self, account_id: str) -> dict[str, Any]:
        """Use one imported DPAPI password only inside the isolated browser."""

        account = self._get_account(account_id)
        protected = self.repository.load_protected_secret(account.id, "saved_password")
        if protected is None:
            raise ValidationError("This account has no imported password in the local vault.")
        try:
            password = self.vault.unprotect(protected).decode("utf-8")
        except Exception as exc:
            raise SecurityError("The imported password could not be opened for this Windows user.") from exc
        if not password:
            raise SecurityError("The imported password is empty.")
        return self._start_browser_login(
            group_id=account.group_id,
            expected_username=account.username,
            prefill_password=password,
        )

    def _start_browser_login(
        self,
        *,
        group_id: str | None = None,
        expected_username: str | None = None,
        prefill_password: str | None = None,
    ) -> dict[str, Any]:
        """Start the shared browser capture flow with optional vault input."""

        from app.backend.roblox.browser_login import BrowserLoginService, EdgeCDPLoginService
        from app.backend.roblox.client import SessionRobloxClient

        with self._browser_login_lock:
            if any(result.get("status") == "waiting" for result in self._browser_login_results.values()):
                raise ConflictError("A Roblox browser sign-in is already in progress.")
            operation_id = secrets.token_urlsafe(18)
            self._browser_login_results[operation_id] = {
                "operation_id": operation_id,
                "status": "waiting",
                "message": "Waiting for Roblox sign-in in the dedicated browser.",
            }

        def _on_captured(cookie_str: str) -> None:
            try:
                if expected_username:
                    with SessionRobloxClient(cookie_str) as validation_client:
                        identity = validation_client.authenticated_user()
                    if identity.username.casefold() != expected_username.casefold():
                        raise SecurityError(
                            "The browser signed into a different Roblox account than the selected profile."
                        )
                account = self.add_account_from_cookie(cookie_str, group_id=group_id)
            except Exception:
                self.logger.exception("Captured Roblox session could not be saved")
                with self._browser_login_lock:
                    self._browser_login_results[operation_id] = {
                        "operation_id": operation_id,
                        "status": "failed",
                        "message": "The captured Roblox session could not be validated or saved.",
                    }
            else:
                with self._browser_login_lock:
                    self._browser_login_results[operation_id] = {
                        "operation_id": operation_id,
                        "status": "completed",
                        "message": "Roblox account added.",
                        "account": self._account_payload(self._get_account(account["id"])),
                    }

        def _on_finished(captured: bool) -> None:
            if captured:
                return
            with self._browser_login_lock:
                current = self._browser_login_results.get(operation_id)
                if current is not None and current.get("status") == "waiting":
                    current["status"] = "failed"
                    current["message"] = "The Roblox sign-in browser was closed or timed out."

        # Try the dedicated Edge CDP service first. It can inspect HttpOnly
        # cookies through the local DevTools session, but completion is still
        # reported only after Roblox validates the captured session.
        try:
            edge_service = EdgeCDPLoginService()
            if prefill_password is not None:
                started = edge_service.start_login(
                    _on_captured,
                    _on_finished,
                    prefill_username=expected_username,
                    prefill_password=prefill_password,
                    auto_submit=True,
                )
            else:
                started = edge_service.start_login(_on_captured, _on_finished)
            if started:
                return {**self._browser_login_results[operation_id], "started": True, "engine": "edge_cdp"}
        except Exception:
            self.logger.debug("Edge CDP login unavailable; falling back to pywebview", exc_info=True)

        # Fallback to PyWebView BrowserLoginService
        if not hasattr(self, "_browser_login_service") or self._browser_login_service is None:
            self._browser_login_service = BrowserLoginService()

        if prefill_password is not None:
            with self._browser_login_lock:
                self._browser_login_results[operation_id]["status"] = "failed"
                self._browser_login_results[operation_id]["message"] = (
                    "Saved-password sign-in requires Microsoft Edge or Google Chrome."
                )
            raise ExternalServiceError(
                "Saved-password sign-in requires Microsoft Edge or Google Chrome."
            )
        started = self._browser_login_service.start_manual_login(_on_captured, _on_finished)
        if not started:
            with self._browser_login_lock:
                self._browser_login_results[operation_id]["status"] = "failed"
                self._browser_login_results[operation_id]["message"] = "No supported browser engine could be started."
            raise ExternalServiceError("No supported Roblox sign-in browser could be started.")
        return {**self._browser_login_results[operation_id], "started": True, "engine": "pywebview"}

    def poll_manual_browser_login(self, operation_id: str) -> dict[str, Any]:
        normalized = self._required_text(operation_id, "Browser sign-in operation ID")
        with self._browser_login_lock:
            result = self._browser_login_results.get(normalized)
            if result is None:
                raise NotFoundError("Browser sign-in operation was not found.")
            return deepcopy(result)

    # Bulk Import ------------------------------------------------------------
    def import_bulk_accounts(self, raw_text: str, group_id: str | None = None) -> dict[str, Any]:
        parsed = BulkAccountImporter.parse_text(raw_text)
        if not parsed:
            raise ValidationError("No supported account records were found in the import text.")
        if len(parsed) > 500:
            raise ValidationError("A bulk import is limited to 500 account records.")
        normalized_group_id = self._optional_id(group_id)
        if normalized_group_id is not None:
            self._get_group(normalized_group_id)
        imported_count = 0
        failed_count = 0
        imported_accounts = []
        warnings: list[str] = []

        for index, item in enumerate(parsed, start=1):
            cookie = item.get("cookie")
            username = item.get("username")
            password = item.get("password")
            if cookie and "_|WARNING" in cookie:
                try:
                    acc = self.add_account_from_cookie(cookie, group_id=normalized_group_id)
                    imported_count += 1
                    imported_accounts.append(acc)
                    if password:
                        protected_password = self.vault.protect(str(password).encode("utf-8"))
                        self.repository.save_protected_secret(acc["id"], "saved_password", protected_password)
                    continue
                except Exception:
                    warnings.append(f"Record {index}: the session cookie was rejected; only non-session metadata was imported.")

            fallback_name = username or f"Account_{len(self.repository.list_accounts()) + 1}"
            try:
                acc_payload = {
                    "username": fallback_name,
                    "group_id": normalized_group_id,
                }
                created = self.create_account(acc_payload)
                if password:
                    protected_password = self.vault.protect(str(password).encode("utf-8"))
                    self.repository.save_protected_secret(created["id"], "saved_password", protected_password)
                imported_count += 1
                imported_accounts.append(created)
            except Exception:
                failed_count += 1
                warnings.append(f"Record {index}: account metadata could not be imported.")
                self.logger.warning("Bulk account metadata import failed for record %s", index, exc_info=True)

        self._activity("bulk_import", f"{imported_count} account(s) bulk imported")
        return {
            "imported": imported_count,
            "failed": failed_count,
            "total_parsed": len(parsed),
            "accounts": imported_accounts,
            "warnings": warnings,
        }

    # Window Positioner ------------------------------------------------------
    def position_instance_window(self, pid: int, x: int, y: int, width: int = 800, height: int = 600) -> dict[str, Any]:
        success = self.window_positioner.position_window(pid, x, y, width, height)
        if success:
            self._activity("window", f"Positioned window PID {pid} at ({x}, {y})")
        return {"pid": pid, "success": success, "x": x, "y": y, "width": width, "height": height}

    def capture_instance_window(self, pid: int, *, confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            raise ValidationError("Saving a Roblox window position requires confirmation.")
        instance = next((item for item in self.monitor.current_instances() if item.pid == pid), None)
        if instance is None or not instance.account_id:
            raise ValidationError("Bind this instance to an account before saving its window position.")
        snapshot = self.window_positioner.inspect_window(pid)
        layout = self._window_layout(snapshot)
        if layout is None:
            raise ValidationError("A visible Roblox window could not be inspected.")
        account = self._get_account(instance.account_id)
        metadata = dict(account.metadata)
        metadata["window_layout"] = layout
        account.metadata = metadata
        try:
            self.repository.save_account(account)
        except RepositoryError as exc:
            raise StorageError("Roblox window position could not be saved.") from exc
        self._activity("window", "Roblox window position saved", account_id=account.id, metadata={"pid": pid})
        return {"pid": pid, "account_id": account.id, **layout}

    def restore_instance_window(self, pid: int, *, confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            raise ValidationError("Restoring a Roblox window position requires confirmation.")
        instance = next((item for item in self.monitor.current_instances() if item.pid == pid), None)
        if instance is None or not instance.account_id:
            raise ValidationError("Bind this instance to an account before restoring its window position.")
        account = self._get_account(instance.account_id)
        layout = self._window_layout(account.metadata)
        if layout is None:
            raise NotFoundError("This account has no saved Roblox window position.")
        success = bool(self.window_positioner.position_window(pid, **layout))
        if not success:
            raise ValidationError("The saved Roblox window position could not be restored.")
        self._activity("window", "Roblox window position restored", account_id=account.id, metadata={"pid": pid})
        return {"pid": pid, "account_id": account.id, "success": True, **layout}

    # Extended Account Utilities & Features ----------------------------------
    def change_account_password(self, account_id: str, current_pass: str, new_pass: str) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        success = self._account_utility_call(self.account_utils.change_password, cookie, current_pass, new_pass)
        self._activity("account_utils", "Password changed", account_id=account_id)
        return {"account_id": account_id, "success": success}

    def change_account_email(self, account_id: str, password: str, new_email: str) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        success = self._account_utility_call(self.account_utils.change_email, cookie, password, new_email)
        self._activity("account_utils", "Email change requested", account_id=account_id)
        return {"account_id": account_id, "success": success}

    def logout_all_account_sessions(self, account_id: str) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        success = self._account_utility_call(self.account_utils.logout_all_sessions, cookie)
        self._activity("account_utils", "Logged out all other sessions", account_id=account_id)
        return {"account_id": account_id, "success": success}

    def set_account_display_name(self, account_id: str, new_display_name: str) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        account = self._get_account(account_id)
        if not account.user_id:
            raise ValidationError("UserId required to update display name.")
        display_name = self._required_text(new_display_name, "Display name")
        if len(display_name) > 20:
            raise ValidationError("Display name is limited to 20 characters.")
        success = self._account_utility_call(self.account_utils.set_display_name, cookie, account.user_id, display_name)
        account.display_name = display_name
        self.repository.save_account(account)
        self._activity("account_utils", "Display name updated", account_id=account_id)
        return {"account_id": account_id, "display_name": display_name, "success": success}

    def send_account_friend_request(self, account_id: str, target_user_id: int | str) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        resolved = self._resolve_target_user_id(target_user_id)
        success = self._account_utility_call(self.account_utils.send_friend_request, cookie, resolved)
        self._activity("account_utils", f"Friend request sent to {resolved}", account_id=account_id)
        return {"account_id": account_id, "target_user_id": resolved, "success": success}

    def block_account_user(self, account_id: str, target_user_id: int | str) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        resolved = self._resolve_target_user_id(target_user_id)
        success = self._account_utility_call(self.account_utils.block_user, cookie, resolved)
        self._activity("account_utils", f"Blocked user {resolved}", account_id=account_id)
        return {"account_id": account_id, "target_user_id": resolved, "success": success}

    def unblock_account_user(self, account_id: str, target_user_id: int | str) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        resolved = self._resolve_target_user_id(target_user_id)
        success = self._account_utility_call(self.account_utils.unblock_user, cookie, resolved)
        self._activity("account_utils", f"Unblocked user {resolved}", account_id=account_id)
        return {"account_id": account_id, "target_user_id": resolved, "success": success}

    def quick_log_in_account(self, account_id: str, code: str) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        normalized = self._required_text(code, "Quick Log In code")
        if len(normalized) != 6 or not normalized.isdigit():
            raise ValidationError("Quick Log In code must contain exactly six digits.")
        success = self._account_utility_call(self.account_utils.quick_log_in, cookie, normalized)
        self._activity("account_utils", "Quick Log In code submitted", account_id=account_id)
        return {"account_id": account_id, "success": success}

    def set_account_follow_privacy(self, account_id: str, privacy: str) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        normalized = self._required_text(privacy, "Follow privacy").lower().replace(" ", "")
        success = self._account_utility_call(self.account_utils.set_follow_privacy, cookie, normalized)
        self._activity("account_utils", "Follow privacy updated", account_id=account_id)
        return {"account_id": account_id, "privacy": normalized, "success": success}

    def unlock_account_pin(self, account_id: str, pin: str) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        normalized = self._required_text(pin, "Account PIN")
        if len(normalized) != 4 or not normalized.isdigit():
            raise ValidationError("Account PIN must contain exactly four digits.")
        success = self._account_utility_call(self.account_utils.unlock_parental_pin, cookie, normalized)
        self._activity("account_utils", "Account PIN unlock requested", account_id=account_id)
        return {"account_id": account_id, "success": success}

    def get_account_blocked_list(self, account_id: str) -> list[dict[str, Any]]:
        cookie = self._get_account_cookie_raw(account_id)
        return self._account_utility_call(self.account_utils.get_blocked_users, cookie)

    def unblock_all_account_users(self, account_id: str) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        count = self._account_utility_call(self.account_utils.unblock_everyone, cookie)
        self._activity("account_utils", f"Unblocked all users ({count})", account_id=account_id)
        return {"account_id": account_id, "unblocked_count": count}

    def set_account_avatar(self, account_id: str, asset_ids: list[int]) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        if not isinstance(asset_ids, list) or not 1 <= len(asset_ids) <= 100:
            raise ValidationError("Provide between 1 and 100 avatar asset IDs.")
        normalized = [self._positive_int(item, "Avatar asset ID") for item in asset_ids]
        success = self._account_utility_call(self.account_utils.set_avatar, cookie, normalized)
        self._activity("account_utils", "Avatar outfit updated", account_id=account_id)
        return {"account_id": account_id, "asset_ids": normalized, "success": success}

    def list_universe_places(self, universe_id: int | str) -> list[dict[str, Any]]:
        try:
            return list(self.roblox.list_universe_places(self._positive_int(universe_id, "Universe ID")))
        except RobloxServiceError as exc:
            raise ExternalServiceError(str(exc), retryable=True) from exc

    def list_user_outfits(self, user_id: int | str) -> list[dict[str, Any]]:
        return self._account_utility_call(
            self.account_utils.list_outfits, self._positive_int(user_id, "Roblox User ID")
        )

    def wear_account_outfit(self, account_id: str, outfit_id: int | str) -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        details = self._account_utility_call(
            self.account_utils.wear_outfit, cookie, self._positive_int(outfit_id, "Outfit ID")
        )
        self._activity("account_utils", f"Outfit applied: {details.get('name', 'Outfit')}", account_id=account_id)
        return {"account_id": account_id, **details, "success": True}

    def join_account_group(self, account_id: str, group: int | str) -> dict[str, Any]:
        raw = str(group or "").strip()
        match = re.search(r"(?:groups/|gid=)(\d+)", raw, flags=re.IGNORECASE)
        group_id = self._positive_int(match.group(1) if match else raw, "Group ID")
        cookie = self._get_account_cookie_raw(account_id)
        success = self._account_utility_call(self.account_utils.join_group, cookie, group_id)
        self._activity("account_utils", f"Joined Roblox group {group_id}", account_id=account_id)
        return {"account_id": account_id, "group_id": group_id, "success": success}

    def open_account_browser(self, account_id: str, url: str = "https://www.roblox.com/home") -> dict[str, Any]:
        cookie = self._get_account_cookie_raw(account_id)
        try:
            result = self.authenticated_browser.open(cookie, url)
        except RobloxLaunchError as exc:
            raise ExternalServiceError(str(exc), retryable=False) from exc
        self._activity("account_utils", "Authenticated Roblox browser opened", account_id=account_id)
        return {"account_id": account_id, **result}

    def get_account_saved_password(self, account_id: str) -> dict[str, Any]:
        account = self._get_account(account_id)
        protected = self.repository.load_protected_secret(account.id, "saved_password")
        if protected is None:
            raise NotFoundError("This account has no saved password in the local vault.")
        try:
            password = self.vault.unprotect(protected).decode("utf-8")
        except Exception as exc:
            raise SecurityError("The saved password could not be opened for this Windows user.") from exc
        self._activity("account_utils", "Saved password extracted for copy", account_id=account.id)
        return {"account_id": account.id, "username": account.username, "password": password}

    def _resolve_target_user_id(self, value: int | str) -> int:
        if not isinstance(value, bool):
            try:
                return self._positive_int(value, "Target User ID")
            except ValidationError:
                pass
        username = self._required_text(value, "Target username")
        if len(username) > 20 or not all(character.isalnum() or character == "_" for character in username):
            raise ValidationError("Target must be a positive User ID or valid Roblox username.")
        try:
            candidates = self.player_search.search_players(username, 10)
        except RobloxServiceError as exc:
            raise ExternalServiceError("Roblox username resolution is unavailable.") from exc
        exact = next(
            (
                item for item in candidates
                if isinstance(item, Mapping) and str(item.get("name", "")).casefold() == username.casefold()
            ),
            None,
        )
        if exact is None:
            raise NotFoundError("The target Roblox username was not found.")
        return self._positive_int(exact.get("user_id"), "Resolved User ID")

    @staticmethod
    def _account_utility_call(action: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return action(*args, **kwargs)
        except RobloxServiceError as exc:
            raise ExternalServiceError(str(exc), retryable=False) from exc

    def parse_vip_link(self, link: str) -> dict[str, Any] | None:
        return PrivateServerHelper.parse_vip_link(link)

    def search_players(self, keyword: str, limit: int = 10) -> list[dict[str, Any]]:
        return self._account_utility_call(self.player_search.search_players, keyword, limit)

    def get_player_presence(self, user_id: int) -> dict[str, Any]:
        return self._account_utility_call(self.player_search.get_player_presence, user_id)

    def find_player_server(self, place_id: int, user_id: int, max_pages: int = 10) -> dict[str, Any] | None:
        return self._account_utility_call(
            self.player_search.find_player_server,
            place_id,
            user_id,
            max_pages=max_pages,
        )

    def get_random_server(self, place_id: int) -> dict[str, Any] | None:
        return self._account_utility_call(self.random_server.get_random_server, place_id)

    def close_beta_home_windows(self) -> dict[str, Any]:
        closed = BetaHomeCleaner.close_beta_home_windows()
        if closed:
            self._activity("watcher", f"{closed} Beta Home window(s) closed")
        return {"closed_count": closed}

    def check_for_updates(self) -> dict[str, Any]:
        result = UpdateChecker.check_for_updates()
        return {**result, "status": self.get_update_status()}

    # Macros, presence, updater and local launch preparation -----------------
    def list_macros(self) -> list[dict[str, Any]]:
        return self.repository.list_macros()

    def save_macro(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = dict(self._require_mapping(payload, "Macro data"))
        mode = str(data.get("mode") or "blocks").strip().lower()
        try:
            actions = (
                parse_macro_dsl(str(data.get("source") or ""))
                if mode == "dsl"
                else validate_macro_actions(data.get("actions") or [])
            )
        except MacroParseError as exc:
            raise ValidationError(str(exc)) from exc
        data["mode"] = mode
        data["actions"] = actions
        try:
            saved = self.repository.save_macro(data)
        except RepositoryError as exc:
            raise StorageError("Macro could not be saved.") from exc
        self._activity("macro", f"Macro saved: {saved['name']}")
        return saved

    def delete_macro(self, macro_id: str, *, confirm: bool = False) -> dict[str, Any]:
        if confirm is not True:
            raise SecurityError("Deleting a macro requires explicit confirmation.")
        try:
            deleted = self.repository.delete_macro(str(macro_id))
        except RepositoryError as exc:
            raise StorageError("Macro could not be deleted.") from exc
        if not deleted:
            raise NotFoundError("Macro was not found.")
        return {"deleted": True, "id": str(macro_id)}

    def start_macro(self, macro_id: str, pid: int, *, dry_run: bool = False) -> dict[str, Any]:
        settings = self.get_settings()["categories"].get("macros", {})
        if not bool(settings.get("enabled", True)):
            raise ConflictError("Macros are disabled in Settings.")
        process_id = self._positive_int(pid, "Process ID")
        try:
            definition = self.repository.get_macro(str(macro_id))
        except RepositoryNotFoundError as exc:
            raise NotFoundError("Macro was not found.") from exc
        instance = next((item for item in self.monitor.current_instances() if item.pid == process_id), None)
        # A dry run only traces the macro, so it does not need a live client.
        if instance is None and not dry_run:
            raise ValidationError("Select a currently verified Roblox instance.")
        account_id = instance.account_id if instance is not None else None
        required_account = definition.get("account_id")
        if instance is not None and required_account and required_account != account_id:
            raise ConflictError("This macro is assigned to a different account.")
        started_at = None
        if instance is not None and instance.started_at:
            try:
                started_at = datetime.fromisoformat(instance.started_at.replace("Z", "+00:00")).timestamp()
            except ValueError:
                started_at = None
        # Per-account variables make one macro usable by the whole fleet.
        variables: dict[str, Any] = {}
        if account_id:
            try:
                metadata = self._get_account(account_id).metadata or {}
                variables = dict((metadata.get("macro") or {}).get("variables") or {})
            except AppError:
                variables = {}
        try:
            result = self.macro_engine.start(
                definition,
                pid=process_id,
                expected_created_at=started_at,
                account_id=account_id,
                dry_run=bool(dry_run),
                variables=variables,
            )
        except MacroParseError as exc:
            raise ValidationError(str(exc)) from exc
        verb = "Macro dry run started" if dry_run else "Macro started"
        self._activity("macro", f"{verb}: {definition['name']}", account_id=account_id)
        return result

    def stop_macro(self, run_id: str) -> dict[str, Any]:
        try:
            return self.macro_engine.stop(str(run_id))
        except MacroParseError as exc:
            raise NotFoundError(str(exc)) from exc

    def pause_macro(self, run_id: str) -> dict[str, Any]:
        try:
            return self.macro_engine.pause(str(run_id))
        except MacroRunNotFound as exc:
            raise NotFoundError(str(exc)) from exc
        except MacroParseError as exc:
            raise ConflictError(str(exc)) from exc

    def resume_macro(self, run_id: str) -> dict[str, Any]:
        try:
            return self.macro_engine.resume(str(run_id))
        except MacroRunNotFound as exc:
            raise NotFoundError(str(exc)) from exc
        except MacroParseError as exc:
            raise ConflictError(str(exc)) from exc

    def get_macro_run_log(self, run_id: str) -> list[dict[str, Any]]:
        try:
            return self.macro_engine.run_log(str(run_id))
        except MacroRunNotFound as exc:
            raise NotFoundError(str(exc)) from exc

    def list_macro_runs(self) -> list[dict[str, Any]]:
        return self.macro_engine.list_runs()

    def get_discord_presence_status(self) -> dict[str, Any]:
        settings = self.get_settings()["categories"].get("discord", {})
        return {**self.discord_presence.status(), "enabled": bool(settings.get("enabled"))}

    def refresh_discord_presence(self) -> dict[str, Any]:
        settings = self.get_settings()["categories"].get("discord", {})
        client_id = str(settings.get("client_id") or "").strip()
        if not bool(settings.get("enabled")):
            self.discord_presence.close()
            return self.get_discord_presence_status()
        if not client_id:
            raise ValidationError("Configure a Discord Application ID first.")

        def game_name(place_id: int) -> str | None:
            try:
                return self.repository.get_game(place_id).name
            except RepositoryError:
                return None

        instances = [self._instance_payload(item) for item in self.monitor.current_instances()]
        activity = self.discord_presence.activity_for_instances(
            instances,
            strategy=str(settings.get("strategy") or "latest"),
            show_account=bool(settings.get("show_account")),
            game_lookup=game_name,
        )
        try:
            return self.discord_presence.publish(client_id, activity)
        except DiscordRpcError as exc:
            raise ExternalServiceError(str(exc), retryable=True) from exc

    def get_update_status(self) -> dict[str, Any]:
        return self.update_manager.status()

    def download_update(self, *, confirm: bool = False) -> dict[str, Any]:
        try:
            result = self.update_manager.download_latest(confirm=confirm)
        except UpdateError as exc:
            raise ExternalServiceError(str(exc), retryable=True) from exc
        self._activity("update", f"Update {result.get('version') or ''} downloaded")
        return result

    def schedule_update_install(self, *, confirm: bool = False) -> dict[str, Any]:
        try:
            result = self.update_manager.install_on_exit(confirm=confirm)
        except UpdateError as exc:
            raise ValidationError(str(exc)) from exc
        self._activity("update", "Update scheduled for application exit")
        return result

    def cancel_update(self, *, confirm: bool = False) -> dict[str, Any]:
        try:
            return self.update_manager.cancel_staged(confirm=confirm)
        except UpdateError as exc:
            raise ValidationError(str(exc)) from exc

    def auto_update_tick(self) -> dict[str, Any]:
        settings = self.get_settings()["categories"].get("updates", {})
        if not bool(settings.get("auto_check", True)):
            return {"checked": False, "reason": "disabled"}
        result = self.check_for_updates()
        if result.get("update_available") and bool(settings.get("auto_download", False)):
            try:
                staged = self.update_manager.download_latest(confirm=True)
                result["staged"] = staged
                if bool(settings.get("install_on_exit", False)) and self.update_manager.status().get("frozen"):
                    result["install"] = self.update_manager.install_on_exit(confirm=True)
            except UpdateError as exc:
                result["stage_error"] = str(exc)
        return result

    def get_roblox_background_status(self) -> dict[str, Any]:
        processes = self.background_manager.list_running()
        return {
            "running": bool(processes),
            "count": len(processes),
            "processes": [{"pid": item.pid, "created_at": item.created_at} for item in processes],
        }

    def close_running_roblox(self, *, confirm: bool = False) -> dict[str, Any]:
        try:
            result = self.background_manager.close_running(confirm=confirm)
        except ValidationError:
            raise
        self._activity("instances", "Existing Roblox clients were closed by explicit request")
        return result

    def launch_account_from_private_link(self, account_id: str, link: str) -> dict[str, Any]:
        parsed = PrivateServerHelper.parse_vip_link(str(link or "").strip())
        if parsed is None:
            raise ValidationError("Enter a valid roblox.com private server link.")
        if parsed.get("needs_resolution"):
            parsed = self._resolve_share_link(account_id, parsed)
        return self.launch_account(account_id, {
            "place_id": parsed["place_id"],
            "private_server_link_code": parsed["link_code"],
        })

    def _resolve_share_link(self, account_id: str, parsed: Mapping[str, Any]) -> dict[str, Any]:
        """Ask Roblox what a share link points at, signed in as the joining account.

        A share link is opaque, so this is the only way to honour one.  It needs
        a stored session: the error says so plainly rather than blaming the link.
        """

        kind = str(parsed.get("link_type") or "server").casefold()
        if kind != "server":
            raise ValidationError(f"That share link points to a {kind}, not a private server.")
        cookie = self._get_account_cookie_raw(account_id)
        resolved = self._account_utility_call(
            self.auth_tools.resolve_share_link, cookie, str(parsed.get("share_code") or "")
        )
        try:
            place_id = int(resolved.get("place_id") or 0)
        except (TypeError, ValueError):
            place_id = 0
        link_code = str(resolved.get("link_code") or "")
        if place_id <= 0 or not link_code:
            raise ValidationError("Roblox did not return a private server for that share link.")
        self._activity(
            "instances",
            "Share link resolved to a private server",
            account_id=account_id,
            metadata={"place_id": place_id},
        )
        return {"place_id": place_id, "link_code": link_code}

    def export_support_bundle(self) -> dict[str, Any]:
        result = self.support_bundle_builder.create(
            diagnostics=self.get_diagnostics(include_logs=False),
            settings=self.get_settings()["categories"],
        )
        self._activity("diagnostics", "Redacted support bundle created")
        return result


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
