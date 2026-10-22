"""Google sign-in.

The real provider uses Authlib for the OAuth code exchange; tests inject
`FakeGoogleProvider` so the suite never needs Google credentials or a network.

Why a provider seam rather than a test flag: the production path stays exactly the code
that runs in production, and the fake can only be installed by the code that builds the
app (tests), never by a request.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPES = "openid email profile"


class GoogleSignInError(Exception):
    """Google refused, timed out, or is not configured."""


@dataclass(frozen=True)
class GoogleIdentity:
    """What we accept from Google. `email_verified` is the claim, not our opinion."""

    subject: str
    email: str
    email_verified: bool
    name: str


class GoogleProvider(Protocol):
    def authorize_url(self, *, state: str, redirect_uri: str) -> str: ...

    def exchange(self, *, code: str, redirect_uri: str) -> GoogleIdentity: ...


class FakeGoogleProvider:
    """Stands in for Google in tests. Codes are checked so a stray code cannot pass."""

    TEST_CODE = "test-code"

    def __init__(self, identity: GoogleIdentity) -> None:
        self.identity = identity
        self.authorize_calls: list[dict[str, str]] = []

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        self.authorize_calls.append({"state": state, "redirect_uri": redirect_uri})
        query = urlencode(
            {
                "client_id": "fake-client-id",
                "response_type": "code",
                "scope": SCOPES,
                "redirect_uri": redirect_uri,
                "state": state,
            }
        )
        return f"https://fake-google.example/authorize?{query}"

    def exchange(self, *, code: str, redirect_uri: str) -> GoogleIdentity:
        if code != self.TEST_CODE:
            raise GoogleSignInError("the fake provider only accepts its test code")
        return self.identity


class AuthlibGoogleProvider:
    """The real thing. `authorize_url` is offline; `exchange` calls Google."""

    def __init__(self, client_id: str, client_secret: str, *, timeout: float = 10.0) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout = timeout

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        query = urlencode(
            {
                "client_id": self._client_id,
                "response_type": "code",
                "scope": SCOPES,
                "redirect_uri": redirect_uri,
                "state": state,
                "prompt": "select_account",
            }
        )
        return f"{GOOGLE_AUTHORIZE_URL}?{query}"

    def exchange(self, *, code: str, redirect_uri: str) -> GoogleIdentity:
        # Imported here so the app can start (and serve /health) without authlib's
        # HTTP stack being importable, and so an offline unit test never touches it.
        from authlib.integrations.httpx_client import OAuth2Client

        client = OAuth2Client(
            client_id=self._client_id,
            client_secret=self._client_secret,
            timeout=self._timeout,
        )
        try:
            client.fetch_token(
                GOOGLE_TOKEN_URL,
                code=code,
                redirect_uri=redirect_uri,
                grant_type="authorization_code",
            )
            response = client.get(GOOGLE_USERINFO_URL)
            response.raise_for_status()
            claims = response.json()
        except Exception as exc:  # network, 4xx, bad JSON — all the same to the caller
            raise GoogleSignInError("Google sign-in could not be completed") from exc

        return GoogleIdentity(
            subject=str(claims.get("sub", "")),
            email=str(claims.get("email", "")).strip().lower(),
            # Google sends a bool; treat anything else as unverified, not as true.
            email_verified=claims.get("email_verified") is True,
            name=str(claims.get("name") or claims.get("email") or ""),
        )


class UnconfiguredGoogleProvider:
    """No GOOGLE_CLIENT_ID/SECRET: say so plainly instead of failing obscurely."""

    MESSAGE = "Google sign-in is not configured (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)"

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        raise GoogleSignInError(self.MESSAGE)

    def exchange(self, *, code: str, redirect_uri: str) -> GoogleIdentity:
        raise GoogleSignInError(self.MESSAGE)


def build_google_provider(settings) -> GoogleProvider:
    client_id = settings.google_client_id
    client_secret = settings.google_client_secret
    if client_id and client_secret and client_secret.get_secret_value():
        return AuthlibGoogleProvider(client_id, client_secret.get_secret_value())
    return UnconfiguredGoogleProvider()
