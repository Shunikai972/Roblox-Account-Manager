"""Guards for the render loop, the icon cache and the single dashboard poll.

The background poll runs every three seconds.  Before these guards it rebuilt
the whole document on every tick, which reset scrolling and focus, and it asked
the backend three separate questions to fill one screen.  Each assertion below
pins one of those costs down so a later refactor cannot silently bring it back.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "frontend" / "src" / "app.js"
SERVICE_PY = ROOT / "app" / "backend" / "services" / "application_service.py"


def test_render_skips_the_dom_rebuild_when_the_markup_is_identical() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert "const html = '<aside class=\"sidebar\" aria-label=\"Main navigation\">'" in source
    assert "if (html !== this.state.lastRenderHtml) {" in source
    assert "this.state.lastRenderHtml = html;" in source


def test_the_loading_screen_invalidates_the_markup_cache() -> None:
    """The loading screen writes the document outside render().

    Without dropping the cache the next render would compare against markup
    that is no longer on screen and skip the rebuild, leaving the app stuck on
    the loading card.
    """

    source = APP_JS.read_text(encoding="utf-8")
    assert "loading-page" in source
    assert "this.state.lastRenderHtml = null;" in source


def test_overlays_are_only_rewritten_when_they_change() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert "if (output === this.state.lastOverlayHtml) return;" in source
    assert "this.state.lastOverlayHtml = output;" in source


def test_icons_are_built_once_and_memoized() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert "const ICON_CACHE = new Map();" in source
    assert "const cached = ICON_CACHE.get(cacheKey);" in source
    assert "ICON_CACHE.set(cacheKey, markup);" in source


def test_dashboard_polls_one_joined_snapshot() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert "applyDashboard(payload) {" in source
    assert "this.bridge.call('get_dashboard')" in source
    # The joined snapshot must feed the fleet card as well, otherwise those
    # numbers would still need a poll of their own.
    assert "this.state.fleet.resources = data.resources;" in source


def test_resource_plan_reuses_a_snapshot_the_caller_already_has() -> None:
    source = SERVICE_PY.read_text(encoding="utf-8")
    assert "windows: list[Any] | None = None," in source
    assert "runs: list[Any] | None = None," in source
    assert (
        "watched_pid=self._clean_pid(watched_pid), windows=windows, runs=runs"
        in source
    )


def test_dashboard_lists_groups_once() -> None:
    source = SERVICE_PY.read_text(encoding="utf-8")
    assert "groups = self.list_groups()" in source
    assert '"groups": len(groups),' in source
    assert '"groups": len(self.repository.list_groups()),' not in source
