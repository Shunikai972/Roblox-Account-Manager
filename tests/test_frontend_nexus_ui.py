"""Tests for JS Frontend Bridge Nexus contract compatibility."""

from pathlib import Path


def test_frontend_bridge_contains_nexus_contract_methods():
    bridge_path = Path("app/frontend/src/bridge.js")
    assert bridge_path.is_file()

    content = bridge_path.read_text(encoding="utf-8")
    assert "'start_nexus_server'" in content
    assert "'stop_nexus_server'" in content
    assert "'get_nexus_status'" in content
    assert "'send_nexus_command'" in content
    assert "'get_nexus_lua_script'" in content
