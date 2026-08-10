"""Desktop entry point. Run with ``python main.py``."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from app.backend.api import DesktopBridge, LoopbackApiError, LoopbackApiServer
from app.backend.core.config import APP_NAME, AppPaths
from app.backend.core.logging import configure_logging
from app.backend.services import ApplicationService


def main() -> int:
    """Create a native pywebview desktop window backed by local services."""

    paths = AppPaths.for_current_user()
    paths.ensure_exists()
    # Keep the old variable as a migration fallback for existing diagnostics
    # scripts, while making the public application name and configuration key
    # consistently Astro.
    debug_enabled = (
        os.environ.get("ASTRO_DEBUG") == "1"
        or os.environ.get("ASTERIA_DEBUG") == "1"
    )
    logger = configure_logging(paths.logs, verbose=debug_enabled)
    service = ApplicationService(paths=paths, logger=logger)
    bridge = DesktopBridge(service, logger=logger.logger)
    loopback_api: LoopbackApiServer | None = None
    frontend = Path(__file__).resolve().parent / "app" / "frontend" / "index.html"
    icon = frontend.parent / "assets" / "asteria.ico"
    if not frontend.is_file():
        logger.critical("Frontend asset is missing: %s", frontend)
        service.close()
        return 2

    try:
        import webview

        service.start_watcher()
        api_settings = service.get_settings()["categories"].get("api", {})
        if bool(api_settings.get("enabled")):
            api_token = os.environ.get("ASTRO_LOCAL_API_TOKEN") or os.environ.get(
                "ASTERIA_LOCAL_API_TOKEN"
            )
            if not api_token:
                logger.warning(
                    "Local API is enabled in settings but was not started: "
                    "ASTRO_LOCAL_API_TOKEN is missing."
                )
            else:
                try:
                    loopback_api = LoopbackApiServer(
                        service,
                        token=api_token,
                        port=int(api_settings.get("port", 7963)),
                        logger=logger.logger,
                    )
                    status = loopback_api.start()
                    logger.info("Authenticated local API started at %s", status.base_url)
                except (LoopbackApiError, TypeError, ValueError):
                    # The desktop interface remains usable when an optional
                    # integration port is occupied or has invalid preferences.
                    logger.exception("Configured local API could not be started")
                    loopback_api = None

        def close_application() -> None:
            if loopback_api is not None:
                loopback_api.stop()
            service.close()

        window = webview.create_window(
            APP_NAME,
            url=frontend.as_uri(),
            js_api=bridge,
            width=1500,
            height=960,
            min_size=(1080, 680),
            resizable=True,
            background_color="#0d1020",
        )
        window.events.closed += close_application
        webview.start(
            debug=debug_enabled,
            http_server=True,
            private_mode=True,
            icon=str(icon) if icon.is_file() else None,
        )
        return 0
    except Exception:
        logger.exception("Desktop application failed to start")
        if loopback_api is not None:
            loopback_api.stop()
        service.close()
        return 1


if __name__ == "__main__":
    sys.exit(main())
