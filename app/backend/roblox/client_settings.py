"""Roblox ClientAppSettings.json patcher for FPS caps and custom client flags."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import shutil
import threading
from typing import Any

from app.backend.core.errors import ValidationError

logger = logging.getLogger("astro.client_settings")


class ClientSettingsPatcher:
    """Manages ClientAppSettings.json in Roblox LocalAppData folder."""

    def __init__(self, local_app_data: Path | str | None = None) -> None:
        self.available = True
        self.unavailable_reason: str | None = None
        if local_app_data is not None:
            base = Path(local_app_data)
            self.version_dir: Path | None = None
            self.settings_dir = base / "Roblox" / "ClientSettings"
        else:
            self.version_dir = self._discover_version_directory()
            if self.version_dir is None:
                self.available = False
                self.unavailable_reason = (
                    "The installed Roblox version could not be found through the registered roblox protocol."
                )
                base = Path(os.getenv("LOCALAPPDATA", "."))
                self.settings_dir = base / "Roblox" / "ClientSettings"
            else:
                self.settings_dir = self.version_dir / "ClientSettings"
        self.settings_file = self.settings_dir / "ClientAppSettings.json"
        self.backup_file = self.settings_dir / "ClientAppSettings.astro-backup.json"
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

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "reason": self.unavailable_reason,
            "version_directory": str(self.version_dir) if self.version_dir else None,
            "settings_file": str(self.settings_file),
        }

    def _require_available(self) -> None:
        if not self.available:
            raise ValidationError(self.unavailable_reason or "Roblox ClientSettings are unavailable.")

    def _read_for_update(self) -> dict[str, Any]:
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
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        if self.settings_file.is_file():
            shutil.copy2(self.settings_file, self.backup_file)
        temporary = self.settings_dir / "ClientAppSettings.astro-tmp.json"
        try:
            temporary.write_text(json.dumps(data, indent=4), encoding="utf-8")
            os.replace(temporary, self.settings_file)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def read_settings(self) -> dict[str, Any]:
        """Read all flags from ClientAppSettings.json."""
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
                self._write_atomic(data)
            logger.info(f"Client FPS cap set to {fps_val} in {self.settings_file}")
            return True
        except ValidationError:
            raise
        except Exception as exc:
            logger.error(f"Failed to set client FPS cap: {exc}")
            return False

    def remove_fps_cap(self) -> bool:
        """Remove DFIntTaskSchedulerTargetFps from ClientAppSettings.json."""
        self._require_available()
        if not self.settings_file.is_file():
            return True
        try:
            with self._lock:
                data = self._read_for_update()
                if "DFIntTaskSchedulerTargetFps" in data:
                    del data["DFIntTaskSchedulerTargetFps"]
                    self._write_atomic(data)
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
                elif "DFIntTaskSchedulerTargetFps" in data and fps == 0:
                    del data["DFIntTaskSchedulerTargetFps"]

                if potato_graphics:
                    data.update(self.POTATO_FLAGS)
                else:
                    for k in self.POTATO_FLAGS:
                        data.pop(k, None)

                self._write_atomic(data)

            logger.info(f"ClientSettings patched: fps={fps}, potato={potato_graphics}")
            return True
        except Exception as exc:
            logger.error(f"Failed to patch ClientSettings: {exc}")
            return False
