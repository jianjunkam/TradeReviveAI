"""Failed sign-ins: slow down first, then lock.

The counter lives in the store, keyed by user, so every server sees the same number.
The clock is injected so a 15-minute lock is testable in milliseconds.

Policy: three wrong codes are simply wrong. The fourth and fifth are answered with
`429 Retry-After`; the fifth arms the lock, and nothing gets through until it expires.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.auth.store import AuthStore

SLOWDOWN_AFTER_FAILURES = 3
LOCK_AFTER_FAILURES = 5
LOCK_SECONDS = 900  # 15 minutes
BACKOFF_SECONDS = 2


class Throttle:
    def __init__(
        self,
        store: AuthStore,
        clock: Callable[[], datetime] | None = None,
        *,
        slowdown_after: int = SLOWDOWN_AFTER_FAILURES,
        lock_after: int = LOCK_AFTER_FAILURES,
        lock_seconds: int = LOCK_SECONDS,
    ) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._slowdown_after = slowdown_after
        self._lock_after = lock_after
        self._lock_seconds = lock_seconds

    def check(self, key: str) -> int | None:
        """Seconds to wait if this key is locked, otherwise None."""
        state = self._store.get_attempts(key)
        if state.locked_until is None:
            return None
        remaining = (state.locked_until - self._clock()).total_seconds()
        if remaining > 0:
            return max(1, math.ceil(remaining))
        # The lock has been served: forget the history so one more slip does not
        # lock the account again immediately.
        self._store.clear_attempts(key)
        return None

    def record_failure(self, key: str) -> int | None:
        """Count one failure. Returns seconds to wait, or None if the attempt was free."""
        state = self._store.record_failure(key)
        if state.failures >= self._lock_after:
            self._store.lock(key, self._clock() + timedelta(seconds=self._lock_seconds))
            return self._lock_seconds
        if state.failures > self._slowdown_after:
            return BACKOFF_SECONDS
        return None

    def clear(self, key: str) -> None:
        self._store.clear_attempts(key)
