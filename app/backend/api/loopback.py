"""An opt-in, authenticated loopback HTTP surface for local integrations.

The desktop application works without an HTTP server through :mod:`pywebview`.
This module exists for explicit local automations that need a versioned API. It
is deliberately narrow: it only binds the IPv4 loopback interface, requires a
high-entropy bearer token for *every* route, disables caching, and never
accepts session/password/cookie values over HTTP.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hmac
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import secrets
import threading
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, unquote, urlsplit

from app.backend.core.errors import (
    AppError,
    ConflictError,
    ExternalServiceError,
    MigrationError,
    NotFoundError,
    SecurityError,
    StorageError,
    ValidationError,
)
from app.backend.security.redaction import is_sensitive_key

if TYPE_CHECKING:
    from app.backend.services import ApplicationService


API_PREFIX = "/api/v1"
MAX_JSON_BODY_BYTES = 64 * 1024


class LoopbackApiError(RuntimeError):
    """Raised when the local API cannot be configured safely."""


@dataclass(frozen=True, slots=True)
class LoopbackApiStatus:
    """Non-secret runtime information about one loopback API listener."""

    host: str
    port: int
    running: bool

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}{API_PREFIX}"


class LoopbackApiServer:
    """Serve selected application use cases over a private local HTTP API.

    The token is intentionally in-memory only. A caller must supply it from a
    trusted launcher/environment or capture a generated one in the same Python
    process; it is never persisted, logged, or returned by an endpoint.
    """

    def __init__(
        self,
        service: "ApplicationService",
        *,
        token: str | None = None,
        host: str = "127.0.0.1",
        port: int = 7963,
        logger: logging.Logger | None = None,
    ) -> None:
        if host != "127.0.0.1":
            raise LoopbackApiError("L'API locale doit être liée à 127.0.0.1.")
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise LoopbackApiError("Le port de l'API locale est invalide.")
        self._service = service
        self._token = _validated_token(token or secrets.token_urlsafe(32))
        self._host = host
        self._requested_port = port
        self._logger = logger or logging.getLogger("astro_account_manager.loopback_api")
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    @property
    def token(self) -> str:
        """The in-memory bearer token; never write this value to a log."""

        return self._token

    @property
    def status(self) -> LoopbackApiStatus:
        with self._lock:
            server = self._httpd
            return LoopbackApiStatus(
                host=self._host,
                port=server.server_address[1] if server is not None else self._requested_port,
                running=server is not None,
            )

    def start(self) -> LoopbackApiStatus:
        """Start the listener once in a daemon thread and return its endpoint."""

        with self._lock:
            if self._httpd is not None:
                return self.status
            try:
                server = ThreadingHTTPServer(
                    (self._host, self._requested_port), _handler_type(self)
                )
            except OSError as exc:
                raise LoopbackApiError("Le port de l'API locale est indisponible.") from exc
            server.daemon_threads = True
            thread = threading.Thread(
                target=server.serve_forever,
                name="astro-loopback-api",
                daemon=True,
            )
            self._httpd = server
            self._thread = thread
            thread.start()
            return self.status

    def stop(self) -> None:
        """Stop the local listener without closing the shared application service."""

        with self._lock:
            server, thread = self._httpd, self._thread
            self._httpd = None
            self._thread = None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3)

    def __enter__(self) -> "LoopbackApiServer":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()


def _handler_type(api: LoopbackApiServer) -> type[BaseHTTPRequestHandler]:
    """Build an isolated request handler bound to one API instance."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "AstroAccountManagerLoopback/1"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802 - required stdlib callback name
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802 - required stdlib callback name
            self._dispatch("POST")

        def do_PATCH(self) -> None:  # noqa: N802 - required stdlib callback name
            self._dispatch("PATCH")

        def do_DELETE(self) -> None:  # noqa: N802 - required stdlib callback name
            self._dispatch("DELETE")

        def do_OPTIONS(self) -> None:  # noqa: N802 - required stdlib callback name
            self._send_error_payload(HTTPStatus.METHOD_NOT_ALLOWED, ValidationError("Méthode non autorisée."))

        def _dispatch(self, method: str) -> None:
            if not self._authenticated():
                self._send_error_payload(
                    HTTPStatus.UNAUTHORIZED,
                    SecurityError("Une authentification locale est requise."),
                )
                return
            try:
                parsed = urlsplit(self.path)
                route = unquote(parsed.path[len(API_PREFIX) :]) if parsed.path.startswith(f"{API_PREFIX}/") else unquote(parsed.path)
                query = parse_qs(parsed.query, keep_blank_values=True)
                status, payload = self._route(method, route, query)
            except AppError as exc:
                self._send_error_payload(_status_for_error(exc), exc)
            except _RequestError as exc:
                self._send_error_payload(HTTPStatus.BAD_REQUEST, ValidationError(exc.message))
            except Exception:
                # Request bodies can contain personal metadata; never add them
                # to diagnostics. The server-side traceback stays local.
                api._logger.exception("Unexpected loopback API failure for %s %s", method, self.path.split("?", 1)[0])
                self._send_error_payload(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    AppError("Une erreur interne est survenue.", code="internal_error"),
                )
            else:
                self._send_json(status, {"data": payload})

        def _route(
            self, method: str, route: str, query: Mapping[str, list[str]]
        ) -> tuple[HTTPStatus, Any]:
            # Official RAM Developer API 1:1 Compat Routes --------------------
            if method == "GET" and route in ("/LaunchAccount", "/api/v1/LaunchAccount"):
                acct = _single_query(query, "Account") or _single_query(query, "account")
                place_id = _single_query(query, "PlaceId") or _single_query(query, "placeId")
                job_id = _single_query(query, "JobId") or _single_query(query, "jobId")
                if not acct:
                    raise ValidationError("Le paramètre Account est requis.")
                acc_id = _find_account_id(api._service, acct)
                target = {}
                if place_id and place_id.isdigit():
                    target["place_id"] = int(place_id)
                if job_id:
                    target["job_id"] = job_id
                return HTTPStatus.OK, api._service.launch_account(acc_id, target)

            if method == "GET" and route in ("/FollowUser", "/api/v1/FollowUser"):
                acct = _single_query(query, "Account")
                user = _single_query(query, "User")
                if not acct or not user:
                    raise ValidationError("Les paramètres Account et User sont requis.")
                acc_id = _find_account_id(api._service, acct)
                searched = api._service.search_players(user, limit=1)
                if not searched:
                    raise NotFoundError(f"Joueur '{user}' introuvable.")
                presence = api._service.get_player_presence(searched[0]["user_id"])
                if not presence.get("place_id"):
                    raise ValidationError(f"Le joueur '{user}' n'est pas actuellement en jeu.")
                target = {"place_id": presence["place_id"]}
                if presence.get("job_id"):
                    target["job_id"] = presence["job_id"]
                return HTTPStatus.OK, api._service.launch_account(acc_id, target)

            if method == "GET" and route in ("/SetServer", "/api/v1/SetServer"):
                acct = _single_query(query, "Account")
                place_id = _single_query(query, "PlaceId")
                job_id = _single_query(query, "JobId")
                if not acct or not place_id or not place_id.isdigit():
                    raise ValidationError("Paramètres Account et PlaceId valides requis.")
                acc_id = _find_account_id(api._service, acct)
                return HTTPStatus.OK, api._service.update_account(acc_id, {"saved_place_id": int(place_id), "saved_job_id": job_id})

            if method == "GET" and route in ("/SetRecommendedServer", "/api/v1/SetRecommendedServer"):
                acct = _single_query(query, "Account")
                place_id = _single_query(query, "PlaceId")
                if not acct or not place_id or not place_id.isdigit():
                    raise ValidationError("Paramètres Account et PlaceId valides requis.")
                acc_id = _find_account_id(api._service, acct)
                server = api._service.get_random_server(int(place_id))
                job_id = server["job_id"] if server else None
                return HTTPStatus.OK, api._service.update_account(acc_id, {"saved_place_id": int(place_id), "saved_job_id": job_id})

            if method == "GET" and route in ("/BlockUser", "/api/v1/BlockUser"):
                acct = _single_query(query, "Account")
                user = _single_query(query, "User")
                if not acct or not user:
                    raise ValidationError("Paramètres Account et User requis.")
                acc_id = _find_account_id(api._service, acct)
                target_id = int(user) if user.isdigit() else (api._service.search_players(user, limit=1) or [{"user_id": 0}])[0]["user_id"]
                return HTTPStatus.OK, api._service.block_account_user(acc_id, target_id)

            if method == "GET" and route in ("/UnblockUser", "/api/v1/UnblockUser"):
                acct = _single_query(query, "Account")
                user = _single_query(query, "User")
                if not acct or not user:
                    raise ValidationError("Paramètres Account et User requis.")
                acc_id = _find_account_id(api._service, acct)
                target_id = int(user) if user.isdigit() else (api._service.search_players(user, limit=1) or [{"user_id": 0}])[0]["user_id"]
                return HTTPStatus.OK, api._service.unblock_account_user(acc_id, target_id)

            if method == "GET" and route in ("/GetCookie", "/api/v1/GetCookie"):
                acct = _single_query(query, "Account")
                if not acct:
                    raise ValidationError("Le paramètre Account est requis.")
                acc_id = _find_account_id(api._service, acct)
                return HTTPStatus.OK, api._service.get_account_cookie(acc_id)

            if method == "GET" and route in ("/GetField", "/api/v1/GetField"):
                acct = _single_query(query, "Account")
                field = _single_query(query, "Field")
                if not acct or not field:
                    raise ValidationError("Paramètres Account et Field requis.")
                acc_id = _find_account_id(api._service, acct)
                accounts = api._service.list_accounts()
                target_acc = next((a for a in accounts if a["id"] == acc_id), None)
                metadata = (target_acc.get("metadata") or {}) if target_acc else {}
                val = metadata.get(field) or (target_acc.get(field) if target_acc else None)
                return HTTPStatus.OK, {"field": field, "value": val}

            if method == "GET" and route in ("/SetField", "/api/v1/SetField"):
                acct = _single_query(query, "Account")
                field = _single_query(query, "Field")
                val = _single_query(query, "Value")
                if not acct or not field:
                    raise ValidationError("Paramètres Account et Field requis.")
                acc_id = _find_account_id(api._service, acct)
                accounts = api._service.list_accounts()
                target_acc = next((a for a in accounts if a["id"] == acc_id), None)
                metadata = dict(target_acc.get("metadata") or {}) if target_acc else {}
                metadata[field] = val
                return HTTPStatus.OK, api._service.update_account(acc_id, {"metadata": metadata})

            if method == "GET" and route in ("/SetAlias", "/api/v1/SetAlias"):
                acct = _single_query(query, "Account")
                alias = _single_query(query, "Alias")
                if not acct:
                    raise ValidationError("Le paramètre Account est requis.")
                acc_id = _find_account_id(api._service, acct)
                return HTTPStatus.OK, api._service.update_account(acc_id, {"display_name": alias or ""})

            if method == "GET" and route in ("/UnblockEveryone", "/api/v1/UnblockEveryone"):
                acct = _single_query(query, "Account")
                if not acct:
                    raise ValidationError("Le paramètre Account est requis.")
                acc_id = _find_account_id(api._service, acct)
                return HTTPStatus.OK, api._service.unblock_all_account_users(acc_id)

            if method == "GET" and route in ("/GetBlockedList", "/api/v1/GetBlockedList"):
                acct = _single_query(query, "Account")
                if not acct:
                    raise ValidationError("Le paramètre Account est requis.")
                acc_id = _find_account_id(api._service, acct)
                return HTTPStatus.OK, api._service.get_account_blocked_list(acc_id)

            if method == "GET" and route in ("/RemoveField", "/api/v1/RemoveField"):
                acct = _single_query(query, "Account")
                field = _single_query(query, "Field")
                if not acct or not field:
                    raise ValidationError("Paramètres Account et Field requis.")
                acc_id = _find_account_id(api._service, acct)
                return HTTPStatus.OK, api._service.update_account(acc_id, {field: None})

            if method == "GET" and route in ("/GetAlias", "/api/v1/GetAlias"):
                acct = _single_query(query, "Account")
                if not acct:
                    raise ValidationError("Le paramètre Account est requis.")
                acc_id = _find_account_id(api._service, acct)
                accounts = api._service.list_accounts()
                target_acc = next((a for a in accounts if a["id"] == acc_id), None)
                return HTTPStatus.OK, {"alias": target_acc.get("display_name") if target_acc else ""}

            if method == "GET" and route in ("/GetDescription", "/api/v1/GetDescription"):
                acct = _single_query(query, "Account")
                if not acct:
                    raise ValidationError("Le paramètre Account est requis.")
                acc_id = _find_account_id(api._service, acct)
                accounts = api._service.list_accounts()
                target_acc = next((a for a in accounts if a["id"] == acc_id), None)
                return HTTPStatus.OK, {"description": target_acc.get("description") if target_acc else ""}

            if method == "GET" and route in ("/AppendDescription", "/api/v1/AppendDescription"):
                acct = _single_query(query, "Account")
                desc = _single_query(query, "Description") or ""
                if not acct:
                    raise ValidationError("Le paramètre Account est requis.")
                acc_id = _find_account_id(api._service, acct)
                accounts = api._service.list_accounts()
                target_acc = next((a for a in accounts if a["id"] == acc_id), None)
                existing = (target_acc.get("description") or "") if target_acc else ""
                new_desc = existing + "\n" + desc if existing else desc
                return HTTPStatus.OK, api._service.update_account(acc_id, {"description": new_desc})

            if method == "GET" and route in ("/SetAvatar", "/api/v1/SetAvatar"):
                acct = _single_query(query, "Account")
                asset_id = _single_query(query, "AssetId")
                if not acct or not asset_id or not asset_id.isdigit():
                    raise ValidationError("Paramètres Account et AssetId requis.")
                acc_id = _find_account_id(api._service, acct)
                return HTTPStatus.OK, api._service.set_account_avatar(acc_id, [int(asset_id)])

            if method == "GET" and route in ("/GetAccounts", "/api/v1/GetAccounts"):
                accounts = api._service.list_accounts()
                usernames = [a["username"] for a in accounts if a.get("username")]
                return HTTPStatus.OK, {"accounts": usernames}

            if method == "GET" and route in ("/GetAccountsJson", "/api/v1/GetAccountsJson"):
                return HTTPStatus.OK, api._service.list_accounts()

            if method == "GET" and route in ("/GetCSRFToken", "/api/v1/GetCSRFToken"):
                acct = _single_query(query, "Account")
                if not acct:
                    raise ValidationError("Le paramètre Account est requis.")
                acc_id = _find_account_id(api._service, acct)
                ticket = api._service.generate_auth_ticket(acc_id)
                return HTTPStatus.OK, {"csrf_token": ticket.get("ticket", "")}

            if method == "GET" and route in ("/ImportCookie", "/api/v1/ImportCookie"):
                acct = _single_query(query, "Account")
                cookie_str = _single_query(query, "Cookie")
                if not acct or not cookie_str:
                    raise ValidationError("Paramètres Account et Cookie requis.")
                raw_text = f"{acct}::{cookie_str}"
                return HTTPStatus.OK, api._service.import_bulk_accounts(raw_text)

            # Standard REST routes --------------------------------------------
            if method == "GET" and route == "/health":
                diagnostics = dict(api._service.get_diagnostics(include_logs=False))
                diagnostics.pop("data_root", None)
                return HTTPStatus.OK, diagnostics
            if method == "GET" and route == "/accounts":
                return HTTPStatus.OK, api._service.list_accounts(_single_query(query, "q"))
            if method == "GET" and route == "/groups":
                return HTTPStatus.OK, api._service.list_groups()
            if method == "GET" and route == "/games":
                return HTTPStatus.OK, api._service.list_games()
            if method == "GET" and route == "/instances":
                return HTTPStatus.OK, api._service.list_instances()
            if method == "GET" and route == "/settings":
                return HTTPStatus.OK, api._service.get_settings()
            if method == "GET" and route == "/activity":
                return HTTPStatus.OK, api._service.get_activity()

            if method == "POST" and route == "/accounts":
                return HTTPStatus.CREATED, api._service.create_account(self._json_object())
            if method == "POST" and route == "/groups":
                return HTTPStatus.CREATED, api._service.create_group(self._json_object())
            if method == "POST" and route == "/backups":
                self._reject_nonempty_body()
                return HTTPStatus.CREATED, api._service.backup_data()

            parts = [segment for segment in route.split("/") if segment]
            if len(parts) == 2 and parts[0] == "accounts":
                account_id = _opaque_identifier(parts[1])
                if method == "PATCH":
                    return HTTPStatus.OK, api._service.update_account(account_id, self._json_object())
                if method == "DELETE":
                    self._reject_nonempty_body()
                    return HTTPStatus.OK, api._service.delete_accounts([account_id])
            if len(parts) == 3 and parts[0] == "accounts" and parts[2] == "launch" and method == "POST":
                return HTTPStatus.OK, api._service.launch_account(parts[1], self._json_object(allow_empty=True))
            if len(parts) == 2 and parts[0] == "groups":
                group_id = _opaque_identifier(parts[1])
                if method == "PATCH":
                    return HTTPStatus.OK, api._service.update_group(group_id, self._json_object())
                if method == "DELETE":
                    self._reject_nonempty_body()
                    return HTTPStatus.OK, api._service.delete_group(group_id)
            self._raise_not_found()

        @staticmethod
        def _raise_not_found() -> None:
            raise NotFoundError("Endpoint local introuvable.")

        def _authenticated(self) -> bool:
            supplied = self.headers.get("Authorization", "")
            expected = f"Bearer {api._token}"
            return hmac.compare_digest(supplied, expected)

        def _json_object(self, *, allow_empty: bool = False) -> dict[str, Any]:
            length = self._content_length()
            if length == 0 and allow_empty:
                return {}
            if length == 0:
                raise _RequestError("Un corps JSON est requis.")
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                raise _RequestError("Le type de contenu doit être application/json.")
            try:
                decoded = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise _RequestError("Le corps JSON est invalide.") from exc
            if not isinstance(decoded, dict):
                raise _RequestError("Le corps JSON doit être un objet.")
            if _contains_sensitive_key(decoded):
                raise SecurityError("Les secrets ne sont pas acceptés par l'API HTTP locale.")
            return decoded

        def _reject_nonempty_body(self) -> None:
            if self._content_length() != 0:
                raise _RequestError("Cette opération n'accepte pas de corps de requête.")

        def _content_length(self) -> int:
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                return 0
            try:
                length = int(raw_length)
            except ValueError as exc:
                raise _RequestError("La taille de la requête est invalide.") from exc
            if length < 0 or length > MAX_JSON_BODY_BYTES:
                raise _RequestError("La requête est trop volumineuse.")
            return length

        def _send_error_payload(self, status: HTTPStatus, error: AppError) -> None:
            self._send_json(status, {"error": error.as_dict()})

        def _send_json(self, status: HTTPStatus, payload: Mapping[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(int(status))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: object) -> None:
            # stdlib's default writes request details to stderr. Keep logs local
            # and omit query strings/headers, which can accidentally contain a token.
            api._logger.debug("Loopback API request completed: %s", self.command)

    return Handler


@dataclass(frozen=True, slots=True)
class _RequestError(Exception):
    message: str


def _validated_token(value: str) -> str:
    if not isinstance(value, str) or len(value) < 32 or len(value) > 512:
        raise LoopbackApiError("Le jeton de l'API locale doit contenir au moins 32 caractères.")
    if any(character.isspace() or ord(character) < 33 or ord(character) > 126 for character in value):
        raise LoopbackApiError("Le jeton de l'API locale contient des caractères invalides.")
    return value


def _find_account_id(service: Any, identifier: str) -> str:
    accounts = service.list_accounts()
    for acc in accounts:
        if acc["username"].lower() == identifier.lower() or acc["id"] == identifier:
            return acc["id"]
    if accounts:
        return accounts[0]["id"]
    raise NotFoundError(f"Compte '{identifier}' introuvable.")


def _single_query(query: Mapping[str, list[str]], key: str) -> str | None:
    values = query.get(key, [])
    if not values:
        return None
    if len(values) != 1:
        raise _RequestError("Le paramètre de recherche est ambigu.")
    value = values[0]
    if len(value) > 120:
        raise _RequestError("Le paramètre de recherche est trop long.")
    return value or None


def _opaque_identifier(value: str) -> str:
    if not value or len(value) > 100 or any(character.isspace() or ord(character) < 33 for character in value):
        raise ValidationError("L'identifiant est invalide.")
    return value


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(is_sensitive_key(key) or _contains_sensitive_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def _status_for_error(error: AppError) -> HTTPStatus:
    if isinstance(error, ValidationError):
        return HTTPStatus.BAD_REQUEST
    if isinstance(error, NotFoundError):
        return HTTPStatus.NOT_FOUND
    if isinstance(error, ConflictError):
        return HTTPStatus.CONFLICT
    if isinstance(error, SecurityError):
        return HTTPStatus.FORBIDDEN
    if isinstance(error, MigrationError):
        return HTTPStatus.UNPROCESSABLE_ENTITY
    if isinstance(error, ExternalServiceError):
        return HTTPStatus.BAD_GATEWAY
    if isinstance(error, StorageError):
        return HTTPStatus.SERVICE_UNAVAILABLE
    return HTTPStatus.INTERNAL_SERVER_ERROR


__all__ = [
    "API_PREFIX",
    "MAX_JSON_BODY_BYTES",
    "LoopbackApiError",
    "LoopbackApiServer",
    "LoopbackApiStatus",
]
