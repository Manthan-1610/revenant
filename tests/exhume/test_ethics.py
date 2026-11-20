"""Tests for the Ethics_Filter (`revenant.exhume.ethics`)."""

from __future__ import annotations

from urllib.parse import quote

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from revenant.exhume.ethics import AUTH_SUBSTRINGS, has_auth_param

BASE = "http://ichart.yahoo.com:80"
UNRESERVED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~")

printable = st.characters(min_codepoint=0x20, max_codepoint=0x7E)
auth_word = st.sampled_from(AUTH_SUBSTRINGS).flatmap(
    lambda w: st.lists(st.booleans(), min_size=len(w), max_size=len(w)).map(
        lambda ups: "".join(c.upper() if u else c for c, u in zip(w, ups, strict=True))
    )
)
fragment_text = st.lists(st.one_of(auth_word, st.text(printable, max_size=5)), max_size=4).map(
    "".join
)


def _is_auth(name: str) -> bool:
    return any(sub in name.lower() for sub in AUTH_SUBSTRINGS)


@st.composite
def encoded_name(draw: st.DrawFn, name: str) -> str:
    """Percent-encode `name`; unreserved characters stay raw or get encoded at random."""
    out = []
    for ch in name:
        if ch in UNRESERVED and draw(st.booleans()):
            out.append(ch)
        else:
            out.append(f"%{ord(ch):02X}")
    return "".join(out)


@st.composite
def urls(draw: st.DrawFn, names: st.SearchStrategy[str]) -> tuple[str, list[str]]:
    """A URL whose decoded parameter names are exactly the returned list.

    Values, path and fragment are stuffed with Auth words; names are fully percent-encoded
    (apart from random raw unreserved characters), so escaping never forms or hides a name.
    """
    decoded = draw(st.lists(names, min_size=1, max_size=5))
    pairs = []
    for name in decoded:
        enc = draw(encoded_name(name))
        if draw(st.booleans()):
            pairs.append(enc)  # a name without a value still counts
        else:
            pairs.append(f"{enc}={quote(draw(fragment_text), safe='')}")
    path = "/" + quote(draw(fragment_text), safe="") + "/table.csv"
    url = f"{BASE}{path}?{'&'.join(pairs)}"
    if draw(st.booleans()):
        # A raw `&key=1`-style fragment must never count either.
        url += "#" + quote(draw(fragment_text), safe="=&")
    return url, decoded


any_name = (
    st.lists(st.one_of(auth_word, st.text(printable, max_size=6)), max_size=3)
    .map("".join)
    .filter(bool)
)
clean_name = st.text(printable, min_size=1, max_size=8).filter(lambda n: not _is_auth(n))


# Feature: exhume, Property 5: Auth filter matches names only
@settings(max_examples=100)
@given(urls(any_name))
def test_auth_filter_matches_decoded_names(case: tuple[str, list[str]]) -> None:
    """**Validates: Requirements 8.2, 8.3**"""
    url, names = case
    assert has_auth_param(url) == any(_is_auth(n) for n in names)


# Feature: exhume, Property 5: Auth filter matches names only
@settings(max_examples=100)
@given(urls(clean_name))
def test_auth_words_outside_names_never_count(case: tuple[str, list[str]]) -> None:
    """**Validates: Requirements 8.3**"""
    url, _ = case
    assert has_auth_param(url) is False


@pytest.mark.parametrize(
    "query",
    [
        "apiKey=x",
        "X-Crumb=1",
        "%63rumb=1",
        "keyword=x",
        "s=GOOG&session",
        "s=DISH&amp;crumb=x",
        "s=DISH&notoken=x",
        "USER_EMAIL=a",
    ],
)
def test_auth_like_names_are_rejected(query: str) -> None:
    assert has_auth_param(f"{BASE}/table.csv?{query}") is True


@pytest.mark.parametrize(
    "url",
    [
        f"{BASE}/table.csv?s=TOKEN",
        f"{BASE}/table.csv?s=DISH&amp",
        f"{BASE}/table.csv?s=%5EVIX&amp;g=d&amp;ignore=.csv",
        f"{BASE}/token/key/table.csv?s=GOOG",
        f"{BASE}/table.csv?s=GOOG#crumb=1&key=2",
        f"{BASE}/table.csv",
    ],
)
def test_auth_words_in_values_path_or_fragment_are_accepted(url: str) -> None:
    assert has_auth_param(url) is False


def test_unparseable_url_is_rejected() -> None:
    assert has_auth_param("http://[::1/table.csv?s=GOOG") is True
