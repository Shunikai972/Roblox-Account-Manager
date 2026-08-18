"""Macro studio: key profiles, variables, versions, profiler, step debugger.

Everything in this module works on a macro's action tree without running it,
so the editor can offer real tooling while the engine keeps its single, small,
bounded execution path.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Iterable, Mapping

from app.backend.core.errors import ValidationError

MAX_PROFILES = 20
MAX_PROFILE_KEYS = 40
MAX_NAME_CHARS = 40
MAX_VARIABLES = 20
MAX_VARIABLE_VALUE_CHARS = 120
MAX_VERSIONS = 20
MAX_STEPS = 2_000

_VARIABLE_PATTERN = re.compile(r"\{\{\s*([A-Za-z][A-Za-z0-9_]{0,31})\s*\}\}")
_KEY_PATTERN = re.compile(r"^[A-Z0-9_]{1,20}$")
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9 _-]{1,40}$")


def validated_key_profile(raw: Any) -> dict[str, Any]:
    """A key profile renames logical keys to the ones a game really uses."""

    if not isinstance(raw, Mapping):
        raise ValidationError("A key profile must be an object.")
    name = str(raw.get("name") or "").strip()
    if not _NAME_PATTERN.match(name):
        raise ValidationError("A key profile name may hold letters, numbers, spaces, dashes and underscores.")
    mapping_raw = raw.get("keys")
    if not isinstance(mapping_raw, Mapping) or not mapping_raw:
        raise ValidationError("A key profile needs at least one key.")
    if len(mapping_raw) > MAX_PROFILE_KEYS:
        raise ValidationError(f"A key profile may remap at most {MAX_PROFILE_KEYS} keys.")
    keys: dict[str, str] = {}
    for logical, physical in mapping_raw.items():
        source = str(logical or "").strip().upper()
        target = str(physical or "").strip().upper()
        if not _KEY_PATTERN.match(source) or not _KEY_PATTERN.match(target):
            raise ValidationError("Key profile entries must be short key names such as W or SPACE.")
        keys[source] = target
    return {"name": name, "keys": keys}


def validated_key_profiles(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise ValidationError("Key profiles must be a list.")
    if len(raw) > MAX_PROFILES:
        raise ValidationError(f"At most {MAX_PROFILES} key profiles can be saved.")
    profiles = [validated_key_profile(item) for item in raw]
    names = [profile["name"].casefold() for profile in profiles]
    if len(names) != len(set(names)):
        raise ValidationError("Two key profiles share the same name.")
    return profiles


def validated_variables(raw: Any) -> dict[str, str]:
    """Per-account macro variables such as SLOT or TARGET."""

    if raw is None or raw == "":
        return {}
    if not isinstance(raw, Mapping):
        raise ValidationError("Macro variables must be an object.")
    if len(raw) > MAX_VARIABLES:
        raise ValidationError(f"An account may carry at most {MAX_VARIABLES} macro variables.")
    variables: dict[str, str] = {}
    for key, value in raw.items():
        name = str(key or "").strip()
        if not re.match(r"^[A-Za-z][A-Za-z0-9_]{0,31}$", name):
            raise ValidationError("A variable name must start with a letter and hold letters, numbers or underscores.")
        text = "" if value is None else str(value).strip()
        if len(text) > MAX_VARIABLE_VALUE_CHARS:
            raise ValidationError(f"A variable value may hold at most {MAX_VARIABLE_VALUE_CHARS} characters.")
        if any(ord(char) < 32 for char in text):
            raise ValidationError("A variable value contains an invalid character.")
        variables[name] = text
    return variables


def _substitute(text: str, variables: Mapping[str, str], missing: set[str]) -> str:
    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in variables:
            return str(variables[name])
        missing.add(name)
        return match.group(0)

    return _VARIABLE_PATTERN.sub(_replace, text)


def apply_profile_and_variables(
    actions: Iterable[Any],
    *,
    profile: Mapping[str, Any] | None = None,
    variables: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a resolved copy of the tree plus the names that stayed unbound.

    Unresolved placeholders are reported instead of being silently typed into
    the game, which is how a macro ends up writing "{{TARGET}}" in chat.
    """

    keys = {}
    if isinstance(profile, Mapping):
        keys = {str(k).upper(): str(v).upper() for k, v in (profile.get("keys") or {}).items()}
    values = {str(k): str(v) for k, v in (variables or {}).items()}
    missing: set[str] = set()
    remapped = 0

    def _walk(nodes: Iterable[Any]) -> list[dict[str, Any]]:
        nonlocal remapped
        output: list[dict[str, Any]] = []
        for node in nodes:
            if not isinstance(node, Mapping):
                continue
            item = deepcopy(dict(node))
            key = item.get("key")
            if isinstance(key, str):
                upper = key.upper()
                if upper in keys and keys[upper] != upper:
                    item["key"] = keys[upper]
                    remapped += 1
            for field in ("value", "name", "place_id", "job_id"):
                if isinstance(item.get(field), str):
                    item[field] = _substitute(item[field], values, missing)
            if isinstance(item.get("actions"), list):
                item["actions"] = _walk(item["actions"])
            output.append(item)
        return output

    resolved = _walk(actions or [])
    return {
        "actions": resolved,
        "missing_variables": sorted(missing),
        "remapped_keys": remapped,
        "resolved": not missing,
    }


