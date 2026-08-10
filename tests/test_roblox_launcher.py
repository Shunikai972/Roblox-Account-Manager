from __future__ import annotations

import pytest

from app.backend.core.errors import ValidationError
from app.backend.roblox.errors import RobloxLaunchError
from app.backend.roblox.launcher import WindowsRobloxLauncher
from app.backend.roblox.types import LaunchTarget


def test_launcher_builds_encoded_registered_protocol_uri_only() -> None:
    launcher = WindowsRobloxLauncher(
        opener=lambda _: None,
        platform_name=lambda: "Windows",
        protocol_checker=lambda: True,
    )

    result = launcher.launch(LaunchTarget(place_id=123, job_id="a1b2-c3d4"))

    assert result.launched is True
    assert result.uri == "roblox://experiences/start?placeId=123&gameInstanceId=a1b2-c3d4"
    assert "cookie" not in result.uri.casefold()
    assert "token" not in result.uri.casefold()


def test_launcher_hands_uri_to_injected_windows_opener() -> None:
    opened: list[str] = []
    launcher = WindowsRobloxLauncher(
        opener=opened.append,
        platform_name=lambda: "Windows",
        protocol_checker=lambda: True,
    )

    launcher.launch(LaunchTarget(place_id=555))

    assert opened == ["roblox://experiences/start?placeId=555"]


def test_launcher_requires_windows_and_registered_protocol() -> None:
    unsupported = WindowsRobloxLauncher(
        opener=lambda _: None,
        platform_name=lambda: "Linux",
        protocol_checker=lambda: True,
    )
    missing_protocol = WindowsRobloxLauncher(
        opener=lambda _: None,
        platform_name=lambda: "Windows",
        protocol_checker=lambda: False,
    )

    with pytest.raises(RobloxLaunchError):
        unsupported.launch(LaunchTarget(place_id=1))
    with pytest.raises(RobloxLaunchError):
        missing_protocol.launch(LaunchTarget(place_id=1))


@pytest.mark.parametrize("job_id", ["bad&arg=1", "with space", "../../bad", ""])
def test_launcher_rejects_untrusted_job_id(job_id: str) -> None:
    launcher = WindowsRobloxLauncher(
        opener=lambda _: None,
        platform_name=lambda: "Windows",
        protocol_checker=lambda: True,
    )

    with pytest.raises(ValidationError):
        launcher.build_uri(LaunchTarget(place_id=1, job_id=job_id))

