"""Bounded, opt-in server-region resolution compatible with RAM 3.7.2."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
import ipaddress
import json
import threading
import time
from typing import Any, Callable, Final
from urllib.parse import urlsplit

import requests


Clock = Callable[[], float]
FetchJson = Callable[[str, float], Mapping[str, Any]]

DEFAULT_PROVIDER_URL: Final = "http://ip-api.com/json/{ip}"
DEFAULT_REGION_FORMAT: Final = "{city}, {country}"
DEFAULT_TIMEOUT_SECONDS: Final = 4.0
DEFAULT_CACHE_TTL_SECONDS: Final = 900.0
DEFAULT_NEGATIVE_CACHE_TTL_SECONDS: Final = 120.0
DEFAULT_CACHE_SIZE: Final = 512
MAX_BATCH_ADDRESSES: Final = 100
MAX_RESPONSE_BYTES: Final = 64 * 1024

_MAX_REGION_LENGTH: Final = 80
_ALLOWED_FIELDS: Final = (
    "city",
    "regionName",
    "region",
    "country",
    "countryCode",
    "continent",
)


@dataclass(frozen=True, slots=True)
class RegionLookupSettings:
    """Validated settings for the historical server-region column."""

    enabled: bool = False
    provider_url: str = DEFAULT_PROVIDER_URL
    region_format: str = DEFAULT_REGION_FORMAT
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any] | None) -> "RegionLookupSettings":
        data = dict(values or {})
        return cls(
            enabled=bool(data.get("region_lookup_enabled", False)),
            provider_url=_bounded_url(
                data.get("region_lookup_provider"), DEFAULT_PROVIDER_URL
            ),
            region_format=_bounded_format(
                data.get("region_lookup_format"), DEFAULT_REGION_FORMAT
            ),
            timeout_seconds=_bounded_number(
                data.get("region_lookup_timeout_seconds"),
                DEFAULT_TIMEOUT_SECONDS,
                0.5,
                30.0,
            ),
            cache_ttl_seconds=_bounded_number(
                data.get("region_cache_ttl_seconds"),
                DEFAULT_CACHE_TTL_SECONDS,
                30.0,
                86_400.0,
            ),
        )


class RequestsRegionTransport:
    """Small JSON transport with redirect, size and timeout bounds.

    It performs no request until region lookup is explicitly enabled and a
    public server address is available. URLs and addresses are never logged.
    """

    def __init__(self, session: requests.Session | Any | None = None) -> None:
        self._session = session or requests.Session()

    def __call__(self, url: str, timeout: float) -> Mapping[str, Any]:
        response = self._session.get(
            url,
            timeout=float(timeout),
            allow_redirects=False,
            stream=True,
            headers={
                "Accept": "application/json",
                "User-Agent": "AstroAccountManager/4.0",
            },
        )
        try:
            response.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=8_192):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    raise ValueError("Region provider response is too large.")
                chunks.append(bytes(chunk))
            payload = json.loads(b"".join(chunks).decode("utf-8"))
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        if not isinstance(payload, Mapping):
            raise ValueError("Region provider response must be a JSON object.")
        return payload


class ServerRegionResolver:
    """Resolve public IP addresses to display regions without surfacing errors."""

    def __init__(
        self,
        *,
        settings: RegionLookupSettings | None = None,
        fetch_json: FetchJson | None = None,
        clock: Clock | None = None,
        cache_size: int = DEFAULT_CACHE_SIZE,
        negative_ttl_seconds: float = DEFAULT_NEGATIVE_CACHE_TTL_SECONDS,
    ) -> None:
        self._settings = settings or RegionLookupSettings()
        self._fetch_json = fetch_json
        self._clock = clock or time.monotonic
        self._cache_size = max(1, int(cache_size))
        self._negative_ttl_seconds = max(1.0, float(negative_ttl_seconds))
        self._entries: OrderedDict[str, tuple[float, str | None]] = OrderedDict()
        self._lock = threading.RLock()
        self._lookups = 0
        self._hits = 0

    @property
    def enabled(self) -> bool:
        return bool(self._settings.enabled)

    @property
    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "lookups": self._lookups,
                "cache_hits": self._hits,
                "cached": len(self._entries),
            }

    def update_settings(self, settings: RegionLookupSettings) -> None:
        with self._lock:
            previous = self._settings
            self._settings = settings
            if (
                previous.provider_url != settings.provider_url
                or previous.region_format != settings.region_format
            ):
                self._entries.clear()

    def resolve(self, address: object) -> str | None:
        if not self._settings.enabled:
            return None
        ip = _public_ip(address)
        if ip is None:
            return None

        cached = self._cache_get(ip)
        if cached is not _MISS:
            with self._lock:
                self._hits += 1
            return cached  # type: ignore[return-value]

        region = self._lookup(ip)
        ttl = (
            self._settings.cache_ttl_seconds
            if region is not None
            else self._negative_ttl_seconds
        )
        self._cache_put(ip, region, ttl)
        return region

    def resolve_many(self, addresses: object) -> dict[str, str | None]:
        if not isinstance(addresses, (list, tuple, set, frozenset)):
            return {}
        unique: list[str] = []
        seen: set[str] = set()
        for candidate in addresses:
            ip = _public_ip(candidate)
            if ip is None or ip in seen:
                continue
            seen.add(ip)
            unique.append(ip)
            if len(unique) >= MAX_BATCH_ADDRESSES:
                break
        return {ip: self.resolve(ip) for ip in unique}

    def annotate_servers(self, servers: object) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not isinstance(servers, (list, tuple)):
            return rows
        for server in servers:
            if not isinstance(server, Mapping):
                continue
            row = dict(server)
            if not row.get("region"):
                address = (
                    row.get("address")
                    or row.get("ip")
                    or row.get("machine_address")
                )
                row["region"] = self.resolve(address)
            rows.append(row)
        return rows

    def _lookup(self, ip: str) -> str | None:
        fetch = self._fetch_json
        if fetch is None:
            return None
        with self._lock:
            self._lookups += 1
            url = self._settings.provider_url.replace("{ip}", ip)
            timeout = self._settings.timeout_seconds
            template = self._settings.region_format
        try:
            payload = fetch(url, timeout)
        except Exception:
            return None
        return _format_region(payload, template)

    def _cache_get(self, ip: str) -> object:
        with self._lock:
            entry = self._entries.get(ip)
            if entry is None:
                return _MISS
            expires_at, value = entry
            if self._clock() >= expires_at:
                self._entries.pop(ip, None)
                return _MISS
            self._entries.move_to_end(ip)
            return value

    def _cache_put(self, ip: str, region: str | None, ttl_seconds: float) -> None:
        with self._lock:
            self._entries[ip] = (self._clock() + float(ttl_seconds), region)
            self._entries.move_to_end(ip)
            while len(self._entries) > self._cache_size:
                self._entries.popitem(last=False)


class _Miss:
    __slots__ = ()


_MISS: Final = _Miss()


def _public_ip(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > 45:
        return None
    if text.count(":") == 1 and "." in text:
        text = text.split(":", 1)[0]
    try:
        parsed = ipaddress.ip_address(text)
    except ValueError:
        return None
    if (
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_multicast
        or parsed.is_reserved
        or parsed.is_unspecified
    ):
        return None
    return str(parsed)


def _format_region(payload: Mapping[str, Any], template: str) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    status = payload.get("status")
    if isinstance(status, str) and status.casefold() != "success":
        return None

    values: dict[str, str] = {}
    for field in _ALLOWED_FIELDS:
        raw = payload.get(field)
        if isinstance(raw, str) and raw.strip():
            values[field] = raw.strip()[:_MAX_REGION_LENGTH]
    if not values:
        return None

    rendered = template
    for field in _ALLOWED_FIELDS:
        rendered = rendered.replace("{" + field + "}", values.get(field, ""))
    rendered = " ".join(rendered.split()).strip(" ,-/|")
    while ", ," in rendered:
        rendered = rendered.replace(", ,", ",")
    rendered = " ".join(rendered.split()).strip(" ,-/|")
    if rendered:
        return rendered[:_MAX_REGION_LENGTH]
    for field in ("regionName", "region", "city", "country", "countryCode", "continent"):
        if field in values:
            return values[field]
    return None


def _bounded_number(value: object, default: float, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    number = float(value)
    if number != number:
        return default
    return min(max(number, minimum), maximum)


def _bounded_url(value: object, default: str) -> str:
    if not isinstance(value, str):
        return default
    text = value.strip()
    if not text or len(text) > 300 or "{ip}" not in text:
        return default
    try:
        parsed = urlsplit(text.replace("{ip}", "1.1.1.1"))
    except ValueError:
        return default
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return default
    if parsed.username or parsed.password or parsed.fragment:
        return default
    return text


def _bounded_format(value: object, default: str) -> str:
    if not isinstance(value, str):
        return default
    text = value.strip()
    if not text or len(text) > 120:
        return default
    return text
