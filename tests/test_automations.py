"""Tests for historical Roblox automations: FPS patcher & batch launcher."""

import time
from pathlib import Path

import pytest

from app.backend.api.bridge import DesktopBridge
from app.backend.core.config import AppPaths
from app.backend.repositories.sqlite_repository import SQLiteRepository
from app.backend.roblox.batch_launcher import BatchLauncher
from app.backend.roblox.client_settings import ClientSettingsPatcher
from app.backend.services.application_service import ApplicationService


def _paths(tmp_path: Path) -> AppPaths:
    return AppPaths(
        root=tmp_path,
        database=tmp_path / "astro.db",
        logs=tmp_path / "logs",
        backups=tmp_path / "backups",
        cache=tmp_path / "cache",
        exports=tmp_path / "exports",
    )


def test_client_settings_patcher(tmp_path: Path):
    patcher = ClientSettingsPatcher(local_app_data=tmp_path)
    assert patcher.get_fps_cap() is None

    success = patcher.set_fps_cap(144)
    assert success is True
    assert patcher.get_fps_cap() == 144

    removed = patcher.remove_fps_cap()
    assert removed is True
    assert patcher.get_fps_cap() is None


def test_client_settings_updates_are_atomic_and_preserve_existing_flags(tmp_path: Path):
    patcher = ClientSettingsPatcher(local_app_data=tmp_path)
    patcher.settings_dir.mkdir(parents=True)
    patcher.settings_file.write_text('{"ExistingFlag": true}', encoding="utf-8")

    assert patcher.set_fps_cap(120) is True

    assert patcher.read_settings() == {"ExistingFlag": True, "DFIntTaskSchedulerTargetFps": 120}
    assert patcher.backup_file.read_text(encoding="utf-8") == '{"ExistingFlag": true}'


def test_fps_cap_updates_and_restores_roblox_global_frame_cap(tmp_path: Path):
    patcher = ClientSettingsPatcher(local_app_data=tmp_path)
    patcher.global_settings_file.parent.mkdir(parents=True, exist_ok=True)
    original = """<?xml version='1.0' encoding='utf-8'?>
<roblox><Item><Properties><int name="FramerateCap">60</int><bool name="Other">true</bool></Properties></Item></roblox>
"""
    patcher.global_settings_file.write_text(original, encoding="utf-8")

    assert patcher.set_fps_cap(144) is True
    assert '<int name="FramerateCap">144</int>' in patcher.global_settings_file.read_text(encoding="utf-8")
    assert patcher.global_settings_backup_file.read_text(encoding="utf-8") == original

    assert patcher.set_fps_cap(240) is True
    assert '<int name="FramerateCap">240</int>' in patcher.global_settings_file.read_text(encoding="utf-8")
    # The backup remains the user's original value, not the previous Astro cap.
    assert patcher.global_settings_backup_file.read_text(encoding="utf-8") == original

    assert patcher.remove_fps_cap() is True
    assert patcher.global_settings_file.read_text(encoding="utf-8") == original


def test_global_roblox_settings_are_typed_atomic_and_profile_ready(tmp_path: Path):
    patcher = ClientSettingsPatcher(local_app_data=tmp_path)
    patcher.roblox_root.mkdir(parents=True)
    original = """<?xml version="1.0" encoding="utf-8"?>
<roblox><Item><Properties>
<int name="FramerateCap">60</int>
<float name="MasterVolume">1</float>
<int name="GraphicsQualityLevel">5</int>
<token name="SavedQualityLevel">5</token>
<bool name="Fullscreen">true</bool>
<token name="CameraMode">0</token>
<string name="Unrelated">keep</string>
</Properties></Item></roblox>
"""
    patcher.global_settings_file.write_text(original, encoding="utf-8")

    result = patcher.apply_global_settings(
        {
            "MasterVolume": 0.25,
            "GraphicsQualityLevel": 1,
            "SavedQualityLevel": 1,
            "Fullscreen": False,
        }
    )

    assert result["basic"] == {
        "fps": 60,
        "volume_percent": 25,
        "graphics_quality": 1,
        "fullscreen": False,
        "camera_mode": 0,
    }
    assert patcher.global_settings_backup_file.read_text(encoding="utf-8") == original
    assert next(row for row in result["advanced"] if row["name"] == "Unrelated")["value"] == "keep"


