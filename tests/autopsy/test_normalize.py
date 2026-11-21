"""Query_Normalizer tests (Req 2.1, F15)."""

from __future__ import annotations

import html

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from revenant.autopsy.normalize import normalize_query, unescape_fixpoint
from revenant.exhume.select import interval, parameter_shape, parse_query

QUERY_CHARS = st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789^%.=&")


def _escape(text: str, times: int) -> str:
    for _ in range(times):
        text = html.escape(text)
    return text


# Feature: autopsy, Property 3: Unescape fixpoint
@settings(max_examples=100)
@given(query=st.text(QUERY_CHARS, max_size=40), times=st.integers(min_value=0, max_value=3))
def test_unescape_fixpoint_matches_parse_query(query: str, times: int) -> None:
    """**Validates: Requirements 2.1**

    Raw queries that already look like HTML entities (e.g. `&ampamp`) are skipped: there a single
    unescape (Exhume's `parse_query`, the reference) and the fixpoint legitimately differ.
    """
    # The unescaped query is one that Exhume's single unescape already settles: a query such as
    # `&ampamp` (legacy entities without `;`) needs two unescapes even before any escaping.
    assume(html.unescape(query) == unescape_fixpoint(query))
    original = "http://ichart.yahoo.com/table.csv?" + _escape(query, times)
    assert normalize_query(original) == parse_query("?" + query)


def test_double_escaped_amp_yields_d() -> None:
    original = "http://ichart.yahoo.com/table.csv?s=DISH&amp;amp;d=0&amp;amp;g=d"
    pairs = normalize_query(original)
    assert pairs == [("s", "DISH"), ("d", "0"), ("g", "d")]
    assert interval(pairs) == "d"


def test_shape_from_exhume_on_normalized_pairs() -> None:
    pairs = normalize_query("http://ichart.yahoo.com/table.csv?s=IBM&amp;ignore=.csv")
    assert parameter_shape(pairs) == "s_only"
