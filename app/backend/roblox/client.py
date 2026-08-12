"""Small, typed clients for public and session-aware Roblox requests.

Only public game/server metadata and a session's own identity are supported
here.  The client purposefully has no method to retrieve, serialise, log, or
put a ``.ROBLOSECURITY`` value into a launch URI.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
import math
import re
import threading
import time
from typing import Any, Final
from urllib.parse import urlsplit
from uuid import uuid4

import requests

from app.backend.core.errors import NotFoundError, ValidationError
from app.backend.models.domain import Game, Server

from .errors import RobloxAuthenticationError, RobloxServiceError
from .types import (
    AuthenticatedUser,
    PresenceState,
    PublicUserProfile,
    PublicUsernameResolution,
    ServerPage,
    ServerSortOrder,
    UserPresence,
)


JsonMapping = Mapping[str, Any]
Sleep = Callable[[float], None]
Clock = Callable[[], float]

_GAMES_BASE: Final = "https://games.roblox.com"
_UNIVERSES_BASE: Final = "https://apis.roblox.com"
_SEARCH_BASE: Final = "https://apis.roblox.com/search-api"
_USERS_BASE: Final = "https://users.roblox.com"
_THUMBNAILS_BASE: Final = "https://thumbnails.roblox.com"
_PRESENCE_BASE: Final = "https://presence.roblox.com"
_MAX_CURSOR_LENGTH: Final = 2_048
_MAX_SEARCH_LENGTH: Final = 100
_MAX_PAGE_SIZE: Final = 100
_MAX_PRESENCE_USERS: Final = 50
_PROFILE_CACHE_TTL_SECONDS: Final = 300.0
_PRESENCE_CACHE_TTL_SECONDS: Final = 30.0
_PROFILE_CACHE_SIZE: Final = 256
_PRESENCE_CACHE_SIZE: Final = 512
_USERNAME_RESOLUTION_CACHE_TTL_SECONDS: Final = 300.0
_USERNAME_RESOLUTION_CACHE_SIZE: Final = 256
_USERNAME_RESOLUTION_MIN_INTERVAL_SECONDS: Final = 0.25
_SEARCH_CACHE_TTL_SECONDS: Final = 60.0
_SEARCH_CACHE_SIZE: Final = 64
_ROBLOX_USERNAME_PATTERN: Final = re.compile(r"^[A-Za-z0-9_]{3,20}$")


class _TimedCache:
    """Small thread-safe LRU cache with monotonic expiration.

    Public profile and presence lookups can be triggered by several pywebview
    workers at once.  Keeping the cache here avoids storing volatile presence
    in SQLite while bounding memory use and network churn.
    """

    def __init__(self, *, maximum_entries: int, ttl_seconds: float, clock: Clock) -> None:
        self._maximum_entries = maximum_entries
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._entries: OrderedDict[object, tuple[float, Any]] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: object) -> Any | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if self._clock() >= expires_at:
                self._entries.pop(key, None)
                return None
            self._entries.move_to_end(key)
            return value

    def put(self, key: object, value: Any) -> None:
        with self._lock:
            self._entries[key] = (self._clock() + self._ttl_seconds, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self._maximum_entries:
                self._entries.popitem(last=False)


class _RequestRateGate:
    """A tiny monotonic gate for one public endpoint.

    The username endpoint is invoked from a free-text add-account flow.  A
    cache suppresses repeated names and this gate bounds distinct cache misses
    without sleeping a pywebview worker or exposing a server response body.
    """

    def __init__(self, *, minimum_interval_seconds: float, clock: Clock) -> None:
        self._minimum_interval_seconds = minimum_interval_seconds
        self._clock = clock
        self._next_allowed_at: float | None = None
        self._lock = threading.RLock()

    def try_acquire(self) -> bool:
        with self._lock:
            now = self._clock()
            if self._next_allowed_at is not None and now < self._next_allowed_at:
                return False
            self._next_allowed_at = now + self._minimum_interval_seconds
            return True


class RobloxClient:
    """A defensive client for public Roblox experience and server metadata.

    Requests have a bounded retry policy for transient failures.  Exception
    messages remain deliberately generic, because lower-level HTTP exceptions
    can sometimes embed request headers or cookies in their text.
    """

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 10.0,
        retry_attempts: int = 2,
        retry_backoff_seconds: float = 0.25,
        sleep: Sleep = time.sleep,
        clock: Clock = time.monotonic,
        profile_cache_ttl_seconds: float = _PROFILE_CACHE_TTL_SECONDS,
        presence_cache_ttl_seconds: float = _PRESENCE_CACHE_TTL_SECONDS,
        username_resolution_cache_ttl_seconds: float = _USERNAME_RESOLUTION_CACHE_TTL_SECONDS,
        username_resolution_min_interval_seconds: float = _USERNAME_RESOLUTION_MIN_INTERVAL_SECONDS,
        search_cache_ttl_seconds: float = _SEARCH_CACHE_TTL_SECONDS,
    ) -> None:
        if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise ValidationError("Network timeout must be positive.")
        if not isinstance(retry_attempts, int) or retry_attempts < 0:
            raise ValidationError("Retry attempts count must be positive or zero.")
        if (
            not isinstance(retry_backoff_seconds, (int, float))
            or retry_backoff_seconds < 0
        ):
            raise ValidationError("Retry backoff delay is invalid.")

        if not isinstance(profile_cache_ttl_seconds, (int, float)) or profile_cache_ttl_seconds <= 0:
            raise ValidationError("Profile cache TTL must be positive.")
        if not isinstance(presence_cache_ttl_seconds, (int, float)) or presence_cache_ttl_seconds <= 0:
            raise ValidationError("Presence cache TTL must be positive.")
        if (
            not isinstance(username_resolution_cache_ttl_seconds, (int, float))
            or username_resolution_cache_ttl_seconds <= 0
        ):
            raise ValidationError("Username resolution cache TTL must be positive.")
        if (
            not isinstance(username_resolution_min_interval_seconds, (int, float))
            or username_resolution_min_interval_seconds < 0
        ):
            raise ValidationError("Username resolution min interval is invalid.")
        if not isinstance(search_cache_ttl_seconds, (int, float)) or search_cache_ttl_seconds <= 0:
            raise ValidationError("Search cache TTL must be positive.")
        if not callable(clock):
            raise ValidationError("Roblox client clock function is invalid.")

        self._http = session or requests.Session()
        self._timeout_seconds = float(timeout_seconds)
        self._retry_attempts = retry_attempts
        self._retry_backoff_seconds = float(retry_backoff_seconds)
        self._sleep = sleep
        self._closed = False
        self._profile_cache = _TimedCache(
            maximum_entries=_PROFILE_CACHE_SIZE,
            ttl_seconds=float(profile_cache_ttl_seconds),
            clock=clock,
        )
        self._presence_cache = _TimedCache(
            maximum_entries=_PRESENCE_CACHE_SIZE,
            ttl_seconds=float(presence_cache_ttl_seconds),
            clock=clock,
        )
        self._username_resolution_cache = _TimedCache(
            maximum_entries=_USERNAME_RESOLUTION_CACHE_SIZE,
            ttl_seconds=float(username_resolution_cache_ttl_seconds),
            clock=clock,
        )
        self._username_resolution_gate = _RequestRateGate(
            minimum_interval_seconds=float(username_resolution_min_interval_seconds),
            clock=clock,
        )
        self._search_cache = _TimedCache(
            maximum_entries=_SEARCH_CACHE_SIZE,
            ttl_seconds=float(search_cache_ttl_seconds),
            clock=clock,
        )
        # Roblox's replacement for the retired games/list endpoint requires a
        # stable session id.  It is analytics-only, random per local client and
        # contains no account/session information.
        self._search_session_id = str(uuid4())

        # A stable Accept header makes error handling more predictable without
        # impersonating a browser or adding account-identifying headers.
        headers = getattr(self._http, "headers", None)
        if headers is not None and hasattr(headers, "setdefault"):
            headers.setdefault("Accept", "application/json")

    def close(self) -> None:
        """Release HTTP resources.  It is safe to call more than once."""

        if self._closed:
            return
        self._closed = True
        close = getattr(self._http, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> "RobloxClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get_universe_id(self, place_id: int) -> int:
        """Resolve a public place id to its Roblox universe id."""

        validated_place_id = _positive_id(place_id, "PlaceId")
        payload = self._request_json(
            f"{_UNIVERSES_BASE}/universes/v1/places/{validated_place_id}/universe"
        )
        universe_id = _as_positive_int(payload.get("universeId"))
        if universe_id is None:
            raise NotFoundError("No Roblox universe was found for this PlaceId.")
        return universe_id

    def get_game_details(self, place_id: int) -> Game:
        """Fetch an experience's details using its public PlaceId."""

        validated_place_id = _positive_id(place_id, "PlaceId")
        universe_id = self.get_universe_id(validated_place_id)
        return self.get_game_by_universe(universe_id, fallback_place_id=validated_place_id)

    def get_game_by_universe(
        self, universe_id: int, *, fallback_place_id: int | None = None
    ) -> Game:
        """Fetch details for a known public universe id."""

        validated_universe_id = _positive_id(universe_id, "UniverseId")
        payload = self._request_json(
            f"{_GAMES_BASE}/v1/games", params={"universeIds": validated_universe_id}
        )
        entries = payload.get("data")
        if not isinstance(entries, list) or not entries:
            raise NotFoundError("This Roblox experience was not found.")
        for entry in entries:
            if isinstance(entry, Mapping):
                return _to_game(
                    entry,
                    fallback_place_id=fallback_place_id,
                    fallback_universe_id=validated_universe_id,
                )
        raise RobloxServiceError("Roblox returned an invalid game response.")

    def search_games(self, query: str, *, limit: int = 20) -> tuple[Game, ...]:
        """Search public experiences by a human-entered title or keyword.

        Roblox retired ``games.roblox.com/v1/games/list``.  Its current search
        surface groups experiences under ``searchResults[].contents``.  The
        parser also retains the legacy shapes for deterministic compatibility
        tests and defensive handling of a transitional response.
        """

        normalized_query = _search_query(query)
        validated_limit = _page_size(limit)
        cache_key = (normalized_query.casefold(), validated_limit)
        cached = self._search_cache.get(cache_key)
        if cached is not None:
            return cached
        payload = self._request_json(
            f"{_SEARCH_BASE}/omni-search",
            params={
                "searchQuery": normalized_query,
                "sessionId": self._search_session_id,
                "pageType": "all",
            },
        )
        raw_games = _find_search_games(payload)
        games: list[Game] = []
        for raw_game in raw_games:
            if not isinstance(raw_game, Mapping):
                continue
            nested = raw_game.get("game")
            candidate = nested if isinstance(nested, Mapping) else raw_game
            try:
                games.append(_to_game(candidate))
            except ValueError:
                # A malformed entry should not make an otherwise useful search
                # response unusable.  The server details endpoint still validates
                # all fields strictly when a game is opened.
                continue
        result = tuple(games[:validated_limit])
        self._search_cache.put(cache_key, result)
        return result

    def list_public_servers(
        self,
        place_id: int,
        *,
        cursor: str | None = None,
        limit: int = 50,
        sort_order: ServerSortOrder = ServerSortOrder.ASCENDING,
    ) -> ServerPage:
        """Return one cursor-bounded page of public servers for a PlaceId."""

        validated_place_id = _positive_id(place_id, "PlaceId")
        validated_limit = _page_size(limit)
        validated_cursor = _cursor(cursor)
        if not isinstance(sort_order, ServerSortOrder):
            raise ValidationError("Server sort order is invalid.")

        parameters: dict[str, str | int] = {
            "sortOrder": sort_order.value,
            "limit": validated_limit,
        }
        if validated_cursor is not None:
            parameters["cursor"] = validated_cursor
        payload = self._request_json(
            f"{_GAMES_BASE}/v1/games/{validated_place_id}/servers/Public",
            params=parameters,
        )
        raw_servers = payload.get("data")
        if not isinstance(raw_servers, list):
            raise RobloxServiceError("Roblox returned an invalid server list.")

        servers: list[Server] = []
        for raw_server in raw_servers:
            if not isinstance(raw_server, Mapping):
                continue
            parsed = _to_server(raw_server, place_id=validated_place_id)
            if parsed is not None:
                servers.append(parsed)

        return ServerPage(
            servers=tuple(servers),
            next_page_cursor=_optional_text(payload.get("nextPageCursor")),
            previous_page_cursor=_optional_text(payload.get("previousPageCursor")),
        )

    def get_public_profile(self, user_id: int) -> PublicUserProfile:
        """Return public identity details and a cacheable avatar headshot.

        The legacy client retrieved ``Account.GetUserInfo`` from
        ``users.roblox.com`` and used the thumbnail batch service for account
        images.  The two current public endpoints are deliberately called
        without an authenticated client or cookie.  A thumbnail failure does
        not hide an otherwise usable public profile; it is represented as an
        unavailable avatar state instead.
        """

        validated_user_id = _positive_id(user_id, "UserId")
        cached = self._profile_cache.get(validated_user_id)
        if isinstance(cached, PublicUserProfile):
            return cached

        payload = self._request_json(f"{_USERS_BASE}/v1/users/{validated_user_id}")
        profile = _to_public_profile(payload, expected_user_id=validated_user_id)
        avatar_url: str | None = None
        avatar_state: str | None = None
        try:
            thumbnail_payload = self._request_json(
                f"{_THUMBNAILS_BASE}/v1/users/avatar-headshot",
                params={
                    "userIds": validated_user_id,
                    "size": "150x150",
                    "format": "Png",
                    "isCircular": "false",
                },
            )
            avatar_url, avatar_state = _headshot_from_payload(
                thumbnail_payload, expected_user_id=validated_user_id
            )
        except RobloxServiceError:
            # Profile identity is still useful while Roblox's thumbnail CDN is
            # delayed or rate-limited.  Do not leak a lower-layer error into a
            # partial result; callers can retry the normal refresh action.
            avatar_state = "Unavailable"

        resolved = PublicUserProfile(
            user_id=profile.user_id,
            username=profile.username,
            display_name=profile.display_name,
            description=profile.description,
            created_at=profile.created_at,
            is_banned=profile.is_banned,
            has_verified_badge=profile.has_verified_badge,
            avatar_url=avatar_url,
            avatar_state=avatar_state,
        )
        self._profile_cache.put(validated_user_id, resolved)
        return resolved

    def get_public_presence(self, user_ids: Sequence[int]) -> tuple[UserPresence, ...]:
        """Look up up to 50 public presence records with a short bounded cache.

        ``Presence.UpdatePresence`` in 3.7.2 sent a visible-account batch to
        ``POST presence.roblox.com/v1/presence/users``.  This port keeps that
        batch behavior, validates every numeric id and only returns records
        matching requested users.  It does not change local process state or
        make an account-authenticated request.
        """

        normalized_ids = _presence_user_ids(user_ids)
        resolved: dict[int, UserPresence] = {}
        missing: list[int] = []
        for user_id in normalized_ids:
            cached = self._presence_cache.get(user_id)
            if isinstance(cached, UserPresence):
                resolved[user_id] = cached
            else:
                missing.append(user_id)

        if missing:
            payload = self._post_json(
                f"{_PRESENCE_BASE}/v1/presence/users", json_body={"userIds": missing}
            )
            entries = payload.get("userPresences")
            if not isinstance(entries, list):
                raise RobloxServiceError("Roblox returned an invalid user presence response.")
            requested = set(missing)
            for entry in entries:
                if not isinstance(entry, Mapping):
                    continue
                parsed = _to_user_presence(entry)
                if parsed is None or parsed.user_id not in requested:
                    continue
                self._presence_cache.put(parsed.user_id, parsed)
                resolved[parsed.user_id] = parsed

        return tuple(resolved[user_id] for user_id in normalized_ids if user_id in resolved)

    def _request_json(
        self, url: str, *, params: Mapping[str, str | int] | None = None
    ) -> JsonMapping:
        """Issue a GET request without ever reflecting low-level error text."""

        return self._send_json("GET", url, params=params)

    def _post_json(
        self, url: str, *, json_body: Mapping[str, Any] | list[Mapping[str, Any]]
    ) -> JsonMapping:
        """Issue a JSON POST request without reflecting HTTP implementation data."""

        return self._send_json("POST", url, json_body=json_body)

    def _send_json(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        json_body: Mapping[str, Any] | list[Mapping[str, Any]] | None = None,
    ) -> JsonMapping:
        """Issue a bounded public request and normalize its JSON response."""

        if self._closed:
            raise RobloxServiceError("Roblox client is closed.")

        last_status: int | None = None
        for attempt in range(self._retry_attempts + 1):
            try:
                if method == "GET":
                    response = self._http.get(url, params=params, timeout=self._timeout_seconds)
                elif method == "POST":
                    body: Any
                    if isinstance(json_body, list):
                        body = [dict(item) for item in json_body]
                    else:
                        body = dict(json_body or {})
                    response = self._http.post(url, json=body, timeout=self._timeout_seconds)
                else:  # Internal-only guard: public methods use GET or POST only.
                    raise RuntimeError("Unsupported Roblox HTTP method")
            except requests.RequestException:
                if attempt < self._retry_attempts:
                    self._backoff(attempt)
                    continue
                raise RobloxServiceError(retryable=True) from None
            except Exception:
                # Session fakes and alternative HTTP adapters can raise a
                # non-requests exception.  Their text is intentionally hidden.
                if attempt < self._retry_attempts:
                    self._backoff(attempt)
                    continue
                raise RobloxServiceError(retryable=True) from None

            status = _status_code(response)
            last_status = status
            if status == 401 or status == 403:
                raise RobloxAuthenticationError()
            if 200 <= status < 300:
                try:
                    payload = response.json()
                except (AttributeError, TypeError, ValueError):
                    raise RobloxServiceError(
                        "Roblox returned an unreadable response.", retryable=False
                    ) from None
                if not isinstance(payload, Mapping):
                    raise RobloxServiceError(
                        "Roblox returned an invalid response.", retryable=False
                    )
                return payload

            retryable = status == 429 or status >= 500 or status == 0
            if retryable and attempt < self._retry_attempts:
                self._backoff(attempt)
                continue
            raise _http_error(status, retryable=retryable)

        # The loop always returns or raises, but a defensive error keeps static
        # analyzers and future changes from accidentally exposing request state.
        raise RobloxServiceError(retryable=last_status is None or last_status >= 500)

    def _backoff(self, attempt: int) -> None:
        delay = min(self._retry_backoff_seconds * (2**attempt), 2.0)
        if delay:
            self._sleep(delay)


