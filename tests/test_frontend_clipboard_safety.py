"""Regression guards for clipboard error handling and secret-safe feedback."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "frontend" / "src" / "app.js"


def test_clipboard_notifications_never_echo_the_copied_value() -> None:
    source = APP_JS.read_text(encoding="utf-8")

    assert "async writeClipboard(value)" in source
    assert "String(value) + ' is on your clipboard.'" not in source
    assert "this.toast('success', String(label || 'Value') + ' copied', 'Copied to the clipboard.');" in source


def test_sensitive_copy_paths_propagate_clipboard_failures() -> None:
    source = APP_JS.read_text(encoding="utf-8")

    for expression in (
        "this.writeClipboard(result.password || '')",
        "this.writeClipboard(res.cookie || '')",
        "this.writeClipboard(res.ticket || '')",
        "this.writeClipboard(res.link || '')",
    ):
        assert expression in source

    # copyText handles errors for the standalone Place ID button. Sensitive
    # form actions call writeClipboard directly so their shared catch keeps the
    # modal open and never reports a second, false success.
    assert "this.copyText(button.dataset.value, 'Place ID')" in source
    assert source.count("this.copyText(") == 1


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend UI checks.")
def test_clipboard_success_and_failure_are_reported_without_the_value() -> None:
    script = rf"""
import {{ readFile }} from 'node:fs/promises';

const element = {{ innerHTML: '', querySelector: () => null }};
const elements = {{ '#app': element, '#overlay-root': element, '#toast-root': element }};
globalThis.document = {{ querySelector: (selector) => elements[selector] || null, querySelectorAll: () => [] }};
globalThis.window = {{ setTimeout: () => 0, clearTimeout: () => {{}}, setInterval: () => 1, clearInterval: () => {{}} }};
let copied = '';
Object.defineProperty(globalThis, 'navigator', {{ configurable: true, value: {{ clipboard: {{ writeText: async (value) => {{ copied = value; }} }} }} }});

let source = await readFile({json.dumps(str(APP_JS))}, 'utf8');
source = source.replace("import {{ Bridge }} from './bridge.js';", 'const Bridge = {{}};');
source = source.replace(/const app = new OrbitApp\(\);\s*app\.init\(\);\s*$/, 'export {{ OrbitApp }};');
const {{ OrbitApp }} = await import('data:text/javascript;charset=utf-8,' + encodeURIComponent(source));
const app = new OrbitApp();
const toasts = [];
app.toast = (kind, title, body) => toasts.push({{ kind, title, body }});
const secret = '.ROBLOSECURITY=never-show-this';

if (await app.copyText(secret, 'Session') !== true) throw new Error('Clipboard success was not returned.');
if (copied !== secret) throw new Error('Clipboard received the wrong value.');
if (JSON.stringify(toasts).includes(secret)) throw new Error('The secret leaked into a toast.');

navigator.clipboard.writeText = async () => {{ throw new Error('denied'); }};
if (await app.copyText(secret, 'Session') !== false) throw new Error('Clipboard failure was not returned.');
if (toasts.at(-1).kind !== 'error') throw new Error('Clipboard failure was reported as success.');
if (JSON.stringify(toasts).includes(secret)) throw new Error('The secret leaked after a failure.');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
