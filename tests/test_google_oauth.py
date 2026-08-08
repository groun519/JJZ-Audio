from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs
from urllib.request import Request

from jang_app.config import GOOGLE_OAUTH_CLIENT_PATH
from jang_app.services.google_oauth import (
    DRIVE_FILE_SCOPE,
    GoogleAccount,
    GoogleAccountStateStore,
    GoogleOAuthConfig,
    GoogleOAuthConfigurationError,
    GoogleOAuthError,
    GoogleOAuthSession,
    HttpResponse,
    load_google_oauth_config,
)


class _MemoryCredentials:
    def __init__(self, value: str | None = None) -> None:
        self.value = value

    def read(self, _target: str) -> str | None:
        return self.value

    def write(self, _target: str, secret: str) -> None:
        self.value = secret

    def delete(self, _target: str) -> None:
        self.value = None


class _OAuthCallback:
    redirect_uri = "http://127.0.0.1:54321"

    def __init__(self, _state: str) -> None:
        pass

    def wait(self, _timeout: float, _cancelled: object) -> str:
        return "authorization-code"

    def close(self) -> None:
        pass


class GoogleOAuthTests(unittest.TestCase):
    def test_connect_accepts_omitted_scope_for_identical_authorization(self) -> None:
        credentials = _MemoryCredentials()

        def request(request: Request, _timeout: float) -> HttpResponse:
            if request.full_url == "https://oauth2.googleapis.com/token":
                payload = {
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "expires_in": 3600,
                }
            else:
                payload = {
                    "sub": "account-id",
                    "email": "user@example.com",
                    "name": "User",
                }
            return HttpResponse(200, {}, json.dumps(payload).encode("utf-8"))

        with tempfile.TemporaryDirectory() as directory, patch(
            "jang_app.services.google_oauth._OAuthCallbackServer",
            _OAuthCallback,
        ):
            session = GoogleOAuthSession(
                GoogleOAuthConfig("client-id"),
                credentials,
                GoogleAccountStateStore(Path(directory) / "account.json"),
                requester=request,
                browser_open=lambda _url: True,
            )

            account = session.connect()

        self.assertEqual(account.email, "user@example.com")
        self.assertEqual(credentials.value, "refresh-token")

    def test_connect_rejects_explicitly_reduced_scope(self) -> None:
        credentials = _MemoryCredentials()

        def request(_request: Request, _timeout: float) -> HttpResponse:
            return HttpResponse(
                200,
                {},
                json.dumps(
                    {
                        "access_token": "access-token",
                        "refresh_token": "refresh-token",
                        "expires_in": 3600,
                        "scope": "openid email profile",
                    }
                ).encode("utf-8"),
            )

        with tempfile.TemporaryDirectory() as directory, patch(
            "jang_app.services.google_oauth._OAuthCallbackServer",
            _OAuthCallback,
        ):
            session = GoogleOAuthSession(
                GoogleOAuthConfig("client-id"),
                credentials,
                GoogleAccountStateStore(Path(directory) / "account.json"),
                requester=request,
                browser_open=lambda _url: True,
            )

            with self.assertRaisesRegex(GoogleOAuthError, "file access"):
                session.connect()

        self.assertIsNone(credentials.value)

    def test_packaged_desktop_client_secret_is_sent_to_token_endpoint(self) -> None:
        requests: list[Request] = []

        def request(request: Request, _timeout: float) -> HttpResponse:
            requests.append(request)
            return HttpResponse(
                200,
                {},
                json.dumps(
                    {
                        "access_token": "access-token",
                        "expires_in": 3600,
                    }
                ).encode("utf-8"),
            )

        config = load_google_oauth_config(GOOGLE_OAUTH_CLIENT_PATH)
        with tempfile.TemporaryDirectory() as directory:
            session = GoogleOAuthSession(
                config,
                _MemoryCredentials("refresh-token"),
                GoogleAccountStateStore(Path(directory) / "account.json"),
                requester=request,
            )

            session.access_token()

        form = parse_qs((requests[0].data or b"").decode("ascii"))
        self.assertTrue(config.client_secret)
        self.assertEqual(form["client_secret"], [config.client_secret])

    def test_invalid_client_disables_the_oauth_route(self) -> None:
        def request(_request: Request, _timeout: float) -> HttpResponse:
            return HttpResponse(
                400,
                {"Content-Type": "application/json"},
                json.dumps(
                    {
                        "error": "invalid_client",
                        "error_description": "The OAuth client was deleted.",
                    }
                ).encode("utf-8"),
            )

        with tempfile.TemporaryDirectory() as directory:
            session = GoogleOAuthSession(
                GoogleOAuthConfig("deleted-client"),
                _MemoryCredentials("refresh-token"),
                GoogleAccountStateStore(Path(directory) / "account.json"),
                requester=request,
            )

            with self.assertRaises(GoogleOAuthConfigurationError):
                session.access_token()

    def test_configuration_uses_environment_before_packaged_asset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            asset = Path(directory) / "client.json"
            asset.write_text(
                json.dumps({"installed": {"client_id": "asset-id"}}),
                encoding="utf-8",
            )

            config = load_google_oauth_config(
                asset,
                {"JJZERO_GOOGLE_CLIENT_ID": "environment-id"},
            )

        self.assertEqual(config.client_id, "environment-id")

    def test_account_metadata_never_contains_refresh_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "account.json"
            store = GoogleAccountStateStore(path)
            store.save(GoogleAccount("subject", "user@example.com", "User"))

            data = path.read_text(encoding="utf-8")

        self.assertNotIn("refresh", data.casefold())
        self.assertNotIn("token", data.casefold())

    def test_access_token_is_refreshed_from_credential_store(self) -> None:
        requests: list[Request] = []

        def request(request: Request, _timeout: float) -> HttpResponse:
            requests.append(request)
            return HttpResponse(
                200,
                {},
                json.dumps(
                    {
                        "access_token": "new-access-token",
                        "expires_in": 3600,
                        "scope": DRIVE_FILE_SCOPE,
                    }
                ).encode("utf-8"),
            )

        with tempfile.TemporaryDirectory() as directory:
            session = GoogleOAuthSession(
                GoogleOAuthConfig("client-id"),
                _MemoryCredentials("refresh-token"),
                GoogleAccountStateStore(Path(directory) / "account.json"),
                requester=request,
            )

            token = session.access_token()

        self.assertEqual(token, "new-access-token")
        self.assertEqual(requests[0].full_url, "https://oauth2.googleapis.com/token")
        self.assertIn(b"refresh_token=refresh-token", requests[0].data or b"")


if __name__ == "__main__":
    unittest.main()
