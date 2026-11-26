"""Example tests and Property 3 for the Redactor (Req 7.2)."""

from __future__ import annotations

import string
from urllib.parse import quote

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

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


_COLONS = (":", "%3A", "%3a")
_SEPS = ("\\", "/", "\\\\", "%5C", "%5c")
_FILLER = string.ascii_letters + string.digits + " .,;=-_"

keys = st.text(string.ascii_letters + string.digits + "-_", min_size=16, max_size=40)
names = st.text(string.ascii_letters + string.digits + " .-_", min_size=1, max_size=12).filter(
    lambda n: n.strip(" ") == n and n.strip()
)
emails = st.builds(
    lambda local, domain, tld: f"{local}@{domain}.{tld}",
    st.text(string.ascii_letters + string.digits + "._%+-", min_size=1, max_size=10),
    st.text(string.ascii_letters + string.digits + "-", min_size=1, max_size=10),
    st.text(string.ascii_letters, min_size=2, max_size=4),
)


def _all_spellings(letter: str, name: str) -> list[str]:
    """Every Home_Path spelling of `<letter>:\\Users\\<name>` the Redactor must remove."""
    out = []
    for drive in {letter.lower(), letter.upper()}:
        for colon in _COLONS:
            for sep in _SEPS:
                for seg in {name, quote(name, safe="")}:
                    out.append(f"{drive}{colon}{sep}Users{sep}{seg}")
    return out


# Feature: reanimate, Property 3: Redaction removes every secret
@settings(max_examples=100)
@given(
    key=keys,
    letter=st.sampled_from(string.ascii_letters),
    name=names,
    mail=st.lists(emails, min_size=1, max_size=3),
    picks=st.lists(st.integers(min_value=0), min_size=1, max_size=6),
    filler=st.lists(st.text(_FILLER, max_size=12), min_size=1, max_size=6),
    data=st.data(),
)
def test_property_redaction_removes_every_secret(
    key: str,
    letter: str,
    name: str,
    mail: list[str],
    picks: list[int],
    filler: list[str],
    data: st.DataObject,
) -> None:
    """**Validates: Requirements 7.2**"""
    spellings = _all_spellings(letter, name)
    homes = [spellings[p % len(spellings)] + "\\x.py" for p in picks]
    parts = [key, *mail, *homes, *filler]
    text = " ".join(data.draw(st.permutations(parts)))

    redact = Redactor(key, f"{letter.upper()}:\\Users\\{name}")
    once = redact(text)

    assert key not in once
    for address in mail:
        assert address not in once
    for spelling in spellings:
        assert spelling not in once
    assert redact(once) == once
