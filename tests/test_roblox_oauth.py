from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import socket
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

import pytest

from app.backend.api import DesktopBridge
from app.backend.core.config import AppPaths
from app.backend.models.domain import Account
from app.backend.repositories.sqlite_repository import SQLiteRepository
from app.backend.roblox.oauth import (
    OAuthCallback,
    OAuthClientConfiguration,
    OAuthConfigurationError,
    OAuthGrant,
    OAuthGrantVault,
    OAuthLoginCompletion,
    OAuthLoginCoordinator,
    OAuthLoopbackCallbackServer,
    RobloxOAuthClient,
)
from app.backend.services import ApplicationService


class _Response:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


class _Http:
    def __init__(self, *, posts: list[_Response], gets: list[_Response]) -> None:
        self.posts = list(posts)
        self.gets = list(gets)
        self.post_calls: list[tuple[str, dict[str, str], dict[str, str], float]] = []
        self.get_calls: list[tuple[str, dict[str, str], float]] = []
        self.closed = False

    def post(self, url: str, *, data: dict[str, str], headers: dict[str, str], timeout: float) -> _Response:
        self.post_calls.append((url, data, headers, timeout))
        return self.posts.pop(0)

    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> _Response:
        self.get_calls.append((url, headers, timeout))
        return self.gets.pop(0)

    def close(self) -> None:
        self.closed = True


class _Receiver:
    def __init__(self, redirect_uri: str, expected_state: str) -> None:
        self.redirect_uri = redirect_uri
        self.expected_state = expected_state
        self.callback: OAuthCallback | None = None
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def poll(self) -> OAuthCallback | None:
        callback = self.callback
        self.callback = None
        return callback

    def close(self) -> None:
        self.closed = True


class _VaultProtector:
    """Reversible fake DPAPI implementation that does not retain plaintext."""

    available = True
    status = SimpleNamespace(available=True, reason=None)

    @staticmethod
    def protect(value: bytes, **_kwargs: object) -> bytes:
        return bytes(byte ^ 0xA5 for byte in value)

    @staticmethod
    def unprotect(value: bytes, **_kwargs: object) -> bytes:
        return bytes(byte ^ 0xA5 for byte in value)


class _Monitor:
    def scan(self) -> SimpleNamespace:
        return SimpleNamespace(instances=(), events=())

    def current_instances(self) -> tuple[object, ...]:
        return ()


class _Roblox:
    def close(self) -> None:
        return None


class _Launcher:
    def launch(self, _target: object) -> object:
        raise AssertionError("OAuth tests do not launch Roblox")


def _paths(tmp_path: Path) -> AppPaths:
    root = tmp_path / "app-data"
    return AppPaths(
        root=root,
        database=root / "asteria.db",
        logs=root / "logs",
        backups=root / "backups",
        cache=root / "cache",
        exports=root / "exports",
    )


def _config() -> OAuthClientConfiguration:
    return OAuthClientConfiguration(
        client_id="123456789",
        redirect_uri="http://127.0.0.1:8989/oauth/callback",
    )


def _grant(access: str = "access-secret", refresh: str = "refresh-secret") -> OAuthGrant:
    return OAuthGrant(
        access_token=access,
        refresh_token=refresh,
        expires_at=datetime(2026, 8, 10, 12, 15, tzinfo=UTC),
        scopes=("openid", "profile"),
        id_token="id-secret",
    )


def _oauth_payload(access: str = "access-secret", refresh: str = "refresh-secret") -> dict[str, object]:
    return {
        "access_token": access,
        "refresh_token": refresh,
        "id_token": "id-secret",
        "expires_in": 900,
        "scope": "openid profile",
    }


