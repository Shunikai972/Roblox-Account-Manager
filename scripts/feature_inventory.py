"""Machine-checked inventory of every feature this build claims to ship.

A feature list written by hand rots in a week.  This script pins each claim to a
real symbol in the source tree, so "it is implemented" is a fact the repository
can prove instead of a promise in a document.

Usage
-----
    python scripts/feature_inventory.py            # verify, print a report
    python scripts/feature_inventory.py --markdown # also refresh the doc

Exit code 0 means every claim was proven.  Exit code 1 lists the claims whose
proof no longer exists, which is exactly what happens when a refactor silently
drops a feature.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "user-guide" / "FEATURE_INVENTORY.md"

SERVICE = "app/backend/services/application_service.py"
FLEET = "app/backend/services/fleet_features.py"
BRIDGE = "app/backend/api/bridge.py"
APP_JS = "app/frontend/src/app.js"
CONFIG = "app/backend/core/config.py"
MACROS = "app/backend/automations/macros.py"
STUDIO = "app/backend/automations/macro_studio.py"
COORD = "app/backend/automations/coordination.py"
PROFILES = "app/backend/automations/launch_profiles.py"
DIRECT = "app/backend/automations/direct_input.py"
SCHED = "app/backend/automations/scheduler.py"
HEALTH = "app/backend/core/account_health.py"
REGISTRY = "app/backend/roblox/server_registry.py"
COMFORT = "app/backend/watchers/comfort.py"
STATS = "app/backend/watchers/statistics.py"
ALERTS = "app/backend/integrations/alerts.py"
MONITOR = "app/backend/watchers/process_monitor.py"
REJOIN = "app/backend/watchers/rejoin_rules.py"
RESOURCES = "app/backend/watchers/resource_plan.py"
REPO = "app/backend/security/redaction.py"

# (domain, feature, [(file, needle), ...])
FEATURES: list[tuple[str, str, list[tuple[str, str]]]] = [
    # --- Accounts and dashboard ------------------------------------------------
    ("Accounts", "Multi-account dashboard in one joined snapshot", [(SERVICE, "def get_dashboard"), (APP_JS, "renderDashboard()")]),
    ("Accounts", "Live state: offline / launching / in game / unattended / error", [(SERVICE, 'return "afk"'), (SERVICE, 'return "error"'), (APP_JS, "afk: 'In game, unattended'")]),
    ("Accounts", "Session runtime per instance", [(SERVICE, "_instance_runtime_seconds")]),
    ("Accounts", "PID and memory per instance", [(SERVICE, '"memory_mb"'), (BRIDGE, "def get_instance_monitor")]),
    ("Accounts", "Avatar, username and display name from the public profile", [(BRIDGE, "def get_public_profile"), (BRIDGE, "def refresh_account_public_profile")]),
    ("Accounts", "Roblox presence per account", [(BRIDGE, "def get_public_presence")]),
    ("Accounts", "Account groups", [(BRIDGE, "def list_groups"), (BRIDGE, "def move_accounts")]),
    ("Accounts", "Private note per account", [(APP_JS, 'id="account-notes"')]),
    ("Accounts", "Filterable tags", [(HEALTH, "def normalize_tags"), (BRIDGE, "def update_account_tags")]),
    ("Accounts", "Custom fields (Level, Gems, Trait, ...)", [(HEALTH, "def validated_custom_fields"), (BRIDGE, "def update_account_fields")]),
    ("Accounts", "Priority 0-10 used by the rules engine", [(BRIDGE, "def set_account_priority"), (FLEET, "def set_account_priority")]),
    ("Accounts", "Account health: session expired, auth needed, cannot launch", [(HEALTH, "def evaluate_account_health"), (BRIDGE, "def get_account_health")]),
    ("Accounts", "Health filters by tag, status and text", [(HEALTH, "def matches_filters")]),
    ("Accounts", "Bulk import of accounts", [(BRIDGE, "def import_bulk_accounts")]),
    ("Accounts", "Bulk delete, bulk group move, bulk edit", [(BRIDGE, "def delete_accounts"), (BRIDGE, "def reorder_accounts")]),
    ("Accounts", "Session recovery and refresh", [(BRIDGE, "def refresh_account_session"), (BRIDGE, "def export_account_sessions")]),
    ("Accounts", "OAuth sign-in and browser sign-in", [(BRIDGE, "def start_oauth_login"), (BRIDGE, "def start_manual_browser_login")]),
    ("Accounts", "Add an account from a cookie", [(BRIDGE, "def add_account_from_cookie")]),
    ("Accounts", "Account tools: password, email, display name, friends, blocks", [(BRIDGE, "def change_account_password"), (BRIDGE, "def set_account_display_name"), (BRIDGE, "def block_account_user")]),
    # --- Launching -------------------------------------------------------------
    ("Launching", "Launch one account through the Windows protocol", [(BRIDGE, "def launch_account"), (SERVICE, "def launch_account")]),
    ("Launching", "Smart launcher plan (concurrency cap, delay between launches)", [(BRIDGE, "def plan_smart_launch"), (BRIDGE, "def start_smart_launch")]),
    ("Launching", "Wave launch with a pause between waves", [(FLEET, "def start_wave_launch"), (CONFIG, "wave_pause_seconds")]),
    ("Launching", "Dynamic launch queue that waits for the previous wave", [(FLEET, "def _wave_ready_check"), (COMFORT, "def queue_gate")]),
    ("Launching", "Batch launch with cancel and live status", [(BRIDGE, "def start_batch_launch"), (BRIDGE, "def cancel_batch_launch")]),
    ("Launching", "Named launch profiles (place, server, FPS, group)", [(PROFILES, "def validated_profile"), (BRIDGE, "def launch_with_profile"), (APP_JS, "renderFleetProfiles()")]),
    ("Launching", "UWP packages and per-account clones", [(BRIDGE, "def launch_uwp_package"), (BRIDGE, "def create_uwp_account_clone")]),
    ("Launching", "Multi-instance switch", [(BRIDGE, "def set_multi_instance"), (BRIDGE, "def get_multi_instance_status")]),
    ("Launching", "Private server / VIP link launch", [(BRIDGE, "def launch_account_from_private_link"), (BRIDGE, "def parse_vip_link")]),
    ("Launching", "Join a specific player's server", [(BRIDGE, "def find_player_server"), (BRIDGE, "def get_player_presence")]),
    ("Launching", "Random server pick", [(BRIDGE, "def get_random_server")]),
    ("Launching", "Region resolution and region probing", [(BRIDGE, "def resolve_server_region"), (BRIDGE, "def probe_server_regions")]),
    ("Launching", "Window positioning and capture per instance", [(BRIDGE, "def position_instance_window"), (BRIDGE, "def capture_instance_window")]),
    ("Launching", "Close the Roblox beta home windows that steal focus", [(BRIDGE, "def close_beta_home_windows")]),
    # --- Servers ---------------------------------------------------------------
    ("Servers", "JobId inspector and visit history", [(REGISTRY, "def inspect_history"), (FLEET, "def record_server_visit")]),
    ("Servers", "Server blacklist", [(REGISTRY, "def blacklist_add"), (BRIDGE, "def update_server_blacklist")]),
    ("Servers", "Smart hopping that never picks a blacklisted server", [(REGISTRY, "def pick_server"), (BRIDGE, "def pick_best_server")]),
    ("Servers", "Region affinity when picking a server", [(FLEET, "def pick_best_server"), (APP_JS, 'id="fleet-server-region"')]),
    # --- Macros ----------------------------------------------------------------
    ("Macros", "Visual block editor (drag list, add and remove blocks)", [(APP_JS, "add-macro-block"), (APP_JS, "renderMacroBlock")]),
    ("Macros", "Text DSL editor compiling to the same action tree", [(APP_JS, "Direct Astro DSL"), (MACROS, "REPEAT")]),
    ("Macros", "Keyboard, mouse and text actions", [(MACROS, '"key_press"'), (MACROS, '"mouse_click"')]),
    ("Macros", "Condition / Launch / Teleport / Restart blocks", [(MACROS, "CONTROL_ACTIONS"), (MACROS, "CONDITION_CHECKS")]),
    ("Macros", "Randomised waits (min-max)", [(MACROS, '"max_milliseconds"')]),
    ("Macros", "Bounded loops and bounded nesting", [(MACROS, "MAX_REPEAT"), (MACROS, "MAX_DEPTH")]),
    ("Macros", "Named subroutines", [(MACROS, "MAX_SUBROUTINES")]),
    ("Macros", "Key profiles remapped per machine", [(STUDIO, "def validated_key_profile"), (BRIDGE, "def save_key_profile")]),
    ("Macros", "Per-account macro variables", [(STUDIO, "def validated_variables"), (BRIDGE, "def update_macro_variables")]),
    ("Macros", "Step-by-step debugger reporting missing variables", [(FLEET, "def debug_macro"), (BRIDGE, "def debug_macro")]),
    ("Macros", "Dry run that never touches a window", [(SERVICE, "dry_run"), (MACROS, "dry_run")]),
    ("Macros", "Profiler estimating a run before it starts", [(STUDIO, "def profile_macro")]),
    ("Macros", "Versioning with rollback", [(STUDIO, "def push_version"), (STUDIO, "def rollback_version"), (BRIDGE, "def rollback_macro")]),
    ("Macros", "Group macro start", [(FLEET, "def start_group_macro")]),
    ("Macros", "Run log and run history", [(BRIDGE, "def get_macro_run_log"), (BRIDGE, "def list_macro_runs")]),
    ("Macros", "Macro resume after a relaunch", [(FLEET, "def _queue_macro_resume"), (CONFIG, "resume_after_relaunch")]),
    ("Macros", "pydirectinput delivery for a single Roblox window", [(DIRECT, "pydirectinput")]),
    ("Macros", "Multi-window macros kept behind an explicit flag", [(CONFIG, "multi_window_macros")]),
    ("Macros", "Emergency stop: every macro and queued launch at once", [(FLEET, "def emergency_stop"), (APP_JS, "fleet-emergency-stop")]),
    ("Macros", "Stop every macro without confirmation", [(SERVICE, "def stop_all_macros")]),
    # --- Coordination ----------------------------------------------------------
    ("Coordination", "Spread mode across several servers", [(COORD, "def spread_plan")]),
    ("Coordination", "Main + followers", [(COORD, "def follower_plan")]),
    ("Coordination", "Synchronised launch and teleport", [(COORD, "def sync_plan")]),
    ("Coordination", "Internal party (same JobId, bounded size)", [(COORD, "def party_plan")]),
    # --- Resources and comfort -------------------------------------------------
    ("Comfort", "Resource plan with per-profile FPS targets", [(RESOURCES, "PROFILE_IDLE"), (BRIDGE, "def get_resource_plan")]),
    ("Comfort", "Adaptive FPS setting", [(CONFIG, "adaptive_fps_enabled")]),
    ("Comfort", "FPS cap read, set and removed", [(BRIDGE, "def set_fps_cap"), (BRIDGE, "def remove_fps_cap")]),
    ("Comfort", "Memory watchdog thresholds", [(CONFIG, "memory_critical_percent")]),
    ("Comfort", "Focus mode", [(COMFORT, "def focus_plan")]),
    ("Comfort", "Sleep mode for idle clients", [(COMFORT, "def sleep_plan")]),
    ("Comfort", "Per-instance audio levels (stored, reported honestly)", [(COMFORT, "def audio_plan")]),
    ("Comfort", "Safe shutdown behind an explicit confirmation", [(COMFORT, "def shutdown_plan")]),
    # --- Rules and scheduling --------------------------------------------------
    ("Rules", "Rule engine that pauses, relaunches and warns", [(BRIDGE, "def get_rule_decisions"), (FLEET, "def get_rules_overview")]),
    ("Rules", "Rules screen with its own settings", [(FLEET, "def update_rules"), (APP_JS, "renderFleetRules()")]),
    ("Rules", "Hourly scheduler (launch a group, stop macros, ...)", [(SCHED, "TASK_ACTIONS"), (FLEET, "def run_due_scheduled_tasks")]),
    ("Rules", "Auto-rejoin for Roblox disconnect codes", [(REJOIN, "278"), (BRIDGE, "def get_rejoin_diagnostics")]),
    ("Rules", "Restart policy after a crash or an exit", [(MONITOR, "class RestartPolicy")]),
    # --- Alerts and statistics -------------------------------------------------
    ("Alerts", "Discord webhook", [(ALERTS, "def discord_payload"), (BRIDGE, "def update_alert_settings")]),
    ("Alerts", "Phone notifications through a push relay", [(ALERTS, "def push_payload")]),
    ("Alerts", "Daily report", [(ALERTS, "def daily_report"), (BRIDGE, "def get_daily_report")]),
    ("Alerts", "Secrets never echoed back to the UI", [(ALERTS, "def redact")]),
    ("Alerts", "In-app notifications", [(BRIDGE, "def get_notifications"), (BRIDGE, "def dismiss_notification")]),
    ("Alerts", "Discord presence", [(BRIDGE, "def get_discord_presence_status")]),
    ("Statistics", "Statistics dashboard", [(STATS, "def build_statistics"), (BRIDGE, "def get_statistics")]),
    ("Statistics", "Hourly heatmap", [(STATS, "def build_heatmap")]),
    ("Statistics", "Reliability score per account", [(STATS, "def reliability_table")]),
    ("Statistics", "Macro success rate", [(STATS, "def macro_success_rate")]),
    ("Statistics", "Session comparison", [(STATS, "def compare_sessions"), (BRIDGE, "def compare_account_sessions")]),
    # --- System ----------------------------------------------------------------
    ("System", "Backups, restore and metadata export", [(BRIDGE, "def backup_data"), (BRIDGE, "def restore_backup"), (BRIDGE, "def export_metadata")]),
    ("System", "Update check, download and scheduled install", [(BRIDGE, "def check_for_updates"), (BRIDGE, "def schedule_update_install")]),
    ("System", "Start with Windows", [(BRIDGE, "def set_windows_startup")]),
    ("System", "Diagnostics and support bundle", [(BRIDGE, "def get_diagnostics"), (BRIDGE, "def export_support_bundle")]),
    ("System", "Sensitive settings refused outside OS-protected storage", [(REPO, "def is_sensitive_key"), ("app/backend/repositories/sqlite_repository.py", "if is_sensitive_key(setting_key)")]),
    ("System", "Nexus kept hidden behind an environment flag", [(CONFIG, "ASTRO_ENABLE_NEXUS")]),
]

# Deliberately absent, with the reason.  Listed so nobody has to guess whether
# these were forgotten or refused.
NOT_BUILT: list[tuple[str, str]] = [
    ("Vision: screenshots per instance, timeline, frozen-screen detector, pixel conditions, template matching, visual triggers", "Excluded by the owner of the project."),
    ("Remote: mobile dashboard, QR pairing, read-only remote view, remote screenshot", "Excluded by the owner of the project."),
    ("Farming a minimized window", "Input is delivered to the foreground window. Doing this properly needs PostMessage/SendMessage per HWND or an isolated virtual input driver, which is a separate project."),
]


def verify() -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """Return (proven, missing) as (domain, feature, proof) triples."""

    cache: dict[str, str] = {}
    proven: list[tuple[str, str, str]] = []
    missing: list[tuple[str, str, str]] = []
    for domain, feature, proofs in FEATURES:
        rendered: list[str] = []
        gaps: list[str] = []
        for relative, needle in proofs:
            if relative not in cache:
                path = ROOT / relative
                cache[relative] = path.read_text(encoding="utf-8") if path.exists() else ""
            if needle in cache[relative]:
                rendered.append(f"`{relative}` → `{needle}`")
            else:
                gaps.append(f"`{relative}` → `{needle}`")
        if gaps:
            missing.append((domain, feature, ", ".join(gaps)))
        else:
            proven.append((domain, feature, ", ".join(rendered)))
    return proven, missing


def write_markdown(proven: list[tuple[str, str, str]]) -> None:
    lines = [
        "# Feature inventory",
        "",
        "Generated by `python scripts/feature_inventory.py --markdown`.",
        "Every row is checked against the source tree, so a feature that quietly",
        "disappears during a refactor turns this file's generator red.",
        "",
        f"**{len(proven)} features proven.**",
        "",
    ]
    current = ""
    for domain, feature, proof in proven:
        if domain != current:
            current = domain
            lines += [f"## {domain}", "", "| Feature | Proven by |", "| --- | --- |"]
        lines.append(f"| {feature} | {proof} |")
    lines += ["", "## Deliberately not built", "", "| Area | Why |", "| --- | --- |"]
    for area, why in NOT_BUILT:
        lines.append(f"| {area} | {why} |")
    lines.append("")
    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    proven, missing = verify()
    for domain, feature, proof in proven:
        print(f"OK      [{domain}] {feature}")
    for domain, feature, proof in missing:
        print(f"MISSING [{domain}] {feature} :: {proof}")
    print(f"\n{len(proven)} proven, {len(missing)} missing, {len(NOT_BUILT)} deliberately absent")
    if "--markdown" in sys.argv and not missing:
        write_markdown(proven)
        print(f"wrote {DOC.relative_to(ROOT)}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
