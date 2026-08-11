"""Safe, bridge-friendly errors for Roblox operations.

These exceptions intentionally never retain response bodies, request headers,
or URLs.  Those values can contain a session cookie when an HTTP library or a
proxy includes diagnostic context in an exception message.
"""

from __future__ import annotations

from app.backend.core.errors import AppError, ExternalServiceError


class RobloxServiceError(ExternalServiceError):
    """A sanitized failure from a Roblox HTTP endpoint."""

    def __init__(
        self,
        message: str = "Roblox service is currently unavailable.",
        *,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message, retryable=retryable)
        # Status is useful for UI retry affordances and has no secret value.
        if status_code is not None:
            self.details = {**(self.details or {}), "status_code": status_code}


class RobloxAuthenticationError(RobloxServiceError):
    """The locally held session is absent, expired, or unauthorized."""

    def __init__(self) -> None:
        super().__init__(
            "Roblox session must be reconnected.", retryable=False, status_code=401
        )
        self.code = "roblox_authentication_error"


class RobloxLaunchError(AppError):
    """Windows could not hand off an experience URI to Roblox."""

    def __init__(self, message: str) -> None:
        super().__init__(message=message, code="roblox_launch_error")


class RobloxUwpError(AppError):
    """A sanitized failure while discovering or launching a Roblox UWP app."""

    def __init__(self, message: str) -> None:
        super().__init__(message=message, code="roblox_uwp_error")


class ProcessMonitorError(AppError):
    """A safe failure while inspecting or terminating a local Roblox process."""

    def __init__(self, message: str, *, code: str = "process_monitor_error") -> None:
        super().__init__(message=message, code=code)


__all__ = [
    "ProcessMonitorError",
    "RobloxAuthenticationError",
    "RobloxLaunchError",
    "RobloxServiceError",
    "RobloxUwpError",
]
