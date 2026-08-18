"""Application paths and validated default preferences."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


APP_NAME = "Astro Account Manager"
APP_SLUG = "AstroAccountManager"
# Keep existing local workspaces reachable after the product rename.  We do
# not move or overwrite an old directory automatically; on first run after
# the rename, the app continues to use it until the user explicitly migrates
# their data.
LEGACY_APP_SLUG = "AsteriaAccountManager"
APP_VERSION = "4.0.3"


# Features that stay in the source tree but are intentionally unreachable from
# the shipped product.  Nothing is deleted: flip the matching environment
# variable (for example ASTRO_ENABLE_NEXUS=1) to bring a surface back without
# touching any code.  Keeping the registry here means the backend, the desktop
# bridge and the UI all read the same single source of truth.
HIDDEN_FEATURES: dict[str, str] = {
    "nexus": "ASTRO_ENABLE_NEXUS",
    # Running macros on several Roblox windows at once is set aside, not
    # removed: pydirectinput needs the foreground, so two concurrent runs
    # fight over it and steal each other's keystrokes.  The code path stays
    # intact behind this flag for a later redesign.
    "multi_window_macros": "ASTRO_ENABLE_MULTI_WINDOW_MACROS",
}

_TRUTHY = {"1", "true", "yes", "on", "enable", "enabled"}


def feature_enabled(name: str) -> bool:
    """Return True when a hidden feature has been explicitly re-enabled.

    Unknown feature names are always enabled: only names listed in
    ``HIDDEN_FEATURES`` are hidden, so adding a normal feature never needs a
    flag.
    """

    variable = HIDDEN_FEATURES.get(str(name))
    if variable is None:
        return True
    return str(os.environ.get(variable, "")).strip().casefold() in _TRUTHY


def feature_flags() -> dict[str, bool]:
    """Return the resolved state of every hideable feature for the UI."""

    return {name: feature_enabled(name) for name in HIDDEN_FEATURES}


DEFAULT_SETTINGS: dict[str, Any] = {
    "general": {
        "launch_delay_ms": 2500,
        "max_recent_games": 8,
        "auto_refresh_account_state": False,
        "auto_backup": True,
        "start_with_windows": False,
        "warn_if_roblox_running": True,
    },
    "appearance": {
        "theme": "dark",
        "accent": "#7c5cff",
        "density": "comfortable",
        "reduced_motion": False,
    },
    "accounts": {
        "remember_login_details": False,
        "show_presence": True,
        "presence_update_seconds": 60,
    },
    "instances": {
        "allow_multiple_launches": False,
        "prevent_duplicate_accounts": True,
        "remember_window_positions": False,
        "launch_queue_parallelism": 1,
    },
    "macros": {
        "enabled": True,
        "allow_background_delivery": True,
        # When a client is relaunched by the rules, the macro it was running is
        # queued and restarted once the new process is verified.
        "resume_after_relaunch": True,
    },
    "discord": {
        "enabled": False,
        "client_id": "",
        "strategy": "latest",
        "show_account": False,
    },
    "updates": {
        "auto_check": True,
        "auto_download": False,
        "install_on_exit": False,
    },
    "watcher": {
        "enabled": True,
        "scan_interval_seconds": 6,
        "termination_enabled": False,
        "launch_match_timeout_seconds": 45,
        "crash_window_seconds": 120,
        "auto_relaunch_enabled": False,
        "relaunch_delay_seconds": 15,
        "relaunch_max_attempts": 2,
        "relaunch_on_crash": True,
        "relaunch_on_exit": False,
        "close_unconnected": False,
        "unconnected_timeout_seconds": 60,
        "close_if_memory_low": False,
        "memory_low_mb": 200,
        "close_if_title_mismatch": False,
        "health_grace_seconds": 30,
        # Rejoin shaping for relaunches the process watcher already granted.
        # Closing a live client from a log event is deliberately NOT done here:
        # terminate_known_process() requires explicit human confirmation.
        "rejoin_change_server_after": 2,
        "rejoin_backoff_factor": 2.0,
        "rejoin_max_delay_seconds": 300,
        "expected_window_title": "Roblox",
    },
    # IF/THEN automation rules.  Disabled by default: they act on live farms.
    "rules": {
        "enabled": False,
        "macro_stuck_seconds": 60,
        # Never name a setting with a credential-like word (session, token,
        # secret, cookie, password): flattened keys go through
        # SQLiteRepository.set_setting, which refuses them outright.
        "max_runtime_hours": 6.0,
        "cpu_pause_percent": 90,
        "memory_pause_percent": 90,
        "pause_priority_at_or_below": 3,
        "restart_stuck_macros": True,
        "group_ids": [],
    },
    # Smart launcher.  Ten clients booting at the same instant is what melts a
    # machine, so launches are staggered and capped by default.
    "launcher": {
        "max_concurrent": 3,
        "delay_seconds": 4.0,
        "wait_for_wave": True,
        # The breather between waves: what keeps 20 alts from starting at once.
        "wave_pause_seconds": 6.0,
        "skip_running": True,
    },
    # Focus, sleep and the dynamic launch gate.  Every value here is read by
    # the comfort planner or the wave gate; none of them is a dead switch.
    "comfort": {
        "focus_volume": 100,
        "background_volume": 0,
        "focus_minimizes_others": True,
        "sleep_after_minutes": 15,
        "queue_cpu_percent": 80,
        "queue_memory_percent": 85,
        "queue_max_instances": 0,
    },
    # Adaptive frame rates and the memory watchdog.  Adaptive FPS stays off by
    # default because applying it rewrites the shared Roblox client settings.
    "resources": {
        "adaptive_fps_enabled": False,
        "watched_fps": 60,
        "macro_fps": 20,
        "idle_fps": 5,
        "memory_warn_percent": 85,
        "memory_critical_percent": 93,
        "reserve_mb": 2048,
        "average_instance_mb": 1200,
    },
    "performance": {
        "global_max_fps": 0,
        "potato_graphics": False,
    },
    "network": {
        "request_timeout_seconds": 15,
        "region_lookup_enabled": False,
        "region_lookup_provider": "",
        "region_lookup_format": "{city}, {country}",
        "region_lookup_timeout_seconds": 4,
        "region_cache_ttl_seconds": 900,
    },
    "oauth": {
        # OAuth is opt-in because each distribution or developer build needs
        # its own Roblox OAuth application registration.  The client id is
        # public; no client secret is used or stored by this desktop flow.
        "enabled": False,
        "client_id": "",
        "redirect_uri": "http://127.0.0.1:8989/oauth/callback",
        "callback_timeout_seconds": 300,
    },
    "api": {
        "enabled": False,
        "host": "127.0.0.1",
        "port": 7963,
        "allow_external": False,
        "allow_get_cookie": False,
        "allow_launch_account": False,
        "allow_account_editing": False,
        "allow_import_cookie": False,
        "allow_get_accounts": False,
        "legacy_password_auth_enabled": False,
    },
    "nexus": {
        "enabled": False,
        "host": "127.0.0.1",
        "port": 5242,
        "allow_external": False,
    },
    "notifications": {
        "auto_dismiss_seconds": 7,
        "desktop_notifications": True,
    },
    "developer": {
        "enabled": False,
        "verbose_logs": False,
    },
}


@dataclass(frozen=True, slots=True)
class AppPaths:
    root: Path
    database: Path
    logs: Path
    backups: Path
    cache: Path
    exports: Path

    @classmethod
    def for_current_user(cls) -> "AppPaths":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            base = Path(local_app_data)
        else:
            base = Path.home() / ".local" / "share"
        preferred = base / APP_SLUG
        legacy = base / LEGACY_APP_SLUG
        # Existing Asteria data remains the active workspace rather than being
        # silently copied or split into a second database under the new name.
        root = legacy if not preferred.exists() and legacy.exists() else preferred
        # New Astro installs use the matching database name.  An existing
        # Asteria workspace keeps its old database filename, so the rebrand
        # never hides or duplicates user data.
        legacy_database = root / "asteria.db"
        database = legacy_database if root == legacy or legacy_database.exists() else root / "astro.db"
        return cls(
            root=root,
            database=database,
            logs=root / "logs",
            backups=root / "backups",
            cache=root / "cache",
            exports=root / "exports",
        )

    def ensure_exists(self) -> None:
        for directory in (self.root, self.logs, self.backups, self.cache, self.exports):
            directory.mkdir(parents=True, exist_ok=True)


def merge_settings(base: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge a user settings payload without mutating defaults."""

    merged = dict(base)
    for key, value in values.items():
        previous = merged.get(key)
        if isinstance(previous, dict) and isinstance(value, dict):
            merged[key] = merge_settings(previous, value)
        else:
            merged[key] = value
    return merged
