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
SERVICE_DIR = ROOT / "app" / "backend" / "services"
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


def service_surface() -> set[str]:
    """Every public method callable on the service, mixins included.

    ``ApplicationService`` inherits part of its surface from mixins that live
    beside it in the services package, so a static scan of one file alone would
    report perfectly valid bridge calls as dangling.
    """

    module = ast.parse(SERVICE_PY.read_text(encoding="utf-8"))
    service = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "ApplicationService"
    )
    names = {
        node.name
        for node in service.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    }
    bases = {base.id for base in service.bases if isinstance(base, ast.Name)}
    for path in sorted(SERVICE_DIR.glob("*.py")):
        if path == SERVICE_PY:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name in bases:
                names |= {
                    child.name
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and not child.name.startswith("_")
                }
    return names


def main() -> int:
    backend_methods = class_methods(BRIDGE_PY, "DesktopBridge")
    service_methods = service_surface()
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
        "service_surface_methods": len(service_methods),
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