def flatten_steps(actions: Iterable[Any], *, _depth: int = 0, _path: str = "") -> list[dict[str, Any]]:
    """Flatten the tree into numbered steps for the step-by-step debugger."""

    steps: list[dict[str, Any]] = []

    def _walk(nodes: Iterable[Any], depth: int, path: str) -> None:
        for index, node in enumerate(nodes or []):
            if not isinstance(node, Mapping) or len(steps) >= MAX_STEPS:
                continue
            location = f"{path}{index + 1}"
            kind = str(node.get("type") or "")
            steps.append(
                {
                    "index": len(steps),
                    "path": location,
                    "depth": depth,
                    "type": kind,
                    "label": describe_action(node),
                    "estimated_ms": estimate_action_ms(node),
                }
            )
            children = node.get("actions")
            if isinstance(children, list) and children:
                _walk(children, depth + 1, f"{location}.")

    _walk(actions, _depth, _path)
    return steps


def describe_action(action: Mapping[str, Any]) -> str:
    kind = str(action.get("type") or "")
    if kind == "wait":
        upper = action.get("max_milliseconds")
        return f"Wait {action.get('milliseconds', 0)}-{upper} ms" if upper else f"Wait {action.get('milliseconds', 0)} ms"
    if kind == "key_press":
        return f"Press {action.get('key')} for {action.get('milliseconds', 0)} ms"
    if kind in {"key_down", "key_up"}:
        return f"{'Hold' if kind == 'key_down' else 'Release'} {action.get('key')}"
    if kind == "mouse_click":
        return f"Click {action.get('button')} at {action.get('x')}, {action.get('y')}"
    if kind == "text":
        return f"Type {str(action.get('value') or '')[:40]}"
    if kind == "repeat":
        return f"Repeat {action.get('count')} times"
    if kind == "checkpoint":
        return f"Checkpoint {action.get('name')}"
    if kind == "stop":
        return "Stop the macro"
    if kind == "launch":
        return "Launch the account"
    if kind == "teleport":
        return f"Teleport to place {action.get('place_id') or '-'}"
    if kind == "restart":
        return "Restart the client"
    if kind == "condition":
        return f"If {action.get('check')} then continue"
    return kind or "unknown"


def estimate_action_ms(action: Mapping[str, Any]) -> int:
    """A conservative duration estimate; waits and holds dominate a macro."""

    kind = str(action.get("type") or "")
    if kind == "wait":
        low = int(action.get("milliseconds") or 0)
        high = int(action.get("max_milliseconds") or low)
        return (low + high) // 2
    if kind == "key_press":
        return int(action.get("milliseconds") or 80)
    if kind in {"mouse_click", "key_down", "key_up"}:
        return 20
    if kind == "text":
        return max(20, len(str(action.get("value") or "")) * 12)
    if kind in {"launch", "restart"}:
        return 8_000
    if kind == "teleport":
        return 5_000
    return 0


