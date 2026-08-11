from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


APP_SOURCE = Path(__file__).resolve().parents[1] / "app" / "frontend" / "src" / "app.js"


def _run_ui_script(script: str) -> None:
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend UI checks.")
def test_public_account_snapshot_renders_real_bridge_data_and_never_fakes_preview() -> None:
    """Profile/presence snapshots are displayed only after desktop bridge refreshes."""

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
const account = {{
  id: 'acct-public', username: 'PublicUser', display_name: 'Local profile', user_id: 123456789,
  avatar_url: 'https://tr.rbxcdn.com/public-avatar/150/150/AvatarHeadshot/Png', avatar_color: 'violet',
  status: 'ready', metadata: {{}}
}};
const calls = [];
const bridge = {{
  call: async (method, ...args) => {{
    calls.push([method, ...args]);
    if (method === 'refresh_account_public_profile') {{
      account.display_name = 'Public Display';
      account.metadata.public_profile = {{ user_id: 123456789, username: 'PublicUser', display_name: 'Public Display', has_verified_badge: true, refreshed_at: new Date().toISOString() }};
      return {{ account, profile: account.metadata.public_profile }};
    }}
    if (method === 'refresh_account_presence') {{
      account.metadata.public_presence = {{ user_id: 123456789, state: 'in_game', last_location: 'Arcade', refreshed_at: new Date().toISOString() }};
      return [{{ account_id: account.id, user_id: account.user_id, presence: account.metadata.public_presence }}];
    }}
    if (method === 'bootstrap') return {{ accounts: [account], groups: [], games: [], instances: [], activity: [], notifications: [], settings, diagnostics: {{ services: [], logs: [], status: 'healthy' }} }};
    throw new Error('Unexpected bridge method: ' + method);
  }}
}};

const app = new OrbitApp();
app.bridge = bridge;
app.state.mode = 'desktop';
app.state.settings = settings;
app.state.accounts = [account];
app.applyTheme = () => {{}};
app.render = () => {{}};
app.renderOverlays = () => {{}};
app.toast = () => {{}};

await app.refreshPublicProfile(account.id);
await app.refreshPublicPresence(account.id);
if (!calls.some((call) => call[0] === 'refresh_account_public_profile' && call[1] === account.id)) throw new Error('Public profile refresh did not reach the bridge.');
if (!calls.some((call) => call[0] === 'refresh_account_presence' && Array.isArray(call[1]) && call[1][0] === account.id)) throw new Error('Public presence refresh did not reach the bridge.');
const card = app.renderAccountCard(app.state.accounts[0]);
if (!card.includes('Refresh public profile') || !card.includes('Public Display') || !card.includes('Arcade') || !card.includes('public-avatar')) {{
  throw new Error('The refreshed public identity, presence, or Roblox CDN avatar was not rendered.');
}}

app.state.mode = 'preview';
const preview = app.renderAccountCard(app.state.accounts[0]);
if (!preview.includes('Public Roblox data is unavailable in Preview') || preview.includes('data-action="refresh-public-profile"')) {{
  throw new Error('Preview rendered a usable or simulated public Roblox refresh action.');
}}
"""
    _run_ui_script(script)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend UI checks.")
def test_card_reordering_persists_full_order_and_rolls_back_on_bridge_failure() -> None:
    """The optimistic card order is restored if the atomic desktop request fails."""

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
let accounts = [
  {{ id: 'a', username: 'Alpha', display_name: 'Alpha', status: 'ready' }},
  {{ id: 'b', username: 'Bravo', display_name: 'Bravo', status: 'ready' }},
  {{ id: 'c', username: 'Charlie', display_name: 'Charlie', status: 'ready' }}
];
let fail = false;
const calls = [];
const bridge = {{
  call: async (method, ...args) => {{
    calls.push([method, ...args]);
    if (method === 'reorder_accounts') {{
      if (fail) throw new Error('Atomic order write failed');
      const byId = new Map(accounts.map((account) => [account.id, account]));
      accounts = args[0].map((id) => byId.get(id));
      return accounts;
    }}
    if (method === 'bootstrap') return {{ accounts, groups: [], games: [], instances: [], activity: [], notifications: [], settings, diagnostics: {{ services: [], logs: [], status: 'healthy' }} }};
    throw new Error('Unexpected bridge method: ' + method);
  }}
}};

const app = new OrbitApp();
app.bridge = bridge;
app.state.mode = 'desktop';
app.state.settings = settings;
app.state.accounts = accounts.slice();
app.applyTheme = () => {{}};
app.render = () => {{}};
app.toast = () => {{}};

await app.reorderAccountDrop('c', 'a');
if (app.state.accounts.map((account) => account.id).join(',') !== 'c,a,b') throw new Error('Successful reorder did not apply the returned full order.');
const request = calls.find((call) => call[0] === 'reorder_accounts');
if (!request || request[1].join(',') !== 'c,a,b') throw new Error('Reorder did not send a complete ordered account list.');

fail = true;
await app.reorderAccountDrop('b', 'c');
if (app.state.accounts.map((account) => account.id).join(',') !== 'c,a,b') throw new Error('Failed reorder did not roll back the optimistic account order.');
"""
    _run_ui_script(script)

