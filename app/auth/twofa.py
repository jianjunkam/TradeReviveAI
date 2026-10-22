"""Two-factor sign-in: a TOTP code from an authenticator app.

`pyotp` does the maths (RFC 6238). AGENTS.md: no secret in a log, so the provisioning
URI is only ever returned to the signed-in page, never logged.
"""

from __future__ import annotations

import pyotp

ISSUER = "TradeRevive AI"


class InvalidCode(Exception):
    """The code did not match the user's secret."""


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, *, email: str) -> str:
    """The otpauth:// URI an authenticator app scans (shown once, at enrolment)."""
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER)


def verify(secret: str, code: str) -> bool:
    """True if the code is valid now, allowing one step of clock drift either way."""
    code = (code or "").strip()
    if not secret or not code.isdigit():
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)
