from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.backend.core.updater import CURRENT_VERSION, UpdateChecker, _version_key


def test_version_comparison_handles_prereleases_semantically() -> None:
    assert _version_key("4.0.0") > _version_key("4.0.0rc2") > _version_key("4.0.0b9") > _version_key("4.0.0a1")
    assert _version_key("4.0.10") > _version_key("4.0.9")
    assert _version_key("not-a-version") is None


@patch("app.backend.core.updater.requests.get")
def test_update_checker_uses_astro_version_and_semantic_release_order(mock_get: MagicMock) -> None:
    response = MagicMock(status_code=200)
    response.json.return_value = {"tag_name": "v4.0.0", "body": "stable", "html_url": "https://example.invalid/release"}
    mock_get.return_value = response

    result = UpdateChecker.check_for_updates()

    assert result["current_version"] == CURRENT_VERSION == "4.0.0a1"
    assert result["latest_version"] == "4.0.0"
    assert result["update_available"] is True
