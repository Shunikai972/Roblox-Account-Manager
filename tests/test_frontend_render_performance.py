"""Guards for the render loop, the icon cache and the single dashboard poll.

The background poll runs every three seconds.  Before these guards it rebuilt
the whole document on every tick, which reset scrolling and focus, and it asked
the backend three separate questions to fill one screen.  Each assertion below
pins one of those costs down so a later refactor cannot silently bring it back.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "frontend" / "src" / "app.js"
SERVICE_PY = ROOT / "app" / "backend" / "services" / "application_service.py"


def test_render_updates_stable_shell_sections_independently() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert "lastSidebarHtml: null" in source
    assert "lastTopbarHtml: null" in source
    assert "lastPageHtml: null" in source
    assert "if (sidebarHtml !== this.state.lastSidebarHtml) this.swapHtml(sidebar, sidebarHtml);" in source
    assert "if (topbarHtml !== this.state.lastTopbarHtml) this.swapHtml(topbar, topbarHtml);" in source
    assert "if (pageHtml !== this.state.lastPageHtml) this.swapHtml(page, pageHtml);" in source
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
    assert "this.state.lastSidebarHtml = null;" in source
    assert "this.state.lastTopbarHtml = null;" in source
    assert "this.state.lastPageHtml = null;" in source


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend UI checks.")
def test_runtime_repaint_only_rewrites_the_section_that_changed() -> None:
    script = rf"""
import {{ readFile }} from 'node:fs/promises';

function node() {{
  return {{
    writes: 0, value: '', contains: () => false, querySelector: () => null,
    set innerHTML(value) {{ this.value = value; this.writes += 1; }},
    get innerHTML() {{ return this.value; }}
  }};
}}
const sidebar = node();
const topbar = node();
const page = node();
const root = node();
root.querySelector = (selector) => selector === '.sidebar' ? sidebar : selector === '.topbar' ? topbar : selector === '#app-main' ? page : null;
const elements = {{ '#app': root, '#overlay-root': node(), '#toast-root': node() }};
globalThis.document = {{
  activeElement: null,
  querySelector: (selector) => elements[selector] || null,
  querySelectorAll: () => [],
  documentElement: {{ dataset: {{}}, style: {{ setProperty: () => {{}}, removeProperty: () => {{}} }} }}
}};
globalThis.window = {{ setTimeout: () => 0, clearTimeout: () => {{}}, setInterval: () => 1, clearInterval: () => {{}} }};

let source = await readFile({json.dumps(str(APP_JS))}, 'utf8');
source = source.replace("import {{ Bridge }} from './bridge.js';", 'const Bridge = {{}};');
source = source.replace(/const app = new OrbitApp\(\);\s*app\.init\(\);\s*$/, 'export {{ OrbitApp }};');
const {{ OrbitApp }} = await import('data:text/javascript;charset=utf-8,' + encodeURIComponent(source));
const app = new OrbitApp();
app.renderOverlays = () => {{}};
app.pageMeta = () => ['Dashboard', 'Stable'];
app.renderPage = () => '<p>first</p>';
app.nexusEnabled = () => false;

app.render();
sidebar.writes = 0; topbar.writes = 0; page.writes = 0; root.writes = 0;
app.renderPage = () => '<p>second</p>';
app.render();

if (sidebar.writes !== 0 || topbar.writes !== 0 || root.writes !== 0 || page.writes !== 1) {{
  throw new Error('Section cache failed: ' + JSON.stringify({{ sidebar: sidebar.writes, topbar: topbar.writes, page: page.writes, root: root.writes }}));
}}
"""
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


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


def test_macro_runtime_and_comfort_panels_fetch_independent_data_in_parallel() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert "Promise.all([this.bridge.call('get_instance_monitor'), this.bridge.call('list_macro_runs')])" in source
    assert "Promise.all([this.bridge.call('get_comfort_overview', null), this.bridge.call('get_wave_status')])" in source


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


def test_streamer_toggle_rolls_back_when_persistence_fails() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert "const previous = this.state.hideUsernames;" in source
    assert "const saved = await this.updateSettings({ privacy_mode: requested }, false);" in source
    assert "if (!saved)" in source
    assert "this.state.hideUsernames = previous;" in source
    assert "return true;" in source
    assert "return false;" in source