def _profile(username: str = "OAuthUser") -> dict[str, object]:
    return {
        "sub": "12345",
        "preferred_username": username,
        "name": "OAuth Display",
        "picture": "https://tr.rbxcdn.com/example/avatar.png",
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_pkce_authorization_url_keeps_verifier_off_the_browser_url() -> None:
    client = RobloxOAuthClient(http=_Http(posts=[], gets=[]), now=lambda: datetime(2026, 8, 10, tzinfo=UTC))
    attempt = client.build_authorization_attempt(_config(), monotonic_now=100.0)
    query = parse_qs(urlsplit(attempt.authorization_url).query)

    assert query["client_id"] == ["123456789"]
    assert query["redirect_uri"] == ["http://127.0.0.1:8989/oauth/callback"]
    assert query["scope"] == ["openid profile"]
    assert query["code_challenge_method"] == ["S256"]
    assert "client_secret" not in query
    assert "code_verifier" not in query
    assert 43 <= len(attempt.code_verifier) <= 128
    expected_challenge = __import__("base64").urlsafe_b64encode(
        hashlib.sha256(attempt.code_verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    assert query["code_challenge"] == [expected_challenge]
    assert "REDACTED" in repr(attempt)


def test_loopback_callback_requires_the_expected_state_and_never_echoes_code() -> None:
    port = _free_port()
    redirect = f"http://127.0.0.1:{port}/oauth/callback"
    receiver = OAuthLoopbackCallbackServer(redirect, "expected-state")
    receiver.start()
    try:
        with pytest.raises(HTTPError) as invalid:
            urlopen(f"{redirect}?code=test-code&state=wrong-state", timeout=2)
        assert invalid.value.code == 400
        assert receiver.poll() is None

        with urlopen(f"{redirect}?code=test-code&state=expected-state", timeout=2) as response:
            body = response.read().decode("utf-8")
        assert "test-code" not in body
        callback = receiver.poll()
        assert callback is not None
        assert callback.code == "test-code"
        assert callback.error is None
    finally:
        receiver.close()


def test_oauth_coordinator_exchanges_pkce_code_and_returns_only_private_grant() -> None:
    http = _Http(posts=[_Response(200, _oauth_payload())], gets=[_Response(200, _profile())])
    client = RobloxOAuthClient(http=http, now=lambda: datetime(2026, 8, 10, tzinfo=UTC))
    receivers: list[_Receiver] = []
    opened_urls: list[str] = []

    def receiver_factory(redirect_uri: str, state: str) -> _Receiver:
        receiver = _Receiver(redirect_uri, state)
        receivers.append(receiver)
        return receiver

    coordinator = OAuthLoginCoordinator(
        client=client,
        browser_open=lambda url: opened_urls.append(url) or True,
        callback_factory=receiver_factory,
        monotonic=lambda: 50.0,
        now=lambda: datetime(2026, 8, 10, tzinfo=UTC),
    )
    try:
        waiting = coordinator.start(_config())
        assert waiting.status == "waiting"
        assert "access-secret" not in json.dumps(waiting.as_public_dict())
        assert len(opened_urls) == 1
        assert receivers[0].started is True

        receivers[0].callback = OAuthCallback(state=receivers[0].expected_state, code="test-code")
        completed = coordinator.poll(waiting.operation_id)

        assert isinstance(completed, OAuthLoginCompletion)
        assert completed.identity.user_id == 12345
        assert completed.identity.username == "OAuthUser"
        assert "access-secret" not in repr(completed)
        assert http.post_calls[0][1]["grant_type"] == "authorization_code"
        assert "client_secret" not in http.post_calls[0][1]
        assert http.post_calls[0][1]["code_verifier"]
        assert receivers[0].closed is True
    finally:
        coordinator.close()


def test_oauth_grant_vault_uses_an_opaque_blob_and_redacts_repr(tmp_path: Path) -> None:
    with SQLiteRepository(tmp_path / "oauth.db") as repository:
        account = repository.save_account(Account(username="OAuthVaultUser"))
        vault = OAuthGrantVault(repository, _VaultProtector())
        original = _grant()

        vault.store(account.id, original)
        blob = repository.load_protected_secret(account.id, "oauth_grant")
        assert blob is not None
        assert b"access-secret" not in blob
        assert b"refresh-secret" not in blob
        assert "access-secret" not in repr(original)
        assert vault.load(account.id) == original


def test_service_and_bridge_link_refresh_and_disconnect_without_returning_tokens(tmp_path: Path) -> None:
    http = _Http(
        posts=[
            _Response(200, _oauth_payload("first-access", "first-refresh")),
            _Response(200, _oauth_payload("second-access", "second-refresh")),
        ],
        gets=[_Response(200, _profile()), _Response(200, _profile())],
    )
    receivers: list[_Receiver] = []

    def receiver_factory(redirect_uri: str, state: str) -> _Receiver:
        receiver = _Receiver(redirect_uri, state)
        receivers.append(receiver)
        return receiver

    coordinator = OAuthLoginCoordinator(
        client=RobloxOAuthClient(http=http, now=lambda: datetime(2026, 8, 10, tzinfo=UTC)),
        browser_open=lambda _url: True,
        callback_factory=receiver_factory,
        monotonic=lambda: 100.0,
        now=lambda: datetime(2026, 8, 10, tzinfo=UTC),
    )
    service = ApplicationService(
        paths=_paths(tmp_path),
        vault=_VaultProtector(),  # type: ignore[arg-type]
        roblox=_Roblox(),  # type: ignore[arg-type]
        launcher=_Launcher(),  # type: ignore[arg-type]
        monitor=_Monitor(),  # type: ignore[arg-type]
        oauth_login=coordinator,
    )
    try:
        service.update_settings(
            {
                "categories": {
                    "oauth": {
                        "enabled": True,
                        "client_id": "123456789",
                        "redirect_uri": "http://127.0.0.1:8989/oauth/callback",
                        "callback_timeout_seconds": 300,
                    }
                }
            }
        )
        bridge = DesktopBridge(service)
        waiting = bridge.start_oauth_login()
        assert waiting["status"] == "waiting"
        assert set(waiting) == {"operation_id", "status", "expires_at", "message"}

        receivers[0].callback = OAuthCallback(state=receivers[0].expected_state, code="one-time-code")
        completed = bridge.poll_oauth_login(waiting["operation_id"])
        account = completed["account"]
        serialised = json.dumps(completed)
        assert completed["status"] == "completed"
        assert account["username"] == "OAuthUser"
        assert account["has_session"] is False
        assert account["oauth_connected"] is True
        assert "first-access" not in serialised
        assert "first-refresh" not in serialised

        stored = service.repository.load_protected_secret(account["id"], "oauth_grant")
        assert stored is not None
        assert b"first-access" not in stored
        assert b"first-refresh" not in stored

        exported = service.export_metadata()
        portable = json.loads(Path(exported["path"]).read_text(encoding="utf-8"))
        assert "oauth" not in portable["accounts"][0]["metadata"]
        assert "first-access" not in json.dumps(portable)
        assert "first-refresh" not in json.dumps(portable)

        refreshed = bridge.refresh_oauth_account(account["id"])
        assert refreshed["oauth_connected"] is True
        assert "second-access" not in json.dumps(refreshed)
        disconnected = bridge.disconnect_oauth_account(account["id"])
        assert disconnected["oauth_connected"] is False
        assert service.repository.load_protected_secret(account["id"], "oauth_grant") is None
    finally:
        service.close()


def test_oauth_configuration_rejects_non_loopback_callbacks() -> None:
    with pytest.raises(OAuthConfigurationError):
        OAuthClientConfiguration(client_id="123", redirect_uri="https://example.test/oauth/callback")
