"""Roblox ClientAppSettings.json patcher for FPS caps and custom client flags."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("astro.client_settings")


class ClientSettingsPatcher:
    """Manages ClientAppSettings.json in Roblox LocalAppData folder."""

    def __init__(self, local_app_data: Path | str | None = None) -> None:
        if local_app_data:
            base = Path(local_app_data)
        else:
            base = Path(os.getenv("LOCALAPPDATA", "~\\AppData\\Local")).expanduser()
        self.settings_dir = base / "Roblox" / "ClientSettings"
        self.settings_file = self.settings_dir / "ClientAppSettings.json"

    def get_fps_cap(self) -> int | None:
        """Read current DFIntTaskSchedulerTargetFps from ClientAppSettings.json."""
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
        try:
            self.settings_dir.mkdir(parents=True, exist_ok=True)
            data: dict[str, Any] = {}
            if self.settings_file.is_file():
                try:
                    data = json.loads(self.settings_file.read_text(encoding="utf-8"))
                except Exception:
                    data = {}

            data["DFIntTaskSchedulerTargetFps"] = int(fps)
            self.settings_file.write_text(json.dumps(data, indent=4), encoding="utf-8")
            logger.info(f"Client FPS cap set to {fps} in {self.settings_file}")
            return True
        except Exception as exc:
            logger.error(f"Failed to set client FPS cap: {exc}")
            return False

    def remove_fps_cap(self) -> bool:
        """Remove DFIntTaskSchedulerTargetFps from ClientAppSettings.json."""
        if not self.settings_file.is_file():
            return True
        try:
            data = json.loads(self.settings_file.read_text(encoding="utf-8"))
            if "DFIntTaskSchedulerTargetFps" in data:
                del data["DFIntTaskSchedulerTargetFps"]
                if data:
                    self.settings_file.write_text(json.dumps(data, indent=4), encoding="utf-8")
                else:
                    self.settings_file.unlink()
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
        try:
            self.settings_dir.mkdir(parents=True, exist_ok=True)
            data: dict[str, Any] = {}
            if self.settings_file.is_file():
                try:
                    data = json.loads(self.settings_file.read_text(encoding="utf-8"))
                except Exception:
                    data = {}

            if fps and fps > 0:
                data["DFIntTaskSchedulerTargetFps"] = int(fps)
            elif "DFIntTaskSchedulerTargetFps" in data and fps == 0:
                del data["DFIntTaskSchedulerTargetFps"]

            if potato_graphics:
                data.update(self.POTATO_FLAGS)
            else:
                for k in self.POTATO_FLAGS:
                    data.pop(k, None)

            if data:
                self.settings_file.write_text(json.dumps(data, indent=4), encoding="utf-8")
            elif self.settings_file.is_file():
                self.settings_file.unlink()

            logger.info(f"ClientSettings patched: fps={fps}, potato={potato_graphics}")
            return True
        except Exception as exc:
            logger.error(f"Failed to patch ClientSettings: {exc}")
            return False
