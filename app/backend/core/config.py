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
APP_VERSION = "4.0.0a1"


DEFAULT_SETTINGS: dict[str, Any] = {
    "general": {
        "launch_delay_ms": 2500,
        "max_recent_games": 8,
        "auto_refresh_account_state": False,
        "auto_backup": True,
        "start_with_windows": False,
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
        "expected_window_title": "Roblox",
    },
    "network": {
        "request_timeout_seconds": 15,
        "region_lookup_enabled": False,
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