class SessionRobloxClient(RobloxClient):
    """A Roblox client authenticated with an opaque, locally stored session.

    The secret is placed directly into the HTTP cookie jar and is never exposed
    as an attribute, result, error detail, or URI.  Callers should obtain it
    from the local vault only for the lifetime of this client instance.
    """

    def __init__(
        self,
        session_cookie: str,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 10.0,
        retry_attempts: int = 2,
        retry_backoff_seconds: float = 0.25,
        sleep: Sleep = time.sleep,
    ) -> None:
        if not isinstance(session_cookie, str) or not session_cookie.strip():
            raise ValidationError("A Roblox session cookie is required.")
        if len(session_cookie) > 8_192:
            raise ValidationError("Roblox session cookie is invalid.")

        http = session or requests.Session()
        _set_session_cookie(http, session_cookie)
        super().__init__(
            session=http,
            timeout_seconds=timeout_seconds,
            retry_attempts=retry_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
            sleep=sleep,
        )
        self._has_session_cookie = True

    def __repr__(self) -> str:
        return "SessionRobloxClient(session_cookie=[REDACTED])"

    def authenticated_user(self) -> AuthenticatedUser:
        """Return the account identity associated with the stored session."""

        payload = self._request_json(f"{_USERS_BASE}/v1/users/authenticated")
        user_id = _as_positive_int(payload.get("id"))
        username = _optional_text(payload.get("name"))
        if user_id is None or username is None:
            raise RobloxServiceError("Roblox returned an invalid session profile.")
        return AuthenticatedUser(
            user_id=user_id,
            username=username,
            display_name=_optional_text(payload.get("displayName")),
        )

    def close(self) -> None:
        """Clear the in-memory cookie before releasing the HTTP session."""

        if getattr(self, "_has_session_cookie", False):
            _clear_session_cookie(self._http)
            self._has_session_cookie = False
        super().close()


