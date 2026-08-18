"""Tests for feature surfaces that are hidden but intentionally NOT deleted.

Nexus is kept in the source tree so it can be recovered later.  These tests pin
down both halves of that promise:

1. With no flag set, nothing in the product can reach Nexus.
2. Setting ASTRO_ENABLE_NEXUS brings the whole surface back, and every Nexus
   source file is still on disk.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.backend.core.config import HIDDEN_FEATURES, feature_enabled, feature_flags
from app.backend.core.errors import ConflictError
from app.backend.services.application_service import ApplicationService

NEXUS_FLAG = "ASTRO_ENABLE_NEXUS"


def _app_js() -> str:
    path = Path("app/frontend/src/app.js")
    assert path.is_file()
    return path.read_text(encoding="utf-8")


# Flag plumbing ------------------------------------------------------------


def test_nexus_is_hidden_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(NEXUS_FLAG, raising=False)

    assert HIDDEN_FEATURES["nexus"] == NEXUS_FLAG
    assert feature_enabled("nexus") is False
    assert feature_flags()["nexus"] is False


def test_nexus_can_be_recovered_with_the_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("1", "true", "TRUE", "yes", "on", "enabled"):
        monkeypatch.setenv(NEXUS_FLAG, value)
        assert feature_enabled("nexus") is True, value
        assert feature_flags()["nexus"] is True, value


def test_meaningless_flag_values_keep_nexus_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("", "0", "false", "no", "off", "maybe"):
        monkeypatch.setenv(NEXUS_FLAG, value)
        assert feature_enabled("nexus") is False, value


def test_features_not_listed_as_hidden_stay_enabled() -> None:
    assert feature_enabled("macros") is True
    assert feature_enabled("instances") is True


# Backend surface ----------------------------------------------------------


def test_nexus_service_entry_points_refuse_while_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(NEXUS_FLAG, raising=False)
    guard = ApplicationService._require_nexus_feature

    with pytest.raises(ConflictError) as error:
        guard(SimpleNamespace())

    message = str(error.value)
    assert "hidden" in message.lower()
    assert NEXUS_FLAG in message


def test_nexus_guard_allows_calls_once_recovered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(NEXUS_FLAG, "1")

    ApplicationService._require_nexus_feature(SimpleNamespace())


def test_nexus_status_reports_unavailable_while_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(NEXUS_FLAG, raising=False)

    status = ApplicationService.get_nexus_status(SimpleNamespace(_nexus_server=None))

    assert status["available"] is False
    assert status["running"] is False
    assert status["accounts"] == []


def test_shutdown_can_stop_a_listener_without_the_flag() -> None:
    """close() must never raise just because the surface is hidden now."""

    assert hasattr(ApplicationService, "_stop_nexus_server_unchecked")
    source = Path("app/backend/services/application_service.py").read_text(encoding="utf-8")
    assert "self._stop_nexus_server_unchecked()" in source


# Frontend surface ---------------------------------------------------------


def test_frontend_gates_every_nexus_entry_point() -> None:
    content = _app_js()

    # The tab, the route, the embedded panel and the account-card button.
    assert "(this.nexusEnabled() ? this.navItem('nexus'" in content
    assert "this.nexusEnabled() ? this.renderNexusExecutor() : this.renderDashboard()" in content
    assert "(this.nexusEnabled() ? this.renderNexusSection() : '')" in content
    assert "(this.nexusEnabled() ? '<button" in content

    # Navigation, the command palette and the modal cannot reach it either.
    assert "if (route === 'nexus' && !this.nexusEnabled()) route = 'dashboard';" in content
    assert "].concat(this.nexusEnabled()" in content
    assert "value.kind === 'send-nexus' && !this.nexusEnabled()" in content

    # Clicks on any retained Nexus control are ignored while hidden.
    assert "if (!this.nexusEnabled() && NEXUS_ACTIONS.has(action)) return;" in content


def test_frontend_defaults_to_hidden_before_the_backend_answers() -> None:
    content = _app_js()

    assert "features: { nexus: false }," in content
    assert "this.state.features = Object.assign({ nexus: false }, unwrap(boot.features) || {});" in content


def test_every_gated_nexus_action_is_listed() -> None:
    content = _app_js()
    start = content.index("const NEXUS_ACTIONS")
    listed = content[start : content.index("]);", start)]

    for action in (
        "open-nexus-panel",
        "open-send-nexus",
        "start-nexus-server",
        "stop-nexus-server",
        "copy-nexus-script",
        "refresh-nexus-status",
        "nexus-execute",
        "nexus-clear-editor",
        "nexus-clear-log",
        "nexus-target-client",
        "nexus-quick",
    ):
        assert "'" + action + "'" in listed, action


# Recovery guarantee -------------------------------------------------------


def test_nexus_implementation_is_still_present_for_recovery() -> None:
    """Hidden means unreachable, not removed: every file must still exist."""

    for relative in (
        "app/backend/nexus/__init__.py",
        "app/backend/nexus/controlled_account.py",
        "app/backend/nexus/lua_script.py",
        "app/backend/nexus/server.py",
        "tests/test_nexus.py",
        "tests/test_frontend_nexus_ui.py",
    ):
        assert Path(relative).is_file(), relative

    packaged = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "app.backend.nexus" in packaged

    app_js = _app_js()
    for renderer in ("renderNexusSection", "renderNexusExecutor", "sendNexusCommand", "nexusExecute"):
        assert renderer in app_js, renderer
