"""Magic-link tokens: signed, time-limited, single use.

`itsdangerous` signs the token so it cannot be forged; the store keeps a per-token id so
the link can only be redeemed once, which a signature alone cannot enforce.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.auth.store import AuthStore

MAGIC_LINK_MAX_AGE = 15 * 60  # seconds
PURPOSE = "magic_link"
_SALT = "traderevive.magic-link"


class MagicLinkTokens:
    def __init__(self, secret: str, store: AuthStore) -> None:
        self._serializer = URLSafeTimedSerializer(secret_key=secret, salt=_SALT)
        self._store = store

    def issue(self, user_id: str, *, now: datetime | None = None) -> str:
        """Create a link token for one user and remember its id for single use."""
        issued = now or datetime.now(timezone.utc)
        token_id = secrets.token_urlsafe(16)
        self._store.put_token(
            token_id,
            user_id,
            PURPOSE,
            expires_at=issued + timedelta(seconds=MAGIC_LINK_MAX_AGE),
        )
        return self._serializer.dumps({"uid": user_id, "jti": token_id})

    def redeem(self, token: str, *, now: datetime | None = None) -> str | None:
        """Return the user id if the token is genuine, unexpired and unused."""
        try:
            payload = self._serializer.loads(token, max_age=MAGIC_LINK_MAX_AGE)
        except (BadSignature, SignatureExpired):
            return None
        if not isinstance(payload, dict):
            return None
        token_id = payload.get("jti")
        user_id = payload.get("uid")
        if not isinstance(token_id, str) or not isinstance(user_id, str):
            return None
        redeemed_for = self._store.consume_token(
            token_id, PURPOSE, now or datetime.now(timezone.utc)
        )
        if redeemed_for != user_id:
            return None
        return user_id
