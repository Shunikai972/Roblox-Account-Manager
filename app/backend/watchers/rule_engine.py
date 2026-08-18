"""Explicit, bounded IF/THEN rules for long-running multi-account sessions.

A farm that runs for hours drifts: a macro stops making progress, a client sits
on its own disconnect dialog, a session ages past the point where Roblox leaks
memory, or the machine simply runs out of CPU because too many alts are awake.
Every one of those situations is currently noticed by a human watching the
dashboard.  This module turns them into decisions.

It is deliberately pure: no I/O, no psutil, no process handles, no clock.  The
caller samples the facts, the rules return decisions, and the caller decides
what to apply.  That separation is what makes the dangerous half honest --
closing or relaunching a live client requires explicit human confirmation in
this codebase (``terminate_known_process`` documents it), so those decisions
are returned as *recommendations* with ``automatic`` set to false rather than
quietly executed.

Two details matter more than the rule list itself:

* **Hysteresis.**  Pausing alts at 90% CPU and resuming them at 89% would flap
  forever.  Pressure is only considered released once usage falls a margin
  below the threshold that triggered it.
* **One decision per account.**  Rules are evaluated in a fixed precedence, so
  an account can never be told to pause and restart in the same tick.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from app.backend.core.errors import ValidationError

# Bounds ---------------------------------------------------------------------
# Bounded here, once, so a settings payload, a stored group rule and a UI form
# cannot disagree about what is acceptable.

MIN_MACRO_STUCK_SECONDS = 10
MAX_MACRO_STUCK_SECONDS = 3_600
MIN_SESSION_MAX_HOURS = 1.0
MAX_SESSION_MAX_HOURS = 48.0
MIN_PRESSURE_PERCENT = 50
MAX_PRESSURE_PERCENT = 100
MIN_PRIORITY = 0
MAX_PRIORITY = 10
DEFAULT_PRIORITY = 5
PRESSURE_RELEASE_MARGIN = 10
MAX_DECISIONS = 100
MAX_GROUP_SCOPE = 50
MAX_ID_CHARS = 128

# Rule identifiers -----------------------------------------------------------

RULE_CPU_PRESSURE = "cpu_pressure"
RULE_MEMORY_PRESSURE = "memory_pressure"
RULE_PRESSURE_RELEASED = "pressure_released"
RULE_MACRO_STUCK = "macro_stuck"
RULE_DISCONNECTED = "disconnected"
RULE_SESSION_TOO_LONG = "session_too_long"

# Action identifiers ---------------------------------------------------------

ACTION_PAUSE_MACRO = "pause_macro"
ACTION_RESUME_MACRO = "resume_macro"
ACTION_RESTART_MACRO = "restart_macro"
ACTION_RECOMMEND_RESTART_CLIENT = "recommend_restart_client"

#: Actions the service may apply on its own.  Anything outside this set needs a
#: human, and the decision says so instead of pretending otherwise.
AUTOMATIC_ACTIONS = frozenset(
    {ACTION_PAUSE_MACRO, ACTION_RESUME_MACRO, ACTION_RESTART_MACRO}
)

MACRO_STATE_RUNNING = "running"
MACRO_STATE_PAUSED = "paused"


@dataclass(frozen=True, slots=True)
class AccountFacts:
    """One sampled account, as observed by the caller.

    Unknown values stay falsy rather than guessed: an account whose runtime is
    unknown must not be restarted for being "too old".
    """

    account_id: str
    username: str = ""
    group_id: str | None = None
    priority: int = DEFAULT_PRIORITY
    running: bool = False
    runtime_seconds: float = 0.0
    disconnected: bool = False
    macro_run_id: str | None = None
    macro_id: str | None = None
    macro_state: str | None = None
    macro_idle_seconds: float = 0.0
    macro_paused_by_rule: bool = False


@dataclass(frozen=True, slots=True)
class SystemFacts:
    """Machine-wide pressure sample.  ``None`` means "not measured"."""

    cpu_percent: float | None = None
    memory_percent: float | None = None


@dataclass(frozen=True, slots=True)
class RuleSettings:
    """Bounded rule configuration.  Disabled by default, always."""

    enabled: bool = False
    macro_stuck_seconds: int = 60
    max_runtime_hours: float = 6.0
    cpu_pause_percent: int = 90
    memory_pause_percent: int = 90
    pause_priority_at_or_below: int = 3
    restart_stuck_macros: bool = True
    group_ids: tuple[str, ...] = ()

    def covers(self, group_id: str | None) -> bool:
        """Return whether this rule set applies to one account's group."""

        if not self.group_ids:
            return True
        return bool(group_id) and str(group_id) in self.group_ids

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "macro_stuck_seconds": self.macro_stuck_seconds,
            "max_runtime_hours": self.max_runtime_hours,
            "cpu_pause_percent": self.cpu_pause_percent,
            "memory_pause_percent": self.memory_pause_percent,
            "pause_priority_at_or_below": self.pause_priority_at_or_below,
            "restart_stuck_macros": self.restart_stuck_macros,
            "group_ids": list(self.group_ids),
        }


