from __future__ import annotations

from http.client import HTTPConnection
import json
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
) -> tuple[int, dict[str, object]]:
    status = api.status
    connection = HTTPConnection(status.host, status.port, timeout=3)
    headers: dict[str, str] = {}
    body: str | None = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        body = json.dumps(payload)
        headers["Content-Type"] = "application/json"
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

        status, payload = _request(api, "GET", "/GetAccounts", token=token)
        assert status == 200
        assert "LoopbackUser" in payload["data"]["accounts"]
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
    finally:
        service.close()
