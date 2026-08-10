from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


APP_SOURCE = Path(__file__).resolve().parents[1] / "app" / "frontend" / "src" / "app.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend UI checks.")
def test_account_oauth_ui_polls_completion_and_cancels_the_real_operation() -> None:
    """Exercise the UI state machine without a browser or a real OAuth provider.

    The bridge stub only returns public operation/account data. This protects
    the important wiring: start -> poll -> bootstrap refresh, and an explicit
    cancellation must reach the bridge rather than merely hiding the modal.
    """

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

const calls = [];
let pollStatus = 'waiting';
const linked = {{ id: 'acct_oauth', username: 'VerifiedRoblox', display_name: 'Verified Roblox', oauth_connected: true, status: 'ready' }};
const settings = {{
  theme: 'dark', accent: 'violet', density: 'comfortable', reduce_motion: false,
  categories: {{ oauth: {{ enabled: true, client_id: '123456', redirect_uri: 'http://127.0.0.1:8989/oauth/callback', callback_timeout_seconds: 300 }} }}
}};
const bridge = {{
  call: async (method, ...args) => {{
    calls.push([method, ...args]);
    if (method === 'start_oauth_login') return {{ operation_id: 'operation-123', status: 'waiting', expires_at: '2026-08-10T12:05:00+00:00' }};
    if (method === 'poll_oauth_login') return pollStatus === 'completed'
      ? {{ operation_id: args[0], status: 'completed', account: linked }}
      : {{ operation_id: args[0], status: 'waiting' }};
    if (method === 'cancel_oauth_login') return {{ operation_id: args[0], status: 'cancelled' }};
    if (method === 'bootstrap') return {{ accounts: [linked], groups: [], games: [], instances: [], activity: [], notifications: [], settings: settings, diagnostics: {{ services: [], logs: [], status: 'healthy' }} }};
    throw new Error('Unexpected bridge method: ' + method);
  }}
}};

const app = new OrbitApp();
app.bridge = bridge;
app.state.mode = 'desktop';
app.state.settings = settings;
const notices = [];
app.render = () => {{}};
app.renderOverlays = () => {{}};
app.toast = (...notice) => notices.push(notice);

await app.startOAuthLogin();
await new Promise((resolve) => setImmediate(resolve));
if (!calls.some((call) => call[0] === 'start_oauth_login')) throw new Error('OAuth start was not called.');
if (!calls.some((call) => call[0] === 'poll_oauth_login' && call[1] === 'operation-123')) throw new Error('OAuth operation was not polled.');
await app.cancelOAuthLogin();
if (!calls.some((call) => call[0] === 'cancel_oauth_login' && call[1] === 'operation-123')) throw new Error('Closing OAuth did not cancel the real operation.');
if (app.state.modal !== null) throw new Error('Cancelled OAuth modal remained open.');

pollStatus = 'completed';
await app.startOAuthLogin();
await new Promise((resolve) => setImmediate(resolve));
if (!calls.some((call) => call[0] === 'bootstrap')) throw new Error('Completed OAuth did not resync the workspace.');
if (!app.state.accounts.some((account) => account.oauth_connected && account.username === 'VerifiedRoblox')) throw new Error('Linked public account was not applied after completion.');
if (!notices.some((notice) => notice[0] === 'success' && notice[1] === 'Roblox account connected')) throw new Error('Successful OAuth completion was not announced.');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend UI checks.")
def test_failed_oauth_cancellation_keeps_polling_the_live_operation() -> None:
    """A failed cancel request must not leave an apparently waiting flow idle."""

    script = rf"""
import {{ readFile }} from 'node:fs/promises';

const root = {{ innerHTML: '' }};
const elements = {{ '#app': root, '#overlay-root': {{ innerHTML: '' }}, '#toast-root': {{ innerHTML: '' }} }};
let intervals = 0;
globalThis.document = {{
  querySelector: (selector) => elements[selector] || null,
  querySelectorAll: () => [],
  documentElement: {{ dataset: {{}}, style: {{ setProperty: () => {{}}, removeProperty: () => {{}} }} }}
}};
globalThis.window = {{
  setTimeout: (callback) => {{ callback(); return 0; }}, clearTimeout: () => {{}},
  setInterval: () => ++intervals, clearInterval: () => {{}}
}};

let source = await readFile({json.dumps(str(APP_SOURCE))}, 'utf8');
source = source.replace("import {{ Bridge }} from './bridge.js';", 'const Bridge = {{}};');
source = source.replace(/const app = new OrbitApp\(\);\s*app\.init\(\);\s*$/, 'export {{ OrbitApp }};');
const moduleUrl = 'data:text/javascript;charset=utf-8,' + encodeURIComponent(source);
const {{ OrbitApp }} = await import(moduleUrl);

const settings = {{
  theme: 'dark', accent: 'violet', density: 'comfortable', reduce_motion: false,
  categories: {{ oauth: {{ enabled: true, client_id: '123456', redirect_uri: 'http://127.0.0.1:8989/oauth/callback', callback_timeout_seconds: 300 }} }}
}};
const calls = [];
const bridge = {{
  call: async (method, ...args) => {{
    calls.push([method, ...args]);
    if (method === 'start_oauth_login') return {{ operation_id: 'operation-cancel', status: 'waiting' }};
    if (method === 'poll_oauth_login') return {{ operation_id: args[0], status: 'waiting' }};
    if (method === 'cancel_oauth_login') throw new Error('Temporary bridge failure');
    throw new Error('Unexpected bridge method: ' + method);
  }}
}};

const app = new OrbitApp();
app.bridge = bridge;
app.state.mode = 'desktop';
app.state.settings = settings;
app.render = () => {{}};
app.renderOverlays = () => {{}};
app.toast = () => {{}};

await app.startOAuthLogin();
await new Promise((resolve) => setImmediate(resolve));
if (intervals !== 1) throw new Error('The initial OAuth wait did not start one polling interval.');
await app.cancelOAuthLogin();
if (!calls.some((call) => call[0] === 'cancel_oauth_login' && call[1] === 'operation-cancel')) throw new Error('The cancellation request never reached the bridge.');
if (!app.state.modal || app.state.modal.operation.status !== 'waiting' || app.state.modal.operation.cancellation_requested) throw new Error('The failed cancellation did not restore the waiting operation.');
if (intervals !== 2) throw new Error('Polling was not restarted after a failed cancellation.');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
