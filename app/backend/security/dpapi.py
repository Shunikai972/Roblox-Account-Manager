"""Minimal, explicit Windows DPAPI protection using the current user scope.

There is deliberately no insecure cross-platform fallback.  On systems without
Windows DPAPI callers can detect the capability and keep secret-dependent
features unavailable rather than silently writing secrets in clear text.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
import sys
from typing import Final


CRYPTPROTECT_UI_FORBIDDEN: Final[int] = 0x1


class DPAPIError(RuntimeError):
    """Raised when Windows reports a DPAPI operation failure."""


class DPAPIUnavailableError(DPAPIError):
    """Raised instead of falling back to unencrypted storage off Windows."""


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


@dataclass(frozen=True, slots=True)
class DPAPIStatus:
    """A small capability object useful for a UI or diagnostics page."""

    available: bool
    reason: str | None = None


class CurrentUserDPAPI:
    """Protect byte payloads with Windows DPAPI in **CurrentUser** scope.

    DPAPI's user scoping means an encrypted value is normally usable only by the
    same Windows account.  The class never requests `CRYPTPROTECT_LOCAL_MACHINE`
    and disables UI, so background app operations do not produce credential
    prompts.  Optional entropy is supported for callers that can retain it
    safely; do not derive entropy from a user secret that may be lost.
    """

    def __init__(self) -> None:
        self._crypt32: ctypes.WinDLL | None = None
        self._kernel32: ctypes.WinDLL | None = None
        self._unavailable_reason: str | None = None
        self._initialize()

    def _initialize(self) -> None:
        if os.name != "nt" or sys.platform != "win32":
            self._unavailable_reason = "Windows DPAPI is unavailable on this operating system."
            return
        try:
            crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

            crypt32.CryptProtectData.argtypes = [
                ctypes.POINTER(_DATA_BLOB),
                wintypes.LPCWSTR,
                ctypes.POINTER(_DATA_BLOB),
                wintypes.LPVOID,
                wintypes.LPVOID,
                wintypes.DWORD,
                ctypes.POINTER(_DATA_BLOB),
            ]
            crypt32.CryptProtectData.restype = wintypes.BOOL
            crypt32.CryptUnprotectData.argtypes = [
                ctypes.POINTER(_DATA_BLOB),
                ctypes.POINTER(wintypes.LPWSTR),
                ctypes.POINTER(_DATA_BLOB),
                wintypes.LPVOID,
                wintypes.LPVOID,
                wintypes.DWORD,
                ctypes.POINTER(_DATA_BLOB),
            ]
            crypt32.CryptUnprotectData.restype = wintypes.BOOL
            kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
            kernel32.LocalFree.restype = wintypes.HLOCAL
        except (AttributeError, OSError) as exc:
            self._unavailable_reason = f"Windows DPAPI could not be initialized: {exc.__class__.__name__}."
            return

        self._crypt32 = crypt32
        self._kernel32 = kernel32

    @property
    def status(self) -> DPAPIStatus:
        """Return availability without exposing environment-specific internals."""

        return DPAPIStatus(self.available, self._unavailable_reason)

    @property
    def available(self) -> bool:
        return self._crypt32 is not None and self._kernel32 is not None

    def protect(
        self,
        plaintext: bytes | bytearray | memoryview,
        *,
        description: str = "Roblox Account Manager secret",
        entropy: bytes | bytearray | memoryview | None = None,
    ) -> bytes:
        """Encrypt a bytes-like value using the interactive Windows user's key."""

        crypt32, _ = self._require_available()
        source, source_buffer = _make_blob(_coerce_bytes(plaintext, "plaintext"))
        entropy_blob, entropy_buffer = _make_optional_blob(entropy)
        output = _DATA_BLOB()
        ok = crypt32.CryptProtectData(
            ctypes.byref(source),
            description,
            ctypes.byref(entropy_blob) if entropy_blob is not None else None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output),
        )
        # Keep source/entropy buffers alive through the native call.
        _ = (source_buffer, entropy_buffer)
        if not ok:
            raise self._operation_error("protect")
        return self._copy_and_free(output)

    def unprotect(
        self,
        protected: bytes | bytearray | memoryview,
        *,
        entropy: bytes | bytearray | memoryview | None = None,
    ) -> bytes:
        """Decrypt a DPAPI payload for the same Windows user."""

        crypt32, _ = self._require_available()
        source, source_buffer = _make_blob(_coerce_bytes(protected, "protected"))
        entropy_blob, entropy_buffer = _make_optional_blob(entropy)
        output = _DATA_BLOB()
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(source),
            None,
            ctypes.byref(entropy_blob) if entropy_blob is not None else None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output),
        )
        _ = (source_buffer, entropy_buffer)
        if not ok:
            raise self._operation_error("unprotect")
        return self._copy_and_free(output)

    def try_protect(
        self,
        plaintext: bytes | bytearray | memoryview,
        *,
        description: str = "Roblox Account Manager secret",
        entropy: bytes | bytearray | memoryview | None = None,
    ) -> bytes | None:
        """Return ``None`` when DPAPI is unavailable; propagate real failures."""

        if not self.available:
            return None
        return self.protect(plaintext, description=description, entropy=entropy)

    def try_unprotect(
        self,
        protected: bytes | bytearray | memoryview,
        *,
        entropy: bytes | bytearray | memoryview | None = None,
    ) -> bytes | None:
        """Return ``None`` when DPAPI is unavailable; propagate real failures."""

        if not self.available:
            return None
        return self.unprotect(protected, entropy=entropy)

    def _require_available(self) -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
        if not self.available:
            raise DPAPIUnavailableError(
                self._unavailable_reason
                or "Windows DPAPI is unavailable; refusing an unencrypted fallback."
            )
        # Narrowed by ``available`` above.
        return self._crypt32, self._kernel32  # type: ignore[return-value]

    def _operation_error(self, operation: str) -> DPAPIError:
        code = ctypes.get_last_error()
        return DPAPIError(f"DPAPI {operation} failed (Windows error {code}).")

    def _copy_and_free(self, blob: _DATA_BLOB) -> bytes:
        _, kernel32 = self._require_available()
        try:
            if blob.cbData == 0:
                return b""
            if not blob.pbData:
                raise DPAPIError("DPAPI returned an invalid empty data pointer.")
            return ctypes.string_at(blob.pbData, blob.cbData)
        finally:
            if blob.pbData:
                kernel32.LocalFree(ctypes.cast(blob.pbData, wintypes.HLOCAL))


def _coerce_bytes(value: bytes | bytearray | memoryview, label: str) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise TypeError(f"{label} must be bytes-like.")
    return bytes(value)


def _make_blob(value: bytes) -> tuple[_DATA_BLOB, ctypes.Array[ctypes.c_byte] | None]:
    if not value:
        return _DATA_BLOB(0, None), None
    buffer = (ctypes.c_byte * len(value)).from_buffer_copy(value)
    return _DATA_BLOB(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _make_optional_blob(
    value: bytes | bytearray | memoryview | None,
) -> tuple[_DATA_BLOB | None, ctypes.Array[ctypes.c_byte] | None]:
    if value is None:
        return None, None
    blob, buffer = _make_blob(_coerce_bytes(value, "entropy"))
    return blob, buffer


__all__ = [
    "CRYPTPROTECT_UI_FORBIDDEN",
    "CurrentUserDPAPI",
    "DPAPIError",
    "DPAPIStatus",
    "DPAPIUnavailableError",
]
