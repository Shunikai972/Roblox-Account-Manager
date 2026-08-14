from __future__ import annotations

import json
from urllib.request import Request, urlopen

import pytest

from app.backend.api.loopback import LoopbackApiServer


class _LegacyRouteService:
    """Stateful double used only behind the real loopback HTTP server."""

    def __init__(self) -> None:
        self.account = {
            "id": "account-1",
            "username": "MatrixUser",
            "alias": "",
            "description": "",
            "custom_fields": {"xp": "10"},
            "group_id": "group-1",
        }

    def list_accounts(self, _query=None):
        return [dict(self.account)]

    def list_groups(self):
        return [{"id": "group-1", "name": "Matrix"}]

    def launch_account(self, account_id, target):
        return {"account_id": account_id, "accepted": True, "target": dict(target)}

    def search_players(self, username, limit=1):
        return [{"user_id": 99, "name": username}][:limit]

    def get_player_presence(self, _user_id):
        return {"place_id": 123, "job_id": "job-matrix"}

    def update_account(self, _account_id, values):
        self.account.update(values)
        return dict(self.account)

    def get_random_server(self, place_id):
        return {"place_id": place_id, "job_id": "job-random"}

    def block_account_user(self, account_id, target_id):
        return {"account_id": account_id, "target_user_id": target_id, "success": True}

    def unblock_account_user(self, account_id, target_id):
        return {"account_id": account_id, "target_user_id": target_id, "success": True}

    def get_account_cookie(self, account_id):
        return {"account_id": account_id, "cookie": "test-cookie-placeholder"}

    def unblock_all_account_users(self, account_id):
        return {"account_id": account_id, "success": True}

    def get_account_blocked_list(self, _account_id):
        return []

    def set_account_avatar(self, account_id, asset_ids):
        return {"account_id": account_id, "asset_ids": asset_ids, "success": True}

    def get_account_csrf_token(self, account_id):
        return {"account_id": account_id, "csrf_token": "test-csrf-placeholder"}

    def add_account_from_cookie(self, _cookie):
        return dict(self.account)


LEGACY_ROUTES = (
    "/LaunchAccount?Account=MatrixUser&PlaceId=123",
    "/FollowUser?Account=MatrixUser&User=TargetUser",
    "/SetServer?Account=MatrixUser&PlaceId=123&JobId=job-1",
    "/SetRecommendedServer?Account=MatrixUser&PlaceId=123",
    "/BlockUser?Account=MatrixUser&UserId=99",
    "/UnblockUser?Account=MatrixUser&UserId=99",
    "/GetCookie?Account=MatrixUser",
    "/GetField?Account=MatrixUser&Field=xp",
    "/SetField?Account=MatrixUser&Field=rank&Value=7",
    "/SetAlias?Account=MatrixUser&Alias=QA",
    "/UnblockEveryone?Account=MatrixUser",
    "/GetBlockedList?Account=MatrixUser",
    "/RemoveField?Account=MatrixUser&Field=rank",
    "/GetAlias?Account=MatrixUser",
    "/SetDescription?Account=MatrixUser&Description=Matrix",
    "/GetDescription?Account=MatrixUser",
    "/AppendDescription?Account=MatrixUser&Description=QA",
    "/SetAvatar?Account=MatrixUser&AssetId=1234",
    "/GetAccounts?Group=Matrix",
    "/GetAccountsJson?Group=Matrix",
    "/GetCSRFToken?Account=MatrixUser",
    "/ImportCookie?Cookie=test-cookie-placeholder",
)


@pytest.mark.parametrize("route", LEGACY_ROUTES, ids=lambda route: route.split("?", 1)[0].lstrip("/"))
def test_each_legacy_route_is_reachable_over_authenticated_loopback_http(route: str) -> None:
    service = _LegacyRouteService()
    token = "matrix-route-token-0123456789abcdef"
    api = LoopbackApiServer(service, token=token, port=0)  # type: ignore[arg-type]
    status = api.start()
    try:
        request = Request(
            f"{status.base_url}{route}",
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            assert response.status == 200
            assert "data" in payload
    finally:
        api.stop()


def test_legacy_route_matrix_contains_all_22_ram_routes() -> None:
    assert len(LEGACY_ROUTES) == 22


def _read_http(api: LoopbackApiServer, path: str, token: str) -> tuple[int, str, str]:
    status = api.status
    request = Request(
        f"http://127.0.0.1:{status.port}{path}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    with urlopen(request, timeout=5) as response:
        return (
            response.status,
            response.headers.get_content_type(),
            response.read().decode("utf-8"),
        )


def test_historical_root_v2_and_modern_contracts_are_kept_separate() -> None:
    service = _LegacyRouteService()
    token = "matrix-shape-token-0123456789abcdef"
    api = LoopbackApiServer(service, token=token, port=0)  # type: ignore[arg-type]
    api.start()
    try:
        status, content_type, body = _read_http(api, "/GetAccounts?Group=Matrix", token)
        assert status == 200
        assert content_type == "text/plain"
        assert body == "MatrixUser"

        status, content_type, body = _read_http(api, "/v2/GetAccounts?Group=Matrix", token)
        assert status == 200
        assert content_type == "text/plain"
        assert json.loads(body) == {"Success": True, "Message": "MatrixUser"}

        status, content_type, body = _read_http(api, "/api/v1/GetAccounts?Group=Matrix", token)
        assert status == 200
        assert content_type == "application/json"
        assert json.loads(body) == {"data": {"accounts": ["MatrixUser"]}}

        _, _, body = _read_http(api, "/GetAlias?Account=MatrixUser", token)
        assert body == ""
        _, _, body = _read_http(api, "/GetField?Account=MatrixUser&Field=xp", token)
        assert body == "10"
        _, _, body = _read_http(api, "/GetCookie?Account=MatrixUser", token)
        assert body == "test-cookie-placeholder"
        _, _, body = _read_http(api, "/GetCSRFToken?Account=MatrixUser", token)
        assert body == "test-csrf-placeholder"
    finally:
        api.stop()


@pytest.mark.parametrize("route", LEGACY_ROUTES, ids=lambda route: "raw-" + route.split("?", 1)[0].lstrip("/"))
def test_each_historical_root_route_returns_text_plain(route: str) -> None:
    service = _LegacyRouteService()
    token = "matrix-raw-token-0123456789abcdef"
    api = LoopbackApiServer(service, token=token, port=0)  # type: ignore[arg-type]
    api.start()
    try:
        status, content_type, _body = _read_http(api, route, token)
        assert status == 200
        assert content_type == "text/plain"
    finally:
        api.stop()
