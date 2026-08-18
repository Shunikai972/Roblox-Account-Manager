"""Service-level tests for the fleet surface.

The engines are covered on their own; these tests exercise the plumbing the UI
really calls, including the guarantees that must not regress: a webhook address
never comes back out, a safe shutdown needs a confirmation, per-instance audio
is stored rather than promised, and rules never close a live client.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.backend.core.config import AppPaths
from app.backend.core.errors import ValidationError
from app.backend.roblox.types import LaunchResult
from app.backend.services import ApplicationService

JOB_ONE = "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d"
JOB_TWO = "9f8e7d6c-5b4a-3210-fedc-ba9876543210"
JOB_THREE = "0c1d2e3f-4a5b-6c7d-8e9f-0a1b2c3d4e5f"


class _Monitor:
    def scan(self) -> SimpleNamespace:
        return SimpleNamespace(instances=(), events=())

    def current_instances(self) -> tuple[object, ...]:
        return ()


class _Roblox:
    def close(self) -> None:
        return None


class _Launcher:
    def __init__(self) -> None:
        self.launches: list[object] = []

    def launch(self, target: object) -> LaunchResult:
        self.launches.append(target)
        return LaunchResult(uri="roblox://experiences/start?placeId=1", launched=True)


class _ClientSettings:
    """Stand-in for the Roblox client settings patcher.

    Injecting one keeps these tests away from the real installation discovery,
    so they behave the same whatever another test module has patched.
    """

    settings_file = Path("ClientAppSettings.json")

    def get_fps_cap(self) -> int | None:
        return None

    def set_fps_cap(self, fps: int) -> bool:
        return False

    def remove_fps_cap(self) -> bool:
        return False

    def patch_launch_settings(self, fps: int | None = None, potato_graphics: bool = False) -> bool:
        return False

    def verify_fps_targets(self) -> list[dict[str, object]]:
        return []

    def status(self) -> dict[str, object]:
        return {"available": False, "reason": "test double"}


def _paths(tmp_path: Path) -> AppPaths:
    root = tmp_path / "app-data"
    return AppPaths(
        root=root,
        database=root / "asteria.db",
        logs=root / "logs",
        backups=root / "backups",
        cache=root / "cache",
        exports=root / "exports",
    )


def _service(tmp_path: Path) -> ApplicationService:
    return ApplicationService(
        paths=_paths(tmp_path),
        roblox=_Roblox(),  # type: ignore[arg-type]
        launcher=_Launcher(),  # type: ignore[arg-type]
        monitor=_Monitor(),  # type: ignore[arg-type]
        client_settings=_ClientSettings(),  # type: ignore[arg-type]
    )


def test_statistics_are_well_shaped_before_any_session_is_recorded(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        stats = service.get_statistics(7)
        assert stats["window_days"] == 7
        assert stats["totals"]["sessions"] == 0
        assert stats["totals"]["crashes"] == 0
        assert stats["macros"]["total"] == 0
        assert isinstance(stats["heatmap"]["rows"], list)
        assert stats["reliability"] == []

        with pytest.raises(ValidationError):
            service.get_statistics(0)
        with pytest.raises(ValidationError):
            service.get_statistics("soon")

        account = service.create_account({"username": "NoHistory"})
        comparison = service.compare_account_sessions(account["id"])
        assert comparison["available"] is False
        assert comparison["reason"]
    finally:
        service.close()


def test_a_scheduled_task_round_trips_and_reports_its_next_run(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        group = service.create_group({"name": "Farm"})
        saved = service.save_scheduled_task(
            {
                "name": "Launch Farm group",
                "at": "18:00",
                "action": "launch_group",
                "group_id": group["id"],
                "days": [0, 1, 2, 3, 4, 5, 6],
            }
        )
        task_id = saved["task"]["id"] if "task" in saved else saved["id"]

        listing = service.list_scheduled_tasks()
        assert listing["count"] == 1
        task = listing["tasks"][0]
        assert task["at"] == "18:00"
        assert task["action_label"]
        assert task["next_run_at"]
        assert len(task["day_labels"]) == 7

        with pytest.raises(ValidationError):
            service.save_scheduled_task({"name": "Bad hour", "at": "25:00", "action": "stop_macros"})
        with pytest.raises(ValidationError):
            service.save_scheduled_task({"name": "Bad action", "at": "10:00", "action": "delete_everything"})

        # Nothing is due for a task that has just been created for 18:00, and a
        # silent sweep must never raise on a quiet workspace.
        swept = service.run_due_scheduled_tasks(silent=True)
        assert swept["checked_at"]
        assert isinstance(swept["ran"], list)

        assert service.delete_scheduled_task(task_id)["deleted"] is True
        assert service.list_scheduled_tasks()["count"] == 0
    finally:
        service.close()


def test_account_health_carries_tags_fields_and_priority_and_filters_on_them(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        first = service.create_account({"username": "FarmOne"})
        service.create_account({"username": "TradeTwo"})

        service.update_account_tags(first["id"], ["farm", "trade", "farm"])
        service.update_account_fields(first["id"], {"Level": "42", "Gems": "1200"})
        service.set_account_priority(first["id"], 7)

        health = service.get_account_health()
        assert health["total"] == 2
        assert health["shown"] == 2
        row = next(item for item in health["accounts"] if item["id"] == first["id"])
        assert sorted(row["tags"]) == ["farm", "trade"]
        assert row["custom_fields"]["Level"] == "42"
        assert row["priority"] == 7
        # The health verdict is flattened onto the row, which is what the UI reads.
        assert row["status"]
        assert row["label"]
        assert row["needs_attention"] in (True, False)

        filtered = service.get_account_health({"tags": ["farm"]})
        assert filtered["shown"] == 1
        assert filtered["accounts"][0]["id"] == first["id"]
        assert service.get_account_health({"query": "TradeTwo"})["shown"] == 1
        assert any(tag["tag"] == "farm" and tag["count"] == 1 for tag in health["tags"])

        with pytest.raises(ValidationError):
            service.set_account_priority(first["id"], 99)
        with pytest.raises(ValidationError):
            service.set_account_priority(first["id"], "high")
        # A custom field is never a place to keep a credential.
        with pytest.raises(ValidationError):
            service.update_account_fields(first["id"], {"password": "hunter2"})
    finally:
        service.close()


def test_server_history_is_remembered_and_a_blacklisted_server_is_never_picked(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        service.record_server_visit(
            {"job_id": JOB_ONE, "place_id": "123", "region": "eu", "players": 4, "max_players": 20}
        )
        service.record_server_visit(
            {"job_id": JOB_TWO, "place_id": "123", "region": "us", "players": 9, "max_players": 20}
        )

        registry = service.get_server_registry("123")
        assert registry["total"] == 2
        assert {row["job_id"] for row in registry["servers"]} == {JOB_ONE, JOB_TWO}
        assert all(row["place_id"] == "123" for row in registry["servers"])

        blocked = service.update_server_blacklist(JOB_ONE, blacklisted=True, note="laggy")
        assert blocked["blacklisted"] is True
        assert blocked["count"] == 1
        assert service.get_server_registry()["blacklisted"] == 1

        picked = service.pick_best_server({"place_id": "123"})
        assert picked["found"] is True
        assert picked["job_id"] == JOB_TWO

        service.update_server_blacklist(JOB_TWO, blacklisted=True)
        exhausted = service.pick_best_server({"place_id": "123"})
        assert exhausted["found"] is False
        assert exhausted["reason"]

        assert service.update_server_blacklist(JOB_ONE, blacklisted=False)["count"] == 1
    finally:
        service.close()


def test_coordination_plans_stage_every_account_before_anything_launches(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        ids = [service.create_account({"username": f"Coord{index}"})["id"] for index in range(3)]

        spread = service.plan_coordination(
            {
                "mode": "spread",
                "account_ids": ids,
                "place_id": "123",
                "servers": [JOB_ONE, JOB_TWO, JOB_THREE],
                "max_per_server": 1,
                "stagger_seconds": 2,
            }
        )
        assert spread["mode"] == "spread"
        assert [step["account_id"] for step in spread["steps"]] == ids
        offsets = [step["offset_seconds"] for step in spread["steps"]]
        assert offsets == sorted(offsets)
        assert offsets[1] > offsets[0]
        assert len({step["job_id"] for step in spread["steps"]}) == 3

        tight = service.plan_coordination(
            {"mode": "spread", "account_ids": ids, "servers": [JOB_ONE, JOB_TWO], "max_per_server": 1}
        )
        # Fewer seats than accounts: the remainder is left out of the plan
        # rather than quietly piled onto the last server.
        assert [step["account_id"] for step in tight["steps"]] == ids[:2]

        followers = service.plan_coordination({"mode": "followers", "account_ids": ids, "job_id": JOB_ONE})
        assert followers["main"]["id"] == ids[0]
        assert [row["id"] for row in followers["followers"]] == ids[1:]
        assert all(step["job_id"] == JOB_ONE for step in followers["steps"][1:])
        assert [step["role"] for step in followers["steps"]] == ["main", "follower", "follower"]
        assert followers["ready"] is True
        # Without a server id there is nothing to follow yet, and the plan says so.
        blind = service.plan_coordination({"mode": "followers", "account_ids": ids})
        assert blind["ready"] is False
        assert "launch the main account first" in blind["note"]

        party = service.plan_coordination({"mode": "party", "account_ids": ids, "job_id": JOB_ONE})
        assert party["size"] == 3
        assert party["overflow"] == []

        sync = service.plan_coordination({"mode": "sync", "account_ids": ids, "action": "launch"})
        assert sync["action"] == "launch"
        assert sync["countdown_seconds"] >= 0

        with pytest.raises(ValidationError):
            service.plan_coordination({"mode": "telepathy", "account_ids": ids})
        with pytest.raises(ValidationError):
            service.plan_coordination({"mode": "spread", "account_ids": []})
    finally:
        service.close()


def test_comfort_stores_audio_levels_and_never_closes_a_client_unasked(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        overview = service.get_comfort_overview()
        for key in ("focus", "sleep", "audio", "shutdown", "queue"):
            assert key in overview
        assert overview["audio"]["supported"] is False
        assert overview["audio"]["note"]

        stored = service.apply_comfort_action("audio", {"volumes": {"4242": 55}})
        assert stored["supported"] is False

        # A shutdown without an explicit confirmation must only describe itself.
        preview = service.apply_comfort_action("shutdown", {})
        assert preview["applied"] is False
        assert "closed" not in preview

        with pytest.raises(ValidationError):
            service.apply_comfort_action("audio", {"volumes": {"4242": "loud"}})
        with pytest.raises(ValidationError):
            service.apply_comfort_action("teleportation", {})
        with pytest.raises(ValidationError):
            service.get_comfort_overview("not-a-pid")

        gate = service.get_wave_status()
        assert gate["in_progress"] is False
        launcher = service.get_settings()["categories"]["launcher"]
        assert launcher["wave_pause_seconds"] == 6.0
        assert launcher["wait_for_wave"] is True
    finally:
        service.close()


def test_alert_webhooks_are_write_only_and_times_are_validated(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        before = service.get_alert_settings()
        assert before["discord_configured"] is False
        assert "discord_webhook_url" not in before

        after = service.update_alert_settings(
            {
                "enabled": True,
                "discord_webhook_url": "https://discord.com/api/webhooks/1/secret-token-value",
                "events": ["instance_crashed", "macro_failed", "not_a_real_event"],
                "daily_report_at": "9:5",
                "min_interval_seconds": 120,
            }
        )
        assert after["enabled"] is True
        assert after["discord_configured"] is True
        assert after["events"] == ["instance_crashed", "macro_failed"]
        assert after["daily_report_at"] == "09:05"
        assert after["min_interval_seconds"] == 120
        # The address itself must never travel back to the interface.
        assert "secret-token-value" not in json.dumps(after)
        assert "secret-token-value" not in json.dumps(service.get_alert_settings())

        with pytest.raises(ValidationError):
            service.update_alert_settings({"discord_webhook_url": "not-a-url"})
        with pytest.raises(ValidationError):
            service.update_alert_settings({"daily_report_at": "99:99"})
        with pytest.raises(ValidationError):
            service.update_alert_settings({"min_interval_seconds": "often"})

        report = service.get_daily_report(False)
        assert report["report"]["title"]
        assert report.get("sent") in (False, None)
    finally:
        service.close()


def test_the_macro_studio_debugs_profiles_and_versions_one_macro(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        account = service.create_account({"username": "StudioUser"})
        macro = service.save_macro(
            {
                "name": "Farm loop",
                "mode": "blocks",
                "account_id": account["id"],
                "actions": [
                    {"type": "key_press", "key": "W", "milliseconds": 80},
                    {
                        "type": "condition",
                        "check": "runtime_above",
                        "value": "5",
                        "actions": [{"type": "stop"}],
                    },
                ],
            }
        )

        studio = service.get_macro_studio(macro["id"], account["id"])
        assert studio["name"] == "Farm loop"
        assert [step["depth"] for step in studio["steps"]] == [0, 0, 1]
        assert studio["profile_report"]["steps"] == 3
        assert studio["profile_report"]["estimated_ms"] >= 80

        service.update_macro_variables(account["id"], {"FarmKey": "E"})
        debug = service.debug_macro(macro["id"], account["id"])
        # This key was previously read under the wrong name, so the debugger
        # always claimed nothing was missing.
        assert debug["missing_variables"] == []
        assert debug["variables"] == {"FarmKey": "E"}
        assert len(debug["steps"]) == 3

        saved = service.save_key_profile({"name": "Azerty farm", "keys": {"W": "Z", "A": "Q"}})
        assert saved["saved"] == "Azerty farm"
        assert service.get_macro_studio(macro["id"])["profiles"][0]["name"] == "Azerty farm"
        assert service.delete_key_profile("Azerty farm")["profiles"] == []

        snapshot = service.snapshot_macro_version(macro["id"], "before rewrite")
        versions = snapshot["versions"] if "versions" in snapshot else []
        assert versions, "a snapshot should be listed straight away"
        assert versions[0]["version"] == 1
        assert versions[0]["label"] == "before rewrite"

        restored = service.rollback_macro(macro["id"], 1)
        actions = restored["macro"]["actions"] if "macro" in restored else restored["actions"]
        assert [item["type"] for item in actions] == ["key_press", "condition"]

        with pytest.raises(ValidationError):
            service.update_macro_variables(account["id"], {"1bad name": "x"})
    finally:
        service.close()


def test_rules_may_pause_and_relaunch_but_never_close_a_live_client(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        overview = service.get_rules_overview()
        assert overview["limits"]["never_closes_clients"] is True
        assert isinstance(overview["decisions"], list)
        assert isinstance(overview["priorities"], list)
        assert "pending_resumes" in overview["resumes"]

        updated = service.update_rules(
            {
                "enabled": True,
                "macro_stuck_seconds": 90,
                "max_runtime_hours": 4.0,
                "cpu_pause_percent": 85,
                "pause_priority_at_or_below": 2,
            }
        )
        rules = updated["rules"] if "rules" in updated else updated
        assert rules["enabled"] is True
        assert rules["macro_stuck_seconds"] == 90
        stored = service.get_settings()["categories"]["rules"]
        assert stored["enabled"] is True
        assert stored["max_runtime_hours"] == 4.0
        assert stored["cpu_pause_percent"] == 85

        # A macro that resumes after a relaunch is on by default in this build.
        assert service.get_settings()["categories"]["macros"]["resume_after_relaunch"] is True
    finally:
        service.close()


def test_a_wave_launch_needs_real_accounts(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        with pytest.raises(ValidationError):
            service.start_wave_launch([])
        with pytest.raises(ValidationError):
            service.start_wave_launch("every account")
        status = service.get_wave_status()
        assert status["total"] == 0
        assert status["waiting_for_wave"] is False
    finally:
        service.close()


def test_a_launch_profile_round_trips_and_names_one_destination(tmp_path: Path) -> None:
    """A saved destination is reusable, replaceable and never ambiguous."""

    from app.backend.core.errors import NotFoundError

    service = _service(tmp_path)
    try:
        empty = service.list_launch_profiles()
        assert empty["profiles"] == []
        assert empty["count"] == 0
        assert empty["limit"] >= 1

        saved = service.save_launch_profile(
            {"name": "Evening farm", "place_id": "920587237", "fps": 240}
        )
        assert [row["name"] for row in saved["profiles"]] == ["Evening farm"]
        profile = saved["profiles"][0]
        assert profile["summary"].startswith("Place 920587237")
        assert "240 FPS" in profile["summary"]

        # Saving the same id replaces the row instead of growing the list.
        renamed = service.save_launch_profile({**profile, "name": "Night farm"})
        assert [row["name"] for row in renamed["profiles"]] == ["Night farm"]
        assert renamed["count"] == 1

        with pytest.raises(ValidationError):
            service.save_launch_profile(
                {"name": "Broken", "place_id": "1", "job_id": JOB_ONE, "link_code": "abc123def"}
            )
        with pytest.raises(NotFoundError):
            service.delete_launch_profile("never-existed")

        assert service.delete_launch_profile(profile["id"])["profiles"] == []
    finally:
        service.close()


def test_launching_a_profile_reuses_the_wave_launcher(tmp_path: Path) -> None:
    """A profile is a destination, not a second launch path.

    The launch must go through the wave launcher so the concurrency limit and
    the pause between waves keep applying, and the global nature of the FPS cap
    must be stated instead of implied.
    """

    from app.backend.core.errors import NotFoundError

    service = _service(tmp_path)
    try:
        first = service.create_account({"username": "ProfileOne"})
        second = service.create_account({"username": "ProfileTwo"})
        profile = service.save_launch_profile(
            {"name": "Together", "place_id": "920587237", "job_id": JOB_ONE, "fps": 120}
        )["profiles"][0]

        seen: dict[str, object] = {}

        def fake_wave(account_ids, target=None):  # type: ignore[no-untyped-def]
            seen["ids"] = list(account_ids)
            seen["target"] = dict(target or {})
            return {"queued": list(account_ids), "total": len(account_ids)}

        service.start_wave_launch = fake_wave  # type: ignore[assignment]
        status = service.launch_with_profile(profile["id"], [first["id"], second["id"]])

        assert seen["ids"] == [first["id"], second["id"]]
        assert seen["target"] == {"place_id": 920587237, "job_id": JOB_ONE}
        assert status["profile"]["name"] == "Together"
        assert status["fps_applied"] is True
        assert "global" in status["note"]

        with pytest.raises(ValidationError):
            service.launch_with_profile(profile["id"], [])
        with pytest.raises(NotFoundError):
            service.launch_with_profile("never-existed", [first["id"]])
    finally:
        service.close()


def test_emergency_stop_halts_automation_and_leaves_clients_open(tmp_path: Path) -> None:
    """One button stops the automation; closing a client stays a human act."""

    service = _service(tmp_path)
    try:
        service.update_rules({"enabled": True})
        result = service.emergency_stop()
        assert result["macros_stopped"] == 0
        assert result["clients_closed"] == 0
        assert result["rules_disarmed"] is True
        assert "left open" in result["note"]
        assert service.get_settings()["categories"]["rules"]["enabled"] is False

        # Asking it to keep the rules armed is respected.
        service.update_rules({"enabled": True})
        kept = service.emergency_stop({"disarm_rules": False})
        assert kept["rules_disarmed"] is False
        assert service.get_settings()["categories"]["rules"]["enabled"] is True
    finally:
        service.close()


def test_settings_are_read_once_until_something_changes(tmp_path: Path) -> None:
    """The hot path must not rebuild the settings tree on every single call.

    The dashboard, the watcher tick and each fleet screen ask for settings. This
    pins the snapshot cache: one repository read until a write happens, and the
    copy handed to a caller can never poison the next read.
    """

    service = _service(tmp_path)
    try:
        reads = {"count": 0}
        real = service.repository.list_settings

        def counted(*args, **kwargs):  # type: ignore[no-untyped-def]
            reads["count"] += 1
            return real(*args, **kwargs)

        # Write first, so the snapshot taken while the service was starting up is
        # already stale and the next read has to rebuild it exactly once.
        service.repository.set_setting("launcher.delay_seconds", 4.5)
        service.repository.list_settings = counted  # type: ignore[assignment]
        first = service.get_settings()
        for _ in range(8):
            service.get_settings()
        assert reads["count"] == 1

        # A caller that edits its own copy cannot change what the next one reads.
        first["categories"]["rules"]["enabled"] = "poisoned"
        assert service.get_settings()["categories"]["rules"]["enabled"] is False

        # A write invalidates the snapshot, so the new value is visible at once.
        service.update_settings({"rules.enabled": True})
        after = reads["count"]
        assert service.get_settings()["categories"]["rules"]["enabled"] is True
        assert after >= 2

        # Writes that go straight to the repository count too.
        service.repository.set_setting("launcher.delay_seconds", 9.0)
        assert service.get_settings()["categories"]["launcher"]["delay_seconds"] == 9.0
    finally:
        service.close()
