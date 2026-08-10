from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from requests.cookies import RequestsCookieJar

from app.backend.core.errors import NotFoundError, ValidationError
from app.backend.roblox.client import RobloxClient, SessionRobloxClient
from app.backend.roblox.errors import RobloxAuthenticationError, RobloxServiceError
from app.backend.roblox.types import PresenceState, ServerSortOrder


class FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class ScriptedSession:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, Mapping[str, object] | None, float]] = []
        self.post_calls: list[tuple[str, Mapping[str, object], float]] = []
        self.headers: dict[str, str] = {}
        self.cookies = RequestsCookieJar()
        self.closed = False

    def get(
        self, url: str, *, params: Mapping[str, object] | None, timeout: float
    ) -> FakeResponse:
        self.calls.append((url, params, timeout))
        next_response = self._responses.pop(0)
        if isinstance(next_response, Exception):
            raise next_response
        return next_response

    def post(self, url: str, *, json: Mapping[str, object], timeout: float) -> FakeResponse:
        self.post_calls.append((url, json, timeout))
        next_response = self._responses.pop(0)
        if isinstance(next_response, Exception):
            raise next_response
        return next_response

    def close(self) -> None:
        self.closed = True


def test_game_details_resolve_place_then_return_typed_domain_game() -> None:
    session = ScriptedSession(
        [
            FakeResponse(200, {"universeId": 99}),
            FakeResponse(
                200,
                {
                    "data": [
                        {
                            "id": 99,
                            "rootPlaceId": 123,
                            "name": "Asteria Arena",
                            "description": "Team game",
                            "creator": {"id": 44, "name": "Builder"},
                            "playing": 24,
                            "maxPlayers": 30,
                            "visits": 4500,
                        }
                    ]
                },
            ),
        ]
    )
    client = RobloxClient(session=session, retry_attempts=0)

    game = client.get_game_details(123)

    assert game.place_id == 123
    assert game.universe_id == 99
    assert game.name == "Asteria Arena"
    assert game.creator_name == "Builder"
    assert game.metadata["visits"] == 4500
    assert session.calls[0][0].endswith("/universes/v1/places/123/universe")
    assert session.calls[1][1] == {"universeIds": 99}


def test_missing_game_is_a_safe_not_found_error() -> None:
    session = ScriptedSession(
        [FakeResponse(200, {"universeId": 99}), FakeResponse(200, {"data": []})]
    )

    with pytest.raises(NotFoundError):
        RobloxClient(session=session, retry_attempts=0).get_game_details(123)


def test_search_games_handles_legacy_shape_and_skips_malformed_entries() -> None:
    session = ScriptedSession(
        [
            FakeResponse(
                200,
                {
                    "games": [
                        {"universeId": 1, "placeId": 2, "name": "Moon Farm"},
                        {"name": "missing ids"},
                    ]
                },
            )
        ]
    )

    games = RobloxClient(session=session, retry_attempts=0).search_games("  Moon   Farm  ")

    assert [(game.universe_id, game.place_id, game.name) for game in games] == [
        (1, 2, "Moon Farm")
    ]
    assert session.calls[0][1] == {
        "model.keyword": "Moon Farm",
        "model.startRows": 0,
        "model.maxRows": 20,
        "model.sortOrder": 1,
    }


def test_server_page_is_typed_and_does_not_surface_player_tokens() -> None:
    session = ScriptedSession(
        [
            FakeResponse(
                200,
                {
                    "data": [
                        {
                            "id": "job-123",
                            "playing": 4,
                            "maxPlayers": 12,
                            "ping": 42.5,
                            "fps": 59.8,
                            "playerTokens": ["opaque-player-token"],
                        }
                    ],
                    "nextPageCursor": "next-page",
                    "previousPageCursor": None,
                },
            )
        ]
    )

    page = RobloxClient(session=session, retry_attempts=0).list_public_servers(
        123, cursor="cursor-1", limit=50, sort_order=ServerSortOrder.DESCENDING
    )

    assert page.next_page_cursor == "next-page"
    assert page.previous_page_cursor is None
    assert len(page.servers) == 1
    assert page.servers[0].job_id == "job-123"
    assert page.servers[0].player_tokens == []
    assert session.calls[0][1] == {
        "sortOrder": "Desc",
        "limit": 50,
        "cursor": "cursor-1",
    }


def test_client_retries_transient_errors_with_a_bounded_backoff() -> None:
    delays: list[float] = []
    session = ScriptedSession(
        [FakeResponse(503, {"detail": "irrelevant"}), FakeResponse(200, {"universeId": 88})]
    )

    universe_id = RobloxClient(
        session=session, retry_attempts=1, retry_backoff_seconds=0.1, sleep=delays.append
    ).get_universe_id(123)

    assert universe_id == 88
    assert delays == [0.1]
    assert len(session.calls) == 2


def test_errors_do_not_reflect_response_secret_text() -> None:
    secret = "_ROBLOSECURITY-not-for-output"
    session = ScriptedSession([FakeResponse(500, {"message": f"cookie={secret}"})])

    with pytest.raises(RobloxServiceError) as captured:
        RobloxClient(session=session, retry_attempts=0).get_universe_id(123)

    assert secret not in str(captured.value)
    assert secret not in str(captured.value.as_dict())


def test_session_client_authenticates_without_exposing_cookie_and_clears_on_close() -> None:
    secret = "opaque-cookie-value"
    session = ScriptedSession(
        [FakeResponse(200, {"id": 42, "name": "nova", "displayName": "Nova"})]
    )
    client = SessionRobloxClient(secret, session=session, retry_attempts=0)

    identity = client.authenticated_user()

    assert identity.user_id == 42
    assert identity.username == "nova"
    assert secret not in repr(client)
    assert session.cookies.get(".ROBLOSECURITY", domain=".roblox.com", path="/") == secret
    client.close()
    assert session.cookies.get(".ROBLOSECURITY", domain=".roblox.com", path="/") is None
    assert session.closed is True


