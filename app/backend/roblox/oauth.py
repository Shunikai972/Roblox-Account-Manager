"""Official Roblox OAuth 2.0 + PKCE primitives for desktop identity linking.

This module deliberately models the documented Open Cloud OAuth flow rather
than a browser cookie.  It can associate an authenticated Roblox identity with
an Astro Account Manager account and retain the Open Cloud grant in a Windows DPAPI vault,
but it does *not* create, read, export, or inject a Roblox game-client session.

The flow is designed for a desktop application:

* the system browser handles the Roblox sign-in and consent screens;
* a short-lived HTTP receiver listens only on ``127.0.0.1`` for the registered
  callback URI;
* PKCE state and verifier values stay in the Python process and are never sent
  through pywebview;
* OAuth access/refresh tokens are only ever represented by backend-only value
  objects and persisted as a single DPAPI-protected vault blob.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol
from urllib.parse import parse_qs, urlencode, urlsplit
import webbrowser

import requests

from app.backend.core.errors import ExternalServiceError, SecurityError, ValidationError
from app.backend.security.dpapi import DPAPIError, DPAPIUnavailableError


OAUTH_AUTHORIZE_URL = "https://apis.roblox.com/oauth/v1/authorize"
OAUTH_TOKEN_URL = "https://apis.roblox.com/oauth/v1/token"
OAUTH_USERINFO_URL = "https://apis.roblox.com/oauth/v1/userinfo"
OAUTH_GRANT_KIND = "oauth_grant"
DEFAULT_SCOPES = ("openid", "profile")
DEFAULT_CALLBACK_TIMEOUT_SECONDS = 300


class OAuthConfigurationError(ValidationError):
    """Raised when local OAuth configuration cannot form a safe desktop flow."""


class OAuthFlowError(ExternalServiceError):
    """A sanitized failure from the Roblox OAuth endpoints or callback flow."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message, retryable=retryable)
        self.code = "roblox_oauth_error"


@dataclass(frozen=True, slots=True)
class OAuthClientConfiguration:
    """Non-secret configuration registered in the Roblox credentials dashboard.

    The app intentionally supports only an IPv4 loopback callback.  That gives
    the desktop process a verifiable receiver and avoids sending callbacks to
    an arbitrary LAN or Internet listener.  The exact URI, including port and
    path, must be registered for the Roblox OAuth application.
    """

    client_id: str
    redirect_uri: str
    callback_timeout_seconds: int = DEFAULT_CALLBACK_TIMEOUT_SECONDS
    scopes: tuple[str, ...] = DEFAULT_SCOPES

    def __post_init__(self) -> None:
        client_id = self.client_id.strip() if isinstance(self.client_id, str) else ""
        if not client_id.isdecimal() or len(client_id) > 80:
            raise OAuthConfigurationError("Roblox OAuth client ID is invalid.")
        object.__setattr__(self, "client_id", client_id)

        _validate_loopback_redirect_uri(self.redirect_uri)
        if not isinstance(self.callback_timeout_seconds, int) or not 60 <= self.callback_timeout_seconds <= 900:
            raise OAuthConfigurationError("OAuth login timeout must be between 60 and 900 seconds.")

        normalized_scopes = tuple(str(scope).strip() for scope in self.scopes)
        if normalized_scopes != DEFAULT_SCOPES:
            raise OAuthConfigurationError("This version requires openid and profile OAuth permissions.")
        object.__setattr__(self, "scopes", normalized_scopes)


@dataclass(frozen=True, slots=True)
class OAuthIdentity:
    """Public identity returned by ``/userinfo``; it contains no credential."""

    user_id: int
    username: str
    display_name: str | None = None
    avatar_url: str | None = None


