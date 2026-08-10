from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


APP_SOURCE = Path(__file__).resolve().parents[1] / "app" / "frontend" / "src" / "app.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend UI checks.")
def test_account_form_exposes_and_validates_the_optional_public_user_id() -> None:
    """A local profile can opt into public refreshes without OAuth."""

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

const app = new OrbitApp();
app.state.modal = {{ kind: 'account', account: {{ id: 'acct-public', username: 'PublicProfile', user_id: 123456789 }} }};
const modalHtml = app.renderModal();
if (!modalHtml.includes('id="account-user-id"') || !modalHtml.includes('name="user_id"') || !modalHtml.includes('value="123456789"')) {{
  throw new Error('Account modal does not expose the existing public User ID.');
}}

const calls = [];
app.bridge = {{ call: async (method, ...args) => {{ calls.push([method, ...args]); }} }};
app.toast = () => {{}};
const error = {{ hidden: true, textContent: '' }};
const submit = {{ disabled: false }};
const form = {{
  dataset: {{ form: 'account', id: '' }},
  querySelector: (selector) => selector === '.form-error' ? error : selector === 'button[type="submit"]' ? submit : null
}};
globalThis.FormData = class {{
  entries() {{ return [['username', 'PublicProfile'], ['user_id', '0'], ['display_name', 'Public Profile']][Symbol.iterator](); }}
  get(name) {{ return name === 'favorite' ? null : undefined; }}
}};
let prevented = false;
await app.handleSubmit({{ target: {{ closest: () => form }}, preventDefault: () => {{ prevented = true; }} }});
if (!prevented) throw new Error('Account submission did not prevent the browser default.');
if (calls.length !== 0) throw new Error('An invalid User ID reached the desktop bridge.');
if (error.hidden || !/positive whole number/.test(error.textContent)) throw new Error('The invalid User ID did not surface a form validation error.');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr

