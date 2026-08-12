"""Portable static checks that require only the Python standard library."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
BRIDGE_PY = ROOT / "app" / "backend" / "api" / "bridge.py"
BRIDGE_JS = ROOT / "app" / "frontend" / "src" / "bridge.js"
APP_JS = ROOT / "app" / "frontend" / "src" / "app.js"
SERVICE_PY = ROOT / "app" / "backend" / "services" / "application_service.py"
TESTS = ROOT / "tests"


def class_methods(path: Path, class_name: str) -> set[str]:
    module = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return {
        node.name
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    }


def main() -> int:
    backend_methods = class_methods(BRIDGE_PY, "DesktopBridge")
    service_methods = class_methods(SERVICE_PY, "ApplicationService")
    bridge_source = BRIDGE_JS.read_text(encoding="utf-8")
    contract_match = re.search(
        r"const CONTRACT_METHODS = \[(.*?)\];", bridge_source, re.DOTALL
    )
    if contract_match is None:
        raise RuntimeError("CONTRACT_METHODS was not found.")
    contract_methods = set(re.findall(r"'([^']+)'", contract_match.group(1)))
    referenced = set(
        re.findall(r"self\._service\.([a-z_][a-z0-9_]*)", BRIDGE_PY.read_text(encoding="utf-8"))
    )

    app_source = APP_JS.read_text(encoding="utf-8")
    actions = set(re.findall(r'data-action="([A-Za-z0-9_:.-]+)"', app_source))
    handled = set(re.findall(r"action === '([A-Za-z0-9_:.-]+)'", app_source))
    non_click = {"nexus-change-target", "nexus-code-input"}

    tests = 0
    for path in TESTS.glob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        tests += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        )

    report = {
        "backend_bridge_methods": len(backend_methods),
        "frontend_contract_methods": len(contract_methods),
        "missing_frontend_contract": sorted(backend_methods - contract_methods),
        "extra_frontend_contract": sorted(contract_methods - backend_methods),
        "dangling_bridge_service_calls": sorted(referenced - service_methods),
        "declared_actions": len(actions),
        "unhandled_click_actions": sorted(actions - handled - non_click),
        "test_functions": tests,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    failures = (
        report["missing_frontend_contract"]
        or report["extra_frontend_contract"]
        or report["dangling_bridge_service_calls"]
        or report["unhandled_click_actions"]
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
