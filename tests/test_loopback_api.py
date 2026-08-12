from __future__ import annotations

from http.client import HTTPConnection
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.backend.api.loopback import LoopbackApiError, LoopbackApiServer
from app.backend.core.config import AppPaths
from app.backend.models.domain import Game
from app.backend.roblox.types import LaunchResult
from app.backend.services import ApplicationService


class _Monitor:
    def scan(self) -> SimpleNamespace:
        return SimpleNamespace(instances=(), events=())

    def current_instances(self) -> tuple[object, ...]:
        return ()


class _Roblox:
    def close(self) -> None:
        return None

    def get_game_details(self, place_id: int) -> Game:
        return Game(place_id=place_id, name="Example")


class _Launcher:
    def launch(self, target: object) -> LaunchResult:
        return LaunchResult(uri="roblox://experiences/start?placeId=1", launched=True)


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


def _request(
    api: LoopbackApiServer,
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: object | None = None,
    raw_body: str | None = None,
    content_type: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    status = api.status
    connection = HTTPConnection(status.host, status.port, timeout=3)
    headers: dict[str, str] = {}
    body: str | None = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra_headers:
        headers.update(extra_headers)
    if payload is not None:
        body = json.dumps(payload)
        headers["Content-Type"] = "application/json"
    elif raw_body is not None:
        body = raw_body
        headers["Content-Type"] = content_type or "text/plain"
    connection.request(method, f"/api/v1{path}", body=body, headers=headers)
    response = connection.getresponse()
    decoded = json.loads(response.read().decode("utf-8"))
    connection.close()
    return response.status, decoded


def test_loopback_api_requires_bearer_auth_and_rejects_secret_fields(tmp_path: Path) -> None:
    service = ApplicationService(
        paths=_paths(tmp_path),
        roblox=_Roblox(),  # type: ignore[arg-type]
        launcher=_Launcher(),  # type: ignore[arg-type]
        monitor=_Monitor(),  # type: ignore[arg-type]
    )
    token = "a" * 40
    api = LoopbackApiServer(service, token=token, port=0)
    try:
        api.start()

        status, payload = _request(api, "GET", "/health")
        assert status == 401
        assert payload["error"]["code"] == "security_error"  # type: ignore[index]

        status, payload = _request(api, "GET", "/health", token=token)
        assert status == 200
        assert "data_root" not in payload["data"]  # type: ignore[operator]
        assert token not in json.dumps(payload)

        status, payload = _request(
            api,
            "POST",
            "/accounts",
            token=token,
            payload={"username": "LoopbackUser", "avatar_color": "mint"},
        )
        assert status == 201
        account = payload["data"]  # type: ignore[assignment]
        assert account["username"] == "LoopbackUser"  # type: ignore[index]
        assert account["avatar_color"] == "mint"  # type: ignore[index]

        status, payload = _request(
            api,
            "POST",
            "/accounts",
            token=token,
            payload={"username": "Unsafe", "session": "never-accepted-over-http"},
        )
        assert status == 403
        assert payload["error"]["code"] == "security_error"  # type: ignore[index]

        status, payload = _request(api, "GET", "/accounts?q=loop", token=token)
        assert status == 200
        assert len(payload["data"]) == 1  # type: ignore[arg-type]

        # Test RAM Developer API 1:1 Compat Routes
        status, payload = _request(api, "GET", "/SetAlias?Account=LoopbackUser&Alias=NewAlias", token=token)
        assert status == 200

        status, payload = _request(api, "GET", "/GetAlias?Account=LoopbackUser", token=token)
        assert status == 200
        assert payload["data"]["alias"] == "NewAlias"

        status, payload = _request(api, "GET", "/SetField?Account=LoopbackUser&Field=xp&Value=100", token=token)
        assert status == 200

        status, payload = _request(api, "GET", "/GetField?Account=LoopbackUser&Field=xp", token=token)
        assert status == 200
        assert payload["data"]["value"] == "100"

        status, payload = _request(api, "GET", "/RemoveField?Account=LoopbackUser&Field=xp", token=token)
        assert status == 200

        status, payload = _request(api, "GET", "/GetField?Account=LoopbackUser&Field=xp", token=token)
        assert status == 200
        assert payload["data"]["value"] is None

        status, payload = _request(
            api,
            "POST",
            "/SetAlias?Account=LoopbackUser",
            token=token,
            raw_body="Historical alias",
        )
        assert status == 200

        status, payload = _request(api, "GET", "/GetAlias?Account=LoopbackUser", token=token)
        assert payload["data"]["alias"] == "Historical alias"

        status, payload = _request(
            api,
            "POST",
            "/SetDescription?Account=LoopbackUser",
            token=token,
            raw_body="first",
        )
        assert status == 200
        status, payload = _request(
            api,
            "POST",
            "/AppendDescription?Account=LoopbackUser",
            token=token,
            raw_body=" second",
        )
        assert status == 200
        status, payload = _request(api, "GET", "/GetDescription?Account=LoopbackUser", token=token)
        assert payload["data"]["description"] == "first second"

        status, payload = _request(api, "GET", "/GetAccounts", token=token)
        assert status == 200
        assert "LoopbackUser" in payload["data"]["accounts"]

        # A miss must never fall through to the first account. That could
        # otherwise launch or mutate a completely unrelated profile.
        status, payload = _request(api, "GET", "/GetAlias?Account=DoesNotExist", token=token)
        assert status == 404
        assert payload["error"]["code"] == "not_found"
    finally:
        api.stop()
        service.close()


def _account_service(tmp_path: Path, username: str = "LegacyAuthUser") -> ApplicationService:
    service = ApplicationService(
        paths=_paths(tmp_path),
        roblox=_Roblox(),  # type: ignore[arg-type]
        launcher=_Launcher(),  # type: ignore[arg-type]
        monitor=_Monitor(),  # type: ignore[arg-type]
    )
    service.create_account({"username": username, "saved_place_id": 1})
    return service


def test_get_accounts_routes_honour_the_historical_permission(tmp_path: Path) -> None:
    service = _account_service(tmp_path, "ListingUser")
    token = "g" * 40
    api = LoopbackApiServer(
        service,
        token=token,
        port=0,
        permissions={"allow_get_accounts": False},
    )
    try:
        api.start()
        for path in ("/GetAccounts", "/GetAccountsJson"):
            status, payload = _request(api, "GET", path, token=token)
            assert status == 403
            assert payload["error"]["code"] == "security_error"
    finally:
        api.stop()
        service.close()


def test_get_accounts_routes_work_when_permission_is_granted(tmp_path: Path) -> None:
    service = _account_service(tmp_path, "ListingUser")
    token = "h" * 40
    api = LoopbackApiServer(
        service,
        token=token,
        port=0,
        permissions={"allow_get_accounts": True},
    )
    try:
        api.start()
        status, payload = _request(api, "GET", "/GetAccounts", token=token)
        assert status == 200
        assert "ListingUser" in payload["data"]["accounts"]
    finally:
        api.stop()
        service.close()


def test_unknown_api_permission_is_rejected() -> None:
    with pytest.raises(LoopbackApiError):
        LoopbackApiServer(
            object(),
            token="i" * 40,
            port=0,
            permissions={"allow_everything": True},
        )


@pytest.mark.parametrize(
    "enabled,password",
    [(False, "historical-password"), (True, None), (True, "short")],
)
def test_invalid_legacy_password_configurations_are_refused(tmp_path, enabled, password) -> None:
    service = _account_service(tmp_path)
    try:
        with pytest.raises(LoopbackApiError):
            LoopbackApiServer(
                service,
                token="j" * 40,
                port=0,
                legacy_password_auth_enabled=enabled,
                legacy_password=password,
            )
    finally:
        service.close()


def test_legacy_password_is_disabled_by_default(tmp_path: Path) -> None:
    service = _account_service(tmp_path)
    api = LoopbackApiServer(service, token="k" * 40, port=0)
    try:
        api.start()
        status, _ = _request(
            api,
            "GET",
            "/GetAccounts?Password=historical-password",
            token=None,
        )
        assert status == 401
    finally:
        api.stop()
        service.close()


def test_bearer_query_and_header_auth_coexist_when_legacy_is_enabled(tmp_path: Path) -> None:
    service = _account_service(tmp_path)
    token = "l" * 40
    api = LoopbackApiServer(
        service,
        token=token,
        port=0,
        permissions={"allow_get_accounts": True},
        legacy_password_auth_enabled=True,
        legacy_password="historical-password",
    )
    try:
        api.start()
        status, _ = _request(api, "GET", "/GetAccounts", token=token)
        assert status == 200
        status, _ = _request(
            api,
            "GET",
            "/GetAccounts?Password=historical-password",
        )
        assert status == 200
        status, _ = _request(
            api,
            "GET",
            "/GetAccounts",
            extra_headers={"X-RAM-Password": "historical-password"},
        )
        assert status == 200
        status, _ = _request(api, "GET", "/GetAccounts?Password=wrong-password")
        assert status == 401
    finally:
        api.stop()
        service.close()


def test_legacy_password_never_bypasses_route_permissions(tmp_path: Path) -> None:
    service = _account_service(tmp_path)
    api = LoopbackApiServer(
        service,
        token="m" * 40,
        port=0,
        permissions={"allow_get_cookie": False},
        legacy_password_auth_enabled=True,
        legacy_password="historical-password",
    )
    try:
        api.start()
        status, payload = _request(
            api,
            "GET",
            "/GetCookie?Account=LegacyAuthUser&Password=historical-password",
        )
        assert status == 403
        assert payload["error"]["code"] == "security_error"
    finally:
        api.stop()
        service.close()


def test_legacy_password_is_not_written_to_request_logs(tmp_path: Path, caplog) -> None:
    service = _account_service(tmp_path)
    logger = logging.getLogger("astro.tests.legacy_api")
    api = LoopbackApiServer(
        service,
        token="n" * 40,
        port=0,
        permissions={"allow_get_accounts": True},
        legacy_password_auth_enabled=True,
        legacy_password="historical-password",
        logger=logger,
    )
    try:
        with caplog.at_level(logging.DEBUG, logger=logger.name):
            api.start()
            status, _ = _request(
                api,
                "GET",
                "/GetAccounts?Password=historical-password",
            )
            assert status == 200
        assert "historical-password" not in caplog.text
    finally:
        api.stop()
        service.close()


def test_loopback_api_only_accepts_the_ipv4_loopback_interface(tmp_path: Path) -> None:
    service = ApplicationService(
        paths=_paths(tmp_path),
        roblox=_Roblox(),  # type: ignore[arg-type]
        launcher=_Launcher(),  # type: ignore[arg-type]
        monitor=_Monitor(),  # type: ignore[arg-type]
    )
    try:
        with pytest.raises(LoopbackApiError):
            LoopbackApiServer(service, token="a" * 40, host="0.0.0.0")
        with pytest.raises(LoopbackApiError):
            LoopbackApiServer(service, token="a" * 40, permissions={"unknown": True})
    finally:
        service.close()


def test_loopback_api_enforces_historical_route_permissions(tmp_path: Path) -> None:
    service = ApplicationService(
        paths=_paths(tmp_path),
        roblox=_Roblox(),  # type: ignore[arg-type]
        launcher=_Launcher(),  # type: ignore[arg-type]
        monitor=_Monitor(),  # type: ignore[arg-type]
    )
    account = service.create_account({"username": "PermissionUser", "saved_place_id": 1})
    token = "p" * 40
    api = LoopbackApiServer(
        service,
        token=token,
        port=0,
        permissions={
            "allow_get_cookie": False,
            "allow_launch_account": False,
            "allow_account_editing": False,
            "allow_import_cookie": False,
        },
    )
    try:
        api.start()
        for path in (
            "/GetCookie?Account=PermissionUser",
            "/LaunchAccount?Account=PermissionUser&PlaceId=1",
            "/SetAlias?Account=PermissionUser&Alias=Denied",
            "/ImportCookie?Cookie=not-accepted",
        ):
            status, payload = _request(api, "GET", path, token=token)
            assert status == 403
            assert payload["error"]["code"] == "security_error"

        status, _ = _request(api, "GET", "/GetAccounts", token=token)
        assert status == 200
        status, _ = _request(api, "GET", "/GetAccountsJson?IncludeCookies=true", token=token)
        assert status == 403
        assert service.list_accounts()[0]["id"] == account["id"]
    finally:
        api.stop()
        service.close()