@dataclass(frozen=True, slots=True)
class RuleDecision:
    """One auditable decision about one account."""

    action: str
    rule: str
    account_id: str
    username: str
    explanation: str
    run_id: str | None = None
    macro_id: str | None = None
    automatic: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "rule": self.rule,
            "account_id": self.account_id,
            "username": self.username,
            "explanation": self.explanation,
            "run_id": self.run_id,
            "macro_id": self.macro_id,
            "automatic": self.automatic,
        }


def normalized_priority(value: Any) -> int:
    """Clamp any stored priority into the supported range.

    Priority lives in account metadata, which older builds never wrote, so a
    missing or corrupt value must degrade to the neutral default instead of
    raising and breaking an otherwise valid account.
    """

    if isinstance(value, bool) or value is None:
        return DEFAULT_PRIORITY
    try:
        number = int(value)
    except (TypeError, ValueError):
        return DEFAULT_PRIORITY
    return max(MIN_PRIORITY, min(MAX_PRIORITY, number))


def _bounded_int(value: Any, *, minimum: int, maximum: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{label} is invalid.")
    number = int(value)
    if not minimum <= number <= maximum:
        raise ValidationError(f"{label} must be between {minimum} and {maximum}.")
    return number


def _bounded_float(value: Any, *, minimum: float, maximum: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{label} is invalid.")
    number = float(value)
    if not minimum <= number <= maximum:
        raise ValidationError(f"{label} must be between {minimum} and {maximum}.")
    return round(number, 3)


def _bounded_bool(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{label} is invalid.")
    return value


def _bounded_group_ids(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple, set, frozenset)):
        raise ValidationError("The rule group scope must be a list of groups.")
    groups: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValidationError("A rule group identifier is invalid.")
        cleaned = item.strip()
        if not cleaned or len(cleaned) > MAX_ID_CHARS:
            raise ValidationError("A rule group identifier is invalid.")
        if cleaned not in groups:
            groups.append(cleaned)
    if len(groups) > MAX_GROUP_SCOPE:
        raise ValidationError(f"A rule set cannot target more than {MAX_GROUP_SCOPE} groups.")
    return tuple(groups)


def validated_rule_settings(value: Any, *, existing: Any = None) -> RuleSettings:
    """Validate a stored or submitted rule payload into bounded settings.

    Missing keys fall back to ``existing`` (then to the defaults) so partial
    updates from the UI stay valid, while present-but-wrong values are refused
    loudly instead of silently clamped.
    """

    base = existing if isinstance(existing, RuleSettings) else RuleSettings()
    if value is None:
        return base
    if not isinstance(value, Mapping):
        raise ValidationError("Rule settings are invalid.")

    def pick(key: str, fallback: Any) -> Any:
        return value[key] if key in value else fallback

    return RuleSettings(
        enabled=_bounded_bool(pick("enabled", base.enabled), label="The rule engine state"),
        macro_stuck_seconds=_bounded_int(
            pick("macro_stuck_seconds", base.macro_stuck_seconds),
            minimum=MIN_MACRO_STUCK_SECONDS,
            maximum=MAX_MACRO_STUCK_SECONDS,
            label="The stuck macro delay",
        ),
        max_runtime_hours=_bounded_float(
            pick("max_runtime_hours", base.max_runtime_hours),
            minimum=MIN_SESSION_MAX_HOURS,
            maximum=MAX_SESSION_MAX_HOURS,
            label="The maximum runtime",
        ),
        cpu_pause_percent=_bounded_int(
            pick("cpu_pause_percent", base.cpu_pause_percent),
            minimum=MIN_PRESSURE_PERCENT,
            maximum=MAX_PRESSURE_PERCENT,
            label="The CPU pause threshold",
        ),
        memory_pause_percent=_bounded_int(
            pick("memory_pause_percent", base.memory_pause_percent),
            minimum=MIN_PRESSURE_PERCENT,
            maximum=MAX_PRESSURE_PERCENT,
            label="The memory pause threshold",
        ),
        pause_priority_at_or_below=_bounded_int(
            pick("pause_priority_at_or_below", base.pause_priority_at_or_below),
            minimum=MIN_PRIORITY,
            maximum=MAX_PRIORITY,
            label="The pause priority threshold",
        ),
        restart_stuck_macros=_bounded_bool(
            pick("restart_stuck_macros", base.restart_stuck_macros),
            label="The stuck macro restart option",
        ),
        group_ids=_bounded_group_ids(pick("group_ids", list(base.group_ids))),
    )


def _measured(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number < 0:
        return None
    return number


def _pressure(system: SystemFacts, settings: RuleSettings) -> tuple[str | None, str]:
    """Return the active pressure rule and its human explanation."""

    cpu = _measured(system.cpu_percent)
    memory = _measured(system.memory_percent)
    if cpu is not None and cpu >= settings.cpu_pause_percent:
        return RULE_CPU_PRESSURE, f"CPU load reached {cpu:.0f}% (limit {settings.cpu_pause_percent}%)"
    if memory is not None and memory >= settings.memory_pause_percent:
        return (
            RULE_MEMORY_PRESSURE,
            f"Memory use reached {memory:.0f}% (limit {settings.memory_pause_percent}%)",
        )
    return None, ""


def _pressure_released(system: SystemFacts, settings: RuleSettings) -> bool:
    """Return whether usage fell far enough below both limits to resume.

    The margin is what stops paused alts from flapping back and forth around a
    threshold they are themselves influencing.
    """

    cpu = _measured(system.cpu_percent)
    memory = _measured(system.memory_percent)
    cpu_ok = cpu is None or cpu <= max(0, settings.cpu_pause_percent - PRESSURE_RELEASE_MARGIN)
    memory_ok = memory is None or memory <= max(
        0, settings.memory_pause_percent - PRESSURE_RELEASE_MARGIN
    )
    return cpu_ok and memory_ok


def evaluate_rules(
    *,
    accounts: Iterable[AccountFacts],
    system: SystemFacts | None = None,
    settings: RuleSettings | None = None,
) -> tuple[RuleDecision, ...]:
    """Turn sampled facts into at most one decision per account.

    Precedence is fixed and intentional: relieving machine pressure outranks
    fixing a stuck macro, because restarting a macro on a machine that is
    already saturated makes both problems worse.
    """

    rules = settings if isinstance(settings, RuleSettings) else RuleSettings()
    if not rules.enabled:
        return ()
    facts = _ordered_facts(accounts)
    sample = system if isinstance(system, SystemFacts) else SystemFacts()
    pressure_rule, pressure_reason = _pressure(sample, rules)
    released = pressure_rule is None and _pressure_released(sample, rules)

    decisions: list[RuleDecision] = []
    for account in facts:
        if not rules.covers(account.group_id):
            continue
        decision = _decide(account, rules, pressure_rule, pressure_reason, released)
        if decision is not None:
            decisions.append(decision)
        if len(decisions) >= MAX_DECISIONS:
            break
    return tuple(decisions)


def _ordered_facts(accounts: Iterable[AccountFacts]) -> Sequence[AccountFacts]:
    """Sort so the least important accounts are paused first, deterministically."""

    valid = [item for item in accounts if isinstance(item, AccountFacts) and item.account_id]
    return sorted(valid, key=lambda item: (normalized_priority(item.priority), item.account_id))


def _decide(
    account: AccountFacts,
    rules: RuleSettings,
    pressure_rule: str | None,
    pressure_reason: str,
    released: bool,
) -> RuleDecision | None:
    priority = normalized_priority(account.priority)
    macro_state = str(account.macro_state or "").strip().lower()
    label = account.username or account.account_id

    if pressure_rule is not None:
        if (
            macro_state == MACRO_STATE_RUNNING
            and account.macro_run_id
            and priority <= rules.pause_priority_at_or_below
        ):
            return RuleDecision(
                action=ACTION_PAUSE_MACRO,
                rule=pressure_rule,
                account_id=account.account_id,
                username=account.username,
                explanation=(
                    f"{pressure_reason}, so the macro on {label} "
                    f"(priority {priority}) was paused."
                ),
                run_id=account.macro_run_id,
                macro_id=account.macro_id,
                automatic=True,
            )
        return None

    if (
        released
        and account.macro_paused_by_rule
        and macro_state == MACRO_STATE_PAUSED
        and account.macro_run_id
    ):
        return RuleDecision(
            action=ACTION_RESUME_MACRO,
            rule=RULE_PRESSURE_RELEASED,
            account_id=account.account_id,
            username=account.username,
            explanation=f"Machine load returned to normal, so the macro on {label} was resumed.",
            run_id=account.macro_run_id,
            macro_id=account.macro_id,
            automatic=True,
        )

    if (
        rules.restart_stuck_macros
        and macro_state == MACRO_STATE_RUNNING
        and account.macro_run_id
        and _measured(account.macro_idle_seconds) is not None
        and float(account.macro_idle_seconds) >= rules.macro_stuck_seconds
    ):
        return RuleDecision(
            action=ACTION_RESTART_MACRO,
            rule=RULE_MACRO_STUCK,
            account_id=account.account_id,
            username=account.username,
            explanation=(
                f"The macro on {label} logged nothing for "
                f"{int(float(account.macro_idle_seconds))}s "
                f"(limit {rules.macro_stuck_seconds}s), so it was restarted."
            ),
            run_id=account.macro_run_id,
            macro_id=account.macro_id,
            automatic=True,
        )

    if account.running and account.disconnected:
        return RuleDecision(
            action=ACTION_RECOMMEND_RESTART_CLIENT,
            rule=RULE_DISCONNECTED,
            account_id=account.account_id,
            username=account.username,
            explanation=(
                f"{label} is disconnected but its client is still open. "
                "Closing a live client needs your confirmation."
            ),
            run_id=account.macro_run_id,
            macro_id=account.macro_id,
            automatic=False,
        )

    runtime = _measured(account.runtime_seconds)
    if account.running and runtime is not None and runtime >= rules.max_runtime_hours * 3_600:
        return RuleDecision(
            action=ACTION_RECOMMEND_RESTART_CLIENT,
            rule=RULE_SESSION_TOO_LONG,
            account_id=account.account_id,
            username=account.username,
            explanation=(
                f"{label} has been running for {runtime / 3_600:.1f}h "
                f"(limit {rules.max_runtime_hours:g}h). Restarting it needs your confirmation."
            ),
            run_id=account.macro_run_id,
            macro_id=account.macro_id,
            automatic=False,
        )
    return None


def automatic_decisions(
    decisions: Iterable[RuleDecision],
) -> tuple[RuleDecision, ...]:
    """Filter the decisions the caller is allowed to apply without a human."""

    return tuple(
        item
        for item in decisions
        if isinstance(item, RuleDecision) and item.automatic and item.action in AUTOMATIC_ACTIONS
    )


def recommendations(
    decisions: Iterable[RuleDecision],
) -> tuple[RuleDecision, ...]:
    """Filter the decisions that must be shown to a human instead of applied."""

    return tuple(
        item
        for item in decisions
        if isinstance(item, RuleDecision) and (not item.automatic or item.action not in AUTOMATIC_ACTIONS)
    )