@dataclass(frozen=True, slots=True)
class OAuthGrant:
    """Backend-only OAuth tokens with a deliberately redacted representation."""

    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_at: datetime
    scopes: tuple[str, ...]
    id_token: str | None = field(default=None, repr=False)

    def __repr__(self) -> str:
        return (
            "OAuthGrant(access_token=[REDACTED], refresh_token=[REDACTED], "
            f"expires_at={self.expires_at.isoformat()!r}, scopes={self.scopes!r}, "
            "id_token=[REDACTED])"
        )


@dataclass(frozen=True, slots=True)
class OAuthAuthorizationAttempt:
    """Private state generated before opening the browser."""

    operation_id: str
    state: str = field(repr=False)
    nonce: str = field(repr=False)
    code_verifier: str = field(repr=False)
    authorization_url: str = field(repr=False)
    created_monotonic: float = field(repr=False)
    expires_at: str = field(repr=False)

    def __repr__(self) -> str:
        return f"OAuthAuthorizationAttempt(operation_id={self.operation_id!r}, [REDACTED])"


@dataclass(frozen=True, slots=True)
class OAuthLoginSnapshot:
    """The only login-status object suitable for the bridge/frontend."""

    operation_id: str
    status: str
    expires_at: str | None = None
    message: str | None = None

    def as_public_dict(self) -> dict[str, str | None]:
        return {
            "operation_id": self.operation_id,
            "status": self.status,
            "expires_at": self.expires_at,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class OAuthLoginCompletion:
    """Private completed flow passed from the coordinator to the service layer."""

    snapshot: OAuthLoginSnapshot
    identity: OAuthIdentity
    grant: OAuthGrant = field(repr=False)

    def __repr__(self) -> str:
        return f"OAuthLoginCompletion(snapshot={self.snapshot!r}, identity={self.identity!r}, grant=[REDACTED])"


@dataclass(frozen=True, slots=True)
class OAuthCallback:
    """Minimal callback values captured on loopback; not frontend-facing."""

    state: str = field(repr=False)
    code: str | None = field(default=None, repr=False)
    error: str | None = None


class _CallbackReceiver(Protocol):
    def start(self) -> None: ...

    def poll(self) -> OAuthCallback | None: ...

    def close(self) -> None: ...


CallbackReceiverFactory = Callable[[str, str], _CallbackReceiver]
BrowserOpener = Callable[[str], bool | None]
MonotonicClock = Callable[[], float]
WallClock = Callable[[], datetime]


class OAuthLoopbackCallbackServer:
    """One-shot callback receiver bound exclusively to ``127.0.0.1``.

    ``BaseHTTPRequestHandler`` normally writes the complete request URL to a
    log.  Its logger is overridden because the query contains a short-lived
    authorization code, which must not enter terminal/log files.
    """

    def __init__(self, redirect_uri: str, expected_state: str) -> None:
        parsed = _validate_loopback_redirect_uri(redirect_uri)
        if not _is_bounded_text(expected_state, maximum=256):
            raise OAuthConfigurationError("Local OAuth state is invalid.")
        self._path = parsed.path
        self._expected_state = expected_state
        self._lock = threading.RLock()
        self._callback: OAuthCallback | None = None
        self._closed = False
        self._started = False
        self._server = _LoopbackServer(("127.0.0.1", parsed.port or 0), self._handler_type())
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="astro-oauth-callback",
            daemon=True,
        )

    def _handler_type(self) -> type[BaseHTTPRequestHandler]:
        receiver = self

        class CallbackHandler(BaseHTTPRequestHandler):
            server_version = "AstroAccountManagerOAuth"
            sys_version = ""

            def do_GET(self) -> None:  # noqa: N802 - required HTTP handler spelling
                receiver._handle_get(self)

            def do_POST(self) -> None:  # noqa: N802 - required HTTP handler spelling
                receiver._respond(self, HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

            def log_message(self, _format: str, *_args: object) -> None:
                # Never serialize callback URLs, authorization codes, or state.
                return

        return CallbackHandler

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise OAuthFlowError("OAuth callback receiver is closed.")
            if self._started:
                return
            self._started = True
            self._thread.start()

    def poll(self) -> OAuthCallback | None:
        with self._lock:
            callback = self._callback
            self._callback = None
            return callback

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            started = self._started
        if started:
            self._server.shutdown()
            self._thread.join(timeout=2)
        self._server.server_close()

    def _handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlsplit(handler.path)
        if parsed.path != self._path:
            self._respond(handler, HTTPStatus.NOT_FOUND, "Not found")
            return
        try:
            query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
        except ValueError:
            self._respond(handler, HTTPStatus.BAD_REQUEST, "Invalid callback")
            return

        state = _single_query_value(query, "state", maximum=256)
        code = _single_query_value(query, "code", maximum=4096)
        error = _single_query_value(query, "error", maximum=120)
        if state is None or not hmac.compare_digest(state, self._expected_state):
            self._respond(handler, HTTPStatus.BAD_REQUEST, "Invalid callback")
            return
        if bool(code) == bool(error):
            self._respond(handler, HTTPStatus.BAD_REQUEST, "Invalid callback")
            return

        with self._lock:
            if self._closed or self._callback is not None:
                self._respond(handler, HTTPStatus.CONFLICT, "Callback already received")
                return
            self._callback = OAuthCallback(state=state, code=code, error=error)

        if error:
            self._respond(handler, HTTPStatus.OK, "Connection was not completed. You may return to Astro Account Manager.")
        else:
            self._respond(handler, HTTPStatus.OK, "Connection received. You may return to Astro Account Manager.")

    @staticmethod
    def _respond(handler: BaseHTTPRequestHandler, status: HTTPStatus, message: str) -> None:
        content = (
            "<!doctype html><html><head><meta charset=\"utf-8\"><title>Astro Account Manager</title>"
            "</head><body><p>" + message + "</p></body></html>"
        ).encode("utf-8")
        handler.send_response(status.value)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(content)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
        handler.end_headers()
        handler.wfile.write(content)


class _LoopbackServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class RobloxOAuthClient:
    """Typed HTTPS calls for the official Roblox OAuth PKCE endpoints."""

    def __init__(
        self,
        *,
        http: requests.Session | Any | None = None,
        timeout_seconds: float = 15.0,
        now: WallClock | None = None,
    ) -> None:
        if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise OAuthConfigurationError("OAuth timeout must be positive.")
        self._http = http or requests.Session()
        self._timeout_seconds = float(timeout_seconds)
        self._now = now or (lambda: datetime.now(UTC))
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        closer = getattr(self._http, "close", None)
        if callable(closer):
            closer()

    def build_authorization_attempt(
        self, config: OAuthClientConfiguration, *, monotonic_now: float
    ) -> OAuthAuthorizationAttempt:
        self._ensure_open()
        verifier = _make_code_verifier()
        challenge = _pkce_challenge(verifier)
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(24)
        operation_id = secrets.token_urlsafe(18)
        parameters = {
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "scope": " ".join(config.scopes),
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "nonce": nonce,
            # Explicit selection helps when the system browser is already
            # signed in to another Roblox identity.
            "prompt": "select_account",
        }
        return OAuthAuthorizationAttempt(
            operation_id=operation_id,
            state=state,
            nonce=nonce,
            code_verifier=verifier,
            authorization_url=f"{OAUTH_AUTHORIZE_URL}?{urlencode(parameters)}",
            created_monotonic=monotonic_now,
            expires_at=(self._now() + timedelta(seconds=config.callback_timeout_seconds)).isoformat(),
        )

    def exchange_code(
        self,
        config: OAuthClientConfiguration,
        *,
        code: str,
        code_verifier: str,
    ) -> OAuthGrant:
        if not _is_bounded_text(code, maximum=4096) or not _is_bounded_text(code_verifier, maximum=128):
            raise OAuthFlowError("Roblox authentication response is invalid.")
        payload = self._post_form(
            OAUTH_TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "client_id": config.client_id,
                "code": code,
                "code_verifier": code_verifier,
            },
        )
        return _grant_from_payload(payload, now=self._now())

    def refresh(self, config: OAuthClientConfiguration, grant: OAuthGrant) -> OAuthGrant:
        self._ensure_open()
        payload = self._post_form(
            OAUTH_TOKEN_URL,
            {
                "grant_type": "refresh_token",
                "client_id": config.client_id,
                "refresh_token": grant.refresh_token,
            },
        )
        return _grant_from_payload(payload, now=self._now())

    def userinfo(self, grant: OAuthGrant) -> OAuthIdentity:
        self._ensure_open()
        try:
            response = self._http.get(
                OAUTH_USERINFO_URL,
                headers={"Accept": "application/json", "Authorization": f"Bearer {grant.access_token}"},
                timeout=self._timeout_seconds,
            )
        except requests.RequestException:
            raise OAuthFlowError("Roblox is unavailable to verify connection.", retryable=True) from None
        except Exception:
            raise OAuthFlowError("Roblox is unavailable to verify connection.", retryable=True) from None
        payload = _response_mapping(response, invalid_message="Roblox returned an invalid OAuth profile.")
        return _identity_from_payload(payload)

    def _post_form(self, url: str, data: Mapping[str, str]) -> Mapping[str, Any]:
        self._ensure_open()
        try:
            response = self._http.post(
                url,
                data=dict(data),
                headers={"Accept": "application/json"},
                timeout=self._timeout_seconds,
            )
        except requests.RequestException:
            raise OAuthFlowError("Roblox is unavailable to complete connection.", retryable=True) from None
        except Exception:
            raise OAuthFlowError("Roblox is unavailable to complete connection.", retryable=True) from None
        return _response_mapping(response, invalid_message="Roblox denied OAuth connection.")

    def _ensure_open(self) -> None:
        if self._closed:
            raise OAuthFlowError("OAuth client is closed.")


