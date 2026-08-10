"""A small DPAPI-backed vault layered over the opaque repository blob store."""

from __future__ import annotations

from typing import Protocol

from .dpapi import CurrentUserDPAPI, DPAPIUnavailableError


class ProtectedSecretRepository(Protocol):
    """Minimal persistence interface required by :class:`DPAPISecretVault`."""

    def save_protected_secret(self, account_id: str, secret_kind: str, protected_blob: bytes) -> None: ...

    def load_protected_secret(self, account_id: str, secret_kind: str) -> bytes | None: ...

    def has_protected_secret(self, account_id: str, secret_kind: str = "session") -> bool: ...

    def delete_protected_secret(self, account_id: str, secret_kind: str) -> bool: ...


class SecretVaultError(RuntimeError):
    """Raised without embedding secret material in the failure message."""


class DPAPISecretVault:
    """Store session/password bytes only after CurrentUser DPAPI protection.

    The vault's retrieval method is intended for backend services that need a
    short-lived credential to execute an explicitly requested local action.  It
    must never be wired directly to a pywebview/API response.
    """

    def __init__(self, repository: ProtectedSecretRepository, dpapi: CurrentUserDPAPI | None = None) -> None:
        self._repository = repository
        self._dpapi = dpapi or CurrentUserDPAPI()

    @property
    def available(self) -> bool:
        return self._dpapi.available

    def store(self, account_id: str, secret_kind: str, secret: bytes | bytearray | memoryview) -> None:
        if not self.available:
            raise DPAPIUnavailableError("A Windows CurrentUser DPAPI vault is required for secret import.")
        if not isinstance(secret, (bytes, bytearray, memoryview)) or not secret:
            raise SecretVaultError("Secret material must be a non-empty bytes-like value.")
        kind = _validate_kind(secret_kind)
        try:
            protected = self._dpapi.protect(
                bytes(secret), description=f"Astro Account Manager {kind}"
            )
            self._repository.save_protected_secret(account_id, kind, protected)
        except (DPAPIUnavailableError, SecretVaultError):
            raise
        except Exception as exc:
            raise SecretVaultError("Could not persist the protected secret.") from exc

    def retrieve(self, account_id: str, secret_kind: str) -> bytes | None:
        """Decrypt a secret for a trusted backend caller; never log its value."""

        kind = _validate_kind(secret_kind)
        protected = self._repository.load_protected_secret(account_id, kind)
        if protected is None:
            return None
        if not self.available:
            raise DPAPIUnavailableError("The Windows DPAPI vault is unavailable for this user.")
        try:
            return self._dpapi.unprotect(protected)
        except DPAPIUnavailableError:
            raise
        except Exception as exc:
            raise SecretVaultError("Could not decrypt the protected secret for this Windows user.") from exc

    def has(self, account_id: str, secret_kind: str = "session") -> bool:
        return self._repository.has_protected_secret(account_id, _validate_kind(secret_kind))

    def delete(self, account_id: str, secret_kind: str) -> bool:
        return self._repository.delete_protected_secret(account_id, _validate_kind(secret_kind))


def _validate_kind(value: str) -> str:
    kind = str(value).strip().lower()
    if kind not in {"session", "saved_password"}:
        raise SecretVaultError("Unsupported secret kind.")
    return kind


__all__ = ["DPAPISecretVault", "ProtectedSecretRepository", "SecretVaultError"]
