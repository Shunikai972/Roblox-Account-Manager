from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.backend.roblox.errors import RobloxServiceError
from app.backend.roblox.player_search import PlayerSearchService


def test_find_player_server_matches_historical_thumbnail_algorithm() -> None:
    client = MagicMock()
    client.get_public_profile.return_value = SimpleNamespace(
        avatar_url="https://tr.rbxcdn.com/target/headshot.png"
    )
    client._request_json.side_effect = [
        {
            "data": [
                {
                    "id": "server-one",
                    "playerTokens": ["opaque-a"],
                    "playing": 1,
                    "maxPlayers": 20,
                    "ping": 45,
                }
            ],
            "nextPageCursor": "next-page",
        },
        {
            "data": [
                {
                    "id": "server-two",
                    "playerTokens": ["opaque-b", "opaque-c"],
                    "playing": 2,
                    "maxPlayers": 20,
                    "ping": 61,
                }
            ],
            "nextPageCursor": None,
        },
    ]
    client._post_json.side_effect = [
        {"data": [{"imageUrl": "https://tr.rbxcdn.com/someone/else.png"}]},
        {
            "data": [
                {"imageUrl": "https://tr.rbxcdn.com/someone/else.png"},
                {"imageUrl": "https://tr.rbxcdn.com/target/headshot.png"},
            ]
        },
    ]

    result = PlayerSearchService(client).find_player_server(1234, 5678, max_pages=4)

    assert result == {
        "job_id": "server-two",
        "place_id": 1234,
        "playing": 2,
        "capacity": 20,
        "ping": 61.0,
    }
    assert client._request_json.call_count == 2
    batch = client._post_json.call_args.kwargs["json_body"]
    assert batch[1]["requestId"] == "0:opaque-c:AvatarHeadshot:48x48:png:regular"
    assert "opaque-c" not in result.values()


def test_find_player_server_is_bounded_and_validates_inputs() -> None:
    client = MagicMock()
    client.get_public_profile.return_value = SimpleNamespace(
        avatar_url="https://tr.rbxcdn.com/target.png"
    )
    client._request_json.return_value = {"data": [], "nextPageCursor": "again"}
    service = PlayerSearchService(client)

    assert service.find_player_server(1, 2, max_pages=2) is None
    assert client._request_json.call_count == 2
    with pytest.raises(RobloxServiceError, match="PlaceId"):
        service.find_player_server(0, 2)
    with pytest.raises(RobloxServiceError, match="page limit"):
        service.find_player_server(1, 2, max_pages=0)