class OAuthLoginCoordinator:
    """Coordinates browser, loopback callback, PKCE and HTTPS exchange.

    The coordinator returns a public snapshot while a flow is pending.  Its
    only completion object contains the grant and is intended exclusively for
    :class:`ApplicationService`; it must never be returned by a bridge method.
    """

    def __init__(
        self,
        *,
        client: RobloxOAuthClient | None = None,
        browser_open: BrowserOpener | None = None,
        callback_factory: CallbackReceiverFactory | None = None,
        monotonic: MonotonicClock = time.monotonic,
        now: WallClock | None = None,
    ) -> None:
        self._client = client or RobloxOAuthClient()
        self._browser_open = browser_open or webbrowser.open
        self._callback_factory = callback_factory or OAuthLoopbackCallbackServer
        self._monotonic = monotonic
        self._now = now or (lambda: datetime.now(UTC))
        self._lock = threading.RLock()
        self._active: dict[str, tuple[OAuthClientConfiguration, OAuthAuthorizationAttempt, _CallbackReceiver]] = {}
        self._terminal: OrderedDict[str, OAuthLoginSnapshot] = OrderedDict()
        self._closed = False

    def start(self, config: OAuthClientConfiguration) -> OAuthLoginSnapshot:
        with self._lock:
            if self._closed:
                raise OAuthFlowError("OAuth login service is closed.")
            if self._active:
                raise OAuthFlowError("A Roblox login is already pending in the browser.")
            attempt = self._client.build_authorization_attempt(config, monotonic_now=self._monotonic())
            try:
                receiver = self._callback_factory(config.redirect_uri, attempt.state)
                receiver.start()
            except OAuthFlowError:
                raise
            except OSError:
                raise OAuthFlowError("OAuth callback port is unavailable. Check configuration.") from None
            except Exception:
                raise OAuthFlowError("OAuth callback receiver could not start.") from None

            try:
                opened = self._browser_open(attempt.authorization_url)
            except Exception:
                receiver.close()
                raise OAuthFlowError("System browser could not be opened.") from None
            if opened is False:
                receiver.close()
                raise OAuthFlowError("System browser could not be opened.")

            self._active[attempt.operation_id] = (config, attempt, receiver)
            return self._snapshot(attempt.operation_id, "waiting", attempt)

    def poll(self, operation_id: str) -> OAuthLoginSnapshot | OAuthLoginCompletion:
        with self._lock:
            active = self._active.get(operation_id)
            if active is None:
                terminal = self._terminal.get(operation_id)
                if terminal is not None:
                    return terminal
                raise ValidationError("This OAuth login operation was not found.")
            config, attempt, receiver = active
            if self._monotonic() - attempt.created_monotonic >= config.callback_timeout_seconds:
                return self._finish_terminal(operation_id, "expired", "Roblox login expired. Please try again.")
            callback = receiver.poll()
            if callback is None:
                return self._snapshot(operation_id, "waiting", attempt)
            if not hmac.compare_digest(callback.state, attempt.state):
                return self._finish_terminal(operation_id, "failed", "OAuth response is invalid.")
            if callback.error:
                return self._finish_terminal(operation_id, "cancelled", "Roblox login was cancelled or denied.")
            if not callback.code:
                return self._finish_terminal(operation_id, "failed", "OAuth response is incomplete.")

            try:
                grant = self._client.exchange_code(config, code=callback.code, code_verifier=attempt.code_verifier)
                identity = self._client.userinfo(grant)
            except OAuthFlowError as exc:
                return self._finish_terminal(operation_id, "failed", exc.message)
            finally:
                receiver.close()

            self._active.pop(operation_id, None)
            snapshot = self._remember_terminal(self._snapshot(operation_id, "completed", attempt))
            return OAuthLoginCompletion(snapshot=snapshot, identity=identity, grant=grant)

    def cancel(self, operation_id: str) -> OAuthLoginSnapshot:
        with self._lock:
            active = self._active.pop(operation_id, None)
            if active is None:
                terminal = self._terminal.get(operation_id)
                if terminal is not None:
                    return terminal
                raise ValidationError("This OAuth login operation was not found.")
            _config, _attempt, receiver = active
            receiver.close()
            return self._remember_terminal(
                OAuthLoginSnapshot(operation_id=operation_id, status="cancelled", message="Roblox login cancelled.")
            )

    def refresh(self, config: OAuthClientConfiguration, grant: OAuthGrant) -> tuple[OAuthGrant, OAuthIdentity]:
        refreshed = self._client.refresh(config, grant)
        return refreshed, self._client.userinfo(refreshed)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            active = tuple(self._active.values())
            self._active.clear()
        for _config, _attempt, receiver in active:
            receiver.close()
        self._client.close()

    def _finish_terminal(self, operation_id: str, status: str, message: str) -> OAuthLoginSnapshot:
        active = self._active.pop(operation_id, None)
        if active is not None:
            _config, _attempt, receiver = active
            receiver.close()
        return self._remember_terminal(OAuthLoginSnapshot(operation_id=operation_id, status=status, message=message))

    @staticmethod
    def _snapshot(
        operation_id: str, status: str, attempt: OAuthAuthorizationAttempt
    ) -> OAuthLoginSnapshot:
        return OAuthLoginSnapshot(operation_id=operation_id, status=status, expires_at=attempt.expires_at)

    def _remember_terminal(self, snapshot: OAuthLoginSnapshot) -> OAuthLoginSnapshot:
        self._terminal[snapshot.operation_id] = snapshot
        self._terminal.move_to_end(snapshot.operation_id)
        while len(self._terminal) > 24:
            self._terminal.popitem(last=False)
        return snapshot


