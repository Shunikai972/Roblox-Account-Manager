"""Domain models for Nexus controlled accounts and settings."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class AccountControlSettings:
    """Persisted control settings for an account."""

    account_id: str
    username: str
    auto_relaunch: bool = False
    target_place_id: int | None = None
    target_job_id: str | None = None
    custom_script: str | None = None
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "username": self.username,
            "auto_relaunch": self.auto_relaunch,
            "target_place_id": self.target_place_id,
            "target_job_id": self.target_job_id,
            "custom_script": self.custom_script,
            "updated_at": self.updated_at,
        }


@dataclass
class ControlledAccount:
    """Live state of a connected Roblox client account over WebSocket."""

    username: str
    user_id: int | None = None
    job_id: str | None = None
    place_id: int | None = None
    status: str = "Online"  # "Online" | "Offline"
    connected_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_ping_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    auto_relaunch: bool = False
    logs: list[str] = field(default_factory=list)
    max_logs: int = 100

    def add_log(self, message: str) -> None:
        timestamp = datetime.now(UTC).strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        self.logs.append(entry)
        if len(self.logs) > self.max_logs:
            self.logs = self.logs[-self.max_logs:]

    def to_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "user_id": self.user_id,
            "job_id": self.job_id,
            "place_id": self.place_id,
            "status": self.status,
            "connected_at": self.connected_at,
            "last_ping_at": self.last_ping_at,
            "auto_relaunch": self.auto_relaunch,
            "log_count": len(self.logs),
            "recent_logs": self.logs[-20:],
        }
