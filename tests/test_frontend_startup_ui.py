from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


APP_SOURCE = Path(__file__).resolve().parents[1] / "app" / "frontend" / "src" / "app.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend UI checks.")
def test_windows_startup_ui_requires_a_distinct_confirmation_and_bridge_call() -> None:
    """Windows startup must not be folded into generic settings updates."""

    script = rf"""
import {{ readFile }} from 'node:fs/promises';

const root = {{ innerHTML: '' }};
const elements = {{ '#app': root, '#overlay-root': {{ innerHTML: '' }}, '#toast-root': {{ innerHTML: '' }} }};
globalThis.document = {{
  querySelector: (selector) => elements[selector] || null,
  querySelectorAll: () => [],
  documentElement: {{ dataset: {{}}, style: {{ setProperty: () => {{}}, removeProperty: () => {{}} }} }}
}};
globalThis.window = {{
  setTimeout: (callback) => {{ callback(); return 0; }}, clearTimeout: () => {{}},
  setInterval: () => 1, clearInterval: () => {{}}
}};

let source = await readFile({json.dumps(str(APP_SOURCE))}, 'utf8');
source = source.replace("import {{ Bridge }} from './bridge.js';", 'const Bridge = {{}};');
source = source.replace(/const app = new OrbitApp\(\);\s*app\.init\(\);\s*$/, 'export {{ OrbitApp }};');
const moduleUrl = 'data:text/javascript;charset=utf-8,' + encodeURIComponent(source);
const {{ OrbitApp }} = await import(moduleUrl);

const settings = {{ theme: 'dark', accent: 'violet', density: 'comfortable', reduce_motion: false, categories: {{}} }};
const startup = {{ available: true, supported: true, accessible: true, registered: false, enabled: false, needs_repair: false, configured: false, reason: null }};
const calls = [];
const bridge = {{
  call: async (method, ...args) => {{
    calls.push([method, ...args]);
    if (method === 'set_windows_startup') {{
      if (args.length !== 2 || args[0] !== true || args[1] !== true) throw new Error('Startup call did not include explicit confirmation.');
      return {{ ...startup, registered: true, enabled: true, configured: true }};
    }}
    if (method === 'bootstrap') return {{ accounts: [], groups: [], games: [], instances: [], activity: [], notifications: [], settings, diagnostics: {{ services: [], logs: [], status: 'healthy' }} }};
    throw new Error('Unexpected bridge method: ' + method);
  }}
}};

const app = new OrbitApp();
app.bridge = bridge;
app.state.mode = 'desktop';
app.state.settings = settings;
app.applyWindowsStartupStatus(startup);
app.render = () => {{}};
app.renderOverlays = () => {{}};
app.toast = () => {{}};
app.applyTheme = () => {{}};

const settingsHtml = app.renderSettingsPanel();
if (!settingsHtml.includes('data-action="open-windows-startup"')) throw new Error('General settings did not show the real Windows startup action.');
app.openWindowsStartupModal(true);
if (!app.state.modal || app.state.modal.kind !== 'windows-startup') throw new Error('Windows startup did not open its own confirmation modal.');
const modalHtml = app.renderModal();
if (!modalHtml.includes('data-form="windows-startup"') || !modalHtml.includes('name="confirm"')) throw new Error('Windows startup modal has no distinct confirmation form.');

await app.setWindowsStartup(true);
if (!calls.some((call) => call[0] === 'set_windows_startup' && call[1] === true && call[2] === true)) throw new Error('The confirmed startup update did not reach the bridge.');
if (calls.some((call) => call[0] === 'update_settings')) throw new Error('Windows startup was incorrectly routed through update_settings.');
if (!app.state.windowsStartup.enabled) throw new Error('The returned Windows startup state was not applied.');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr

