from __future__ import annotations

import pytest

from app.backend.core.config import AppPaths
from app.backend.roblox.types import LaunchResult
from app.backend.services import ApplicationService

from app.backend.roblox.server_region import (
    DEFAULT_CACHE_TTL_SECONDS,
    DEFAULT_PROVIDER_URL,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_BATCH_ADDRESSES,
    MAX_RESPONSE_BYTES,
    RegionLookupSettings,
    RequestsRegionTransport,
    ServerRegionResolver,
)


PUBLIC_IP = "128.116.0.1"
SUCCESS = {
    "status": "success",
    "city": "Ashburn",
    "regionName": "Virginia",
    "country": "United States",
    "countryCode": "US",
}


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class RecordingFetch:
    def __init__(self, payload=None, error=None) -> None:
        self.payload = SUCCESS if payload is None else payload
        self.error = error
        self.calls: list[tuple[str, float]] = []

    def __call__(self, url: str, timeout: float):
        self.calls.append((url, timeout))
        if self.error is not None:
            raise self.error
        return self.payload


@pytest.fixture
def enabled() -> RegionLookupSettings:
    return RegionLookupSettings(enabled=True)


def test_historical_provider_and_defaults_are_opt_in():
    assert DEFAULT_PROVIDER_URL.endswith("/json/{ip}")
    assert RegionLookupSettings().enabled is False


def test_disabled_lookup_never_calls_transport():
    fetch = RecordingFetch()
    resolver = ServerRegionResolver(fetch_json=fetch)
    assert resolver.resolve(PUBLIC_IP) is None
    assert fetch.calls == []


def test_resolve_formats_region_and_passes_timeout(enabled):
    fetch = RecordingFetch()
    resolver = ServerRegionResolver(settings=enabled, fetch_json=fetch)
    assert resolver.resolve(PUBLIC_IP) == "Ashburn, United States"
    assert fetch.calls == [(DEFAULT_PROVIDER_URL.replace("{ip}", PUBLIC_IP), DEFAULT_TIMEOUT_SECONDS)]


def test_custom_format_and_missing_fields_are_cleaned():
    settings = RegionLookupSettings(enabled=True, region_format="{regionName} ({countryCode})")
    assert ServerRegionResolver(settings=settings, fetch_json=RecordingFetch()).resolve(PUBLIC_IP) == "Virginia (US)"
    settings = RegionLookupSettings(enabled=True, region_format="{city}, {country}")
    resolver = ServerRegionResolver(
        settings=settings,
        fetch_json=RecordingFetch({"status": "success", "country": "Japan"}),
    )
    assert resolver.resolve(PUBLIC_IP) == "Japan"


def test_cache_hits_and_expires(enabled):
    clock = FakeClock()
    fetch = RecordingFetch()
    resolver = ServerRegionResolver(settings=enabled, fetch_json=fetch, clock=clock)
    assert resolver.resolve(PUBLIC_IP)
    assert resolver.resolve(PUBLIC_IP)
    assert len(fetch.calls) == 1
    assert resolver.stats["cache_hits"] == 1
    clock.advance(DEFAULT_CACHE_TTL_SECONDS + 1)
    assert resolver.resolve(PUBLIC_IP)
    assert len(fetch.calls) == 2


def test_cache_is_lru_bounded(enabled):
    resolver = ServerRegionResolver(
        settings=enabled,
        fetch_json=RecordingFetch(),
        cache_size=2,
    )
    for suffix in (1, 2, 3):
        resolver.resolve(f"128.116.0.{suffix}")
    assert resolver.stats["cached"] == 2


@pytest.mark.parametrize(
    "error",
    [TimeoutError("timeout"), OSError("offline"), ValueError("bad json")],
)
def test_transport_errors_degrade_to_none(enabled, error):
    resolver = ServerRegionResolver(settings=enabled, fetch_json=RecordingFetch(error=error))
    assert resolver.resolve(PUBLIC_IP) is None


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "192.168.1.1",
        "169.254.1.1",
        "0.0.0.0",
        "::1",
        "fe80::1",
        "not-an-ip",
        "",
        None,
        123,
    ],
)
def test_internal_or_invalid_addresses_never_leave_the_machine(enabled, address):
    fetch = RecordingFetch()
    resolver = ServerRegionResolver(settings=enabled, fetch_json=fetch)
    assert resolver.resolve(address) is None
    assert fetch.calls == []


def test_host_port_batch_and_annotation(enabled):
    resolver = ServerRegionResolver(settings=enabled, fetch_json=RecordingFetch())
    assert resolver.resolve(PUBLIC_IP + ":53640") == "Ashburn, United States"
    result = resolver.resolve_many([PUBLIC_IP, PUBLIC_IP, "10.0.0.1", "128.116.0.2"])
    assert set(result) == {PUBLIC_IP, "128.116.0.2"}
    rows = resolver.annotate_servers(
        [
            {"job_id": "a", "address": PUBLIC_IP, "region": None},
            {"job_id": "b", "address": "128.116.0.9", "region": "Known"},
            {"job_id": "c"},
        ]
    )
    assert rows[0]["region"] == "Ashburn, United States"
    assert rows[1]["region"] == "Known"
    assert rows[2]["region"] is None


