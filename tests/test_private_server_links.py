"""Private server links: classic VIP links and the newer share links.

A share link (``/share?code=...&type=Server``) carries no place id at all, so
Astro used to answer "the link isn't valid" for a link that works perfectly in a
browser.  These tests pin the parsing, the resolution, and every failure message
the user can meet, without touching the network.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.backend.core.config import AppPaths
from app.backend.core.errors import ValidationError
from app.backend.roblox.auth_tools import read_private_server_invite
from app.backend.roblox.errors import RobloxServiceError
from app.backend.roblox.private_servers import PrivateServerHelper
from app.backend.roblox.types import LaunchResult
from app.backend.services import ApplicationService

# The exact link shape reported from the field.
SHARE_LINK = "https://www.roblox.com/share?code=e5aa1e62b747164fbedfc291d11ac9ad&type=Server"
SHARE_CODE = "e5aa1e62b747164fbedfc291d11ac9ad"
CLASSIC_LINK = "https://www.roblox.com/games/920587237/Bug?privateServerLinkCode=abcdef123456"


class _Monitor:
    def scan(self) -> SimpleNamespace:
        return SimpleNamespace(instances=(), events=())

    def current_instances(self) -> tuple[object, ...]:
        return ()


class _Roblox:
    def close(self) -> None:
        return None


class _Launcher:
    def __init__(self) -> None:
        self.launches: list[object] = []

    def launch(self, target: object) -> LaunchResult:
        self.launches.append(target)
        return LaunchResult(uri="roblox://experiences/start?placeId=1", launched=True)


class _ClientSettings:
    settings_file = Path("ClientAppSettings.json")

    def get_fps_cap(self) -> int | None:
        return None

    def set_fps_cap(self, fps: int) -> bool:
        return False

    def remove_fps_cap(self) -> bool:
        return False

    def patch_launch_settings(self, fps: int | None = None, potato_graphics: bool = False) -> bool:
        return False

    def verify_fps_targets(self) -> list[dict[str, object]]:
        return []

    def status(self) -> dict[str, object]:
        return {"available": False, "reason": "test double"}


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


def _service(tmp_path: Path) -> ApplicationService:
    return ApplicationService(
        paths=_paths(tmp_path),
        roblox=_Roblox(),  # type: ignore[arg-type]
        launcher=_Launcher(),  # type: ignore[arg-type]
        monitor=_Monitor(),  # type: ignore[arg-type]
        client_settings=_ClientSettings(),  # type: ignore[arg-type]
    )


def test_a_share_link_is_recognised_instead_of_being_called_invalid() -> None:
    """The reported link parses, and says out loud that Roblox must expand it."""

    parsed = PrivateServerHelper.parse_vip_link(SHARE_LINK)

    assert parsed is not None, "a working share link was rejected"
    assert parsed["share_code"] == SHARE_CODE
    assert parsed["link_type"] == "server"
    assert parsed["needs_resolution"] is True


def test_the_classic_vip_link_still_launches_without_any_lookup() -> None:
    parsed = PrivateServerHelper.parse_vip_link(CLASSIC_LINK)

    assert parsed == {"place_id": 920587237, "link_code": "abcdef123456"}
    assert "needs_resolution" not in parsed


def test_links_from_other_sites_are_still_refused() -> None:
    assert PrivateServerHelper.parse_vip_link("https://roblox.evil.com/share?code=aaaaaaaaaaaa") is None
    assert PrivateServerHelper.parse_vip_link("not a link") is None
    assert PrivateServerHelper.parse_vip_link("https://www.roblox.com/share?code=short") is None


def test_roblox_answers_are_read_into_a_place_and_a_code() -> None:
    resolved = read_private_server_invite(
        {
            "privateServerInviteData": {
                "status": "Valid",
                "placeId": 920587237,
                "linkCode": "abcdef123456",
            }
        }
    )

    assert resolved["place_id"] == 920587237
    assert resolved["link_code"] == "abcdef123456"


def test_an_expired_invite_says_expired_rather_than_invalid() -> None:
    with pytest.raises(RobloxServiceError) as failure:
        read_private_server_invite(
            {"privateServerInviteData": {"status": "Expired", "placeId": 1, "linkCode": "abc"}}
        )

    assert "expired" in str(failure.value).lower()


def test_a_share_link_to_something_else_is_named_for_what_it_is() -> None:
    with pytest.raises(RobloxServiceError) as failure:
        read_private_server_invite({"profileLinkResolutionResponseData": {"userId": 1}})

    assert "private server" in str(failure.value).lower()


def test_launching_a_share_link_resolves_it_with_the_joining_account(tmp_path: Path) -> None:
    """End to end: paste the reported link, land on the right private server."""

    service = _service(tmp_path)
    try:
        account_id = service.create_account({"username": "ShareJoiner"})["id"]
        seen: dict[str, object] = {}

        def fake_cookie(target_id: str) -> str:
            seen["cookie_for"] = target_id
            return "session-value"

        def fake_resolve(cookie: str, code: str) -> dict[str, object]:
            seen["cookie"] = cookie
            seen["code"] = code
            return {"place_id": 920587237, "link_code": "abcdef123456", "status": "Valid"}

        def fake_launch(target_id: str, target: dict[str, object]) -> dict[str, object]:
            seen["launch"] = (target_id, target)
            return {"launched": True}

        service._get_account_cookie_raw = fake_cookie  # type: ignore[assignment]
        service.auth_tools.resolve_share_link = fake_resolve  # type: ignore[assignment]
        service.launch_account = fake_launch  # type: ignore[assignment]

        result = service.launch_account_from_private_link(account_id, SHARE_LINK)

        assert result == {"launched": True}
        assert seen["cookie_for"] == account_id
        assert seen["cookie"] == "session-value"
        assert seen["code"] == SHARE_CODE
        assert seen["launch"] == (
            account_id,
            {"place_id": 920587237, "private_server_link_code": "abcdef123456"},
        )
    finally:
        service.close()


def test_a_share_link_that_points_at_a_profile_is_refused_clearly(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        account_id = service.create_account({"username": "WrongLink"})["id"]

        with pytest.raises(ValidationError) as failure:
            service.launch_account_from_private_link(
                account_id, "https://www.roblox.com/share?code=" + SHARE_CODE + "&type=Profile"
            )

        assert "profile" in str(failure.value).lower()
    finally:
        service.close()


def test_a_share_link_without_a_stored_session_blames_the_session_not_the_link(tmp_path: Path) -> None:
    """The account has no session, so say that instead of "invalid link"."""

    service = _service(tmp_path)
    try:
        account_id = service.create_account({"username": "NoSession"})["id"]

        with pytest.raises(ValidationError) as failure:
            service.launch_account_from_private_link(account_id, SHARE_LINK)

        message = str(failure.value).lower()
        assert "session" in message
        assert "valid roblox.com private server link" not in message
    finally:
        service.close()


def test_an_empty_or_broken_link_still_gets_the_plain_message(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        account_id = service.create_account({"username": "BadLink"})["id"]

        with pytest.raises(ValidationError) as failure:
            service.launch_account_from_private_link(account_id, "https://example.com/nope")

        assert "valid roblox.com private server link" in str(failure.value).lower()
    finally:
        service.close()
