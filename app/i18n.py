"""System strings in English and Bahasa Melayu.

AC1.4: the language preference swaps labels from a dictionary. No model is called, so the
UI text is the same every time and costs nothing — AGENTS.md's "language preference
toggles the system string dictionary without calling an LLM".
"""

from __future__ import annotations

LANGUAGES = ("en", "ms")

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "workspace": "Your workspace",
        "signed_in_as": "Signed in as",
        "tenant": "Tenant",
        "sign_out": "Sign out",
        "sign_in": "Sign in",
        "email_me_a_link": "Email me a link",
        "two_factor": "One more step",
        "language": "English",
    },
    "ms": {
        "workspace": "Ruang kerja anda",
        "signed_in_as": "Log masuk sebagai",
        "tenant": "Penyewa",
        "sign_out": "Log keluar",
        "sign_in": "Log masuk",
        "email_me_a_link": "E-mel saya pautan",
        "two_factor": "Satu langkah lagi",
        "language": "Bahasa Melayu",
    },
}


def t(language: str, key: str) -> str:
    """The string for a language, falling back to English rather than to a blank label."""
    table = STRINGS.get(language) or STRINGS["en"]
    return table.get(key) or STRINGS["en"].get(key, key)
