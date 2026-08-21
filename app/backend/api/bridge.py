"""A deliberately thin, error-safe pywebview bridge."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any, Callable

from app.backend.core.errors import AppError
from app.backend.services import ApplicationService


class DesktopBridge:
    """Expose only product use cases to ``window.pywebview.api``.

    pywebview turns raised exceptions into rejected JavaScript promises.  The
    bridge normalizes domain errors first, preventing internal traceback, HTTP
    request, database or credential details from reaching the frontend.
    """

    def __init__(self, service: ApplicationService, *, logger: logging.Logger | None = None) -> None:
        self._service = service
        self._logger = logger or logging.getLogger("astro_account_manager.bridge")

    def bootstrap(self) -> dict[str, Any]:
        return self._invoke(self._service.bootstrap)

    def list_accounts(self, query: str | None = None) -> list[dict[str, Any]]:
        return self._invoke(self._service.list_accounts, query)

    def create_account(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._invoke(self._service.create_account, payload)

    def update_account(self, account_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._invoke(self._service.update_account, account_id, payload)

    def delete_accounts(self, account_ids: list[str]) -> dict[str, Any]:
        return self._invoke(self._service.delete_accounts, account_ids)

    def reorder_accounts(self, account_ids: list[str]) -> list[dict[str, Any]]:
        return self._invoke(self._service.reorder_accounts, account_ids)

    def get_public_profile(self, user_id: int | str) -> dict[str, Any]:
        """Read a public Roblox profile without returning any local secret."""

        return self._invoke(self._service.get_public_profile, user_id)

    def refresh_account_public_profile(self, account_id: str) -> dict[str, Any]:
        return self._invoke(self._service.refresh_account_public_profile, account_id)

    def get_public_presence(self, user_ids: list[int | str]) -> list[dict[str, Any]]:
        return self._invoke(self._service.get_public_presence, user_ids)

    def refresh_account_presence(self, account_ids: list[str]) -> list[dict[str, Any]]:
        return self._invoke(self._service.refresh_account_presence, account_ids)

    def start_oauth_login(self) -> dict[str, Any]:
        """Start official OAuth in the system browser; never returns a token."""

        return self._invoke(self._service.start_oauth_login)

    def poll_oauth_login(self, operation_id: str) -> dict[str, Any]:
        return self._invoke(self._service.poll_oauth_login, operation_id)

    def cancel_oauth_login(self, operation_id: str) -> dict[str, Any]:
        return self._invoke(self._service.cancel_oauth_login, operation_id)

    def refresh_oauth_account(self, account_id: str) -> dict[str, Any]:
        return self._invoke(self._service.refresh_oauth_account, account_id)

    def disconnect_oauth_account(self, account_id: str) -> dict[str, Any]:
        return self._invoke(self._service.disconnect_oauth_account, account_id)

    def list_groups(self) -> list[dict[str, Any]]:
        return self._invoke(self._service.list_groups)

    def create_group(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._invoke(self._service.create_group, payload)

    def update_group(self, group_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._invoke(self._service.update_group, group_id, payload)

    def delete_group(self, group_id: str) -> dict[str, Any]:
        return self._invoke(self._service.delete_group, group_id)

    def move_accounts(self, account_ids: list[str], group_id: str | None) -> dict[str, Any]:
        return self._invoke(self._service.move_accounts, account_ids, group_id)

    def list_games(self) -> list[dict[str, Any]]:
        return self._invoke(self._service.list_games)

    def search_games(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        return self._invoke(self._service.search_games, query, limit)

    def list_recent_games(self) -> list[dict[str, Any]]:
        return self._invoke(self._service.list_recent_games)

    def list_favorite_games(self) -> list[dict[str, Any]]:
        return self._invoke(self._service.list_favorite_games)

    def get_game(self, place_id: int | str) -> dict[str, Any]:
        return self._invoke(self._service.get_game, place_id)

    def set_game_favorite(self, place_id: int | str, favorite: bool) -> dict[str, Any]:
        return self._invoke(self._service.set_game_favorite, place_id, favorite)

    def remove_game(self, place_id: int | str) -> dict[str, Any]:
        return self._invoke(self._service.remove_game, place_id)

    def list_servers(self, place_id: int | str, options: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        return self._invoke(self._service.list_servers, place_id, options)

    def plan_server_distribution(
        self, account_ids: list[str], place_id: int | str, max_per_server: int = 1, options: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        return self._invoke(self._service.plan_server_distribution, account_ids, place_id, max_per_server, options)

    def run_server_distribution(
        self, account_ids: list[str], place_id: int | str, max_per_server: int = 1, options: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        return self._invoke(self._service.run_server_distribution, account_ids, place_id, max_per_server, options)

    def resolve_server_region(self, address: str) -> dict[str, Any]:
        return self._invoke(self._service.resolve_server_region, address)

    def probe_server_regions(
        self, account_id: str, place_id: int, job_ids: list[str]
    ) -> dict[str, Any]:
        return self._invoke(
            self._service.probe_server_regions, account_id, place_id, job_ids
        )

    def launch_account(self, account_id: str, target: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self._invoke(self._service.launch_account, account_id, target)

    def list_uwp_packages(self) -> dict[str, Any]:
        """Return current-user Roblox UWP package metadata only."""

        return self._invoke(self._service.list_uwp_packages)

    def launch_uwp_package(self, package_full_name: str) -> dict[str, Any]:
        return self._invoke(self._service.launch_uwp_package, package_full_name)

    def create_uwp_account_clone(
        self,
        account_id: str,
        confirm: bool = False,
        supports_multiple_instances: bool = True,
    ) -> dict[str, Any]:
        return self._invoke(
            self._service.create_uwp_account_clone,
            account_id,
            confirm=confirm,
            supports_multiple_instances=supports_multiple_instances,
        )

    def unregister_uwp_account_clone(
        self, account_id: str, confirm: bool = False
    ) -> dict[str, Any]:
        return self._invoke(
            self._service.unregister_uwp_account_clone,
            account_id,
            confirm=confirm,
        )

    def list_instances(self) -> list[dict[str, Any]]:
        return self._invoke(self._service.list_instances)

    def refresh_instances(self) -> list[dict[str, Any]]:
        return self._invoke(self._service.refresh_instances)

    def get_instance_monitor(self) -> dict[str, Any]:
        return self._invoke(self._service.get_instance_monitor)

    def get_instance_visibility(self, pid: int | None = None) -> dict[str, Any]:
        return self._invoke(self._service.get_instance_visibility, pid)

    def get_instance_performance(self, pid: int | None = None, include_history: bool = False) -> dict[str, Any]:
        return self._invoke(self._service.get_instance_performance, pid, include_history=include_history)

    def get_compatibility_report(self) -> dict[str, Any]:
        return self._invoke(self._service.get_compatibility_report)

    def acknowledge_roblox_version(self, confirm: bool = False) -> dict[str, Any]:
        return self._invoke(self._service.acknowledge_roblox_version, confirm=confirm)

    def set_instance_visibility(self, pid: int, visible: bool) -> dict[str, Any]:
        return self._invoke(self._service.set_instance_visibility, pid, visible)

    def set_group_visibility(self, group_id: str, visible: bool) -> dict[str, Any]:
        return self._invoke(self._service.set_group_visibility, group_id, visible)

    def close_instance(self, pid: int, confirm: bool = False) -> dict[str, Any]:
        return self._invoke(self._service.close_instance, pid, confirm=confirm)

    def bind_instance(
        self,
        pid: int,
        account_id: str,
        target: Mapping[str, Any] | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        return self._invoke(self._service.bind_instance, pid, account_id, target, confirm=confirm)

    def configure_account_watcher(self, account_id: str, rule: Mapping[str, Any]) -> dict[str, Any]:
        return self._invoke(self._service.configure_account_watcher, account_id, rule)

    def get_settings(self) -> dict[str, Any]:
        return self._invoke(self._service.get_settings)

    def update_settings(self, values: Mapping[str, Any]) -> dict[str, Any]:
        return self._invoke(self._service.update_settings, values)

    def reset_settings(self, category: str | None = None, confirm: bool = False) -> dict[str, Any]:
        return self._invoke(self._service.reset_settings, category, confirm=confirm)

    def get_windows_startup_status(self) -> dict[str, Any]:
        return self._invoke(self._service.get_windows_startup_status)

    def set_windows_startup(self, enabled: bool, confirm: bool = False) -> dict[str, Any]:
        return self._invoke(self._service.set_windows_startup, enabled, confirm=confirm)

    def get_activity(self) -> list[dict[str, Any]]:
        return self._invoke(self._service.get_activity)

    def get_notifications(self) -> list[dict[str, Any]]:
        return self._invoke(self._service.get_notifications)

    def dismiss_notification(self, notification_id: str) -> dict[str, Any]:
        return self._invoke(self._service.dismiss_notification, notification_id)

    def backup_data(self) -> dict[str, Any]:
        return self._invoke(self._service.backup_data)

    def list_backups(self) -> list[dict[str, Any]]:
        return self._invoke(self._service.list_backups)

    def restore_backup(self, backup_id: str, confirm: bool = False) -> dict[str, Any]:
        return self._invoke(self._service.restore_backup, backup_id, confirm=confirm)

    def export_metadata(self) -> dict[str, Any]:
        return self._invoke(self._service.export_metadata)

    def import_metadata(self, path: str, confirm: bool = False) -> dict[str, Any]:
        return self._invoke(self._service.import_metadata, path, confirm=confirm)

    def migrate_legacy(self, path: str) -> dict[str, Any]:
        return self._invoke(self._service.migrate_legacy, path)

    def get_diagnostics(self) -> dict[str, Any]:
        return self._invoke(self._service.get_diagnostics)

    def start_nexus_server(self, host: str | None = None, port: int | None = None) -> dict[str, Any]:
        return self._invoke(self._service.start_nexus_server, host=host, port=port)

    def stop_nexus_server(self) -> dict[str, Any]:
        return self._invoke(self._service.stop_nexus_server)

    def get_nexus_status(self) -> dict[str, Any]:
        return self._invoke(self._service.get_nexus_status)

    def send_nexus_command(self, target_account: str, command_name: str, payload: Any = None) -> bool:
        return self._invoke(self._service.send_nexus_command, target_account, command_name, payload)

    def get_nexus_lua_script(self, host: str = "127.0.0.1", port: int = 5242) -> str:
        return self._invoke(self._service.get_nexus_lua_script, host=host, port=port)

    def get_multi_instance_status(self) -> dict[str, Any]:
        return self._invoke(self._service.get_multi_instance_status)

    def set_multi_instance(self, enabled: bool) -> dict[str, Any]:
        return self._invoke(self._service.set_multi_instance, enabled)

    def get_fps_cap(self) -> dict[str, Any]:
        return self._invoke(self._service.get_fps_cap)

    def set_fps_cap(self, fps: int) -> dict[str, Any]:
        return self._invoke(self._service.set_fps_cap, fps)

    def remove_fps_cap(self) -> dict[str, Any]:
        return self._invoke(self._service.remove_fps_cap)

    def get_roblox_settings_manager(self, query: str = "") -> dict[str, Any]:
        return self._invoke(self._service.get_roblox_settings_manager, query)

    def save_roblox_settings_profile(self, profile: Mapping[str, Any]) -> dict[str, Any]:
        return self._invoke(self._service.save_roblox_settings_profile, profile)

    def delete_roblox_settings_profile(self, profile_id: str) -> dict[str, Any]:
        return self._invoke(self._service.delete_roblox_settings_profile, profile_id)

    def apply_roblox_settings(self, payload: Mapping[str, Any], confirm: bool = False) -> dict[str, Any]:
        return self._invoke(self._service.apply_roblox_settings, payload, confirm=confirm)

    def apply_roblox_settings_profile(self, profile_id: str, confirm: bool = False) -> dict[str, Any]:
        return self._invoke(self._service.apply_roblox_settings_profile, profile_id, confirm=confirm)

    def start_batch_launch(self, account_ids: list[str], target: dict[str, Any] | None = None, delay_seconds: float = 2.5) -> dict[str, Any]:
        return self._invoke(self._service.start_batch_launch, account_ids, target, delay_seconds)

    def cancel_batch_launch(self) -> dict[str, Any]:
        return self._invoke(self._service.cancel_batch_launch)

    def get_batch_launch_status(self) -> dict[str, Any]:
        return self._invoke(self._service.get_batch_launch_status)

    def generate_auth_ticket(self, account_id: str) -> dict[str, Any]:
        return self._invoke(self._service.generate_auth_ticket, account_id)

    def get_account_csrf_token(self, account_id: str) -> dict[str, Any]:
        return self._invoke(self._service.get_account_csrf_token, account_id)

    def generate_rbx_player_link(self, account_id: str, place_id: int, job_id: str | None = None) -> dict[str, Any]:
        return self._invoke(self._service.generate_rbx_player_link, account_id, place_id, job_id)

    def get_account_cookie(self, account_id: str) -> dict[str, Any]:
        return self._invoke(self._service.get_account_cookie, account_id)

    def refresh_account_session(self, account_id: str) -> dict[str, Any]:
        return self._invoke(self._service.refresh_account_session, account_id)

    def export_account_sessions(self, account_ids: list[str], confirm: bool = False) -> dict[str, Any]:
        return self._invoke(self._service.export_account_sessions, account_ids, confirm=confirm)

    def import_bulk_accounts(self, raw_text: str, group_id: str | None = None) -> dict[str, Any]:
        return self._invoke(self._service.import_bulk_accounts, raw_text, group_id)

    def position_instance_window(self, pid: int, x: int, y: int, width: int = 800, height: int = 600) -> dict[str, Any]:
        return self._invoke(self._service.position_instance_window, pid, x, y, width, height)

    def capture_instance_window(self, pid: int, confirm: bool = False) -> dict[str, Any]:
        return self._invoke(self._service.capture_instance_window, pid, confirm=confirm)

    def restore_instance_window(self, pid: int, confirm: bool = False) -> dict[str, Any]:
        return self._invoke(self._service.restore_instance_window, pid, confirm=confirm)

    def change_account_password(self, account_id: str, current_pass: str, new_pass: str) -> dict[str, Any]:
        return self._invoke(self._service.change_account_password, account_id, current_pass, new_pass)

    def change_account_email(self, account_id: str, password: str, new_email: str) -> dict[str, Any]:
        return self._invoke(self._service.change_account_email, account_id, password, new_email)

    def logout_all_account_sessions(self, account_id: str) -> dict[str, Any]:
        return self._invoke(self._service.logout_all_account_sessions, account_id)

    def set_account_display_name(self, account_id: str, new_display_name: str) -> dict[str, Any]:
        return self._invoke(self._service.set_account_display_name, account_id, new_display_name)

    def send_account_friend_request(self, account_id: str, target_user_id: int | str) -> dict[str, Any]:
        return self._invoke(self._service.send_account_friend_request, account_id, target_user_id)

    def block_account_user(self, account_id: str, target_user_id: int | str) -> dict[str, Any]:
        return self._invoke(self._service.block_account_user, account_id, target_user_id)

    def unblock_account_user(self, account_id: str, target_user_id: int | str) -> dict[str, Any]:
        return self._invoke(self._service.unblock_account_user, account_id, target_user_id)

    def quick_log_in_account(self, account_id: str, code: str) -> dict[str, Any]:
        return self._invoke(self._service.quick_log_in_account, account_id, code)

    def set_account_follow_privacy(self, account_id: str, privacy: str) -> dict[str, Any]:
        return self._invoke(self._service.set_account_follow_privacy, account_id, privacy)

    def unlock_account_pin(self, account_id: str, pin: str) -> dict[str, Any]:
        return self._invoke(self._service.unlock_account_pin, account_id, pin)

    def add_account_from_cookie(self, cookie: str, group_id: str | None = None) -> dict[str, Any]:
        return self._invoke(self._service.add_account_from_cookie, cookie, group_id)

    def start_manual_browser_login(self, group_id: str | None = None) -> dict[str, Any]:
        return self._invoke(self._service.start_manual_browser_login, group_id)

    def start_saved_password_browser_login(self, account_id: str) -> dict[str, Any]:
        return self._invoke(self._service.start_saved_password_browser_login, account_id)

    def poll_manual_browser_login(self, operation_id: str) -> dict[str, Any]:
        return self._invoke(self._service.poll_manual_browser_login, operation_id)

    def get_account_blocked_list(self, account_id: str) -> list[dict[str, Any]]:
        return self._invoke(self._service.get_account_blocked_list, account_id)

    def unblock_all_account_users(self, account_id: str) -> dict[str, Any]:
        return self._invoke(self._service.unblock_all_account_users, account_id)

    def set_account_avatar(self, account_id: str, asset_ids: list[int]) -> dict[str, Any]:
        return self._invoke(self._service.set_account_avatar, account_id, asset_ids)

    def list_universe_places(self, universe_id: int | str) -> list[dict[str, Any]]:
        return self._invoke(self._service.list_universe_places, universe_id)

    def list_user_outfits(self, user_id: int | str) -> list[dict[str, Any]]:
        return self._invoke(self._service.list_user_outfits, user_id)

    def wear_account_outfit(self, account_id: str, outfit_id: int | str) -> dict[str, Any]:
        return self._invoke(self._service.wear_account_outfit, account_id, outfit_id)

    def join_account_group(self, account_id: str, group: int | str) -> dict[str, Any]:
        return self._invoke(self._service.join_account_group, account_id, group)

    def open_account_browser(self, account_id: str, url: str = "https://www.roblox.com/home") -> dict[str, Any]:
        return self._invoke(self._service.open_account_browser, account_id, url)

    def get_account_saved_password(self, account_id: str) -> dict[str, Any]:
        return self._invoke(self._service.get_account_saved_password, account_id)

    def parse_vip_link(self, link: str) -> dict[str, Any] | None:
        return self._invoke(self._service.parse_vip_link, link)

    def search_players(self, keyword: str, limit: int = 10) -> list[dict[str, Any]]:
        return self._invoke(self._service.search_players, keyword, limit)

    def get_player_presence(self, user_id: int) -> dict[str, Any]:
        return self._invoke(self._service.get_player_presence, user_id)

    def find_player_server(self, place_id: int, user_id: int, max_pages: int = 10) -> dict[str, Any] | None:
        return self._invoke(self._service.find_player_server, place_id, user_id, max_pages)

    def get_random_server(self, place_id: int) -> dict[str, Any] | None:
        return self._invoke(self._service.get_random_server, place_id)

    def close_beta_home_windows(self) -> dict[str, Any]:
        return self._invoke(self._service.close_beta_home_windows)

    def check_for_updates(self) -> dict[str, Any]:
        return self._invoke(self._service.check_for_updates)

    def list_macros(self) -> list[dict[str, Any]]:
        return self._invoke(self._service.list_macros)

    def save_macro(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._invoke(self._service.save_macro, payload)

    def delete_macro(self, macro_id: str, confirm: bool = False) -> dict[str, Any]:
        return self._invoke(self._service.delete_macro, macro_id, confirm=confirm)

    def start_macro(self, macro_id: str, pid: int, dry_run: bool = False) -> dict[str, Any]:
        return self._invoke(self._service.start_macro, macro_id, pid, dry_run=dry_run)

    def stop_macro(self, run_id: str) -> dict[str, Any]:
        return self._invoke(self._service.stop_macro, run_id)

    def pause_macro(self, run_id: str) -> dict[str, Any]:
        return self._invoke(self._service.pause_macro, run_id)

    def resume_macro(self, run_id: str) -> dict[str, Any]:
        return self._invoke(self._service.resume_macro, run_id)

    def get_macro_run_log(self, run_id: str) -> list[dict[str, Any]]:
        return self._invoke(self._service.get_macro_run_log, run_id)

    def list_macro_runs(self) -> list[dict[str, Any]]:
        return self._invoke(self._service.list_macro_runs)

    def get_discord_presence_status(self) -> dict[str, Any]:
        return self._invoke(self._service.get_discord_presence_status)

    def refresh_discord_presence(self) -> dict[str, Any]:
        return self._invoke(self._service.refresh_discord_presence)

    def get_update_status(self) -> dict[str, Any]:
        return self._invoke(self._service.get_update_status)

    def download_update(self, confirm: bool = False) -> dict[str, Any]:
        return self._invoke(self._service.download_update, confirm=confirm)

    def schedule_update_install(self, confirm: bool = False) -> dict[str, Any]:
        return self._invoke(self._service.schedule_update_install, confirm=confirm)

    def cancel_update(self, confirm: bool = False) -> dict[str, Any]:
        return self._invoke(self._service.cancel_update, confirm=confirm)

    def get_roblox_background_status(self) -> dict[str, Any]:
        return self._invoke(self._service.get_roblox_background_status)

    def close_running_roblox(self, confirm: bool = False) -> dict[str, Any]:
        return self._invoke(self._service.close_running_roblox, confirm=confirm)

    def launch_account_from_private_link(self, account_id: str, link: str) -> dict[str, Any]:
        return self._invoke(self._service.launch_account_from_private_link, account_id, link)

    def export_support_bundle(self) -> dict[str, Any]:
        return self._invoke(self._service.export_support_bundle)

    def get_rule_decisions(self) -> list[dict[str, Any]]:
        return self._invoke(self._service.get_rule_decisions)

    def get_dashboard(self, watched_pid: int | None = None) -> dict[str, Any]:
        return self._invoke(self._service.get_dashboard, watched_pid)

    def plan_smart_launch(
        self, account_ids: list[str] | None = None, group_id: str | None = None
    ) -> dict[str, Any]:
        return self._invoke(self._service.plan_smart_launch, account_ids, group_id)

    def start_smart_launch(
        self,
        account_ids: list[str] | None = None,
        group_id: str | None = None,
        target: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._invoke(
            self._service.start_smart_launch, account_ids, group_id, target
        )

    def get_resource_plan(self, watched_pid: int | None = None) -> dict[str, Any]:
        return self._invoke(self._service.get_resource_plan, watched_pid)

    def apply_resource_plan(self, watched_pid: int | None = None) -> dict[str, Any]:
        return self._invoke(self._service.apply_resource_plan, watched_pid)

    def stop_all_macros(self) -> dict[str, Any]:
        return self._invoke(self._service.stop_all_macros)

    def close_instances(self, pids: list[int], confirm: bool = False) -> dict[str, Any]:
        return self._invoke(self._service.close_instances, pids, confirm=confirm)

    # Statistics -------------------------------------------------------------

    def get_statistics(self, window_days: int | None = None) -> dict[str, Any]:
        return self._invoke(self._service.get_statistics, window_days)

    def compare_account_sessions(self, account_id: str) -> dict[str, Any]:
        return self._invoke(self._service.compare_account_sessions, account_id)

    # Schedule ----------------------------------------------------------------

    def list_scheduled_tasks(self) -> dict[str, Any]:
        return self._invoke(self._service.list_scheduled_tasks)

    def save_scheduled_task(self, task: Mapping[str, Any]) -> dict[str, Any]:
        return self._invoke(self._service.save_scheduled_task, task)

    def delete_scheduled_task(self, task_id: str) -> dict[str, Any]:
        return self._invoke(self._service.delete_scheduled_task, task_id)

    def run_due_scheduled_tasks(self) -> dict[str, Any]:
        return self._invoke(self._service.run_due_scheduled_tasks)

    # Account health, tags and custom fields ----------------------------------

    def get_account_health(self, filters: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self._invoke(self._service.get_account_health, filters)

    def update_account_tags(self, account_id: str, tags: list[str] | None = None) -> dict[str, Any]:
        return self._invoke(self._service.update_account_tags, account_id, tags or [])

    def update_account_fields(self, account_id: str, fields: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self._invoke(self._service.update_account_fields, account_id, fields or {})

    def set_account_priority(self, account_id: str, priority: int = 0) -> dict[str, Any]:
        return self._invoke(self._service.set_account_priority, account_id, priority)

    # Servers ------------------------------------------------------------------

    def get_server_registry(self, place_id: str | None = None) -> dict[str, Any]:
        return self._invoke(self._service.get_server_registry, place_id)

    def record_server_visit(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._invoke(self._service.record_server_visit, payload)

    def update_server_blacklist(self, job_id: str, blacklisted: bool = True, note: str = "") -> dict[str, Any]:
        return self._invoke(
            self._service.update_server_blacklist, job_id, blacklisted=blacklisted, note=note
        )

    def pick_best_server(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self._invoke(self._service.pick_best_server, payload)

    # Waves and coordination ----------------------------------------------------

    def start_wave_launch(self, account_ids: list[str], target: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._invoke(self._service.start_wave_launch, account_ids, target)

    def get_wave_status(self) -> dict[str, Any]:
        return self._invoke(self._service.get_wave_status)

    def plan_coordination(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._invoke(self._service.plan_coordination, payload)

    def run_coordination(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._invoke(self._service.run_coordination, payload)

    # Comfort --------------------------------------------------------------------

    def get_comfort_overview(self, focus_pid: int | None = None) -> dict[str, Any]:
        return self._invoke(self._service.get_comfort_overview, focus_pid)

    def apply_comfort_action(self, action: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self._invoke(self._service.apply_comfort_action, action, payload)

    # Alerts ----------------------------------------------------------------------

    def get_alert_settings(self) -> dict[str, Any]:
        return self._invoke(self._service.get_alert_settings)

    def update_alert_settings(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._invoke(self._service.update_alert_settings, payload)

    def send_alert_test(self) -> dict[str, Any]:
        return self._invoke(self._service.send_alert_test)

    def get_daily_report(self, send: bool = False) -> dict[str, Any]:
        return self._invoke(self._service.get_daily_report, send)

    # Macro studio -------------------------------------------------------------------

    def get_macro_studio(self, macro_id: str = "", account_id: str = "") -> dict[str, Any]:
        return self._invoke(self._service.get_macro_studio, macro_id, account_id)

    def save_key_profile(self, profile: Mapping[str, Any]) -> dict[str, Any]:
        return self._invoke(self._service.save_key_profile, profile)

    def delete_key_profile(self, name: str) -> dict[str, Any]:
        return self._invoke(self._service.delete_key_profile, name)

    def update_macro_variables(self, account_id: str, variables: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self._invoke(self._service.update_macro_variables, account_id, variables or {})

    def debug_macro(self, macro_id: str, account_id: str = "") -> dict[str, Any]:
        return self._invoke(self._service.debug_macro, macro_id, account_id)

    def snapshot_macro_version(self, macro_id: str, label: str = "") -> dict[str, Any]:
        return self._invoke(self._service.snapshot_macro_version, macro_id, label)

    def rollback_macro(self, macro_id: str, version: int = 0) -> dict[str, Any]:
        return self._invoke(self._service.rollback_macro, macro_id, version)

    def start_group_macro(self, group_id: str, macro_id: str) -> dict[str, Any]:
        return self._invoke(self._service.start_group_macro, group_id, macro_id)

    # Rules ---------------------------------------------------------------------------

    def get_rules_overview(self) -> dict[str, Any]:
        return self._invoke(self._service.get_rules_overview)

    def update_rules(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._invoke(self._service.update_rules, payload)

    def get_rejoin_diagnostics(self) -> dict[str, Any]:
        return self._invoke(self._service.get_rejoin_diagnostics)

    # Launch profiles and emergency stop -----------------------------------------------

    def list_launch_profiles(self) -> dict[str, Any]:
        return self._invoke(self._service.list_launch_profiles)

    def save_launch_profile(self, profile: Mapping[str, Any]) -> dict[str, Any]:
        return self._invoke(self._service.save_launch_profile, profile)

    def delete_launch_profile(self, profile_id: str) -> dict[str, Any]:
        return self._invoke(self._service.delete_launch_profile, profile_id)

    def launch_with_profile(self, profile_id: str, account_ids: list[str] | None = None) -> dict[str, Any]:
        return self._invoke(self._service.launch_with_profile, profile_id, account_ids)

    def emergency_stop(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self._invoke(self._service.emergency_stop, payload)

    def _invoke(self, action: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return action(*args, **kwargs)
        except AppError as exc:
            self._logger.info("Bridge request failed with %s", exc.code)
            raise RuntimeError(exc.message) from None
        except Exception:
            self._logger.exception("Unexpected bridge failure in %s", getattr(action, "__name__", "operation"))
            raise RuntimeError("An unexpected error occurred. See Diagnostics for details.") from None