def test_session_auth_failure_is_redacted_and_actionable() -> None:
    session = ScriptedSession([FakeResponse(401, {"message": "cookie=do-not-show"})])
    client = SessionRobloxClient("opaque-cookie", session=session, retry_attempts=0)

    with pytest.raises(RobloxAuthenticationError) as captured:
        client.authenticated_user()

    assert "do-not-show" not in str(captured.value)
    assert captured.value.code == "roblox_authentication_error"


def test_public_profile_combines_identity_and_headshot_with_a_bounded_cache() -> None:
    session = ScriptedSession(
        [
            FakeResponse(
                200,
                {
                    "id": 42,
                    "name": "nova",
                    "displayName": "Nova",
                    "description": "A public profile",
                    "created": "2020-01-01T00:00:00Z",
                    "isBanned": False,
                    "hasVerifiedBadge": True,
                },
            ),
            FakeResponse(
                200,
                {
                    "data": [
                        {
                            "targetId": 42,
                            "state": "Completed",
                            "imageUrl": "https://tr.rbxcdn.com/public-avatar/150/150/AvatarHeadshot/Png",
                        }
                    ]
                },
            ),
        ]
    )
    client = RobloxClient(session=session, retry_attempts=0)

    profile = client.get_public_profile(42)
    cached = client.get_public_profile(42)

    assert profile == cached
    assert profile.username == "nova"
    assert profile.avatar_url == "https://tr.rbxcdn.com/public-avatar/150/150/AvatarHeadshot/Png"
    assert profile.profile_url == "https://www.roblox.com/users/42/profile"
    assert len(session.calls) == 2
    assert session.calls[0][0].endswith("/v1/users/42")
    assert session.calls[1][1] == {
        "userIds": 42,
        "size": "150x150",
        "format": "Png",
        "isCircular": "false",
    }


def test_public_profile_keeps_identity_when_thumbnail_is_unavailable() -> None:
    session = ScriptedSession(
        [
            FakeResponse(200, {"id": 12, "name": "avatarless"}),
            FakeResponse(503, {"message": "temporary CDN failure"}),
        ]
    )

    profile = RobloxClient(session=session, retry_attempts=0).get_public_profile(12)

    assert profile.username == "avatarless"
    assert profile.avatar_url is None
    assert profile.avatar_state == "Unavailable"


def test_public_profile_cache_expires_with_monotonic_time() -> None:
    now = [100.0]
    session = ScriptedSession(
        [
            FakeResponse(200, {"id": 9, "name": "first"}),
            FakeResponse(200, {"data": [{"targetId": 9, "state": "Completed"}]}),
            FakeResponse(200, {"id": 9, "name": "second"}),
            FakeResponse(200, {"data": [{"targetId": 9, "state": "Completed"}]}),
        ]
    )
    client = RobloxClient(
        session=session,
        retry_attempts=0,
        clock=lambda: now[0],
        profile_cache_ttl_seconds=5,
    )

    assert client.get_public_profile(9).username == "first"
    now[0] += 5
    assert client.get_public_profile(9).username == "second"
    assert len(session.calls) == 4


def test_public_profile_rejects_a_non_roblox_avatar_url() -> None:
    session = ScriptedSession(
        [
            FakeResponse(200, {"id": 91, "name": "safe-avatar"}),
            FakeResponse(
                200,
                {
                    "data": [
                        {
                            "targetId": 91,
                            "state": "Completed",
                            "imageUrl": "https://example.invalid/avatar.png",
                        }
                    ]
                },
            ),
        ]
    )

    profile = RobloxClient(session=session, retry_attempts=0).get_public_profile(91)

    assert profile.avatar_url is None
    assert profile.avatar_state == "Unavailable"


def test_public_presence_posts_a_validated_batch_and_reuses_short_cache() -> None:
    session = ScriptedSession(
        [
            FakeResponse(
                200,
                {
                    "userPresences": [
                        {
                            "userId": 42,
                            "userPresenceType": 2,
                            "lastLocation": "Example world",
                            "placeId": 123,
                            "rootPlaceId": 123,
                            "gameId": "job-123",
                            "universeId": 99,
                            "lastOnline": "2026-08-10T12:00:00Z",
                        },
                        {"userId": 77, "userPresenceType": 0, "lastLocation": "Offline"},
                        {"userId": 999, "userPresenceType": 2},
                    ]
                },
            )
        ]
    )
    client = RobloxClient(session=session, retry_attempts=0)

    first = client.get_public_presence([42, 77, 42])
    second = client.get_public_presence([42, 77])

    assert [entry.user_id for entry in first] == [42, 77]
    assert first[0].state is PresenceState.IN_GAME
    assert first[0].place_id == 123
    assert second == first
    assert session.post_calls == [
        (
            "https://presence.roblox.com/v1/presence/users",
            {"userIds": [42, 77]},
            10.0,
        )
    ]


def test_public_presence_rejects_oversized_or_non_numeric_batches() -> None:
    client = RobloxClient(session=ScriptedSession([]), retry_attempts=0)

    with pytest.raises(ValidationError):
        client.get_public_presence(list(range(1, 52)))
    with pytest.raises(ValidationError):
        client.get_public_presence(["42"])  # type: ignore[list-item]


@pytest.mark.parametrize("bad_id", [0, -1, True, "123"])
def test_identifiers_are_strictly_validated(bad_id: object) -> None:
    with pytest.raises(ValidationError):
        RobloxClient(session=ScriptedSession([])).get_universe_id(bad_id)  # type: ignore[arg-type]
