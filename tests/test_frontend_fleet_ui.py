"""Contract tests for the Fleet screen and the new macro control blocks.

The frontend is plain JavaScript rendered by pywebview, so these tests read the
source and assert the wiring a person would otherwise have to click through:
every declared action has a handler, the sidebar keeps exactly one new entry,
and a visual condition compiles into the shape the macro engine validates.
"""

from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "app" / "frontend" / "src" / "app.js").read_text(encoding="utf-8")
BRIDGE_JS = (ROOT / "app" / "frontend" / "src" / "bridge.js").read_text(encoding="utf-8")

FLEET_TABS = (
    "stats",
    "schedule",
    "health",
    "servers",
    "coord",
    "comfort",
    "alerts",
    "rules",
    "studio",
    "profiles",
)


def test_nine_new_screens_cost_the_sidebar_exactly_one_entry() -> None:
    # "ne surcharge pas l'ui": the nine sections live behind one route.
    assert APP_JS.count("this.navItem('fleet'") == 1
    assert "if (this.state.route === 'fleet') return this.renderFleet();" in APP_JS
    assert "fleet: ['Fleet'," in APP_JS
    for tab in FLEET_TABS:
        assert "['" + tab + "', '" in APP_JS, tab


def test_opening_the_route_loads_its_data_once() -> None:
    assert "if (route === 'fleet') void this.loadFleet(this.state.fleetTab);" in APP_JS
    assert "async loadFleet(tab)" in APP_JS


def test_every_declared_fleet_action_has_a_literal_handler() -> None:
    declared = set(re.findall(r'data-action="(fleet-[A-Za-z0-9_:.-]+)"', APP_JS))
    handled = set(re.findall(r"action === '(fleet-[A-Za-z0-9_:.-]+)'", APP_JS))
    assert declared, "the fleet screen should declare actions"
    assert not declared - handled, sorted(declared - handled)


def test_the_fleet_handler_is_consulted_before_the_other_click_actions() -> None:
    hook = "if (await this.handleFleetAction(action, button)) return;"
    assert hook in APP_JS
    assert APP_JS.index("const action = button.dataset.action;") < APP_JS.index(hook)


def test_the_fleet_screen_only_calls_methods_the_bridge_exposes() -> None:
    start = APP_JS.index("fleetTabList()")
    end = APP_JS.index("\n  renderDiagnostics() {", start)
    called = set(re.findall(r"this\.bridge\.call\('([a-z_]+)'", APP_JS[start:end]))
    contract = set(re.findall(r"'([a-z_]+)'", BRIDGE_JS.split("const CONTRACT_METHODS = [")[1].split("];")[0]))
    assert called, "the fleet screen should talk to the backend"
    assert not called - contract, sorted(called - contract)


def test_closing_live_clients_still_needs_a_person() -> None:
    # Decision (a) was "Non": nothing automatic may close a running client.
    shutdown = APP_JS.split("action === 'fleet-comfort-shutdown'")[1][:1200]
    assert "window.confirm(" in shutdown
    assert "{ confirm: true }" in shutdown
    assert shutdown.index("window.confirm(") < shutdown.index("{ confirm: true }")


def test_webhook_fields_are_write_only_in_the_form() -> None:
    assert '<input id="fleet-alert-discord" type="password"' in APP_JS
    assert '<input id="fleet-alert-phone" type="password"' in APP_JS
    # The form reports whether an address exists, never the address itself.
    assert "alerts.discord_configured ? '(configured)'" in APP_JS
    save = APP_JS.split("action === 'fleet-alerts-save'")[1][:1600]
    assert "this.fleetValue('fleet-alert-discord')" in save
    assert "payload.discord_webhook_url" in save


def test_the_visual_editor_offers_the_four_control_blocks() -> None:
    for kind in ("condition", "launch", "teleport", "restart"):
        assert 'data-action="add-macro-block" data-kind="' + kind + '"' in APP_JS, kind
        assert "'" + kind + "': {" in APP_JS or kind + ": { type: '" + kind + "'" in APP_JS, kind


def test_a_visual_condition_compiles_to_one_nested_action() -> None:
    # validate_macro_actions rejects a condition with an empty body, so the
    # serializer must always produce exactly one action inside it.
    assert "block.actions = [{ type: String(block.then || 'stop') }];" in APP_JS
    assert "delete block.then;" in APP_JS


def test_an_empty_teleport_server_is_omitted_rather_than_sent_blank() -> None:
    assert "if (block.type === 'teleport' && !String(block.job_id || '').trim()) delete block.job_id;" in APP_JS


def test_only_conditions_the_engine_can_answer_are_offered() -> None:
    editor = APP_JS.split("if (kind === 'condition')")[1][:1800]
    for check in (
        "runtime_above",
        "runtime_below",
        "checkpoint_reached",
        "checkpoint_missing",
        "variable_equals",
        "variable_missing",
        "account_running",
        "account_stopped",
    ):
        assert check in editor, check
    # No screenshot or pixel work exists in this build, so none may be offered.
    assert "pixel" not in editor.lower()
    assert "screenshot" not in editor.lower()


def test_the_dsl_hint_lists_the_new_commands() -> None:
    hint = APP_JS.split("Commands: WAIT")[1][:200]
    for command in ("IF/END", "LAUNCH", "TELEPORT", "RESTART"):
        assert command in hint, command


def test_the_fleet_screen_states_what_it_measures_without_promising_more() -> None:
    # Per-instance audio is stored, not applied, so the panel repeats the
    # backend's own note instead of implying a mixer that works.
    assert "escapeHtml(audio.note ||" in APP_JS
    assert (
        "Per-process audio control is unavailable on this machine, so levels are stored only."
        in APP_JS
    )


def test_the_launch_profiles_tab_is_wired_to_the_backend() -> None:
    """A saved destination must be listable, savable, launchable and removable."""

    assert "renderFleetProfiles()" in APP_JS
    for method in (
        "list_launch_profiles",
        "save_launch_profile",
        "delete_launch_profile",
        "launch_with_profile",
    ):
        assert "'" + method + "'" in APP_JS, method
        assert "'" + method + "'" in BRIDGE_JS, method
    for action in (
        "fleet-profile-save",
        "fleet-profile-delete",
        "fleet-profile-launch",
    ):
        assert 'data-action=\"' + action + '\"' in APP_JS, action
        assert "action === '" + action + "'" in APP_JS, action
    # The form never asks for a JobId and a private code at the same time by
    # accident: both fields exist, and the backend rejects the pair.
    assert 'id=\"fleet-profile-job\"' in APP_JS
    assert 'id=\"fleet-profile-link\"' in APP_JS


def test_the_emergency_stop_is_offered_and_never_closes_clients() -> None:
    assert 'data-action=\"fleet-emergency-stop\"' in APP_JS
    assert "action === 'fleet-emergency-stop'" in APP_JS
    assert "'emergency_stop'" in APP_JS
    assert "'emergency_stop'" in BRIDGE_JS
    handler = APP_JS[APP_JS.index("action === 'fleet-emergency-stop'") :][:600]
    assert "Running clients were left open" in handler


def test_an_unattended_client_has_its_own_dashboard_label() -> None:
    assert "afk: 'In game, unattended'" in APP_JS
    assert "farming: 'Farming'" in APP_JS
