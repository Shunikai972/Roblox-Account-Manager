"""Pure resource policy: adaptive FPS, RAM watchdog and capacity estimate.

Twelve idle clients rendering at 60 FPS burn a GPU for nothing. The useful
policy is simple: the window you are watching deserves frames, a window running
a macro needs just enough to stay responsive, and an idle window needs almost
none.

One honest limitation is baked into the design. The FPS cap Astro can actually
write is a **global** Roblox client setting, not a per-window one, so this
module computes a single *applied* cap from the most demanding window and keeps
the per-window numbers as advice the UI can display. Pretending otherwise
would mean silently capping the window you are actively playing.

Nothing here reads psutil, the clock or the disk: the caller measures, this
module decides.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.backend.core.errors import ValidationError

MIN_FPS = 5
MAX_FPS = 240
DEFAULT_WATCHED_FPS = 60
DEFAULT_MACRO_FPS = 20
DEFAULT_IDLE_FPS = 5

MIN_PERCENT = 50
MAX_PERCENT = 99
DEFAULT_WARN_PERCENT = 85
DEFAULT_CRITICAL_PERCENT = 93

# Windows itself needs headroom; refusing to plan below it avoids the swap
# death-spiral that looks like a frozen farm.
MIN_RESERVE_MB = 512
MAX_RESERVE_MB = 16_384
DEFAULT_RESERVE_MB = 2_048

# A Roblox client sits around 1.0-1.5 GB once in game.
MIN_INSTANCE_MB = 200
MAX_INSTANCE_MB = 8_000
DEFAULT_INSTANCE_MB = 1_200

MAX_PLANNED_INSTANCES = 64
MAX_ID_CHARS = 128
BYTES_PER_MB = 1_048_576

PROFILE_WATCHED = "watched"
PROFILE_MACRO = "macro"
PROFILE_IDLE = "idle"

LEVEL_OK = "ok"
LEVEL_WARN = "warn"
LEVEL_CRITICAL = "critical"

ACTION_NONE = "none"
ACTION_PAUSE_LAUNCHES = "pause_launches"
ACTION_RECOMMEND_CLOSE = "recommend_close"


@dataclass(frozen=True, slots=True)
class InstanceFacts:
    """What the caller measured about one Roblox window."""

    pid: int
    account_id: str | None = None
    username: str = ""
    watched: bool = False
    macro_running: bool = False
    memory_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class MachineFacts:
    """What the caller measured about the machine."""

    cpu_percent: float | None = None
    memory_percent: float | None = None
    total_bytes: int | None = None
    available_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class ResourceSettings:
    """Bounded resource configuration. Adaptive FPS is off by default."""

    adaptive_fps_enabled: bool = False
    watched_fps: int = DEFAULT_WATCHED_FPS
    macro_fps: int = DEFAULT_MACRO_FPS
    idle_fps: int = DEFAULT_IDLE_FPS
    memory_warn_percent: int = DEFAULT_WARN_PERCENT
    memory_critical_percent: int = DEFAULT_CRITICAL_PERCENT
    reserve_mb: int = DEFAULT_RESERVE_MB
    average_instance_mb: int = DEFAULT_INSTANCE_MB

    def to_dict(self) -> dict[str, Any]:
        return {
            "adaptive_fps_enabled": self.adaptive_fps_enabled,
            "watched_fps": self.watched_fps,
            "macro_fps": self.macro_fps,
            "idle_fps": self.idle_fps,
            "memory_warn_percent": self.memory_warn_percent,
            "memory_critical_percent": self.memory_critical_percent,
            "reserve_mb": self.reserve_mb,
            "average_instance_mb": self.average_instance_mb,
        }


@dataclass(frozen=True, slots=True)
class InstanceTarget:
    """The profile one window should be running at."""

    pid: int
    account_id: str | None
    username: str
    profile: str
    target_fps: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "account_id": self.account_id,
            "username": self.username,
            "profile": self.profile,
            "target_fps": self.target_fps,
        }


@dataclass(frozen=True, slots=True)
class ResourcePlan:
    """Adaptive FPS decision, watchdog verdict and capacity estimate."""

    targets: tuple[InstanceTarget, ...]
    applied_fps: int | None
    applied_reason: str
    level: str
    message: str
    action: str
    instance_count: int
    estimated_additional_instances: int | None
    measured_instance_bytes: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "targets": [target.to_dict() for target in self.targets],
            "applied_fps": self.applied_fps,
            "applied_reason": self.applied_reason,
            "level": self.level,
            "message": self.message,
            "action": self.action,
            "instance_count": self.instance_count,
            "estimated_additional_instances": self.estimated_additional_instances,
            "measured_instance_bytes": self.measured_instance_bytes,
            # The cap Roblox exposes is global, so the UI must not promise a
            # different frame rate per window.
            "per_window_fps_supported": False,
        }


def _bounded_int(value: Any, *, minimum: int, maximum: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{label} is invalid.")
    number = int(value)
    if number < minimum or number > maximum:
        raise ValidationError(f"{label} must be between {minimum} and {maximum}.")
    return number


def _bounded_bool(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{label} is invalid.")
    return value


def validated_resource_settings(
    value: Any, *, existing: ResourceSettings | None = None
) -> ResourceSettings:
    """Return bounded resource settings, refusing anything out of range."""

    base = existing or ResourceSettings()
    if value is None:
        return base
    if not isinstance(value, Mapping):
        raise ValidationError("Resource settings are invalid.")

    def pick(key: str, fallback: Any) -> Any:
        return value.get(key, fallback)

    settings = ResourceSettings(
        adaptive_fps_enabled=_bounded_bool(
            pick("adaptive_fps_enabled", base.adaptive_fps_enabled),
            label="The adaptive frame rate state",
        ),
        watched_fps=_bounded_int(
            pick("watched_fps", base.watched_fps),
            minimum=MIN_FPS,
            maximum=MAX_FPS,
            label="The watched window frame rate",
        ),
        macro_fps=_bounded_int(
            pick("macro_fps", base.macro_fps),
            minimum=MIN_FPS,
            maximum=MAX_FPS,
            label="The macro window frame rate",
        ),
        idle_fps=_bounded_int(
            pick("idle_fps", base.idle_fps),
            minimum=MIN_FPS,
            maximum=MAX_FPS,
            label="The idle window frame rate",
        ),
        memory_warn_percent=_bounded_int(
            pick("memory_warn_percent", base.memory_warn_percent),
            minimum=MIN_PERCENT,
            maximum=MAX_PERCENT,
            label="The memory warning threshold",
        ),
        memory_critical_percent=_bounded_int(
            pick("memory_critical_percent", base.memory_critical_percent),
            minimum=MIN_PERCENT,
            maximum=MAX_PERCENT,
            label="The memory critical threshold",
        ),
        reserve_mb=_bounded_int(
            pick("reserve_mb", base.reserve_mb),
            minimum=MIN_RESERVE_MB,
            maximum=MAX_RESERVE_MB,
            label="The reserved memory",
        ),
        average_instance_mb=_bounded_int(
            pick("average_instance_mb", base.average_instance_mb),
            minimum=MIN_INSTANCE_MB,
            maximum=MAX_INSTANCE_MB,
            label="The expected memory per instance",
        ),
    )
    if settings.memory_critical_percent < settings.memory_warn_percent:
        raise ValidationError(
            "The memory critical threshold must be at or above the warning threshold."
        )
    return settings


def _text(value: Any, *, limit: int = MAX_ID_CHARS) -> str:
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = int(value)
    return number if number > 0 else None


def _percent(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number < 0.0 or number > 100.0:
        return None
    return number


def _measured_instance_bytes(instances: Sequence[InstanceFacts]) -> int | None:
    samples = [
        int(instance.memory_bytes)
        for instance in instances
        if _positive_int(instance.memory_bytes) is not None
    ]
    if not samples:
        return None
    return int(sum(samples) / len(samples))


def estimated_capacity(
    *, machine: MachineFacts, settings: ResourceSettings, measured_bytes: int | None
) -> int | None:
    """How many more clients plausibly fit, or None when unmeasurable.

    Uses the machine's own measured average when available, because a fixed
    guess is wrong on every machine.
    """

    available = _positive_int(machine.available_bytes)
    if available is None:
        return None
    per_instance = measured_bytes or settings.average_instance_mb * BYTES_PER_MB
    if per_instance <= 0:
        return None
    usable = available - settings.reserve_mb * BYTES_PER_MB
    if usable <= 0:
        return 0
    return max(0, int(usable // per_instance))


def _target_for(instance: InstanceFacts, settings: ResourceSettings) -> InstanceTarget:
    if instance.watched:
        profile, fps = PROFILE_WATCHED, settings.watched_fps
    elif instance.macro_running:
        profile, fps = PROFILE_MACRO, settings.macro_fps
    else:
        profile, fps = PROFILE_IDLE, settings.idle_fps
    return InstanceTarget(
        pid=instance.pid,
        account_id=_text(instance.account_id) or None,
        username=_text(instance.username, limit=120),
        profile=profile,
        target_fps=fps,
    )


def _watchdog(
    *, machine: MachineFacts, settings: ResourceSettings, instance_count: int
) -> tuple[str, str, str]:
    memory = _percent(machine.memory_percent)
    if memory is None:
        return (
            LEVEL_OK,
            "Memory use is not measurable on this machine, so the watchdog stays quiet.",
            ACTION_NONE,
        )
    if memory >= settings.memory_critical_percent:
        return (
            LEVEL_CRITICAL,
            (
                f"Memory use is at {memory:.0f}% with {instance_count} client(s) open "
                f"(critical at {settings.memory_critical_percent}%). Close a client "
                "before launching anything else."
            ),
            ACTION_RECOMMEND_CLOSE,
        )
    if memory >= settings.memory_warn_percent:
        return (
            LEVEL_WARN,
            (
                f"Memory use is at {memory:.0f}% (warning at "
                f"{settings.memory_warn_percent}%). New launches are held back."
            ),
            ACTION_PAUSE_LAUNCHES,
        )
    return (
        LEVEL_OK,
        f"Memory use is at {memory:.0f}%, within limits.",
        ACTION_NONE,
    )


def plan_resources(
    *,
    instances: Sequence[InstanceFacts] | None = None,
    machine: MachineFacts | None = None,
    settings: ResourceSettings | None = None,
) -> ResourcePlan:
    """Decide frame rates, the watchdog verdict and the remaining capacity."""

    config = settings or ResourceSettings()
    facts = MachineFacts() if machine is None else machine
    windows = [
        instance
        for instance in (instances or ())
        if isinstance(instance, InstanceFacts) and _positive_int(instance.pid) is not None
    ][:MAX_PLANNED_INSTANCES]

    targets = tuple(_target_for(instance, config) for instance in windows)
    measured = _measured_instance_bytes(windows)
    level, message, action = _watchdog(
        machine=facts, settings=config, instance_count=len(windows)
    )

    applied: int | None = None
    if not config.adaptive_fps_enabled:
        reason = "Adaptive frame rate is off, so Roblox keeps its own cap."
    elif not targets:
        reason = "No Roblox window is open, so there is nothing to cap."
    else:
        # The cap is global: take the most demanding window so the one you are
        # actually looking at is never throttled.
        applied = max(target.target_fps for target in targets)
        winner = next(target for target in targets if target.target_fps == applied)
        reason = (
            f"Roblox caps frames globally, so the cap follows the most demanding "
            f"window ({winner.profile}) at {applied} FPS."
        )

    return ResourcePlan(
        targets=targets,
        applied_fps=applied,
        applied_reason=reason,
        level=level,
        message=message,
        action=action,
        instance_count=len(windows),
        estimated_additional_instances=estimated_capacity(
            machine=facts, settings=config, measured_bytes=measured
        ),
        measured_instance_bytes=measured,
    )
