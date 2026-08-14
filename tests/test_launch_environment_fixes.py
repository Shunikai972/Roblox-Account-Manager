"""Regression tests for the four defects reported from real use.

They cover: the watcher polling loop and its new per-account switch, the FPS
unlocker discovery/settings/reporting chain, the Multi Roblox singleton holder,
and the previously inert Games & servers page.

These tests are deliberately written without pytest fixtures so they can also be
run by the offline runner used in environments where pytest cannot be installed.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import re
import tempfile
import threading
import time
from unittest import mock

import pytest

from app.backend.core.config import AppPaths, DEFAULT_SETTINGS
from app.backend.models.domain import Account
from app.backend.roblox.client_settings import ClientSettingsPatcher
from app.backend.roblox.multi_instance import WindowsMultiInstanceController
from app.backend.services.application_service import ApplicationService
from app.backend.watchers.process_monitor import MonitorPollingLoop

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "frontend" / "src" / "app.js"
BRIDGE_JS = ROOT / "app" / "frontend" / "src" / "bridge.js"
BRIDGE_PY = ROOT / "app" / "backend" / "api" / "bridge.py"
SERVICE_PY = ROOT / "app" / "backend" / "services" / "application_service.py"
MULTI_PY = ROOT / "app" / "backend" / "roblox" / "multi_instance.py"
CLIENT_SETTINGS_PY = ROOT / "app" / "backend" / "roblox" / "client_settings.py"


# =============================================================== 1. watcher


def test_monitor_polling_loop_really_scans_in_the_background() -> None:
    """Prove the loop scans on its own thread instead of only on demand."""

    ticks = []
    gate = threading.Event()

    def scan() -> None:
        ticks.append(time.monotonic())
        if len(ticks) >= 2:
            gate.set()

    loop = MonitorPollingLoop(scan, interval_seconds=lambda: 1.0)
    loop.start()
    try:
        assert loop.running is True
        assert gate.wait(timeout=10.0), "the polling loop never scanned in the background"
        assert len(ticks) >= 2
    finally:
        loop.stop()
    assert loop.running is False


def test_watcher_loop_accepts_a_bound_interval_callable() -> None:
    """The service passes a bound method; that is intended, not a bug."""

    calls = []

    class Holder:
        def interval(self) -> float:
            calls.append(1)
            return 1.0

    loop = MonitorPollingLoop(lambda: None, interval_seconds=Holder().interval)
    loop.start()
    try:
        time.sleep(0.2)
    finally:
        loop.stop()
    assert calls, "the loop never asked for its interval"


def test_watcher_is_enabled_by_default_in_settings() -> None:
    assert DEFAULT_SETTINGS["watcher"]["enabled"] is True


def test_account_watcher_rule_defaults_to_watching() -> None:
    rule = ApplicationService._validated_account_watcher_rule({})
    assert rule["enabled"] is True


def test_account_watcher_rule_can_be_disabled_per_account() -> None:
    rule = ApplicationService._validated_account_watcher_rule({"enabled": False})
    assert rule["enabled"] is False


def test_account_watcher_rule_preserves_an_existing_switch() -> None:
    rule = ApplicationService._validated_account_watcher_rule(
        {"enabled": False, "auto_relaunch": True}
    )
    assert rule["enabled"] is False
    assert rule["auto_relaunch"] is True


def test_account_watcher_rule_rejects_a_non_boolean_switch() -> None:
    with pytest.raises(Exception) as excinfo:
        ApplicationService._validated_account_watcher_rule({"enabled": "yes"})
    assert "enablement" in str(excinfo.value).lower() or "invalid" in str(excinfo.value).lower()


def test_account_management_page_exposes_the_watcher_switch() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert "watcher_enabled" in source
    assert "configure_account_watcher" in source
    assert "Watch this account" in source


def test_a_disabled_account_switch_blocks_the_automatic_relaunch() -> None:
    source = SERVICE_PY.read_text(encoding="utf-8")
    assert 'rule.get("enabled", True)' in source, "the restart policy must honour the switch"


# ========================================================= 2. Multi Roblox


def test_multi_instance_holds_both_singleton_objects() -> None:
    assert WindowsMultiInstanceController.MUTEX_NAME == "ROBLOX_singletonMutex"
    assert WindowsMultiInstanceController.EVENT_NAME == "ROBLOX_singletonEvent"


def test_multi_instance_reports_an_honest_status_off_windows() -> None:
    controller = WindowsMultiInstanceController()
    status = controller.get_status()
    assert status["supported"] is (os.name == "nt")
    if os.name != "nt":
        assert status["enabled"] is False
        assert status["handle_count"] == 0


def test_multi_instance_status_is_reported_for_the_ui() -> None:
    status = WindowsMultiInstanceController().get_status()
    for key in (
        "supported",
        "enabled",
        "handle_count",
        "held_objects",
        "owned_objects",
        "adopted_existing",
        "event_held",
        "mutex_held",
        "holder_thread_alive",
        "reacquisitions",
        "remote_event_handles_closed",
        "last_prepared_pids",
        "last_preparation_error",
        "last_error",
    ):
        assert key in status


def test_multi_instance_adopts_an_existing_object_instead_of_failing() -> None:
    """An existing singleton must be adopted, not refused.

    The original code closed its handle and returned False whenever Roblox had
    created the mutex first, which is exactly the intermittent failure reported.
    """

    source = MULTI_PY.read_text(encoding="utf-8")
    acquire = source[source.index("def _acquire") : source.index("def _heal")]
    assert "ERROR_ALREADY_EXISTS" not in acquire, "acquire must not give up on an existing object"
    assert "adopted" in acquire
    assert "CloseHandle" not in acquire, "the handle must stay open to keep the object alive"


def test_multi_instance_holds_the_objects_on_a_dedicated_thread() -> None:
    """Win32 mutex ownership is thread affine.

    If the owning thread ends without releasing, the mutex is abandoned and
    Roblox can take the gate back. Ownership therefore lives on one long-lived
    holder thread, which is what the launchers that do this reliably rely on.
    """

    source = MULTI_PY.read_text(encoding="utf-8")
    assert "import threading" in source
    enable = source[
        source.index("def enable_multi_instance") : source.index("def disable_multi_instance")
    ]
    assert "threading.Thread" in enable
    assert "_hold_until_released" in enable
    hold = source[source.index("def _hold_until_released") : source.index("def _acquire")]
    assert "self._release.wait" in hold, "the holder thread must stay alive while enabled"
    assert "_release_objects" in hold


def test_multi_instance_releases_ownership_before_closing() -> None:
    source = MULTI_PY.read_text(encoding="utf-8")
    release = source[source.index("def _release_objects") :]
    release = release[: release.index("def _create_mutex")]
    assert "ReleaseMutex" in release
    assert release.index("release_mutex(handle)") < release.index("close_handle(handle)")


def test_multi_instance_retries_an_object_it_could_not_create() -> None:
    source = MULTI_PY.read_text(encoding="utf-8")
    heal = source[source.index("def _heal") : source.index("def _release_objects")]
    assert "_create_mutex" in heal
    assert "_create_event" in heal
    assert "reacquisitions" in heal


def test_multi_instance_prepares_current_clients_before_every_launch() -> None:
    """Current clients retain a singleton event even while Astro owns the mutex."""

    source = MULTI_PY.read_text(encoding="utf-8")
    prepare = source[source.index("def prepare_for_launch") : source.index("def disable_multi_instance")]
    assert "robloxplayerbeta.exe" in prepare.casefold()
    assert "_close_remote_singleton_event_handles" in prepare
    close_remote = source[source.index("def _close_remote_singleton_event_handles") :]
    assert "SYSTEM_EXTENDED_HANDLE_INFORMATION" in close_remote
    assert "DUPLICATE_CLOSE_SOURCE" in close_remote
    assert "endswith(self.EVENT_NAME.casefold())" in close_remote

    service = SERVICE_PY.read_text(encoding="utf-8")
    launch = service[service.index("def launch_account") : service.index("# UWP packages")]
    assert 'getattr(self.multi_instance, "prepare_for_launch", None)' in launch
    assert "prepare_for_launch() if callable(prepare_for_launch) else {}" in launch


def test_multi_instance_releases_every_handle_on_disable() -> None:
    controller = WindowsMultiInstanceController()
    controller.disable_multi_instance()
    status = controller.get_status()
    assert status["handle_count"] == 0
    assert status["enabled"] is False
    assert status["holder_thread_alive"] is False


def test_multi_instance_enable_is_idempotent() -> None:
    controller = WindowsMultiInstanceController()
    first = controller.enable_multi_instance()
    second = controller.enable_multi_instance()
    try:
        assert first == second
        if os.name != "nt":
            assert first is False
    finally:
        controller.disable_multi_instance()


def test_multi_instance_reports_why_it_could_not_start() -> None:
    if os.name == "nt":
        pytest.skip("this path only applies off Windows")
    controller = WindowsMultiInstanceController()
    controller.enable_multi_instance()
    assert controller.get_status()["last_error"]


# ========================================================== 3. FPS unlocker


def test_performance_settings_exist_so_the_global_toggles_persist() -> None:
    performance = DEFAULT_SETTINGS["performance"]
    assert performance["global_max_fps"] == 0
    assert performance["potato_graphics"] is False


def test_global_performance_toggles_are_reachable_from_the_ui() -> None:
    app_source = APP_JS.read_text(encoding="utf-8")
    service_source = SERVICE_PY.read_text(encoding="utf-8")
    assert "global_max_fps" in app_source
    assert "potato_graphics" in app_source
    assert "performance.global_max_fps" in service_source
    assert "performance.potato_graphics" in service_source
    assert "s.global_max_fps == 240 || !s.global_max_fps" not in app_source


def test_launch_consults_the_global_fps_preference() -> None:
    source = SERVICE_PY.read_text(encoding="utf-8")
    assert 'performance.get("global_max_fps")' in source or 'performance["global_max_fps"]' in source


def test_per_account_fps_still_wins_over_the_global_preference() -> None:
    source = SERVICE_PY.read_text(encoding="utf-8")
    account_fps = source.index('launch_opts.get("max_fps")')
    global_fps = source.index('"global_max_fps"', account_fps - 4000)
    assert account_fps < source.index('"global_max_fps"', account_fps), (
        "the account value must be consulted before the global preference"
    )
    assert global_fps > 0


def test_a_failed_client_settings_patch_is_no_longer_silent() -> None:
    source = SERVICE_PY.read_text(encoding="utf-8")
    assert "FPS unlocker not applied" in source


def test_client_settings_falls_back_to_the_versions_directory() -> None:
    base = pathlib.Path(tempfile.mkdtemp())
    versions = base / "Roblox" / "Versions"
    older = versions / "version-aaaaaaaaaaaa"
    newer = versions / "version-bbbbbbbbbbbb"
    decoy = versions / "not-a-version"
    for folder in (older, newer, decoy):
        folder.mkdir(parents=True)
        (folder / "RobloxPlayerBeta.exe").write_bytes(b"stub")
    os.utime(older / "RobloxPlayerBeta.exe", (1_000_000, 1_000_000))
    os.utime(newer / "RobloxPlayerBeta.exe", (2_000_000, 2_000_000))

    found = ClientSettingsPatcher._scan_versions_roots([versions])
    assert found == newer, "the newest version folder must win"


def test_client_settings_fallback_rejects_a_folder_without_a_player() -> None:
    base = pathlib.Path(tempfile.mkdtemp())
    versions = base / "Roblox" / "Versions"
    empty = versions / "version-cccccccccccc"
    empty.mkdir(parents=True)

    assert ClientSettingsPatcher._scan_versions_roots([versions]) is None


def test_client_settings_fallback_is_inert_off_windows() -> None:
    if os.name == "nt":
        pytest.skip("this path only applies off Windows")
    assert ClientSettingsPatcher._discover_versions_directory() is None


def test_client_settings_discovery_uses_the_registry_first() -> None:
    source = CLIENT_SETTINGS_PY.read_text(encoding="utf-8")
    assert "_discover_version_directory() or self._discover_versions_directory()" in source


def test_client_settings_reports_both_discovery_attempts() -> None:
    source = CLIENT_SETTINGS_PY.read_text(encoding="utf-8")
    assert "Versions" in source
    assert "unavailable_reason" in source


# ====================================================== 4. Games & servers


def test_search_games_is_exposed_through_the_desktop_bridge() -> None:
    tree = ast.parse(BRIDGE_PY.read_text(encoding="utf-8"))
    methods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "DesktopBridge":
            methods = [
                child.name
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
    assert "search_games" in methods


def test_search_games_is_part_of_the_frontend_contract() -> None:
    source = BRIDGE_JS.read_text(encoding="utf-8")
    assert "'search_games'" in source or '"search_games"' in source


def test_the_games_page_asks_the_backend_for_data() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert "async loadGames" in source, "the page must load saved games"
    assert "async searchGames" in source, "the search box must query Roblox"
    assert "list_games" in source
    assert "search_games" in source


def test_navigating_to_the_games_route_triggers_a_load() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    navigate = source[source.index("navigate(route)") :]
    navigate = navigate[:2500]
    assert "loadGames" in navigate or "searchGames" in navigate


def test_game_search_ignores_stale_answers() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    search = source[source.index("async searchGames") :]
    search = search[:1800]
    assert "gameQuery" in search, "a late answer must be checked against the current query"


def test_service_search_games_validates_its_input() -> None:
    source = SERVICE_PY.read_text(encoding="utf-8")
    search = source[source.index("def search_games") :]
    search = search[:2500]
    assert "120" in search, "the phrase length must be bounded"
    assert "50" in search, "the result count must be bounded"


def test_search_games_falls_back_to_saved_games_when_roblox_fails() -> None:
    source = SERVICE_PY.read_text(encoding="utf-8")
    search = source[source.index("def search_games") :]
    search = search[:2500]
    assert "RobloxServiceError" in search
    assert "local" in search


# --- Per-account watchdog (crash relaunch) --------------------------------
def test_account_payload_exposes_the_saved_watcher_enabled_flag(tmp_path):
    account = Account(username="WatchdogUser")
    account.metadata = {
        "watcher": {
            "enabled": False,
            "auto_relaunch": True,
            "relaunch_delay_seconds": 20.0,
            "relaunch_max_attempts": 3,
            "relaunch_on_crash": True,
            "relaunch_on_exit": False,
        }
    }
    service = ApplicationService(
        paths=AppPaths(
            root=tmp_path,
            database=tmp_path / "astro.db",
            logs=tmp_path / "logs",
            backups=tmp_path / "backups",
            cache=tmp_path / "cache",
            exports=tmp_path / "exports",
        )
    )
    try:
        payload = service._account_payload(account)
        assert payload["watcher"]["enabled"] is False
        assert payload["watcher"]["auto_relaunch"] is True
        assert payload["watcher"]["relaunch_max_attempts"] == 3
    finally:
        service.close()


def test_relaunch_is_armed_only_when_every_explicit_switch_is_on():
    account = Account(username="WatchdogUser")
    rule = {
        "enabled": True,
        "auto_relaunch": True,
        "relaunch_delay_seconds": 15.0,
        "relaunch_max_attempts": 2,
        "relaunch_on_crash": True,
        "relaunch_on_exit": False,
    }
    watcher = {"enabled": True, "auto_relaunch_enabled": True}
    assert ApplicationService._relaunch_arming_state(account, watcher, rule)["armed"] is True

    off_globally = ApplicationService._relaunch_arming_state(
        account, {"enabled": True, "auto_relaunch_enabled": False}, rule
    )
    assert off_globally["armed"] is False
    assert "globally" in off_globally["reason"]

    monitor_off = ApplicationService._relaunch_arming_state(
        account, {"enabled": False, "auto_relaunch_enabled": True}, rule
    )
    assert monitor_off["armed"] is False
    assert "monitor" in monitor_off["reason"]

    unwatched = dict(rule, enabled=False)
    assert ApplicationService._relaunch_arming_state(account, watcher, unwatched)["armed"] is False

    no_relaunch = dict(rule, auto_relaunch=False)
    assert ApplicationService._relaunch_arming_state(account, watcher, no_relaunch)["armed"] is False

    no_trigger = dict(rule, relaunch_on_crash=False, relaunch_on_exit=False)
    state = ApplicationService._relaunch_arming_state(account, watcher, no_trigger)
    assert state["armed"] is False
    assert "trigger" in state["reason"]

    no_attempts = dict(rule, relaunch_max_attempts=0)
    state = ApplicationService._relaunch_arming_state(account, watcher, no_attempts)
    assert state["armed"] is False
    assert "attempts" in state["reason"]


def test_restart_policy_is_derived_from_the_single_arming_decision():
    source = SERVICE_PY.read_text(encoding="utf-8")
    assert 'enabled=self._relaunch_arming_state(account, watcher, rule)["armed"]' in source
    assert '"effective": effective' in source


def test_account_form_exposes_the_per_account_watchdog_controls():
    source = APP_JS.read_text(encoding="utf-8")
    for field in (
        'name="watcher_auto_relaunch"',
        'name="watcher_relaunch_delay_seconds"',
        'name="watcher_relaunch_max_attempts"',
        'name="watcher_relaunch_on_exit"',
    ):
        assert field in source
    assert "const relaunchChecked = Boolean(accountWatcher.auto_relaunch);" in source


def test_account_form_submits_the_complete_watcher_rule():
    source = APP_JS.read_text(encoding="utf-8")
    submit = source[source.index("const watcherForm = new FormData(form);") :]
    submit = submit[: submit.index("await this.resync()")]
    for key in (
        "enabled:",
        "auto_relaunch:",
        "relaunch_delay_seconds:",
        "relaunch_max_attempts:",
        "relaunch_on_crash:",
        "relaunch_on_exit:",
    ):
        assert key in submit
    assert "configure_account_watcher" in submit
    assert "auto_relaunch_enabled: true" in submit
    assert "savedWatcherRule.effective" in submit


# --- FPS cap reaches the folder Roblox really launches --------------------
def test_client_settings_targets_every_installed_player_folder():
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw) / "Versions"
        first = root / "version-aaaa"
        second = root / "version-bbbb"
        for folder in (first, second):
            folder.mkdir(parents=True)
            (folder / "RobloxPlayerBeta.exe").write_text("", encoding="utf-8")
        (root / "version-without-player").mkdir()
        found = ClientSettingsPatcher._scan_all_versions_roots([root])
        assert set(found) == {first, second}
        assert ClientSettingsPatcher._scan_versions_roots([root]) in (first, second)
        assert ClientSettingsPatcher._scan_all_versions_roots([root / "missing"]) == []


def test_fps_ceiling_flag_is_written_only_above_240():
    data = {}
    ClientSettingsPatcher._apply_fps_ceiling(data, 144)
    assert ClientSettingsPatcher.FPS_CEILING_FLAG not in data
    ClientSettingsPatcher._apply_fps_ceiling(data, 360)
    assert data[ClientSettingsPatcher.FPS_CEILING_FLAG] == "False"
    ClientSettingsPatcher._apply_fps_ceiling(data, 240)
    assert ClientSettingsPatcher.FPS_CEILING_FLAG not in data


def test_fps_cap_is_mirrored_to_every_target_and_verifiable():
    with tempfile.TemporaryDirectory() as raw:
        base = pathlib.Path(raw)
        patcher = ClientSettingsPatcher(local_app_data=base)
        patcher.mirror_dirs = [base / "Roblox" / "Versions" / "version-mirror" / "ClientSettings"]
        assert patcher.set_fps_cap(240) is True
        verified = patcher.verify_fps_targets()
        assert len(verified) == 2
        for entry in verified:
            assert entry["exists"] is True
            assert entry["fps"] == 240
        assert len(patcher.last_write_targets) == 2
        assert len(patcher.status()["targets"]) == 2


def test_mirrored_fps_preserves_unrelated_flags_and_remove_clears_ceiling():
    with tempfile.TemporaryDirectory() as raw:
        base = pathlib.Path(raw)
        patcher = ClientSettingsPatcher(local_app_data=base)
        mirror = base / "Roblox" / "Versions" / "version-mirror" / "ClientSettings"
        mirror.mkdir(parents=True)
        mirror_file = mirror / "ClientAppSettings.json"
        mirror_file.write_text(json.dumps({"UnrelatedUserFlag": "keep"}), encoding="utf-8")
        patcher.mirror_dirs = [mirror]

        assert patcher.set_fps_cap(360) is True
        mirrored = json.loads(mirror_file.read_text(encoding="utf-8"))
        assert mirrored["UnrelatedUserFlag"] == "keep"
        assert mirrored["DFIntTaskSchedulerTargetFps"] == 360
        assert mirrored[ClientSettingsPatcher.FPS_CEILING_FLAG] == "False"

        assert patcher.remove_fps_cap() is True
        mirrored = json.loads(mirror_file.read_text(encoding="utf-8"))
        assert mirrored == {"UnrelatedUserFlag": "keep"}


@pytest.mark.skipif(os.name != "nt", reason="dynamic Roblox version rebasing is Windows-only")
def test_client_settings_rebases_when_roblox_installs_a_new_version():
    with tempfile.TemporaryDirectory() as raw:
        base = pathlib.Path(raw)
        old = base / "Versions" / "version-old"
        new = base / "Versions" / "version-new"
        patcher = ClientSettingsPatcher(local_app_data=base)
        patcher._fixed_settings_root = False
        patcher.version_dir = old
        patcher.settings_dir = old / "ClientSettings"
        patcher.settings_file = patcher.settings_dir / "ClientAppSettings.json"
        patcher.backup_file = patcher.settings_dir / "ClientAppSettings.astro-backup.json"

        with (
            mock.patch.object(ClientSettingsPatcher, "_discover_version_directory", return_value=new),
            mock.patch.object(ClientSettingsPatcher, "_scan_all_versions_roots", return_value=[new, old]),
        ):
            patcher._refresh_mirror_dirs()

        assert patcher.version_dir == new
        assert patcher.settings_file == new / "ClientSettings" / "ClientAppSettings.json"
        assert patcher.mirror_dirs == [old / "ClientSettings"]


def test_no_frontend_callback_reads_this_without_binding():
    """An unbound callback threw inside render() and froze the whole page."""

    source = APP_JS.read_text(encoding="utf-8")
    pattern = re.compile(r"\.(find|filter|map|some|every|forEach|sort|reduce|flatMap)\(function\s*\(")
    offenders = []
    for match in pattern.finditer(source):
        body_start = source.find("{", match.end())
        depth = 0
        end = body_start
        while end < len(source):
            if source[end] == "{":
                depth += 1
            elif source[end] == "}":
                depth -= 1
                if depth == 0:
                    break
            end += 1
        body = source[body_start:end]
        tail = source[end : end + 12]
        bound = tail.startswith("}.bind(this)") or tail.startswith("}, this)")
        if "this." in body and not bound:
            offenders.append(source[: match.start()].count(chr(10)) + 1)
    assert offenders == []
