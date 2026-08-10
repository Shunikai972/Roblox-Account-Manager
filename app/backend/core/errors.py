"""Stable application errors that can safely cross the UI bridge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class AppError(Exception):
    """Base error with an end-user-safe message and a stable code."""

    message: str
    code: str = "app_error"
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class ValidationError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code="validation_error", details=details)


class NotFoundError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code="not_found", details=details)


class ConflictError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code="conflict", details=details)


class SecurityError(AppError):
    def __init__(self, message: str = "Cette opération n'est pas autorisée.") -> None:
        super().__init__(message=message, code="security_error")


class ExternalServiceError(AppError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message=message, code="external_service_error", details={"retryable": retryable})


class StorageError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code="storage_error", details=details)


class MigrationError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code="migration_error", details=details)

