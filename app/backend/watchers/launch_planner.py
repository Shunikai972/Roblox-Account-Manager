"""Pure planning for the smart launcher.

Ten clients booting at the same instant is what actually kills a machine: each
Roblox start spikes CPU and disk, so twenty simultaneous boots make the whole
desktop unusable and half the clients time out. This module answers one
question -- in which order, in which wave, and after how many seconds should
each account start -- and it answers it without touching the process table, the
clock, or the launcher itself.

That keeps the policy unit-testable off Windows, where the real launcher cannot
run at all. Nothing here launches anything: :class:`ApplicationService` owns
every side effect.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from app.backend.core.errors import ValidationError

# How many clients may be booting at the same time.  Above ten, staggering
# stops helping: the disk becomes the bottleneck.
MIN_CONCURRENT_LAUNCHES = 1
MAX_CONCURRENT_LAUNCHES = 10
DEFAULT_CONCURRENT_LAUNCHES = 3

# Roblox needs a couple of seconds before its window even appears, so a delay
# below half a second is indistinguishable from launching everything at once.
MIN_LAUNCH_DELAY_SECONDS = 0.5
MAX_LAUNCH_DELAY_SECONDS = 300.0
DEFAULT_LAUNCH_DELAY_SECONDS = 4.0

# A single plan stays reviewable, and the UI stays honest about what it will do.
MAX_PLANNED_ACCOUNTS = 50
MAX_ID_CHARS = 128

SKIP_INVALID = "invalid"
SKIP_DUPLICATE = "duplicate"
SKIP_ALREADY_RUNNING = "already_running"
SKIP_OVER_LIMIT = "over_limit"


@dataclass(frozen=True, slots=True)
class LaunchStep:
    """One account, its wave, and when it should start."""

    account_id: str
    username: str
    wave: int
    position: int
    start_after_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "username": self.username,
            "wave": self.wave,
            "position": self.position,
            "start_after_seconds": self.start_after_seconds,
        }


@dataclass(frozen=True, slots=True)
class SkippedAccount:
    """An account the plan deliberately leaves alone, and why."""

    account_id: str
    username: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "username": self.username,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class LaunchPlan:
    """A complete, reviewable launch schedule."""

    steps: tuple[LaunchStep, ...]
    skipped: tuple[SkippedAccount, ...]
    max_concurrent: int
    delay_seconds: float
    running_before: int

    @property
    def waves(self) -> int:
        return 0 if not self.steps else self.steps[-1].wave + 1

    @property
    def estimated_seconds(self) -> float:
        """Rough wall-clock length of the whole schedule.

        It is an estimate on purpose: how long a client takes to reach the
        login screen depends on the machine, so the launcher waits for real
        observations rather than trusting this number.
        """

        if not self.steps:
            return 0.0
        return round(self.steps[-1].start_after_seconds + self.delay_seconds, 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": [step.to_dict() for step in self.steps],
            "skipped": [item.to_dict() for item in self.skipped],
            "max_concurrent": self.max_concurrent,
            "delay_seconds": self.delay_seconds,
            "running_before": self.running_before,
            "waves": self.waves,
            "planned": len(self.steps),
            "estimated_seconds": self.estimated_seconds,
        }


@dataclass(frozen=True, slots=True)
class LauncherSettings:
    """Bounded smart-launcher configuration."""

    max_concurrent: int = DEFAULT_CONCURRENT_LAUNCHES
    delay_seconds: float = DEFAULT_LAUNCH_DELAY_SECONDS
    wait_for_wave: bool = True
    skip_running: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_concurrent": self.max_concurrent,
            "delay_seconds": self.delay_seconds,
            "wait_for_wave": self.wait_for_wave,
            "skip_running": self.skip_running,
        }


def _bounded_int(value: Any, *, minimum: int, maximum: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{label} is invalid.")
    number = int(value)
    if number < minimum or number > maximum:
        raise ValidationError(f"{label} must be between {minimum} and {maximum}.")
    return number


def _bounded_float(value: Any, *, minimum: float, maximum: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{label} is invalid.")
    number = round(float(value), 3)
    if number < minimum or number > maximum:
        raise ValidationError(f"{label} must be between {minimum:g} and {maximum:g}.")
    return number


def _bounded_bool(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{label} is invalid.")
    return value


def validated_launcher_settings(
    value: Any, *, existing: LauncherSettings | None = None
) -> LauncherSettings:
    """Return bounded launcher settings, refusing anything out of range."""

    base = existing or LauncherSettings()
    if value is None:
        return base
    if not isinstance(value, Mapping):
        raise ValidationError("Launcher settings are invalid.")

    def pick(key: str, fallback: Any) -> Any:
        return value.get(key, fallback)

    return LauncherSettings(
        max_concurrent=_bounded_int(
            pick("max_concurrent", base.max_concurrent),
            minimum=MIN_CONCURRENT_LAUNCHES,
            maximum=MAX_CONCURRENT_LAUNCHES,
            label="The number of simultaneous launches",
        ),
        delay_seconds=_bounded_float(
            pick("delay_seconds", base.delay_seconds),
            minimum=MIN_LAUNCH_DELAY_SECONDS,
            maximum=MAX_LAUNCH_DELAY_SECONDS,
            label="The delay between launches",
        ),
        wait_for_wave=_bounded_bool(
            pick("wait_for_wave", base.wait_for_wave),
            label="The wait between waves option",
        ),
        skip_running=_bounded_bool(
            pick("skip_running", base.skip_running),
            label="The skip running accounts option",
        ),
    )


def _text(value: Any, *, limit: int = MAX_ID_CHARS) -> str:
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _running_ids(value: Iterable[Any] | None) -> frozenset[str]:
    if not value:
        return frozenset()
    return frozenset(
        identifier for identifier in (_text(item) for item in value) if identifier
    )


def plan_launches(
    *,
    accounts: Sequence[Mapping[str, Any]],
    running_account_ids: Iterable[Any] | None = None,
    settings: LauncherSettings | None = None,
    limit: int = MAX_PLANNED_ACCOUNTS,
) -> LaunchPlan:
    """Spread *accounts* into staggered waves.

    ``accounts`` order is respected: the caller decides priority (group order,
    favourites, custom priority), because the machine cannot.

    Every account that will *not* be launched is reported in ``skipped`` with a
    reason, so the UI never silently drops a request.
    """

    config = settings or LauncherSettings()
    running = _running_ids(running_account_ids)
    ceiling = max(0, min(int(limit), MAX_PLANNED_ACCOUNTS))

    steps: list[LaunchStep] = []
    skipped: list[SkippedAccount] = []
    seen: set[str] = set()
    wave_size = config.max_concurrent

    for entry in accounts or ():
        if not isinstance(entry, Mapping):
            skipped.append(SkippedAccount("", "", SKIP_INVALID))
            continue
        account_id = _text(entry.get("account_id") or entry.get("id"))
        username = _text(entry.get("username") or entry.get("name"), limit=120)
        if not account_id:
            skipped.append(SkippedAccount("", username, SKIP_INVALID))
            continue
        if account_id in seen:
            skipped.append(SkippedAccount(account_id, username, SKIP_DUPLICATE))
            continue
        seen.add(account_id)
        if config.skip_running and account_id in running:
            skipped.append(SkippedAccount(account_id, username, SKIP_ALREADY_RUNNING))
            continue
        if len(steps) >= ceiling:
            skipped.append(SkippedAccount(account_id, username, SKIP_OVER_LIMIT))
            continue
        index = len(steps)
        wave, position = divmod(index, wave_size)
        # Inside a wave every client gets ``delay`` to settle; a wave is done
        # once all of its clients have had that much time.
        offset = (wave * wave_size + position) * config.delay_seconds
        steps.append(
            LaunchStep(
                account_id=account_id,
                username=username,
                wave=wave,
                position=position,
                start_after_seconds=round(offset, 3),
            )
        )

    return LaunchPlan(
        steps=tuple(steps),
        skipped=tuple(skipped),
        max_concurrent=config.max_concurrent,
        delay_seconds=config.delay_seconds,
        running_before=len(running),
    )
