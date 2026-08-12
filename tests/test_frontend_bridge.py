from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest


BRIDGE_SOURCE = Path(__file__).resolve().parents[1] / "app" / "frontend" / "src" / "bridge.js"
BACKEND_BRIDGE_SOURCE = Path(__file__).resolve().parents[1] / "app" / "backend" / "api" / "bridge.py"
FRONTEND_APP_SOURCE = Path(__file__).resolve().parents[1] / "app" / "frontend" / "src" / "app.js"


def test_frontend_contract_covers_desktop_bridge_methods() -> None:
    """A public desktop bridge method cannot become unreachable from the UI."""

    module = ast.parse(BACKEND_BRIDGE_SOURCE.read_text(encoding="utf-8"))
    desktop_bridge = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "DesktopBridge")
    backend_methods = {
        node.name
        for node in desktop_bridge.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
    }
    source = BRIDGE_SOURCE.read_text(encoding="utf-8")
    contract = re.search(r"const CONTRACT_METHODS = \[(.*?)\];", source, re.DOTALL)
    assert contract is not None
    frontend_methods = set(re.findall(r"'([^']+)'", contract.group(1)))

    assert backend_methods <= frontend_methods


def test_region_and_legacy_api_settings_are_reachable_from_the_frontend() -> None:
    source = FRONTEND_APP_SOURCE.read_text(encoding="utf-8")
    bridge = BRIDGE_SOURCE.read_text(encoding="utf-8")
    for marker in (
        "data-form=\"region-settings\"",
        "region_lookup_enabled",
        "region_lookup_provider",
        "region_lookup_timeout_seconds",
        "allow_get_accounts",
        "legacy_password_auth_enabled",
    ):
        assert marker in source
    assert "'resolve_server_region'" in bridge


def test_instance_refresh_resynchronizes_runtime_account_statuses() -> None:
    """The dashboard must not keep an exited account marked as in-game."""

    source = FRONTEND_APP_SOURCE.read_text(encoding="utf-8")
    method = re.search(
        r"async refreshInstances\(\) \{(?P<body>.*?)\n  \}\n",
        source,
        re.DOTALL,
    )
    assert method is not None
    body = method.group("body")
    assert "this.bridge.call('refresh_instances')" in body
    assert "this.bridge.call('get_instance_monitor')" in body
    assert "this.bridge.call('list_accounts')" not in body
    assert "this.applyInstanceMonitor(monitor)" in body


def test_account_launch_prefers_its_default_and_reports_rejected_handoffs() -> None:
    source = FRONTEND_APP_SOURCE.read_text(encoding="utf-8")
    method = re.search(r"async launch\(id, target\) \{(?P<body>.*?)\n  \}\n", source, re.DOTALL)
    assert method is not None
    body = method.group("body")
    assert body.index("account.saved_place_id") < body.index("this.state.gameId")
    assert "result.accepted === false" in body
    assert "await this.refreshLaunchState()" in body
    assert "await this.resync()" not in body


def test_bulk_launch_uses_each_selected_accounts_saved_place() -> None:
    source = FRONTEND_APP_SOURCE.read_text(encoding="utf-8")
    method = re.search(r"async bulkLaunch\(\) \{(?P<body>.*?)\n  \}\n", source, re.DOTALL)
    assert method is not None
    body = method.group("body")
    assert "account.saved_place_id" in body
    assert "start_batch_launch', ids, null" in body
    assert "Choose an experience first" not in body


def test_runtime_poll_is_compact_and_never_replaces_an_open_form() -> None:
    source = FRONTEND_APP_SOURCE.read_text(encoding="utf-8")
    method = re.search(r"async refreshRuntimeSilently\(\) \{(?P<body>.*?)\n  \}\n", source, re.DOTALL)
    assert method is not None
    body = method.group("body")
    assert "this.state.modal" in body
    assert "this.bridge.call('get_instance_monitor')" in body
    assert "this.bridge.call('bootstrap')" not in body


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend bridge checks.")
def test_desktop_bridge_waits_for_late_pywebview_api_instead_of_preview() -> None:
    """A delayed native bridge must not silently turn the desktop app into preview.

    pywebview injects its API asynchronously.  This test reproduces an API that
    becomes available only after ``Bridge.connect`` has started and proves that
    the returned adapter uses the native bridge.
    """

    script = f"""
import {{ readFile }} from 'node:fs/promises';

globalThis.localStorage = {{ getItem: () => null, setItem: () => {{}} }};
globalThis.window = new EventTarget();
window.setTimeout = setTimeout;
window.clearTimeout = clearTimeout;
window.setInterval = setInterval;
window.clearInterval = clearInterval;

const source = await readFile({json.dumps(str(BRIDGE_SOURCE))}, 'utf8');
const moduleUrl = 'data:text/javascript;charset=utf-8,' + encodeURIComponent(source);
const {{ Bridge }} = await import(moduleUrl);
const pending = Bridge.connect();

setTimeout(() => {{
  window.pywebview = {{ api: {{ bootstrap: async () => ({{ source: 'native' }}) }} }};
  window.dispatchEvent(new Event('pywebviewready'));
}}, 20);

const bridge = await pending;
if (bridge.mode !== 'desktop') throw new Error('Preview bridge selected after native event.');
const payload = await bridge.call('bootstrap');
if (!payload || payload.source !== 'native') throw new Error('Native bootstrap was not called.');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend bridge checks.")
def test_preview_bridge_never_simulates_an_oauth_login() -> None:
    """OAuth methods must stay visible in the contract but fail honestly in preview.

    A browser-only preview is useful for layout work; treating it as a real
    Roblox sign-in would make the account UI lie about persisted OAuth state.
    """

    script = f"""
import {{ readFile }} from 'node:fs/promises';

globalThis.localStorage = {{ getItem: () => null, setItem: () => {{}} }};
globalThis.window = new EventTarget();
window.setInterval = () => 0;
window.clearInterval = () => {{}};
window.setTimeout = (callback) => {{ callback(); return 0; }};
window.clearTimeout = () => {{}};

const source = await readFile({json.dumps(str(BRIDGE_SOURCE))}, 'utf8');
const moduleUrl = 'data:text/javascript;charset=utf-8,' + encodeURIComponent(source);
const {{ Bridge, CONTRACT_METHODS }} = await import(moduleUrl);
const names = ['start_oauth_login', 'poll_oauth_login', 'cancel_oauth_login', 'refresh_oauth_account', 'disconnect_oauth_account'];
for (const name of names) {{
  if (!CONTRACT_METHODS.includes(name)) throw new Error('Missing OAuth contract method: ' + name);
}}

