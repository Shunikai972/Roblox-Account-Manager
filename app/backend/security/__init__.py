"""Local security primitives: DPAPI storage and log redaction."""

from .dpapi import DPAPIError, DPAPIUnavailableError, CurrentUserDPAPI
from .redaction import redact_mapping, redact_text
from .vault import DPAPISecretVault, SecretVaultError

__all__ = [
    "CurrentUserDPAPI",
    "DPAPIError",
    "DPAPIUnavailableError",
    "redact_mapping",
    "redact_text",
    "DPAPISecretVault",
    "SecretVaultError",
]