class OAuthGrantVault:
    """Persist a complete OAuth grant as one opaque DPAPI-protected blob."""

    def __init__(self, repository: Any, protector: Any) -> None:
        self._repository = repository
        self._protector = protector

    def store(self, account_id: str, grant: OAuthGrant) -> None:
        try:
            raw = json.dumps(
                {
                    "version": 1,
                    "access_token": grant.access_token,
                    "refresh_token": grant.refresh_token,
                    "id_token": grant.id_token,
                    "expires_at": grant.expires_at.astimezone(UTC).isoformat(),
                    "scopes": list(grant.scopes),
                },
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
            protected = self._protector.protect(raw, description="Astro Account Manager Roblox OAuth grant")
            self._repository.save_protected_secret(account_id, OAUTH_GRANT_KIND, protected)
        except DPAPIUnavailableError as exc:
            raise SecurityError("Windows vault is unavailable to protect OAuth login.") from exc
        except DPAPIError as exc:
            raise SecurityError("OAuth login could not be protected by Windows.") from exc
        except Exception:
            raise OAuthFlowError("OAuth login could not be saved locally.") from None

    def load(self, account_id: str) -> OAuthGrant | None:
        try:
            protected = self._repository.load_protected_secret(account_id, OAUTH_GRANT_KIND)
        except Exception:
            raise OAuthFlowError("Local OAuth login cannot be read.") from None
        if protected is None:
            return None
        try:
            raw = self._protector.unprotect(protected)
            payload = json.loads(raw.decode("utf-8"))
        except DPAPIUnavailableError as exc:
            raise SecurityError("Windows vault is unavailable to read OAuth login.") from exc
        except (DPAPIError, UnicodeDecodeError, ValueError, TypeError):
            raise OAuthFlowError("Local OAuth login is readable. Please reconnect account.") from None
        if not isinstance(payload, Mapping) or payload.get("version") != 1:
            raise OAuthFlowError("Local OAuth login is invalid. Please reconnect account.")
        return _grant_from_storage_payload(payload)

    def delete(self, account_id: str) -> bool:
        try:
            return bool(self._repository.delete_protected_secret(account_id, OAUTH_GRANT_KIND))
        except Exception:
            raise OAuthFlowError("Local OAuth login cannot be deleted.") from None


def _validate_loopback_redirect_uri(value: object) -> Any:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise OAuthConfigurationError("OAuth redirect URI is invalid.")
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        raise OAuthConfigurationError("OAuth redirect URI is invalid.") from None
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or port is None
        or not 1 <= port <= 65535
        or not parsed.path.startswith("/")
        or parsed.path == "/"
        or len(parsed.path) > 256
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise OAuthConfigurationError(
            "OAuth URI must be a local HTTP callback of form http://127.0.0.1:port/path."
        )
    return parsed


def _make_code_verifier() -> str:
    # ``token_urlsafe`` uses only URL-safe unreserved characters.  64 random
    # bytes produce an 86-character verifier, within Roblox's documented range.
    verifier = secrets.token_urlsafe(64)
    if not 43 <= len(verifier) <= 128:  # Defensive against implementation changes.
        raise OAuthFlowError("Local PKCE generator is invalid.")
    return verifier


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _single_query_value(query: Mapping[str, list[str]], key: str, *, maximum: int) -> str | None:
    values = query.get(key)
    if not isinstance(values, list) or len(values) != 1:
        return None
    value = values[0]
    return value if _is_bounded_text(value, maximum=maximum) else None


def _is_bounded_text(value: object, *, maximum: int) -> bool:
    return isinstance(value, str) and 0 < len(value) <= maximum and value.isprintable()


def _response_mapping(response: Any, *, invalid_message: str) -> Mapping[str, Any]:
    status = getattr(response, "status_code", 0)
    if not isinstance(status, int) or not 200 <= status < 300:
        if status in {400, 401, 403}:
            raise OAuthFlowError("Roblox denied OAuth connection.")
        raise OAuthFlowError("Roblox is unavailable to complete connection.", retryable=status == 429 or status >= 500)
    try:
        payload = response.json()
    except (AttributeError, TypeError, ValueError):
        raise OAuthFlowError(invalid_message) from None
    if not isinstance(payload, Mapping):
        raise OAuthFlowError(invalid_message)
    return payload


def _grant_from_payload(payload: Mapping[str, Any], *, now: datetime) -> OAuthGrant:
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    id_token = payload.get("id_token")
    expires_in = payload.get("expires_in")
    scope_value = payload.get("scope")
    if not _is_bounded_text(access_token, maximum=16_384) or not _is_bounded_text(refresh_token, maximum=16_384):
        raise OAuthFlowError("Roblox returned an incomplete OAuth authorization.")
    if id_token is not None and not _is_bounded_text(id_token, maximum=16_384):
        raise OAuthFlowError("Roblox returned an invalid OAuth authorization.")
    if isinstance(expires_in, bool):
        raise OAuthFlowError("Roblox returned an invalid OAuth duration.")
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        raise OAuthFlowError("Roblox returned an invalid OAuth duration.") from None
    if not 1 <= seconds <= 86_400:
        raise OAuthFlowError("Roblox returned an invalid OAuth duration.")
    scopes = tuple(scope for scope in str(scope_value or "").split() if scope)
    if not set(DEFAULT_SCOPES).issubset(scopes):
        raise OAuthFlowError("Roblox did not grant required profile permissions.")
    return OAuthGrant(
        access_token=access_token,
        refresh_token=refresh_token,
        id_token=id_token if isinstance(id_token, str) else None,
        expires_at=now.astimezone(UTC) + timedelta(seconds=seconds),
        scopes=scopes,
    )


def _grant_from_storage_payload(payload: Mapping[str, Any]) -> OAuthGrant:
    expires_raw = payload.get("expires_at")
    try:
        expires_at = datetime.fromisoformat(str(expires_raw).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        raise OAuthFlowError("Local OAuth login is invalid. Please reconnect account.") from None
    scopes_value = payload.get("scopes")
    if not isinstance(scopes_value, list) or not all(isinstance(item, str) for item in scopes_value):
        raise OAuthFlowError("Local OAuth login is invalid. Please reconnect account.")
    return _grant_from_payload(
        {
            "access_token": payload.get("access_token"),
            "refresh_token": payload.get("refresh_token"),
            "id_token": payload.get("id_token"),
            # Keep validation centralized, then restore the persisted expiration.
            "expires_in": 1,
            "scope": " ".join(scopes_value),
        },
        now=expires_at - timedelta(seconds=1),
    )


def _identity_from_payload(payload: Mapping[str, Any]) -> OAuthIdentity:
    raw_user_id = payload.get("sub")
    try:
        user_id = int(raw_user_id)
    except (TypeError, ValueError):
        raise OAuthFlowError("Roblox returned an invalid OAuth profile.") from None
    if user_id <= 0 or isinstance(raw_user_id, bool):
        raise OAuthFlowError("Roblox returned an invalid OAuth profile.")
    username = _clean_public_text(payload.get("preferred_username"), maximum=120)
    if username is None:
        raise OAuthFlowError("Roblox did not return logged in username.")
    display_name = _clean_public_text(payload.get("name") or payload.get("nickname"), maximum=120)
    avatar_url = _safe_https_url(payload.get("picture"))
    return OAuthIdentity(user_id=user_id, username=username, display_name=display_name, avatar_url=avatar_url)


def _clean_public_text(value: object, *, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized if normalized and len(normalized) <= maximum else None


def _safe_https_url(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 2048:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        return None
    return value


__all__ = [
    "DEFAULT_CALLBACK_TIMEOUT_SECONDS",
    "DEFAULT_SCOPES",
    "OAUTH_GRANT_KIND",
    "OAuthAuthorizationAttempt",
    "OAuthCallback",
    "OAuthClientConfiguration",
    "OAuthConfigurationError",
    "OAuthFlowError",
    "OAuthGrant",
    "OAuthGrantVault",
    "OAuthIdentity",
    "OAuthLoginCompletion",
    "OAuthLoginCoordinator",
    "OAuthLoginSnapshot",
    "OAuthLoopbackCallbackServer",
    "RobloxOAuthClient",
]
