"""Example tests for the Redactor (Req 7.2)."""

from __future__ import annotations

import pytest

from revenant.reanimate.redact import Redactor

HOME = r"C:\Users\ghost"


@pytest.mark.parametrize(
    "spelling",
    [
        r"C:\Users\ghost",
        "C:/Users/ghost",
        r"C:\\Users\\ghost",
        "c%3A/Users/ghost",
        r"C%3A%5CUsers%5Cghost",
        "c%3a%5cUsers%5cghost",
        r"c:\Users\ghost",
    ],
)
def test_home_spellings_become_tilde(spelling: str) -> None:
    redact = Redactor(None, HOME)
    assert redact(f"file:///{spelling}/x.py") == "file:///~/x.py"


def test_key_and_email_redacted() -> None:
    redact = Redactor("sk-fake-0123456789abcdef", HOME)
    out = redact("key=sk-fake-0123456789abcdef by ghost@example.invalid")
    assert out == "key=[REDACTED] by [REDACTED]"


def test_empty_key_is_ignored_and_idempotent() -> None:
    redact = Redactor("", HOME)
    text = r"C:\Users\ghost\a ghost@example.invalid plain"
    once = redact(text)
    assert once == r"~\a [REDACTED] plain"
    assert redact(once) == once


def test_accepted_over_redaction() -> None:
    assert Redactor(None, HOME)(r"\n@app.get") == "\\[REDACTED]"


def test_posix_home_and_encoded_segments() -> None:
    redact = Redactor(None, "/home/my ghost")
    assert redact("/home/my ghost/a file:///home/my%20ghost/b") == "~/a file://~/b"