def _positive_id(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError(f"{field_name} must be a positive integer.")
    return value


def _page_size(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= _MAX_PAGE_SIZE:
        raise ValidationError(f"Page size must be between 1 and {_MAX_PAGE_SIZE}.")
    return value


def _search_query(value: object) -> str:
    if not isinstance(value, str):
        raise ValidationError("Search query must be text.")
    normalized = " ".join(value.split())
    if not normalized:
        raise ValidationError("Search query cannot be empty.")
    if len(normalized) > _MAX_SEARCH_LENGTH:
        raise ValidationError(
            f"Search query cannot exceed {_MAX_SEARCH_LENGTH} characters."
        )
    return normalized


def _cursor(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > _MAX_CURSOR_LENGTH:
        raise ValidationError("Pagination cursor is invalid.")
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ValidationError("Pagination cursor is invalid.")
    return value


def _status_code(response: object) -> int:
    status = getattr(response, "status_code", 0)
    return status if isinstance(status, int) else 0


def _http_error(status: int, *, retryable: bool) -> RobloxServiceError:
    if status == 404:
        return RobloxServiceError("The requested Roblox resource was not found.", status_code=status)
    if status == 429:
        return RobloxServiceError(
            "Roblox is temporarily rate-limiting requests. Please try again soon.",
            retryable=True,
            status_code=status,
        )
    if 400 <= status < 500:
        return RobloxServiceError("Roblox denied this request.", status_code=status)
    return RobloxServiceError(retryable=retryable, status_code=status or None)


def _find_collection(payload: JsonMapping, *keys: str) -> list[Any]:
    for key in keys:
        candidate = payload.get(key)
        if isinstance(candidate, list):
            return candidate
        if isinstance(candidate, Mapping):
            nested = candidate.get("data") or candidate.get("games") or candidate.get("results")
            if isinstance(nested, list):
                return nested
    return []


def _find_search_games(payload: JsonMapping) -> list[Any]:
    """Flatten Roblox omni-search experience groups without keeping tokens."""

    grouped = payload.get("searchResults")
    if isinstance(grouped, list):
        games: list[Any] = []
        for group in grouped:
            if not isinstance(group, Mapping):
                continue
            contents = group.get("contents")
            if not isinstance(contents, list):
                continue
            for item in contents:
                if not isinstance(item, Mapping):
                    continue
                content_type = str(item.get("contentType") or group.get("contentGroupType") or "")
                if content_type.casefold() == "game":
                    games.append(item)
        return games
    return _find_collection(payload, "games", "data", "results")


def _to_game(
    payload: Mapping[str, Any],
    *,
    fallback_place_id: int | None = None,
    fallback_universe_id: int | None = None,
) -> Game:
    universe_id = _as_positive_int(
        payload.get("id") or payload.get("universeId") or payload.get("universeID")
    ) or fallback_universe_id
    place_id = _as_positive_int(
        payload.get("rootPlaceId") or payload.get("placeId") or payload.get("placeID")
    ) or fallback_place_id
    name = _optional_text(payload.get("name") or payload.get("gameName"))
    if place_id is None or name is None:
        raise ValueError("Incomplete game payload")

    creator = payload.get("creator")
    creator_mapping = creator if isinstance(creator, Mapping) else {}
    metadata = {
        "visits": _as_nonnegative_int(payload.get("visits")),
        "favorited_count": _as_nonnegative_int(payload.get("favoritedCount")),
        "source_name": _optional_text(payload.get("sourceName")),
        "remote_created_at": _optional_text(payload.get("created")),
        "remote_updated_at": _optional_text(payload.get("updated")),
    }
    return Game(
        place_id=place_id,
        universe_id=universe_id,
        name=name,
        description=_optional_text(payload.get("description")) or "",
        creator_name=_optional_text(creator_mapping.get("name") or payload.get("creatorName")),
        creator_id=_as_positive_int(creator_mapping.get("id") or payload.get("creatorId")),
        icon_url=_optional_text(payload.get("iconImageUrl") or payload.get("imageUrl")),
        playing=_as_nonnegative_int(payload.get("playing") if payload.get("playing") is not None else payload.get("playerCount")),
        max_players=_as_nonnegative_int(payload.get("maxPlayers")),
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _to_server(payload: Mapping[str, Any], *, place_id: int) -> Server | None:
    job_id = _optional_text(payload.get("id"))
    playing = _as_nonnegative_int(payload.get("playing"))
    max_players = _as_nonnegative_int(payload.get("maxPlayers"))
    if job_id is None or playing is None or max_players is None:
        return None
    return Server(
        job_id=job_id,
        place_id=place_id,
        playing=playing,
        max_players=max_players,
        ping=_as_finite_float(payload.get("ping")),
        fps=_as_finite_float(payload.get("fps")),
        region=_optional_text(payload.get("region")),
        address=_optional_text(
            payload.get("machineAddress")
            or payload.get("address")
            or payload.get("ip")
        ),
        server_type="public",
        # Player tokens are not needed by the UI and can be unstable identifiers.
        player_tokens=[],
    )


def _to_public_profile(
    payload: Mapping[str, Any], *, expected_user_id: int
) -> PublicUserProfile:
    user_id = _as_positive_int(payload.get("id"))
    username = _bounded_optional_text(payload.get("name"), maximum=128)
    if user_id != expected_user_id or username is None:
        raise RobloxServiceError("Roblox returned an invalid public user profile.")
    return PublicUserProfile(
        user_id=user_id,
        username=username,
        display_name=_bounded_optional_text(payload.get("displayName"), maximum=128),
        description=_bounded_optional_text(payload.get("description"), maximum=4_000),
        created_at=_bounded_optional_text(payload.get("created"), maximum=80),
        is_banned=_optional_bool(payload.get("isBanned")),
        has_verified_badge=_optional_bool(payload.get("hasVerifiedBadge")),
    )


def _headshot_from_payload(
    payload: Mapping[str, Any], *, expected_user_id: int
) -> tuple[str | None, str | None]:
    entries = payload.get("data")
    if not isinstance(entries, list):
        raise RobloxServiceError("Roblox returned an invalid avatar response.")
    for entry in entries:
        if not isinstance(entry, Mapping) or _as_positive_int(entry.get("targetId")) != expected_user_id:
            continue
        state = _bounded_optional_text(entry.get("state"), maximum=32)
        image_url = _safe_public_image_url(entry.get("imageUrl"))
        return image_url, state if image_url is not None or state != "Completed" else "Unavailable"
    return None, "Unavailable"


def _presence_user_ids(user_ids: Sequence[int]) -> tuple[int, ...]:
    if not isinstance(user_ids, (list, tuple)) or not user_ids:
        raise ValidationError("Fournissez au moins un UserId pour la presence.")
    if len(user_ids) > _MAX_PRESENCE_USERS:
        raise ValidationError(f"La presence est limitee a {_MAX_PRESENCE_USERS} utilisateurs par requete.")
    normalized: list[int] = []
    for value in user_ids:
        user_id = _positive_id(value, "UserId")
        if user_id not in normalized:
            normalized.append(user_id)
    return tuple(normalized)


def _to_user_presence(payload: Mapping[str, Any]) -> UserPresence | None:
    user_id = _as_positive_int(payload.get("userId"))
    raw_state = _as_nonnegative_int(payload.get("userPresenceType"))
    states = {
        0: PresenceState.OFFLINE,
        1: PresenceState.ONLINE,
        2: PresenceState.IN_GAME,
        3: PresenceState.IN_STUDIO,
    }
    state = states.get(raw_state)
    if user_id is None or state is None:
        return None
    return UserPresence(
        user_id=user_id,
        state=state,
        last_location=_bounded_optional_text(payload.get("lastLocation"), maximum=512),
        place_id=_as_positive_int(payload.get("placeId")),
        root_place_id=_as_positive_int(payload.get("rootPlaceId")),
        game_id=_bounded_optional_text(payload.get("gameId"), maximum=128),
        universe_id=_as_positive_int(payload.get("universeId")),
        last_online=_bounded_optional_text(payload.get("lastOnline"), maximum=80),
    )


def _bounded_optional_text(value: object, *, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        return None
    return normalized


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _safe_public_image_url(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 2_048:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    hostname = parsed.hostname.casefold() if parsed.hostname else ""
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or not (hostname == "rbxcdn.com" or hostname.endswith(".rbxcdn.com") or hostname.endswith(".roblox.com"))
    ):
        return None
    return value


def _as_positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.isdecimal():
        parsed = int(value)
        return parsed if parsed > 0 else None
    return None


def _as_nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _as_finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _set_session_cookie(session: requests.Session, value: str) -> None:
    cookie_jar = getattr(session, "cookies", None)
    setter = getattr(cookie_jar, "set", None)
    if not callable(setter):
        raise ValidationError("La session HTTP ne peut pas protÃ©ger cette session Roblox.")
    try:
        setter(
            ".ROBLOSECURITY",
            value,
            domain=".roblox.com",
            path="/",
            secure=True,
        )
    except Exception:
        raise ValidationError("La session HTTP ne peut pas protÃ©ger cette session Roblox.") from None


def _clear_session_cookie(session: requests.Session) -> None:
    cookie_jar = getattr(session, "cookies", None)
    clearer = getattr(cookie_jar, "clear", None)
    if not callable(clearer):
        return
    try:
        clearer(domain=".roblox.com", path="/", name=".ROBLOSECURITY")
    except (KeyError, ValueError):
        # The jar may already have been cleared by its owner.
        pass


__all__ = ["RobloxClient", "SessionRobloxClient"]
