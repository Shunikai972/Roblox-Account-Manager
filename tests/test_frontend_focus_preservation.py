"""Typing must survive the background refresh.

The runtime poll rebuilds the page every three seconds.  It used to assign
``innerHTML`` directly, which destroys the element under the caret: the alias and
description boxes lost focus and the half-typed text mid-sentence.  These tests
run the real ``swapHtml`` from app.js against a fake DOM.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


APP_SOURCE = Path(__file__).resolve().parents[1] / "app" / "frontend" / "src" / "app.js"


def test_the_render_paths_go_through_the_focus_preserving_swap() -> None:
    """No render path may assign innerHTML on the page or overlay root directly."""

    source = APP_SOURCE.read_text(encoding="utf8")

    assert "swapHtml(container, html) {" in source
    assert "this.swapHtml(this.root, html);" in source
    assert "this.swapHtml(this.overlayRoot, output);" in source
    assert "this.root.innerHTML = html;" not in source
    assert "this.overlayRoot.innerHTML = output;" not in source


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend UI checks.")
def test_a_focused_text_box_keeps_its_text_focus_and_caret_across_a_refresh() -> None:
    script = rf"""
import {{ readFile }} from 'node:fs/promises';

const root = {{ innerHTML: '' }};
const elements = {{ '#app': root, '#overlay-root': {{ innerHTML: '' }}, '#toast-root': {{ innerHTML: '' }} }};
globalThis.document = {{
  activeElement: null,
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

// The description box on the accounts screen, mid-sentence.
const typed = {{
  tagName: 'TEXTAREA', id: 'ram-desc-input', value: 'Farming alt, do not touch',
  selectionStart: 7, selectionEnd: 7, getAttribute: () => null
}};
const rebuilt = {{
  tagName: 'TEXTAREA', id: 'ram-desc-input', value: '', focused: false, range: null,
  focus() {{ this.focused = true; }},
  setSelectionRange(start, end) {{ this.range = [start, end]; }}
}};
const container = {{
  innerHTML: '',
  contains: (node) => node === typed,
  querySelector: (selector) => selector === '[id="ram-desc-input"]' ? rebuilt : null
}};

globalThis.document.activeElement = typed;
app.swapHtml(container, '<textarea id="ram-desc-input"></textarea>');

if (container.innerHTML !== '<textarea id="ram-desc-input"></textarea>') {{
  throw new Error('The refresh did not repaint the page.');
}}
if (rebuilt.value !== 'Farming alt, do not touch') {{
  throw new Error('The half-typed description was wiped by the refresh.');
}}
if (rebuilt.focused !== true) {{
  throw new Error('The refresh stole focus from the box being typed into.');
}}
if (JSON.stringify(rebuilt.range) !== '[7,7]') {{
  throw new Error('The caret jumped: got ' + JSON.stringify(rebuilt.range));
}}

// Nothing focused: the plain, cheap path must still run.
globalThis.document.activeElement = null;
const plain = {{ innerHTML: 'old', contains: () => false, querySelector: () => null }};
app.swapHtml(plain, 'new');
if (plain.innerHTML !== 'new') throw new Error('An idle refresh stopped repainting.');

// A focused button is not a text box: no value juggling, just a repaint.
const button = {{ tagName: 'BUTTON', id: 'go' }};
globalThis.document.activeElement = button;
const withButton = {{ innerHTML: 'old', contains: () => true, querySelector: () => null }};
app.swapHtml(withButton, 'fresh');
if (withButton.innerHTML !== 'fresh') throw new Error('A focused button blocked the refresh.');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
