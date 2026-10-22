"""Sending the magic link.

The transport is behind `EmailSender` so tests never open a socket. `RecordingEmailSender`
keeps messages in memory and is what `create_app` falls back to when no provider is
configured — see `build_email_sender` for the open decision.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol

from app.config import Settings

logger = logging.getLogger("app.auth.email")

_URL = re.compile(r"https?://\S+")


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str


class EmailSender(Protocol):
    def send(self, *, to: str, subject: str, text: str) -> None: ...


class RecordingEmailSender:
    """Captures messages instead of sending them. Used by tests and by local dev."""

    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []

    def send(self, *, to: str, subject: str, text: str) -> None:
        self.messages.append(EmailMessage(to=to, subject=subject, text=text))

    def clear(self) -> None:
        self.messages.clear()

    def last(self) -> EmailMessage | None:
        return self.messages[-1] if self.messages else None

    def last_url(self) -> str | None:
        message = self.last()
        if message is None:
            return None
        match = _URL.search(message.text)
        return match.group(0) if match else None


class ConsoleEmailSender:
    """Writes the message to stdout. Local development only, chosen by `build_email_sender`.

    This is the Django-style console backend: the only way to finish a magic-link sign-in
    by hand without an email provider. It is selected only when `ENVIRONMENT` is
    "development"; every other environment uses the real sender or records (see below).
    """

    def send(self, *, to: str, subject: str, text: str) -> None:
        print(f"[dev email] to={to} subject={subject}\n{text}\n", flush=True)


def build_email_sender(settings: Settings) -> EmailSender:
    """The sender the running app uses.

    EMAIL_API_KEY alone does not say *which* email provider to call, and inventing an
    endpoint would be guessing at the integration — that is a decision for the human.
    Until it is made: development prints the mail to the console, and every other
    environment records it in-process and warns loudly, rather than pretending a link
    was delivered.
    """
    if settings.environment == "development":
        return ConsoleEmailSender()

    logger.warning(
        "No email provider is configured yet: magic links are recorded in-process "
        "and not sent. Set up a provider before this environment goes live."
    )
    return RecordingEmailSender()
