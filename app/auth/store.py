"""Where users, single-use tokens and attempt counters live.

M1 keeps this behind a protocol with an in-memory implementation, because PostgreSQL
arrives with the data model in M3. Everything the app does with state goes through
`AuthStore`, so swapping in a Postgres-backed store at M3 is one line in `create_app`
and no change in the routes.

AGENTS.md: every row carries the tenant id. `User` does, and every lookup that returns
a user hands back the tenant, so a caller cannot forget it.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Protocol

TRADER = "Trader (Account Owner)"
GUEST = "Guest / Anonymous Visitor"
ADMIN = "System Administrator"

MFA_REQUIRED_ROLES = frozenset({TRADER, ADMIN})


@dataclass
class User:
    """One person. `tenant_id` is the workspace their data belongs to."""

    id: str
    tenant_id: str
    email: str
    name: str
    role: str = TRADER
    provider: str = "magic_link"
    email_verified: bool = False
    language_preference: str = "en"
    subscription_tier: str = "free"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    totp_secret: str | None = None
    # docs/DATA_MODEL.md lists this column. Nothing in this app ever writes to it:
    # AGENTS.md forbids storing a password ourselves. It stays None, always.
    password_hash: str | None = None


@dataclass
class Attempts:
    """Failed sign-in count for one key, and the lock it may have earned."""

    failures: int = 0
    locked_until: datetime | None = None


@dataclass
class _Token:
    user_id: str
    purpose: str
    expires_at: datetime


class AuthStore(Protocol):
    """The state the sign-in flow needs."""

    def get_user(self, user_id: str) -> User | None: ...

    def get_user_by_email(self, email: str) -> User | None: ...

    def upsert_user(
        self, *, email: str, name: str, provider: str, email_verified: bool
    ) -> User: ...

    def save_user(self, user: User) -> None: ...

    def put_token(
        self, token_id: str, user_id: str, purpose: str, expires_at: datetime
    ) -> None: ...

    def consume_token(
        self, token_id: str, purpose: str, now: datetime
    ) -> str | None: ...

    def get_attempts(self, key: str) -> Attempts: ...

    def record_failure(self, key: str) -> Attempts: ...

    def lock(self, key: str, until: datetime) -> None: ...

    def clear_attempts(self, key: str) -> None: ...


class InMemoryAuthStore:
    """A store that lives as long as the process. Replaced by Postgres in M3.

    It is thread-safe enough for the test client and a single dev server; it is
    explicitly *not* the production answer, because QUALITY.md forbids keeping state in
    the app server's memory and a second server would not see these records.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._users: dict[str, User] = {}
        self._by_email: dict[str, str] = {}
        self._tokens: dict[str, _Token] = {}
        self._attempts: dict[str, Attempts] = {}

    def get_user(self, user_id: str) -> User | None:
        with self._lock:
            return self._users.get(user_id)

    def get_user_by_email(self, email: str) -> User | None:
        with self._lock:
            user_id = self._by_email.get(_normalise(email))
            return self._users.get(user_id) if user_id else None

    def upsert_user(
        self, *, email: str, name: str, provider: str, email_verified: bool
    ) -> User:
        with self._lock:
            key = _normalise(email)
            existing_id = self._by_email.get(key)
            if existing_id:
                existing = self._users[existing_id]
                # Never silently re-point an account at a different provider.
                if email_verified:
                    existing.email_verified = True
                return existing

            user = User(
                id=f"user_{secrets.token_hex(8)}",
                tenant_id=f"tenant_{secrets.token_hex(8)}",
                email=key,
                name=name,
                provider=provider,
                email_verified=email_verified,
                totp_secret=None,
            )
            self._users[user.id] = user
            self._by_email[key] = user.id
            return user

    def save_user(self, user: User) -> None:
        with self._lock:
            self._users[user.id] = user
            self._by_email[_normalise(user.email)] = user.id

    def put_token(
        self, token_id: str, user_id: str, purpose: str, expires_at: datetime
    ) -> None:
        with self._lock:
            self._tokens[token_id] = _Token(user_id, purpose, expires_at)

    def consume_token(self, token_id: str, purpose: str, now: datetime) -> str | None:
        with self._lock:
            token = self._tokens.get(token_id)
            if token is None or token.purpose != purpose:
                return None
            # Single use: it is gone whether or not it had expired.
            del self._tokens[token_id]
            if token.expires_at <= now:
                return None
            return token.user_id

    def get_attempts(self, key: str) -> Attempts:
        with self._lock:
            return self._attempts.setdefault(key, Attempts())

    def record_failure(self, key: str) -> Attempts:
        with self._lock:
            state = self._attempts.setdefault(key, Attempts())
            state.failures += 1
            return state

    def lock(self, key: str, until: datetime) -> None:
        with self._lock:
            self._attempts.setdefault(key, Attempts()).locked_until = until

    def clear_attempts(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)


def _normalise(email: str) -> str:
    return email.strip().lower()
