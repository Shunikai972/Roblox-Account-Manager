"""Outbound alerts: Discord webhook, daily report, phone push.

Payload building is pure and tested.  Delivery is a thin, deliberately boring
HTTPS POST with a timeout and no redirect following, so a webhook URL cannot
quietly become a request to somewhere else.

Phone notifications go through a push relay you already use (ntfy, Pushover,
Gotify, ...).  Astro has no push infrastructure of its own and does not
pretend otherwise.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from app.backend.core.errors import ValidationError

MAX_URL_CHARS = 500
MAX_TITLE_CHARS = 120
MAX_BODY_CHARS = 1_500
MAX_FIELDS = 10
MAX_EVENTS_PER_REPORT = 20
DEFAULT_TIMEOUT_SECONDS = 8
MAX_TIMEOUT_SECONDS = 30
DEFAULT_MIN_INTERVAL_SECONDS = 60
MAX_MIN_INTERVAL_SECONDS = 3_600

EVENT_LEVELS = {"info": 0x5865F2, "success": 0x2ECC71, "warning": 0xF1C40F, "error": 0xE74C3C}
ALERT_EVENTS = {
    "instance_crashed": "A Roblox client stopped",
    "macro_failed": "A macro stopped on an error",
    "rejoin_exhausted": "Automatic rejoin gave up",
    "memory_critical": "Memory is critically high",
    "batch_finished": "A batch launch finished",
    "schedule_ran": "A scheduled task ran",
    "daily_report": "Daily report",
}

# Anything that looks like a credential is stripped before it can leave the
# machine. An alert is not worth leaking a cookie over.
_SECRET_PATTERN = re.compile(
    r"(?i)(roblosecurity|password|passwd|cookie|token|secret|api[_-]?key|authorization)\s*[:=]\s*\S+"
)


def redact(text: Any) -> str:
    """Remove credential-looking fragments from an outgoing string."""

    value = str(text or "")
    return _SECRET_PATTERN.sub(lambda match: f"{match.group(1)}: [removed]", value)


def validated_webhook_url(value: Any, *, allow_empty: bool = True) -> str:
    """Accept only an https URL, which is the only safe place to post."""

    text = str(value or "").strip()
    if not text:
        if allow_empty:
            return ""
        raise ValidationError("A webhook address is required.")
    if len(text) > MAX_URL_CHARS:
        raise ValidationError(f"A webhook address may hold at most {MAX_URL_CHARS} characters.")
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValidationError("A webhook address must start with https://")
    if any(ord(char) < 33 for char in text):
        raise ValidationError("That webhook address is not valid.")
    return text


def build_event(
    *,
    event: str,
    title: str = "",
    body: str = "",
    level: str = "info",
    fields: Mapping[str, Any] | None = None,
    now: float = 0.0,
) -> dict[str, Any]:
    """Normalize one alert before it is formatted for any destination."""

    name = str(event or "").strip().lower()
    if name not in ALERT_EVENTS:
        raise ValidationError("That alert event is not supported.")
    tone = str(level or "info").strip().lower()
    if tone not in EVENT_LEVELS:
        tone = "info"
    rows: list[dict[str, str]] = []
    for key, value in list((fields or {}).items())[:MAX_FIELDS]:
        rows.append({"name": redact(key)[:60], "value": redact(value)[:200] or "-"})
    return {
        "event": name,
        "level": tone,
        "title": redact(title or ALERT_EVENTS[name])[:MAX_TITLE_CHARS],
        "body": redact(body)[:MAX_BODY_CHARS],
        "fields": rows,
        "at": float(now),
    }


def discord_payload(event: Mapping[str, Any], *, username: str = "Astro") -> dict[str, Any]:
    """Format an alert as a Discord webhook body."""

    embed: dict[str, Any] = {
        "title": str(event.get("title") or "Astro")[:MAX_TITLE_CHARS],
        "color": EVENT_LEVELS.get(str(event.get("level") or "info"), EVENT_LEVELS["info"]),
    }
    body = str(event.get("body") or "")
    if body:
        embed["description"] = body[:MAX_BODY_CHARS]
    fields = [row for row in (event.get("fields") or []) if isinstance(row, Mapping)]
    if fields:
        embed["fields"] = [
            {"name": str(row.get("name") or "-")[:60], "value": str(row.get("value") or "-")[:200], "inline": True}
            for row in fields[:MAX_FIELDS]
        ]
    return {"username": str(username or "Astro")[:60], "embeds": [embed]}


def push_payload(event: Mapping[str, Any], *, topic: str = "") -> dict[str, Any]:
    """Format an alert for a phone push relay (ntfy and friends)."""

    priority = {"error": 5, "warning": 4, "success": 3, "info": 3}.get(str(event.get("level") or "info"), 3)
    lines = [str(event.get("body") or "")]
    for row in (event.get("fields") or [])[:MAX_FIELDS]:
        if isinstance(row, Mapping):
            lines.append(f"{row.get('name')}: {row.get('value')}")
    payload = {
        "title": str(event.get("title") or "Astro")[:MAX_TITLE_CHARS],
        "message": "\n".join(line for line in lines if line)[:MAX_BODY_CHARS] or "Astro alert",
        "priority": priority,
        "tags": [str(event.get("event") or "astro")],
    }
    if topic:
        payload["topic"] = str(topic)[:60]
    return payload


def daily_report(
    *,
    statistics: Mapping[str, Any] | None = None,
    events: Iterable[Any] = (),
    now: float = 0.0,
) -> dict[str, Any]:
    """Build the once-a-day summary from the statistics payload."""

    stats = statistics if isinstance(statistics, Mapping) else {}
    totals = stats.get("totals") if isinstance(stats.get("totals"), Mapping) else {}
    macros = stats.get("macros") if isinstance(stats.get("macros"), Mapping) else {}
    reliability = [row for row in (stats.get("reliability") or []) if isinstance(row, Mapping)]
    weakest = min(reliability, key=lambda row: row.get("score", 100)) if reliability else None
    notable = [redact(item)[:120] for item in list(events)[:MAX_EVENTS_PER_REPORT] if item]

    fields: dict[str, Any] = {
        "Sessions": totals.get("sessions", 0),
        "Hours farmed": totals.get("hours", 0),
        "Crashes": totals.get("crashes", 0),
    }
    if macros.get("total"):
        rate = macros.get("success_rate")
        fields["Macro success"] = f"{rate}%" if rate is not None else "no finished run"
    if weakest is not None:
        fields["Lowest score"] = f"{weakest.get('username') or weakest.get('account_id')} ({weakest.get('score')})"

    body_lines = [f"{len(notable)} notable event(s) in the last day."] if notable else ["No notable event."]
    body_lines.extend(f"- {line}" for line in notable[:10])
    return build_event(
        event="daily_report",
        title="Astro daily report",
        body="\n".join(body_lines),
        level="warning" if totals.get("crashes") else "success",
        fields=fields,
        now=now,
    )


def should_send(
    *,
    enabled: bool,
    url: str,
    event: str,
    last_sent_at: float | None,
    now: float,
    min_interval_seconds: int = DEFAULT_MIN_INTERVAL_SECONDS,
    allowed_events: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Decide whether one alert is allowed to leave, and say why not."""

    if not enabled:
        return {"send": False, "reason": "Alerts are turned off."}
    if not str(url or "").strip():
        return {"send": False, "reason": "No webhook address is configured."}
    allowed = {str(item).strip().lower() for item in (allowed_events or []) if str(item).strip()}
    if allowed and str(event).lower() not in allowed:
        return {"send": False, "reason": "That event is not selected for alerts."}
    interval = max(0, min(int(min_interval_seconds or 0), MAX_MIN_INTERVAL_SECONDS))
    if last_sent_at is not None and interval:
        try:
            elapsed = float(now) - float(last_sent_at)
        except (TypeError, ValueError):
            elapsed = interval
        if elapsed < interval:
            # Rate limiting is what stops a crash loop from posting 400 times.
            return {
                "send": False,
                "reason": f"An alert was sent {elapsed:.0f}s ago; the minimum gap is {interval}s.",
                "retry_in_seconds": round(interval - elapsed, 1),
            }
    return {"send": True, "reason": ""}