const bridge = await Bridge.connect();
if (bridge.mode !== 'preview') throw new Error('Expected an explicit browser preview bridge.');
for (const name of names) {{
  let rejected = false;
  try {{ await bridge.call(name, 'opaque-id'); }} catch (error) {{
    rejected = /Preview mode never simulates sign-in/.test(String(error.message || error));
  }}
  if (!rejected) throw new Error('Preview OAuth method did not reject honestly: ' + name);
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


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend bridge checks.")
def test_preview_bridge_never_invents_desktop_success_or_secrets() -> None:
    script = f"""
import {{ readFile }} from 'node:fs/promises';
globalThis.localStorage = {{ getItem: () => null, setItem: () => {{}} }};
globalThis.window = new EventTarget();
window.setInterval = () => 0; window.clearInterval = () => {{}};
window.setTimeout = (callback) => {{ callback(); return 0; }}; window.clearTimeout = () => {{}};
const source = await readFile({json.dumps(str(BRIDGE_SOURCE))}, 'utf8');
const {{ Bridge }} = await import('data:text/javascript;charset=utf-8,' + encodeURIComponent(source));
const bridge = await Bridge.connect();
for (const [name, args] of [
  ['generate_auth_ticket', ['acct']], ['get_account_cookie', ['acct']],
  ['start_manual_browser_login', []], ['start_batch_launch', [[], {{}}, 1]],
  ['send_nexus_command', ['all', 'ping', null]], ['set_multi_instance', [true]],
  ['change_account_password', ['acct', 'old', 'new']]
]) {{
  let rejected = false;
  try {{ await bridge.call(name, ...args); }} catch (error) {{ rejected = /never simulates/.test(String(error.message || error)); }}
  if (!rejected) throw new Error('Preview operation did not reject honestly: ' + name);
}}
const nexus = await bridge.call('get_nexus_status');
if (nexus.running || nexus.accounts.length || nexus.available !== false) throw new Error('Preview invented Nexus state');
const multi = await bridge.call('get_multi_instance_status');
if (multi.supported || multi.enabled) throw new Error('Preview invented multi-instance support');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend bridge checks.")
def test_preview_bridge_keeps_optional_public_user_id_as_local_metadata() -> None:
    """Preview can retain a public ID without pretending to query Roblox."""

    script = f"""
import {{ readFile }} from 'node:fs/promises';

globalThis.localStorage = {{ getItem: () => null, setItem: () => {{}} }};
globalThis.window = new EventTarget();
window.setInterval = () => 0;
window.clearInterval = () => {{}};
window.setTimeout = (callback) => {{ callback(); return 0; }};
window.clearTimeout = () => {{}};

const source = await readFile({json.dumps(str(BRIDGE_SOURCE))}, 'utf8');
const moduleUrl = 'data:text/javascript;charset=utf-8,' + encodeURIComponent(source);
const {{ Bridge }} = await import(moduleUrl);
const bridge = await Bridge.connect();
const created = await bridge.call('create_account', {{ username: 'PublicIdPreview', user_id: '123456789' }});
if (String(created.user_id) !== '123456789') throw new Error('Preview dropped the local public User ID.');
const cleared = await bridge.call('update_account', created.id, {{ user_id: '' }});
if (cleared.user_id !== null) throw new Error('Preview did not clear the optional public User ID.');
const originalOrder = (await bridge.call('list_accounts')).map((account) => account.id);
const reversedOrder = originalOrder.slice().reverse();
const reordered = await bridge.call('reorder_accounts', reversedOrder);
if (reordered.map((account) => account.id).join(',') !== reversedOrder.join(',')) throw new Error('Preview did not persist the complete local account order.');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend bridge checks.")
def test_preview_bridge_does_not_invent_public_uwp_or_windows_startup_data() -> None:
    """Remote, installed-package, and Windows Run state stay desktop-only."""

    script = f"""
import {{ readFile }} from 'node:fs/promises';

globalThis.localStorage = {{ getItem: () => null, setItem: () => {{}} }};
globalThis.window = new EventTarget();
window.setInterval = () => 0;
window.clearInterval = () => {{}};
window.setTimeout = (callback) => {{ callback(); return 0; }};
window.clearTimeout = () => {{}};

const source = await readFile({json.dumps(str(BRIDGE_SOURCE))}, 'utf8');
const moduleUrl = 'data:text/javascript;charset=utf-8,' + encodeURIComponent(source);
const {{ Bridge, CONTRACT_METHODS }} = await import(moduleUrl);
const methods = [
  ['get_public_profile', [123]],
  ['refresh_account_public_profile', ['acct_123']],
  ['get_public_presence', [[123]]],
  ['refresh_account_presence', [['acct_123']]],
  ['list_uwp_packages', []],
  ['launch_uwp_package', ['RobloxCorporation.Roblox_1.0_x64__abc']],
  ['get_windows_startup_status', []],
  ['set_windows_startup', [true, true]]
];
const bridge = await Bridge.connect();
for (const [name, args] of methods) {{
  if (!CONTRACT_METHODS.includes(name)) throw new Error('Missing bridge method: ' + name);
  let rejected = false;
  try {{ await bridge.call(name, ...args); }} catch (error) {{
    rejected = /Preview mode never (simulates remote Roblox data|invents installed Windows packages|simulates a Windows Run registration)/.test(String(error.message || error));
  }}
  if (!rejected) throw new Error('Preview invented unavailable data for: ' + name);
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
