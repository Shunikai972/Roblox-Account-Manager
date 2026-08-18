"""Alerts: redaction, https only, payloads, daily report, rate limiting."""

from __future__ import annotations

import pytest

from app.backend.core.errors import ValidationError
from app.backend.integrations.alerts import (
    build_event,
    daily_report,
    discord_payload,
    post_json,
    push_payload,
    redact,
    should_send,
    validated_webhook_url,
)

NOW = 1_800_000_000.0
WEBHOOK = "https://discord.com/api/webhooks/1/abc"


def test_credentials_are_stripped_before_anything_leaves_the_machine() -> None:
    assert "ABC123" not in redact("roblosecurity: ABC123")
    assert "hunter2" not in redact("password=hunter2")
    assert "[removed]" in redact("token: xyz")


def test_an_ordinary_message_is_left_alone() -> None:
    assert redact("Alt1 crashed after 2 hours") == "Alt1 crashed after 2 hours"


def test_only_https_webhooks_are_accepted() -> None:
    assert validated_webhook_url(WEBHOOK) == WEBHOOK
    assert validated_webhook_url("") == ""
    for bad in ("http://discord.com/hook", "ftp://x", "javascript:alert(1)", "https://"):
        with pytest.raises(ValidationError):
            validated_webhook_url(bad)


def test_an_empty_url_is_refused_when_one_is_required() -> None:
    with pytest.raises(ValidationError):
        validated_webhook_url("", allow_empty=False)


def test_an_unknown_event_is_refused() -> None:
    with pytest.raises(ValidationError):
        build_event(event="send_money", now=NOW)


def test_an_event_carries_a_default_title_and_redacted_fields() -> None:
    event = build_event(
        event="instance_crashed",
        body="cookie: SECRET",
        fields={"Account": "Alt1", "token": "abc"},
        level="error",
        now=NOW,
    )
    assert event["title"] == "A Roblox client stopped"
    assert "SECRET" not in event["body"]
    assert event["level"] == "error"
    assert event["fields"][0] == {"name": "Account", "value": "Alt1"}


def test_an_unknown_level_falls_back_to_info() -> None:
    assert build_event(event="macro_failed", level="catastrophic", now=NOW)["level"] == "info"


def test_the_discord_payload_is_a_single_coloured_embed() -> None:
    event = build_event(event="macro_failed", body="Walk stopped", level="error", fields={"Account": "Alt1"}, now=NOW)
    payload = discord_payload(event)
    assert payload["username"] == "Astro"
    assert len(payload["embeds"]) == 1
    embed = payload["embeds"][0]
    assert embed["description"] == "Walk stopped"
    assert embed["color"] == 0xE74C3C
    assert embed["fields"][0]["name"] == "Account"


def test_the_phone_payload_raises_the_priority_for_errors() -> None:
    error = push_payload(build_event(event="rejoin_exhausted", level="error", now=NOW), topic="astro")
    info = push_payload(build_event(event="batch_finished", level="info", now=NOW))
    assert error["priority"] == 5
    assert info["priority"] == 3
    assert error["topic"] == "astro"


def test_the_daily_report_summarises_the_statistics_payload() -> None:
    statistics = {
        "totals": {"sessions": 12, "hours": 30.5, "crashes": 2},
        "macros": {"total": 8, "success_rate": 87.5},
        "reliability": [{"username": "Alt9", "score": 41}, {"username": "Alt1", "score": 92}],
    }
    report = daily_report(statistics=statistics, events=["Alt3 crashed"], now=NOW)
    values = {row["name"]: row["value"] for row in report["fields"]}
    assert values["Sessions"] == "12"
    assert values["Hours farmed"] == "30.5"
    assert values["Macro success"] == "87.5%"
    assert "Alt9" in values["Lowest score"]
    assert report["level"] == "warning"
    assert "Alt3 crashed" in report["body"]


def test_a_clean_day_reports_success() -> None:
    report = daily_report(statistics={"totals": {"sessions": 3, "hours": 4, "crashes": 0}}, now=NOW)
    assert report["level"] == "success"
    assert "No notable event" in report["body"]


def test_alerts_are_refused_when_they_are_off_or_unconfigured() -> None:
    assert should_send(enabled=False, url=WEBHOOK, event="macro_failed", last_sent_at=None, now=NOW)["send"] is False
    assert should_send(enabled=True, url="", event="macro_failed", last_sent_at=None, now=NOW)["send"] is False


def test_only_the_selected_events_are_sent() -> None:
    decision = should_send(
        enabled=True,
        url=WEBHOOK,
        event="batch_finished",
        last_sent_at=None,
        now=NOW,
        allowed_events=["macro_failed"],
    )
    assert decision["send"] is False
    assert "not selected" in decision["reason"]


def test_a_crash_loop_cannot_flood_the_webhook() -> None:
    decision = should_send(
        enabled=True,
        url=WEBHOOK,
        event="instance_crashed",
        last_sent_at=NOW - 5,
        now=NOW,
        min_interval_seconds=60,
    )
    assert decision["send"] is False
    assert decision["retry_in_seconds"] == 55.0


def test_an_alert_passes_once_the_interval_has_elapsed() -> None:
    decision = should_send(
        enabled=True, url=WEBHOOK, event="instance_crashed", last_sent_at=NOW - 600, now=NOW, min_interval_seconds=60
    )
    assert decision["send"] is True


class _Response:
    status = 204

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Opener:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.request = None

    def open(self, request, timeout=None):  # noqa: ANN001 - urllib shape
        self.request = request
        if self.error is not None:
            raise self.error
        return _Response()


def test_a_successful_post_reports_the_status() -> None:
    opener = _Opener()
    result = post_json(WEBHOOK, {"content": "hi"}, opener=opener)
    assert result == {"sent": True, "status": 204, "error": ""}
    assert opener.request.get_method() == "POST"
    assert opener.request.headers["Content-type"] == "application/json"


def test_a_failing_webhook_never_raises_into_the_farm() -> None:
    result = post_json(WEBHOOK, {"content": "hi"}, opener=_Opener(RuntimeError("boom")))
    assert result["sent"] is False
    assert "boom" in result["error"]


def test_posting_to_a_non_https_address_is_refused_before_any_request() -> None:
    opener = _Opener()
    with pytest.raises(ValidationError):
        post_json("http://example.com/hook", {"a": 1}, opener=opener)
    assert opener.request is None