def post_json(
    url: str,
    payload: Mapping[str, Any],
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    opener: Any = None,
) -> dict[str, Any]:
    """POST one JSON body over https. Never raises; reports what happened."""

    address = validated_webhook_url(url, allow_empty=False)
    timeout = max(1, min(int(timeout_seconds or DEFAULT_TIMEOUT_SECONDS), MAX_TIMEOUT_SECONDS))
    body = json.dumps(dict(payload)).encode("utf-8")
    request = urllib.request.Request(
        address,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "AstroAccountManager"},
        method="POST",
    )
    # No redirect handler: a webhook must answer at the address it was given.
    client = opener if opener is not None else urllib.request.build_opener(urllib.request.HTTPSHandler())
    try:
        with client.open(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 0) or 0)
            return {"sent": 200 <= status < 300, "status": status, "error": ""}
    except urllib.error.HTTPError as exc:
        return {"sent": False, "status": int(exc.code), "error": f"The webhook answered {exc.code}."}
    except urllib.error.URLError as exc:
        return {"sent": False, "status": 0, "error": f"The webhook could not be reached: {exc.reason}"}
    except Exception as exc:  # noqa: BLE001 - an alert must never break a farm
        return {"sent": False, "status": 0, "error": f"The webhook failed: {exc}"}
