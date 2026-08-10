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

    def list_servers(self, place_id: int | str) -> list[dict[str, Any]]:
        return self._invoke(self._service.list_servers, place_id)

    def launch_account(self, account_id: str, target: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self._invoke(self._service.launch_account, account_id, target)

    def list_uwp_packages(self) -> dict[str, Any]:
        """Return current-user Roblox UWP package metadata only."""

        return self._invoke(self._service.list_uwp_packages)

    def launch_uwp_package(self, package_full_name: str) -> dict[str, Any]:
        return self._invoke(self._service.launch_uwp_package, package_full_name)

    def list_instances(self) -> list[dict[str, Any]]:
        return self._invoke(self._service.list_instances)

    def refresh_instances(self) -> list[dict[str, Any]]:
        return self._invoke(self._service.refresh_instances)

    def get_instance_monitor(self) -> dict[str, Any]:
        return self._invoke(self._service.get_instance_monitor)

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

    def start_batch_launch(self, account_ids: list[str], target: dict[str, Any] | None = None, delay_seconds: float = 2.5) -> dict[str, Any]:
        return self._invoke(self._service.start_batch_launch, account_ids, target, delay_seconds)

    def cancel_batch_launch(self) -> dict[str, Any]:
        return self._invoke(self._service.cancel_batch_launch)

    def get_batch_launch_status(self) -> dict[str, Any]:
        return self._invoke(self._service.get_batch_launch_status)

    def generate_auth_ticket(self, account_id: str) -> dict[str, Any]:
        return self._invoke(self._service.generate_auth_ticket, account_id)

    def generate_rbx_player_link(self, account_id: str, place_id: int, job_id: str | None = None) -> dict[str, Any]:
        return self._invoke(self._service.generate_rbx_player_link, account_id, place_id, job_id)

    def get_account_cookie(self, account_id: str) -> dict[str, Any]:
        return self._invoke(self._service.get_account_cookie, account_id)

    def import_bulk_accounts(self, raw_text: str, group_id: str | None = None) -> dict[str, Any]:
        return self._invoke(self._service.import_bulk_accounts, raw_text, group_id)

    def position_instance_window(self, pid: int, x: int, y: int, width: int = 800, height: int = 600) -> dict[str, Any]:
        return self._invoke(self._service.position_instance_window, pid, x, y, width, height)

    def change_account_password(self, account_id: str, current_pass: str, new_pass: str) -> dict[str, Any]:
        return self._invoke(self._service.change_account_password, account_id, current_pass, new_pass)

    def change_account_email(self, account_id: str, password: str, new_email: str) -> dict[str, Any]:
        return self._invoke(self._service.change_account_email, account_id, password, new_email)

    def logout_all_account_sessions(self, account_id: str) -> dict[str, Any]:
        return self._invoke(self._service.logout_all_account_sessions, account_id)

    def set_account_display_name(self, account_id: str, new_display_name: str) -> dict[str, Any]:
        return self._invoke(self._service.set_account_display_name, account_id, new_display_name)

    def send_account_friend_request(self, account_id: str, target_user_id: int) -> dict[str, Any]:
        return self._invoke(self._service.send_account_friend_request, account_id, target_user_id)

    def block_account_user(self, account_id: str, target_user_id: int) -> dict[str, Any]:
        return self._invoke(self._service.block_account_user, account_id, target_user_id)

    def unblock_account_user(self, account_id: str, target_user_id: int) -> dict[str, Any]:
        return self._invoke(self._service.unblock_account_user, account_id, target_user_id)

    def quick_log_in_account(self, account_id: str, code: str) -> dict[str, Any]:
        return self._invoke(self._service.quick_log_in_account, account_id, code)

    def add_account_from_cookie(self, cookie: str, group_id: str | None = None) -> dict[str, Any]:
        return self._invoke(self._service.add_account_from_cookie, cookie, group_id)

    def start_manual_browser_login(self, group_id: str | None = None) -> dict[str, Any]:
        return self._invoke(self._service.start_manual_browser_login, group_id)

    def get_account_blocked_list(self, account_id: str) -> list[dict[str, Any]]:
        return self._invoke(self._service.get_account_blocked_list, account_id)

    def unblock_all_account_users(self, account_id: str) -> dict[str, Any]:
        return self._invoke(self._service.unblock_all_account_users, account_id)

    def set_account_avatar(self, account_id: str, asset_ids: list[int]) -> dict[str, Any]:
        return self._invoke(self._service.set_account_avatar, account_id, asset_ids)

    def parse_vip_link(self, link: str) -> dict[str, Any] | None:
        return self._invoke(self._service.parse_vip_link, link)

    def search_players(self, keyword: str, limit: int = 10) -> list[dict[str, Any]]:
        return self._invoke(self._service.search_players, keyword, limit)

    def get_player_presence(self, user_id: int) -> dict[str, Any]:
        return self._invoke(self._service.get_player_presence, user_id)

    def get_random_server(self, place_id: int) -> dict[str, Any] | None:
        return self._invoke(self._service.get_random_server, place_id)

    def close_beta_home_windows(self) -> dict[str, Any]:
        return self._invoke(self._service.close_beta_home_windows)

    def check_for_updates(self) -> dict[str, Any]:
        return self._invoke(self._service.check_for_updates)

    # Nexus Account Control ---------------------------------------------------
    def start_nexus_server(self, host: str | None = None, port: int | None = None) -> dict[str, Any]:
        return self._invoke(self._service.start_nexus_server, host, port)

    def stop_nexus_server(self) -> dict[str, Any]:
        return self._invoke(self._service.stop_nexus_server)

    def get_nexus_status(self) -> dict[str, Any]:
        return self._invoke(self._service.get_nexus_status)

    def send_nexus_command(self, target_account: str, command_name: str, payload: Any = None) -> bool:
        return self._invoke(self._service.send_nexus_command, target_account, command_name, payload)

    def get_nexus_lua_script(self, host: str = "127.0.0.1", port: int = 5242) -> str:
        return self._invoke(self._service.get_nexus_lua_script, host, port)

    def _invoke(self, action: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return action(*args, **kwargs)
        except AppError as exc:
            self._logger.info("Bridge request failed with %s", exc.code)
            raise RuntimeError(exc.message) from None
        except Exception:
            self._logger.exception("Unexpected bridge failure in %s", getattr(action, "__name__", "operation"))
            raise RuntimeError("Une erreur inattendue est survenue. Consultez Diagnostics pour le détail.") from None
