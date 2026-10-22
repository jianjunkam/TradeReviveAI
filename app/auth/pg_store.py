"""The sign-in store, backed by PostgreSQL.

Users live in the real `users` table so that tenants, roles and language preferences
survive a restart and are visible to every server. Single-use tokens and attempt
counters stay in memory for now: docs/DATA_MODEL.md defines no table for them, and a
shared store for them is an M8 concern (one process, one database until then).
"""

from __future__ import annotations

import secrets
from datetime import datetime
from threading import Lock

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.auth.store import (
    ADMIN,
    GUEST,
    MFA_REQUIRED_ROLES,
    TRADER,
    Attempts,
    AuthStore,
    InMemoryAuthStore,
    User,
)
from app.db import make_session_factory
from app.models import User as UserRow

__all__ = ["PostgresAuthStore", "ADMIN", "GUEST", "TRADER", "MFA_REQUIRED_ROLES", "Attempts"]


class PostgresAuthStore:
    """Implements the `AuthStore` protocol on top of the `users` table."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._factory = make_session_factory(engine)
        self._lock = Lock()
        # Tokens and lockout counters are ephemeral; the in-memory store already has
        # exactly the semantics we need, so it is reused rather than reimplemented.
        self._ephemeral = InMemoryAuthStore()

    # -- users -----------------------------------------------------------------

    def get_user(self, user_id: str) -> User | None:
        with self._factory() as session:
            row = session.scalars(select(UserRow).where(UserRow.id == user_id)).first()
            return _to_domain(row) if row is not None else None

    def get_user_by_email(self, email: str) -> User | None:
        normalised = email.strip().lower()
        with self._factory() as session:
            row = session.scalars(
                select(UserRow).where(UserRow.email == normalised)
            ).first()
            return _to_domain(row) if row is not None else None

    def users_with_email(self, email: str) -> list[User]:
        normalised = email.strip().lower()
        with self._factory() as session:
            rows = session.scalars(select(UserRow).where(UserRow.email == normalised)).all()
            return [_to_domain(row) for row in rows]

    def upsert_user(
        self, *, email: str, name: str, provider: str, email_verified: bool
    ) -> User:
        existing = self.get_user_by_email(email)
        if existing is not None:
            if email_verified and not existing.email_verified:
                existing.email_verified = True
                self.save_user(existing)
            return existing

        normalised = email.strip().lower()
        row = UserRow(
            id=f"user_{secrets.token_hex(8)}",
            tenant_id=f"tenant_{secrets.token_hex(8)}",
            email=normalised,
            name=name or normalised.split("@")[0],
            role=TRADER,
            provider=provider,
            email_verified=email_verified,
            language_preference="en",
            subscription_tier="free",
            totp_secret=None,
            password_hash=None,
        )
        try:
            with self._factory() as session:
                session.add(row)
                session.commit()
        except IntegrityError:
            # Two requests registered the same address at once; the unique index won,
            # so return the row that got there first.
            winner = self.get_user_by_email(email)
            if winner is None:  # pragma: no cover - the insert failed for another reason
                raise
            return winner
        return _to_domain(row)

    def save_user(self, user: User) -> None:
        with self._factory() as session:
            row = session.scalars(select(UserRow).where(UserRow.id == user.id)).first()
            if row is None:  # pragma: no cover - only reachable if a user is deleted
                raise LookupError(f"no user row for {user.id}")
            row.name = user.name
            row.role = user.role
            row.email_verified = user.email_verified
            row.provider = user.provider
            row.language_preference = user.language_preference
            row.subscription_tier = user.subscription_tier
            row.totp_secret = user.totp_secret
            # Deliberately not written: password_hash. Nothing in this app sets it.
            session.commit()

    # -- ephemeral state -------------------------------------------------------

    def put_token(
        self, token_id: str, user_id: str, purpose: str, expires_at: datetime
    ) -> None:
        self._ephemeral.put_token(token_id, user_id, purpose, expires_at)

    def consume_token(self, token_id: str, purpose: str, now: datetime) -> str | None:
        return self._ephemeral.consume_token(token_id, purpose, now)

    def get_attempts(self, key: str) -> Attempts:
        return self._ephemeral.get_attempts(key)

    def record_failure(self, key: str) -> Attempts:
        return self._ephemeral.record_failure(key)

    def lock(self, key: str, until: datetime) -> None:
        self._ephemeral.lock(key, until)

    def clear_attempts(self, key: str) -> None:
        self._ephemeral.clear_attempts(key)


def _to_domain(row: UserRow) -> User:
    """A detached value object, so routes never hold a live ORM row."""
    return User(
        id=row.id,
        tenant_id=row.tenant_id,
        email=row.email,
        name=row.name,
        role=row.role,
        provider=row.provider,
        email_verified=row.email_verified,
        language_preference=row.language_preference,
        subscription_tier=row.subscription_tier,
        created_at=row.created_at,
        totp_secret=row.totp_secret,
        password_hash=row.password_hash,
    )