def profile_macro(actions: Iterable[Any]) -> dict[str, Any]:
    """Estimate one pass of the macro and show where the time goes."""

    counts: dict[str, int] = {}
    total_ms = 0
    slowest: list[dict[str, Any]] = []

    def _walk(nodes: Iterable[Any], multiplier: int) -> None:
        nonlocal total_ms
        for node in nodes or []:
            if not isinstance(node, Mapping):
                continue
            kind = str(node.get("type") or "")
            counts[kind] = counts.get(kind, 0) + multiplier
            if kind == "repeat":
                loops = max(0, int(node.get("count") or 0))
                _walk(node.get("actions") or [], multiplier * loops)
                continue
            cost = estimate_action_ms(node) * multiplier
            total_ms += cost
            if cost:
                slowest.append({"label": describe_action(node), "type": kind, "milliseconds": cost})

    _walk(actions, 1)
    slowest.sort(key=lambda row: -row["milliseconds"])
    steps = flatten_steps(actions)
    return {
        "steps": len(steps),
        "estimated_ms": total_ms,
        "estimated_seconds": round(total_ms / 1000.0, 1),
        "by_type": [{"type": kind, "count": count} for kind, count in sorted(counts.items())],
        "slowest": slowest[:10],
        "note": "Estimates come from the declared durations; the real run also pays the game's own latency.",
    }


def push_version(
    history: Iterable[Any],
    *,
    macro: Mapping[str, Any],
    now: float,
    label: str = "",
) -> list[dict[str, Any]]:
    """Save a snapshot of a macro, newest first, oldest dropped past the cap."""

    if not isinstance(macro, Mapping):
        raise ValidationError("A macro snapshot must be an object.")
    rows = [dict(item) for item in (history or []) if isinstance(item, Mapping)]
    latest = rows[0] if rows else None
    snapshot = {
        "name": str(macro.get("name") or "")[:MAX_NAME_CHARS],
        "actions": deepcopy(macro.get("actions") or []),
        "source": str(macro.get("source") or "")[:32_000],
    }
    # An unchanged save is not a version; it would push real history out.
    if latest and latest.get("snapshot") == snapshot:
        return rows
    version = {
        "version": (int(latest.get("version", 0)) + 1) if latest else 1,
        "saved_at": float(now),
        "label": str(label or "")[:MAX_NAME_CHARS],
        "snapshot": snapshot,
    }
    return [version, *rows][:MAX_VERSIONS]


def rollback_version(history: Iterable[Any], *, version: int) -> dict[str, Any]:
    """Return the stored snapshot for a version number."""

    try:
        wanted = int(version)
    except (TypeError, ValueError) as exc:
        raise ValidationError("That macro version is invalid.") from exc
    for item in history or []:
        if isinstance(item, Mapping) and int(item.get("version", 0)) == wanted:
            snapshot = item.get("snapshot")
            if not isinstance(snapshot, Mapping):
                break
            return {
                "version": wanted,
                "saved_at": item.get("saved_at"),
                "label": item.get("label", ""),
                "name": snapshot.get("name", ""),
                "actions": deepcopy(snapshot.get("actions") or []),
                "source": snapshot.get("source", ""),
            }
    raise ValidationError("That macro version was not found.")


def describe_versions(history: Iterable[Any]) -> list[dict[str, Any]]:
    rows = []
    for item in history or []:
        if not isinstance(item, Mapping):
            continue
        snapshot = item.get("snapshot") if isinstance(item.get("snapshot"), Mapping) else {}
        rows.append(
            {
                "version": int(item.get("version", 0)),
                "saved_at": item.get("saved_at"),
                "label": item.get("label", ""),
                "name": snapshot.get("name", ""),
                "steps": len(flatten_steps(snapshot.get("actions") or [])),
            }
        )
    rows.sort(key=lambda row: -row["version"])
    return rows
