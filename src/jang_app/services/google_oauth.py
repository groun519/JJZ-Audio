from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import webbrowser
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Event
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

from jang_app.services.managed_files import write_json_atomic
from jang_app.services.windows_credentials import CredentialStore


AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USER_INFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
OAUTH_SCOPES = ("openid", "email", "profile", DRIVE_FILE_SCOPE)
GOOGLE_CREDENTIAL_TARGET = "JJZero Audio/Google Drive"
ACCOUNT_STATE_VERSION = 1


class GoogleOAuthError(RuntimeError):
    """Raised when Google account authorization cannot be completed."""


class GoogleOAuthConfigurationError(GoogleOAuthError):
    """Raised when the JJZero Google OAuth client is unusable."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes

    def json(self) -> dict[str, object]:
        if not self.body:
            return {}
        try:
            value = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GoogleOAuthError("Google returned an unreadable response.") from exc
        if not isinstance(value, dict):
            raise GoogleOAuthError("Google returned an unexpected response.")
        return value


HttpRequester = Callable[[Request, float], HttpResponse]


@dataclass(frozen=True)
class GoogleOAuthConfig:
    client_id: str
    client_secret: str = ""


@dataclass(frozen=True)
class GoogleAccount:
    subject: str
    email: str
    display_name: str
    picture_url: str = ""


@dataclass(frozen=True)
class GoogleAccessToken:
    value: str
    expires_at: float

    def is_valid(self, now: float | None = None) -> bool:
        return bool(self.value) and self.expires_at - (time.time() if now is None else now) > 60


class GoogleAccountStateStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> GoogleAccount | None:
        if not self._path.is_file():
            return None
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if data.get("version") != ACCOUNT_STATE_VERSION:
            return None
        account = data.get("account")
        if not isinstance(account, dict):
            return None
        subject = str(account.get("subject", "")).strip()
        email = str(account.get("email", "")).strip()
        if not subject or not email:
            return None
        return GoogleAccount(
            subject=subject,
            email=email,
            display_name=str(account.get("display_name", "")).strip() or email,
            picture_url=str(account.get("picture_url", "")).strip(),
        )

    def save(self, account: GoogleAccount) -> None:
        write_json_atomic(
            self._path,
            {
                "version": ACCOUNT_STATE_VERSION,
                "account": {
                    "subject": account.subject,
                    "email": account.email,
                    "display_name": account.display_name,
                    "picture_url": account.picture_url,
                },
            },
        )

    def clear(self) -> None:
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass


class GoogleOAuthSession:
    def __init__(
        self,
        config: GoogleOAuthConfig,
        credentials: CredentialStore,
        account_store: GoogleAccountStateStore,
        *,
        requester: HttpRequester | None = None,
        browser_open: Callable[[str], bool] | None = None,
    ) -> None:
        if not config.client_id.strip():
            raise GoogleOAuthConfigurationError(
                "Google Drive OAuth client is not configured."
            )
        self._config = config
        self._credentials = credentials
        self._account_store = account_store
        self._request = requester or request_url
        self._browser_open = browser_open or webbrowser.open
        self._access_token = GoogleAccessToken("", 0)

    @property
    def account(self) -> GoogleAccount | None:
        if self._credentials.read(GOOGLE_CREDENTIAL_TARGET) is None:
            return None
        return self._account_store.load()

    @property
    def is_connected(self) -> bool:
        return self.account is not None

    def connect(
        self,
        *,
        timeout_seconds: float = 180,
        cancelled: Callable[[], bool] | None = None,
    ) -> GoogleAccount:
        verifier = secrets.token_urlsafe(64)[:96]
        challenge = _base64url(hashlib.sha256(verifier.encode("ascii")).digest())
        state = secrets.token_urlsafe(32)
        callback = _OAuthCallbackServer(state)
        try:
            authorization_parameters = {
                "client_id": self._config.client_id,
                "redirect_uri": callback.redirect_uri,
                "response_type": "code",
                "scope": " ".join(OAUTH_SCOPES),
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "access_type": "offline",
                "prompt": "consent",
            }
            authorization_url = (
                f"{AUTHORIZATION_URL}?{urlencode(authorization_parameters)}"
            )
            if not self._browser_open(authorization_url):
                raise GoogleOAuthError("The system browser could not be opened.")
            code = callback.wait(timeout_seconds, cancelled)
        finally:
            callback.close()

        token_data = self._post_form(
            TOKEN_URL,
            {
                "client_id": self._config.client_id,
                "code": code,
                "code_verifier": verifier,
                "grant_type": "authorization_code",
                "redirect_uri": callback.redirect_uri,
                **(
                    {"client_secret": self._config.client_secret}
                    if self._config.client_secret
                    else {}
                ),
            },
        )
        refresh_token = str(token_data.get("refresh_token", "")).strip()
        access_token = str(token_data.get("access_token", "")).strip()
        scope_text = str(token_data.get("scope", "")).strip()
        # OAuth 2.0 allows the token response to omit scope when it is
        # identical to the scope requested by the authorization code.
        scopes = set(scope_text.split()) if scope_text else set(OAUTH_SCOPES)
        if not refresh_token or not access_token:
            raise GoogleOAuthError("Google did not return reusable account credentials.")
        if DRIVE_FILE_SCOPE not in scopes:
            raise GoogleOAuthError("Google Drive file access was not granted.")

        self._access_token = _token_from_response(token_data)
        account = self._load_account(access_token)
        self._credentials.write(GOOGLE_CREDENTIAL_TARGET, refresh_token)
        self._account_store.save(account)
        return account

    def access_token(self, *, force_refresh: bool = False) -> str:
        if not force_refresh and self._access_token.is_valid():
            return self._access_token.value
        refresh_token = self._credentials.read(GOOGLE_CREDENTIAL_TARGET)
        if not refresh_token:
            raise GoogleOAuthError("Connect a Google Drive account first.")
        token_data = self._post_form(
            TOKEN_URL,
            {
                "client_id": self._config.client_id,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                **(
                    {"client_secret": self._config.client_secret}
                    if self._config.client_secret
                    else {}
                ),
            },
        )
        self._access_token = _token_from_response(token_data)
        return self._access_token.value

    def disconnect(self) -> None:
        refresh_token = self._credentials.read(GOOGLE_CREDENTIAL_TARGET)
        if refresh_token:
            request = Request(
                REVOKE_URL,
                data=urlencode({"token": refresh_token}).encode("ascii"),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            try:
                self._request(request, 15)
            except Exception:
                pass
        self._credentials.delete(GOOGLE_CREDENTIAL_TARGET)
        self._account_store.clear()
        self._access_token = GoogleAccessToken("", 0)

    def _load_account(self, access_token: str) -> GoogleAccount:
        response = self._request(
            Request(
                USER_INFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            ),
            30,
        )
        data = _successful_json(response, "Google account details")
        subject = str(data.get("sub", "")).strip()
        email = str(data.get("email", "")).strip()
        if not subject or not email:
            raise GoogleOAuthError("Google account details are incomplete.")
        return GoogleAccount(
            subject=subject,
            email=email,
            display_name=str(data.get("name", "")).strip() or email,
            picture_url=str(data.get("picture", "")).strip(),
        )

    def _post_form(self, url: str, values: Mapping[str, str]) -> dict[str, object]:
        response = self._request(
            Request(
                url,
                data=urlencode(values).encode("ascii"),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            ),
            30,
        )
        return _successful_json(response, "Google authorization")


def load_google_oauth_config(
    asset_path: Path,
    environ: Mapping[str, str] | None = None,
) -> GoogleOAuthConfig:
    environment = os.environ if environ is None else environ
    environment_id = environment.get("JJZERO_GOOGLE_CLIENT_ID", "").strip()
    environment_secret = environment.get("JJZERO_GOOGLE_CLIENT_SECRET", "").strip()
    if environment_id:
        return GoogleOAuthConfig(environment_id, environment_secret)
    try:
        data = json.loads(asset_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GoogleOAuthConfigurationError(
            "Google Drive OAuth client is not configured."
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise GoogleOAuthConfigurationError(
            "Google Drive OAuth configuration is invalid."
        ) from exc
    installed = data.get("installed") if isinstance(data, dict) else None
    values = installed if isinstance(installed, dict) else data
    if not isinstance(values, dict):
        raise GoogleOAuthConfigurationError(
            "Google Drive OAuth configuration is invalid."
        )
    client_id = str(values.get("client_id", "")).strip()
    if not client_id:
        raise GoogleOAuthConfigurationError(
            "Google Drive OAuth client is not configured."
        )
    return GoogleOAuthConfig(client_id, str(values.get("client_secret", "")).strip())


def request_url(request: Request, timeout: float) -> HttpResponse:
    try:
        with urlopen(request, timeout=timeout) as response:
            return HttpResponse(
                status=int(response.status),
                headers=dict(response.headers.items()),
                body=response.read(),
            )
    except HTTPError as exc:
        return HttpResponse(
            status=exc.code,
            headers=dict(exc.headers.items()) if exc.headers is not None else {},
            body=exc.read(),
        )
    except URLError as exc:
        raise GoogleOAuthError(f"Google network request failed: {exc.reason}") from exc


class _OAuthCallbackServer:
    def __init__(self, expected_state: str) -> None:
        self._expected_state = expected_state
        self._result = _OAuthCallbackResult()
        result = self._result

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                query = parse_qs(urlsplit(self.path).query)
                result.state = _first_query_value(query, "state")
                result.code = _first_query_value(query, "code")
                result.error = _first_query_value(query, "error")
                body = (
                    "<html><body style='font-family:sans-serif;background:#171717;color:#eee;"
                    "display:grid;place-items:center;height:100vh;margin:0'>"
                    "<div><h2>JJZero Audio</h2><p>You can close this window and return to the app.</p></div>"
                    "</body></html>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                result.received.set()

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self._server = HTTPServer(("127.0.0.1", 0), CallbackHandler)
        self._server.timeout = 0.25
        port = self._server.server_address[1]
        self.redirect_uri = f"http://127.0.0.1:{port}"

    def wait(
        self,
        timeout_seconds: float,
        cancelled: Callable[[], bool] | None,
    ) -> str:
        deadline = time.monotonic() + max(1.0, timeout_seconds)
        while not self._result.received.is_set():
            if cancelled is not None and cancelled():
                raise GoogleOAuthError("Google account connection was cancelled.")
            if time.monotonic() >= deadline:
                raise GoogleOAuthError("Google account connection timed out.")
            self._server.handle_request()
        if self._result.state != self._expected_state:
            raise GoogleOAuthError("Google authorization state did not match.")
        if self._result.error:
            raise GoogleOAuthError(f"Google authorization was declined: {self._result.error}")
        if not self._result.code:
            raise GoogleOAuthError("Google did not return an authorization code.")
        return self._result.code

    def close(self) -> None:
        self._server.server_close()


class _OAuthCallbackResult:
    def __init__(self) -> None:
        self.received = Event()
        self.state = ""
        self.code = ""
        self.error = ""


def _successful_json(response: HttpResponse, operation: str) -> dict[str, object]:
    data = response.json()
    if 200 <= response.status < 300:
        return data
    detail = _google_error_detail(data) or f"HTTP {response.status}"
    if _google_error_code(data) in {
        "deleted_client",
        "invalid_client",
        "unauthorized_client",
    }:
        raise GoogleOAuthConfigurationError(f"{operation} failed: {detail}")
    raise GoogleOAuthError(f"{operation} failed: {detail}")


def _token_from_response(data: Mapping[str, object]) -> GoogleAccessToken:
    value = str(data.get("access_token", "")).strip()
    if not value:
        raise GoogleOAuthError("Google did not return an access token.")
    try:
        expires_in = max(60, int(data.get("expires_in", 3600)))
    except (TypeError, ValueError):
        expires_in = 3600
    return GoogleAccessToken(value, time.time() + expires_in)


def _google_error_detail(data: Mapping[str, object]) -> str:
    error = data.get("error")
    if isinstance(error, str):
        description = str(data.get("error_description", "")).strip()
        return f"{error}: {description}" if description else error
    if isinstance(error, dict):
        message = str(error.get("message", "")).strip()
        status = str(error.get("status", "")).strip()
        return message or status
    return ""


def _google_error_code(data: Mapping[str, object]) -> str:
    error = data.get("error")
    if isinstance(error, str):
        return error.strip()
    if isinstance(error, dict):
        return str(error.get("status", "")).strip()
    return ""


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _first_query_value(query: Mapping[str, list[str]], key: str) -> str:
    values = query.get(key, ())
    return values[0] if values else ""