def test_global_roblox_settings_reject_unknown_or_out_of_range_values(tmp_path: Path):
    patcher = ClientSettingsPatcher(local_app_data=tmp_path)
    patcher.roblox_root.mkdir(parents=True)
    patcher.global_settings_file.write_text(
        '<roblox><float name="MasterVolume">1</float><bool name="Fullscreen">false</bool></roblox>',
        encoding="utf-8",
    )

    with pytest.raises(Exception, match="does not exist"):
        patcher.apply_global_settings({"InventedSetting": 1})
    with pytest.raises(Exception, match="supported range"):
        patcher.apply_global_settings({"MasterVolume": 2})
    with pytest.raises(Exception, match="true or false"):
        patcher.apply_global_settings({"Fullscreen": "maybe"})


def test_removing_fps_preserves_other_global_settings_changed_after_backup(tmp_path: Path):
    patcher = ClientSettingsPatcher(local_app_data=tmp_path)
    patcher.roblox_root.mkdir(parents=True)
    patcher.global_settings_file.write_text(
        '<roblox><int name="FramerateCap">60</int><float name="MasterVolume">1</float></roblox>',
        encoding="utf-8",
    )
    assert patcher.set_fps_cap(144) is True
    patcher.apply_global_settings({"MasterVolume": 0.2})

    assert patcher.remove_fps_cap() is True

    current = patcher.read_global_settings()
    assert current["basic"]["fps"] == 60
    assert current["basic"]["volume_percent"] == 20


def test_client_settings_invalid_json_is_never_overwritten(tmp_path: Path):
    patcher = ClientSettingsPatcher(local_app_data=tmp_path)
    patcher.settings_dir.mkdir(parents=True)
    patcher.settings_file.write_text("{broken", encoding="utf-8")

    with pytest.raises(Exception, match="left it unchanged"):
        patcher.set_fps_cap(120)

    assert patcher.settings_file.read_text(encoding="utf-8") == "{broken"

def test_batch_launcher_execution():
    launched_ids = []

    def mock_launch(acc_id, target):
        launched_ids.append(acc_id)
        return {"accepted": True}

    launcher = BatchLauncher(launch_single_fn=mock_launch)
    status = launcher.start_batch(["acc1", "acc2"], delay_seconds=0.5)
    assert status["in_progress"] is True
    assert status["total"] == 2

    # Wait for completion
    time.sleep(1.2)
    final_status = launcher.get_status()
    assert final_status["in_progress"] is False
    assert final_status["launched"] == 2
    assert launched_ids == ["acc1", "acc2"]


def test_batch_launcher_rejects_duplicates_and_counts_rejected_launches():
    launcher = BatchLauncher(launch_single_fn=lambda account_id, target: {"accepted": account_id != "rejected"})
    with pytest.raises(Exception, match="duplicate"):
        launcher.start_batch(["same", "same"])

    launcher.start_batch(["accepted", "rejected"], delay_seconds=0.5)
    launcher._thread.join(timeout=2)
    assert launcher.get_status()["launched"] == 1
    assert launcher.get_status()["failed"] == 1


def test_batch_launcher_keeps_each_accounts_destination_isolated():
    launches: list[tuple[str, dict | None]] = []
    launcher = BatchLauncher(launch_single_fn=lambda account_id, target: launches.append((account_id, target)) or {"accepted": True})
    launcher.start_batch(
        ["alt1", "alt2"],
        {"place_id": "1"},
        delay_seconds=0.5,
        per_account_targets={
            "alt1": {"place_id": "1", "job_id": "server-a"},
            "alt2": {"place_id": "2", "job_id": "server-b"},
        },
    )
    launcher._thread.join(timeout=2)
    assert launches == [
        ("alt1", {"place_id": "1", "job_id": "server-a"}),
        ("alt2", {"place_id": "2", "job_id": "server-b"}),
    ]


def test_automations_service_and_bridge_integration(tmp_path: Path):
    paths = _paths(tmp_path)
    repo = SQLiteRepository(paths.database)
    service = ApplicationService(
        paths=paths,
        repository=repo,
        client_settings=ClientSettingsPatcher(local_app_data=tmp_path),
    )
    bridge = DesktopBridge(service)

    # FPS Cap via bridge
    res_set = bridge.set_fps_cap(240)
    assert res_set["success"] is True

    res_get = bridge.get_fps_cap()
    assert res_get["fps"] == 240

    res_rem = bridge.remove_fps_cap()
    assert res_rem["success"] is True

    service.close()