def test_batch_is_bounded(enabled):
    addresses = [f"128.116.{a}.{b}" for a in range(4) for b in range(1, 60)]
    resolver = ServerRegionResolver(settings=enabled, fetch_json=RecordingFetch())
    assert len(resolver.resolve_many(addresses)) == MAX_BATCH_ADDRESSES


@pytest.mark.parametrize(
    "value,expected",
    [(9999, 30.0), (-5, 0.5), ("soon", DEFAULT_TIMEOUT_SECONDS), (True, DEFAULT_TIMEOUT_SECONDS)],
)
def test_timeout_setting_is_bounded(value, expected):
    settings = RegionLookupSettings.from_mapping({"region_lookup_timeout_seconds": value})
    assert settings.timeout_seconds == expected


@pytest.mark.parametrize(
    "provider",
    [
        "file:///etc/passwd",
        "https://example.test/geo",
        "https://user:password@example.test/{ip}",
        "https://example.test/{ip}#fragment",
        "",
        None,
    ],
)
def test_unsafe_or_incomplete_provider_falls_back(provider):
    settings = RegionLookupSettings.from_mapping({"region_lookup_provider": provider})
    assert settings.provider_url == DEFAULT_PROVIDER_URL


def test_valid_custom_provider_and_setting_change():
    custom = "https://example.test/geo/{ip}"
    settings = RegionLookupSettings.from_mapping({"region_lookup_provider": custom})
    assert settings.provider_url == custom
    resolver = ServerRegionResolver(
        settings=RegionLookupSettings(enabled=True),
        fetch_json=RecordingFetch(),
    )
    resolver.resolve(PUBLIC_IP)
    resolver.update_settings(RegionLookupSettings(enabled=True, region_format="{country}"))
    assert resolver.stats["cached"] == 0


class FakeResponse:
    def __init__(self, payload, content: bytes | None = None) -> None:
        self._payload = payload
        import json
        self.content = content if content is not None else json.dumps(payload).encode("utf-8")
        self.raised = False
        self.closed = False

    def raise_for_status(self) -> None:
        self.raised = True

    def iter_content(self, chunk_size=8192):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset : offset + chunk_size]

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_requests_transport_is_bounded_and_disables_redirects():
    response = FakeResponse(SUCCESS)
    session = FakeSession(response)
    transport = RequestsRegionTransport(session)
    assert transport("https://example.test/geo/1.1.1.1", 2.5) == SUCCESS
    _, options = session.calls[0]
    assert options["timeout"] == 2.5
    assert options["allow_redirects"] is False
    assert options["stream"] is True
    assert response.raised is True
    assert response.closed is True


def test_requests_transport_rejects_large_or_non_object_payloads():
    large = FakeResponse(SUCCESS, content=b"x" * (MAX_RESPONSE_BYTES + 1))
    with pytest.raises(ValueError):
        RequestsRegionTransport(FakeSession(large))("https://example.test/{ip}", 1)
    with pytest.raises(ValueError):
        RequestsRegionTransport(FakeSession(FakeResponse([])))("https://example.test/{ip}", 1)


def test_service_authenticated_region_probe_is_bounded_and_redacts_addresses(tmp_path, monkeypatch):
    root = tmp_path / "app-data"
    paths = AppPaths(root, root / "astro.db", root / "logs", root / "backups", root / "cache", root / "exports")
    resolver = ServerRegionResolver(fetch_json=RecordingFetch())
    service = ApplicationService(paths=paths, region_resolver=resolver)
    try:
        account = service.create_account({"username": "RegionUser"})
        service.repository.save_protected_secret(
            account["id"], "session", service.vault.protect(b"region-cookie")
        )
        domain = service.repository.get_account(account["id"])
        domain.has_session = True
        service.repository.save_account(domain)
        service.update_settings(
            {"categories": {"network": {"region_lookup_enabled": True}}}
        )
        calls = []

        def probe(cookie, place_id, job_id):
            calls.append((cookie, place_id, job_id))
            return {"address": "128.116.0.1", "port": None}

        monkeypatch.setattr(service.auth_tools, "probe_server_instance", probe)

        result = service.probe_server_regions(
            account["id"], 2512643572, ["job-one", "job-two"]
        )

        assert result["resolved"] == 2
        assert [row["region"] for row in result["servers"]] == [
            "Ashburn, United States",
            "Ashburn, United States",
        ]
        assert "address" not in result["servers"][0]
        assert calls[0] == ("region-cookie", 2512643572, "job-one")
        with pytest.raises(Exception):
            service.probe_server_regions(account["id"], 1, [f"job-{i}" for i in range(17)])
    finally:
        service.close()
