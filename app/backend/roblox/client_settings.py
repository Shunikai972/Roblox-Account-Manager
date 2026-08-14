"""Roblox ClientAppSettings.json patcher for FPS caps and custom client flags."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import shutil
import threading
from typing import Any
import xml.etree.ElementTree as ET

from app.backend.core.errors import ValidationError

logger = logging.getLogger("astro.client_settings")


class ClientSettingsPatcher:
    """Manages ClientAppSettings.json in Roblox LocalAppData folder."""

    def __init__(self, local_app_data: Path | str | None = None) -> None:
        self.available = True
        self.unavailable_reason: str | None = None
        self._fixed_settings_root = local_app_data is not None
        if local_app_data is not None:
            base = Path(local_app_data)
            self.roblox_root = base / "Roblox"
            self.version_dir: Path | None = None
            self.settings_dir = self.roblox_root / "ClientSettings"
        else:
            self.version_dir = self._discover_version_directory() or self._discover_versions_directory()
            if self.version_dir is None:
                self.available = False
                self.unavailable_reason = (
                    "The installed Roblox version folder could not be found. Astro looked at the "
                    "registered roblox protocol and at the Roblox Versions directories. Launch "
                    "Roblox once so the client is installed, then retry."
                )
                base = Path(os.getenv("LOCALAPPDATA", "."))
                self.roblox_root = base / "Roblox"
                self.settings_dir = self.roblox_root / "ClientSettings"
            else:
                self.roblox_root = self.version_dir.parent.parent
                self.settings_dir = self.version_dir / "ClientSettings"
        self.settings_file = self.settings_dir / "ClientAppSettings.json"
        self.backup_file = self.settings_dir / "ClientAppSettings.astro-backup.json"
        self.global_settings_file = self.roblox_root / "GlobalBasicSettings_13.xml"
        self.global_settings_backup_file = self.roblox_root / "GlobalBasicSettings_13.astro-backup.xml"
        self.mirror_dirs: list[Path] = self._discover_mirror_dirs()
        self.last_write_targets: list[str] = []
        self._lock = threading.RLock()

    @staticmethod
    def _discover_version_directory() -> Path | None:
        """Resolve the active Roblox ``version-*`` folder like RAM 3.7.2.

        RAM reads ``HKCR\\roblox\\DefaultIcon`` and refuses to patch when the
        resolved parent is not a real version directory containing the player
        launcher.  Keeping that validation prevents Astro from creating a
        misleading global ``ClientSettings`` folder.
        """

        if os.name != "nt":
            return None
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"roblox\DefaultIcon") as key:
                raw_value, _ = winreg.QueryValueEx(key, "")
        except (OSError, ImportError):
            return None
        if not isinstance(raw_value, str) or not raw_value.strip():
            return None
        executable = raw_value.strip().split(",", 1)[0].strip().strip('"')
        candidate = Path(executable).parent
        if not candidate.name.lower().startswith("version-"):
            return None
        if not candidate.is_dir():
            return None
        if not any((candidate / name).is_file() for name in ("RobloxPlayerLauncher.exe", "RobloxPlayerBeta.exe")):
            return None
        return candidate

    @staticmethod
    def _discover_versions_directory() -> Path | None:
        """Fall back to the newest ``Versions/version-*`` player directory.

        The registry probe above fails on installs where the ``roblox``
        protocol points at a bootstrapper outside the version folder, which
        silently disabled every FPS/FastFlag write.  This fallback keeps RAM's
        validation rule -- the directory must really contain a player binary --
        while still finding the active client.
        """

        if os.name != "nt":
            return None
        roots = []
        for variable in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
            raw = os.getenv(variable)
            if raw:
                roots.append(Path(raw) / "Roblox" / "Versions")
        return ClientSettingsPatcher._scan_versions_roots(roots)

    @staticmethod
    def _scan_versions_roots(roots: list[Path]) -> Path | None:
        """Return the newest ``version-*`` folder that holds a player binary."""

        candidates = ClientSettingsPatcher._scan_all_versions_roots(roots)
        return candidates[0] if candidates else None

    @staticmethod
    def _scan_all_versions_roots(roots: list[Path]) -> list[Path]:
        """Return every ``version-*`` folder that holds a player binary.

        Roblox can start a folder other than the one selected when Astro was
        opened, especially immediately after a client update. Keeping the full
        list lets the patcher mirror managed flags into every installed player
        folder instead of silently writing into a stale version.
        """

        candidates = []
        for root in roots:
            try:
                if not root.is_dir():
                    continue
                for child in root.iterdir():
                    if not child.is_dir() or not child.name.lower().startswith("version-"):
                        continue
                    if not any(
                        (child / name).is_file()
                        for name in ("RobloxPlayerBeta.exe", "RobloxPlayerLauncher.exe")
                    ):
                        continue
                    if child not in candidates:
                        candidates.append(child)
            except OSError:
                continue
        if not candidates:
            return []

        def _sort_key(path: Path) -> float:
            try:
                return (path / "RobloxPlayerBeta.exe").stat().st_mtime
            except OSError:
                try:
                    return path.stat().st_mtime
                except OSError:
                    return 0.0

        candidates.sort(key=_sort_key, reverse=True)
        return candidates

    FPS_CEILING_FLAG = "FFlagTaskSchedulerLimitTargetFpsTo2402"

    def _discover_mirror_dirs(self) -> list[Path]:
        """Return other installed player folders that need the managed flags."""

        if os.name != "nt" or self.version_dir is None:
            return []
        roots = []
        for variable in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
            raw = os.getenv(variable)
            if raw:
                roots.append(Path(raw) / "Roblox" / "Versions")
        mirrors = []
        for candidate in self._scan_all_versions_roots(roots):
            directory = candidate / "ClientSettings"
            if directory != self.settings_dir and directory not in mirrors:
                mirrors.append(directory)
        return mirrors

    def _refresh_mirror_dirs(self) -> None:
        """Rebase onto the active version and pick up post-start updates."""

        if self._fixed_settings_root or os.name != "nt":
            return
        registered = self._discover_version_directory()
        roots = []
        for variable in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
            raw = os.getenv(variable)
            if raw:
                roots.append(Path(raw) / "Roblox" / "Versions")
        candidates = self._scan_all_versions_roots(roots)
        if registered is not None:
            candidates = [registered, *(candidate for candidate in candidates if candidate != registered)]
        if not candidates:
            self.available = False
            self.unavailable_reason = (
                "The installed Roblox version folder could not be found. Launch Roblox once, then retry."
            )
            self.mirror_dirs = []
            return

        primary = candidates[0]
        self.available = True
        self.unavailable_reason = None
        self.version_dir = primary
        self.settings_dir = primary / "ClientSettings"
        self.settings_file = self.settings_dir / "ClientAppSettings.json"
        self.backup_file = self.settings_dir / "ClientAppSettings.astro-backup.json"
        self.mirror_dirs = [
            candidate / "ClientSettings"
            for candidate in candidates[1:]
            if candidate / "ClientSettings" != self.settings_dir
        ]

    def target_files(self) -> list[Path]:
        return [self.settings_file] + [directory / "ClientAppSettings.json" for directory in self.mirror_dirs]

    @classmethod
    def _apply_fps_ceiling(cls, data: dict[str, Any], fps: int) -> None:
        """Roblox clamps the scheduler at 240 unless this flag is disabled."""

        if fps > 240:
            data[cls.FPS_CEILING_FLAG] = "False"
        else:
            data.pop(cls.FPS_CEILING_FLAG, None)

    def verify_fps_targets(self) -> list[dict[str, Any]]:
        """Read the cap back from every target instead of assuming the write worked."""

        self._refresh_mirror_dirs()
        results: list[dict[str, Any]] = []
        for raw in self.target_files():
            entry: dict[str, Any] = {
                "file": str(raw),
                "exists": raw.is_file(),
                "fps": None,
                "ceiling_disabled": False,
            }
            if entry["exists"]:
                try:
                    decoded = json.loads(raw.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    decoded = None
                if isinstance(decoded, dict):
                    entry["fps"] = decoded.get("DFIntTaskSchedulerTargetFps")
                    entry["ceiling_disabled"] = decoded.get(self.FPS_CEILING_FLAG) in {False, "False"}
            results.append(entry)
        return results

    def status(self) -> dict[str, Any]:
        self._refresh_mirror_dirs()
        return {
            "available": self.available,
            "reason": self.unavailable_reason,
            "version_directory": str(self.version_dir) if self.version_dir else None,
            "settings_file": str(self.settings_file),
            "targets": [str(path) for path in self.target_files()],
            "last_write_targets": list(self.last_write_targets),
        }

    def _require_available(self) -> None:
        if not self.available:
            raise ValidationError(self.unavailable_reason or "Roblox ClientSettings are unavailable.")

    def _read_for_update(self) -> dict[str, Any]:
        self._refresh_mirror_dirs()
        self._require_available()
        if not self.settings_file.is_file():
            return {}
        try:
            decoded = json.loads(self.settings_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("Existing ClientAppSettings.json is invalid; Astro left it unchanged.") from exc
        if not isinstance(decoded, dict):
            raise ValidationError("Existing ClientAppSettings.json must contain a JSON object.")
        return decoded

    def _write_atomic(self, data: dict[str, Any]) -> None:
        self._require_available()
        self._refresh_mirror_dirs()
        written: list[str] = []
        self._write_one(self.settings_dir, data, backup=True, managed_only=False)
        written.append(str(self.settings_file))
        for directory in self.mirror_dirs:
            try:
                self._write_one(directory, data, backup=True, managed_only=True)
            except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
                logger.warning("Could not mirror ClientAppSettings.json to %s: %s", directory, exc)
                continue
            written.append(str(directory / "ClientAppSettings.json"))
        self.last_write_targets = written

    def _write_global_fps_cap(self, fps: int) -> None:
        """Keep Roblox's supported per-client frame cap aligned with FastFlags.

        Recent Roblox clients apply ``GlobalBasicSettings_13.xml`` after
        ``ClientAppSettings.json``.  Leaving its ``FramerateCap`` at 60 makes
        an otherwise valid 120/144/240 FastFlag silently ineffective.  The
        original XML is backed up once so removing Astro's cap can restore the
        user's previous Roblox value.
        """

        target = self.global_settings_file
        if not target.is_file():
            return
        try:
            tree = ET.parse(target)
            cap = next(
                (
                    element
                    for element in tree.getroot().iter()
                    if element.tag.rsplit("}", 1)[-1] == "int"
                    and element.attrib.get("name") == "FramerateCap"
                ),
                None,
            )
            if cap is None:
                logger.warning("GlobalBasicSettings_13.xml has no FramerateCap entry")
                return
            if not self.global_settings_backup_file.exists():
                shutil.copy2(target, self.global_settings_backup_file)
            cap.text = str(int(fps))
            temporary = target.with_name("GlobalBasicSettings_13.astro-tmp.xml")
            try:
                tree.write(temporary, encoding="utf-8", xml_declaration=True)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        except (OSError, ET.ParseError, ValueError) as exc:
            raise ValidationError(
                "Roblox GlobalBasicSettings_13.xml could not be updated; Astro left the FPS setting unchanged."
            ) from exc

    def _restore_global_fps_cap(self) -> None:
        backup = self.global_settings_backup_file
        if not backup.is_file():
            return
        try:
            shutil.copy2(backup, self.global_settings_file)
        except OSError as exc:
            raise ValidationError("Roblox's original frame-rate setting could not be restored.") from exc

    def _write_one(
        self,
        directory: Path,
        data: dict[str, Any],
        *,
        backup: bool,
        managed_only: bool,
    ) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "ClientAppSettings.json"
        payload = data
        if managed_only and target.is_file():
            existing = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                raise ValidationError("Existing ClientAppSettings.json must contain a JSON object.")
            payload = dict(existing)
            managed_keys = {"DFIntTaskSchedulerTargetFps", self.FPS_CEILING_FLAG, *self.POTATO_FLAGS}
            for key in managed_keys:
                if key in data:
                    payload[key] = data[key]
                else:
                    payload.pop(key, None)
        if backup and target.is_file():
            shutil.copy2(target, directory / "ClientAppSettings.astro-backup.json")
        temporary = directory / "ClientAppSettings.astro-tmp.json"
        try:
            temporary.write_text(json.dumps(payload, indent=4), encoding="utf-8")
            os.replace(temporary, target)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def read_settings(self) -> dict[str, Any]:
        """Read all flags from ClientAppSettings.json."""
        self._refresh_mirror_dirs()
        if not self.available:
            return {}
        if not self.settings_file.is_file():
            return {}
        try:
            return json.loads(self.settings_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def get_fps_cap(self) -> int | None:
        """Read current DFIntTaskSchedulerTargetFps from ClientAppSettings.json."""
        self._refresh_mirror_dirs()
        if not self.available:
            return None
        if not self.settings_file.is_file():
            return None
        try:
            data = json.loads(self.settings_file.read_text(encoding="utf-8"))
            return data.get("DFIntTaskSchedulerTargetFps")
        except Exception as exc:
            logger.warning(f"Could not read ClientAppSettings.json: {exc}")
            return None

    def set_fps_cap(self, fps: int) -> bool:
        """Set DFIntTaskSchedulerTargetFps in ClientAppSettings.json."""
        self._require_available()
        if isinstance(fps, bool) or not isinstance(fps, (int, str)):
            raise ValidationError("FPS cap must be an integer.")
        try:
            fps_val = int(fps)
            if fps_val < 0 or fps_val > 1000:
                raise ValidationError("FPS cap must be between 0 and 1000.")
        except ValueError as exc:
            raise ValidationError("FPS cap must be an integer.") from exc

        try:
            with self._lock:
                data = self._read_for_update()
                data["DFIntTaskSchedulerTargetFps"] = fps_val
                self._apply_fps_ceiling(data, fps_val)
                self._write_atomic(data)
                if fps_val > 0:
                    self._write_global_fps_cap(fps_val)
            logger.info(f"Client FPS cap set to {fps_val} in {self.settings_file}")
            return True
        except ValidationError:
            raise
        except Exception as exc:
            logger.error(f"Failed to set client FPS cap: {exc}")
            return False

    def remove_fps_cap(self) -> bool:
        """Remove DFIntTaskSchedulerTargetFps from ClientAppSettings.json."""
        self._refresh_mirror_dirs()
        self._require_available()
        if not any(path.is_file() for path in self.target_files()) and not self.global_settings_backup_file.is_file():
            return True
        try:
            with self._lock:
                data = self._read_for_update()
                if "DFIntTaskSchedulerTargetFps" in data or self.FPS_CEILING_FLAG in data:
                    data.pop("DFIntTaskSchedulerTargetFps", None)
                    data.pop(self.FPS_CEILING_FLAG, None)
                    self._write_atomic(data)
                self._restore_global_fps_cap()
            logger.info("Client FPS cap removed.")
            return True
        except Exception as exc:
            logger.error(f"Failed to remove FPS cap: {exc}")
            return False

    POTATO_FLAGS: dict[str, Any] = {
        # Forced minimum graphics level & texture resolution
        "DFIntDebugForceQualityLevel": 1,
        "DFPIntTextureQualityOverride": 1,
        "FIntDebugTextureManagerSkipMips": 16,
        "DFFlagTextureQualityOverrideEnabled": "True",
        # Shadows, lighting & reflections
        "FFlagDebugDisableShadowMap": "True",
        "FIntRenderShadowIntensity": 0,
        "FFlagDisablePostFx": "True",
        "FFlagDisableFXAA": "True",
        # Environmental assets: grass, materials, water & terrain
        "FIntRenderGrassHeightScaler": 0,
        "FFlagDebugDisableMaterials": "True",
        "DFIntMaterialQualityLevel": 1,
        "FIntRenderTerrainMipLevel": 4,
        "FFlagDisableTerrainWater": "True",
        "FFlagDebugSkyGray": "True",
        # Particle effects & extra GPU load
        "FFlagDebugDisableParticleEffects": "True",
    }

    def patch_launch_settings(self, fps: int | None = None, potato_graphics: bool = False) -> bool:
        """Applies FPS cap and potato graphics FastFlags to ClientAppSettings.json prior to launch."""
        self._require_available()
        try:
            with self._lock:
                data = self._read_for_update()

                if fps and fps > 0:
                    data["DFIntTaskSchedulerTargetFps"] = int(fps)
                    self._apply_fps_ceiling(data, int(fps))
                elif fps == 0:
                    data.pop("DFIntTaskSchedulerTargetFps", None)
                    data.pop(self.FPS_CEILING_FLAG, None)

                if potato_graphics:
                    data.update(self.POTATO_FLAGS)
                else:
                    for k in self.POTATO_FLAGS:
                        data.pop(k, None)

                self._write_atomic(data)
                if fps and fps > 0:
                    self._write_global_fps_cap(int(fps))
                elif fps == 0:
                    self._restore_global_fps_cap()

            logger.info(f"ClientSettings patched: fps={fps}, potato={potato_graphics}")
            return True
        except Exception as exc:
            logger.error(f"Failed to patch ClientSettings: {exc}")
            return False