def test_roblox_settings_profiles_are_grouped_persisted_and_confirmed(tmp_path: Path):
    paths = _paths(tmp_path)
    patcher = ClientSettingsPatcher(local_app_data=tmp_path)
    patcher.roblox_root.mkdir(parents=True)
    patcher.global_settings_file.write_text(
        """<roblox><int name="FramerateCap">60</int><float name="MasterVolume">1</float>
<int name="GraphicsQualityLevel">5</int><token name="SavedQualityLevel">5</token>
<bool name="Fullscreen">true</bool><token name="CameraMode">0</token></roblox>""",
        encoding="utf-8",
    )
    service = ApplicationService(paths=paths, client_settings=patcher)
    bridge = DesktopBridge(service)
    try:
        group = bridge.create_group({"name": "Farm"})
        saved = bridge.save_roblox_settings_profile(
            {
                "name": "LOW RESOURCE FARM",
                "group_id": group["id"],
                "values": {
                    "fps": 60,
                    "volume_percent": 0,
                    "graphics_quality": 1,
                    "fullscreen": False,
                    "camera_mode": 0,
                },
            }
        )
        profile = saved["profiles"][0]
        assert profile["group_id"] == group["id"]
        assert profile["values"]["graphics_quality"] == 1

        with pytest.raises(Exception, match="confirmation"):
            bridge.apply_roblox_settings_profile(profile["id"], False)
        applied = bridge.apply_roblox_settings_profile(profile["id"], True)
        assert applied["applied_profile"]["name"] == "LOW RESOURCE FARM"
        assert applied["basic"]["volume_percent"] == 0
        assert applied["basic"]["graphics_quality"] == 1
        assert applied["basic"]["fullscreen"] is False

        # Profiles use the existing settings repository: no schema migration,
        # and the association survives a service-level readback.
        assert bridge.get_roblox_settings_manager()["profiles"][0]["name"] == "LOW RESOURCE FARM"
        assert bridge.delete_roblox_settings_profile(profile["id"])["profiles"] == []
    finally:
        service.close()


def test_roblox_settings_profile_rolls_back_fps_when_xml_change_is_rejected(tmp_path: Path):
    paths = _paths(tmp_path)
    patcher = ClientSettingsPatcher(local_app_data=tmp_path)
    patcher.roblox_root.mkdir(parents=True)
    patcher.global_settings_file.write_text(
        '<roblox><int name="FramerateCap">60</int><float name="MasterVolume">1</float></roblox>',
        encoding="utf-8",
    )
    assert patcher.set_fps_cap(144) is True
    service = ApplicationService(paths=paths, client_settings=patcher)
    try:
        with pytest.raises(Exception, match="does not exist"):
            service.apply_roblox_settings(
                {"fps": 60, "advanced": {"MissingSetting": 1}},
                confirm=True,
            )
        assert patcher.get_fps_cap() == 144
    finally:
        service.close()


def test_default_client_settings_path_uses_validated_roblox_version(monkeypatch, tmp_path: Path):
    version = tmp_path / "Versions" / "version-test"
    version.mkdir(parents=True)
    (version / "RobloxPlayerLauncher.exe").write_bytes(b"")
    monkeypatch.setattr(ClientSettingsPatcher, "_discover_version_directory", staticmethod(lambda: version))

    patcher = ClientSettingsPatcher()

    assert patcher.available is True
    assert patcher.settings_file == version / "ClientSettings" / "ClientAppSettings.json"


def test_default_client_settings_path_refuses_when_roblox_is_not_discovered(monkeypatch):
    # Discovery now has two stages: the registered ``roblox`` protocol first,
    # then the Roblox ``Versions`` directories. Refusing requires *both* to come
    # up empty, so both are neutralised here. On a machine where Roblox really
    # is installed, silencing only the registry probe lets the fallback find the
    # actual client, and the patcher is then correctly available.
    monkeypatch.setattr(ClientSettingsPatcher, "_discover_version_directory", staticmethod(lambda: None))
    monkeypatch.setattr(ClientSettingsPatcher, "_discover_versions_directory", staticmethod(lambda: None))
    monkeypatch.setattr(ClientSettingsPatcher, "_scan_all_versions_roots", staticmethod(lambda _roots: []))
    patcher = ClientSettingsPatcher()

    assert patcher.status()["available"] is False
    with pytest.raises(Exception, match="could not be found"):
        patcher.set_fps_cap(120)
