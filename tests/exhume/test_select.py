"""Tests for deterministic selection (`revenant/exhume/select.py`)."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from revenant.exhume.models import CdxRow
from revenant.exhume.select import (
    backfill_order,
    interval,
    parameter_shape,
    parse_query,
    select,
)

# F1 `original` URLs, verbatim.
F1_GOOG = (
    "http://ichart.yahoo.com:80/table.csv?s=GOOG&a=0&b=1&c=2000&d=0&e=31&f=2010&g=w&ignore=.csv"
)
F1_HK = (
    "http://ichart.yahoo.com:80/table.csv?s=0298.HK&d=0&e=1&f=2009&g=d&a=0&b=1&c=2003&ignore=.csv"
)
F15_DISH = "http://ichart.yahoo.com:80/table.csv?s=DISH&amp"
F15_VIX = "http://ichart.finance.yahoo.com:80/table.csv?s=%5EVIX&amp;g=d&amp;ignore=.csv"
F17_JUNK = (
    "http://ichart.yahoo.com:80/table.csv?s=AAPL&a=0&b=1&c={{(-1 month).year}}"
    "&d=0&e=31&f=2016&g=d&ignore=.csv"
)


def _row(timestamp: str, original: str, digest: str) -> CdxRow:
    return CdxRow(
        timestamp=timestamp,
        original=original,
        mimetype="text/csv",
        statuscode="200",
        digest=digest,
        length="100",
    )


def _group(row: CdxRow) -> tuple[str, str]:
    pairs = parse_query(row.original)
    return (interval(pairs), parameter_shape(pairs))


# --- parse_query, parameter_shape, interval (Req 4.1, F1, F15, F17) ---------------------------


def test_parse_query_f1_urls_keep_order_and_ignore_port() -> None:
    assert parse_query(F1_GOOG) == [
        ("s", "GOOG"),
        ("a", "0"),
        ("b", "1"),
        ("c", "2000"),
        ("d", "0"),
        ("e", "31"),
        ("f", "2010"),
        ("g", "w"),
        ("ignore", ".csv"),
    ]
    assert dict(parse_query(F1_HK))["s"] == "0298.HK"
    assert parameter_shape(parse_query(F1_HK)) == "full_range"
    assert interval(parse_query(F1_HK)) == "d"


def test_parse_query_raw_and_percent_encoded_caret_match() -> None:
    raw = parse_query("http://ichart.finance.yahoo.com:80/table.csv?s=^DJI&g=d")
    encoded = parse_query("http://ichart.finance.yahoo.com:80/table.csv?s=%5EDJI&g=d")
    assert raw == encoded == [("s", "^DJI"), ("g", "d")]


def test_f15_amp_artifacts() -> None:
    dish = parse_query(F15_DISH)
    assert dict(dish)["s"] == "DISH"
    assert parameter_shape(dish) == "s_only"
    assert interval(dish) == "none"
    vix = parse_query(F15_VIX)
    assert dict(vix) == {"s": "^VIX", "g": "d", "ignore": ".csv"}
    assert interval(vix) == "d"
    assert "amp" not in dict(vix)


def test_f17_template_junk_is_other_and_does_not_raise() -> None:
    pairs = parse_query(F17_JUNK)
    assert dict(pairs)["c"] == "{{(-1 month).year}}"
    assert parameter_shape(pairs) == "other"
    assert interval(pairs) == "d"


def test_each_shape_kind() -> None:
    base = "http://ichart.yahoo.com:80/table.csv?"
    assert parameter_shape(parse_query(base + "s=IBM")) == "s_only"
    assert parameter_shape(parse_query(base + "s=IBM&ignore=.csv")) == "s_only"
    empty = base + "s=IBM&a=&b=&c=&d=&e=&f=&g=&ignore=.csv"
    assert parameter_shape(parse_query(empty)) == "empty_range"
    assert interval(parse_query(empty)) == "none"
    assert parameter_shape(parse_query(F1_GOOG)) == "full_range"
    # Partial range, mixed empty/non-empty, extra names, no `s`: all `other`.
    assert parameter_shape(parse_query(base + "s=IBM&a=0&b=1&c=2000")) == "other"
    assert parameter_shape(parse_query(base + "s=IBM&a=0&b=&c=&d=&e=&f=&g=d")) == "other"
    assert parameter_shape(parse_query(base + "s=IBM&x=1")) == "other"
    assert parameter_shape(parse_query(base + "ignore=.csv")) == "other"
    assert parameter_shape(parse_query(base + "s=IBM&a=0&b=1&c=2000&d=0&e=1&f=2001&g=")) == (
        "other"
    )


def test_malformed_urls_never_raise() -> None:
    for original in ("", "not a url", "http://[::1/table.csv?s=x", "http://h/t?%%%=&&=="):
        pairs = parse_query(original)
        assert parameter_shape(pairs) in {"s_only", "empty_range", "full_range", "other"}
        assert isinstance(interval(pairs), str)


# --- select and backfill_order (Req 4.2 to 4.6) ----------------------------------------------


def _range_url(g: str, year: int) -> str:
    return f"http://ichart.yahoo.com:80/table.csv?s=IBM&a=0&b=1&c={year}&d=0&e=1&f=2010&g={g}"


def _known_group(g: str, count: int, tag: str) -> list[CdxRow]:
    return [_row(f"2010010100000{i}", _range_url(g, 2000 + i), f"{tag}{i}") for i in range(count)]


def test_floor_indices_on_a_known_group() -> None:
    rows = _known_group("d", 10, "D")
    assert select(rows, 3) == [rows[0], rows[3], rows[6]]
    assert select(rows, 10) == rows
    assert select(rows, 50) == rows


def test_round_robin_allocation_and_full_groups() -> None:
    big = _known_group("d", 5, "D")
    small = _known_group("w", 1, "W")
    # Group d gets 3 picks (indices 0, 1, 3), group w is full after 1.
    assert select(small + big, 4) == [big[0], big[1], big[3], small[0]]


def test_every_group_gets_one_pick_when_n_covers_groups() -> None:
    rows = [
        _row("20100101000000", F1_GOOG, "A"),
        _row("20100101000001", F1_HK, "B"),
        _row("20100101000002", F15_DISH, "C"),
        _row("20100101000003", F15_VIX, "D"),
        _row("20100101000004", F17_JUNK, "E"),
        _row("20100101000005", F1_HK.replace("s=0298.HK", "s=0005.HK"), "F"),
    ]
    groups = {_group(row) for row in rows}
    # (w, full_range), (d, full_range), (none, s_only), (d, other): VIX and F17 junk share one.
    assert len(groups) == 4
    picked = select(rows, len(groups))
    assert {_group(row) for row in picked} == groups


def test_dedup_keeps_earliest_timestamp() -> None:
    late = _row("20150101000000", F1_GOOG, "SAME")
    early = _row("20100101000000", F1_GOOG, "SAME")
    assert select([late, early], 5) == [early]


def test_backfill_order_on_a_known_set() -> None:
    d = _known_group("d", 5, "D")
    w = _known_group("w", 3, "W")
    selected = select(w + d, 2)
    assert selected == [d[0], w[0]]
    assert backfill_order(w + d, selected) == [d[1], w[1], d[2], w[2], d[3], d[4]]


def test_select_with_no_candidates() -> None:
    assert select([], 5) == []
    assert backfill_order([], []) == []


# --- Property 3 -------------------------------------------------------------------------------

_HOST = "http://ichart.yahoo.com:80/table.csv?"
_SYMBOLS = ["GOOG", "0298.HK", "0005.HK", "^DJI", "%5EDJI", "%5EAEX", "DISH"]
_INTERVALS = ["d", "w", "m", "v", ""]


@st.composite
def _originals(draw: st.DrawFn) -> str:
    sep = draw(st.sampled_from(["&", "&amp;"]))
    symbol = draw(st.sampled_from(_SYMBOLS))
    kind = draw(st.sampled_from(["s_only", "s_amp", "empty", "full", "partial", "junk"]))
    g = draw(st.sampled_from(_INTERVALS))
    if kind == "s_only":
        pairs = [f"s={symbol}", "ignore=.csv"]
    elif kind == "s_amp":
        return f"{_HOST}s={symbol}&amp"
    elif kind == "empty":
        pairs = [f"s={symbol}"] + [f"{name}=" for name in "abcdefg"]
    else:
        values = {
            "a": "0",
            "b": "1",
            "c": str(draw(st.integers(1990, 2017))),
            "d": "0",
            "e": "31",
            "f": "2010",
            "g": g,
        }
        if kind == "junk":
            values[draw(st.sampled_from("abcdef"))] = "{{(-1 month).year}}"
        names = list("abcdefg")
        if kind == "partial":
            names = names[: draw(st.integers(0, 6))]
        names = draw(st.permutations(names))
        pairs = [f"s={symbol}"] + [f"{name}={values[name]}" for name in names] + ["ignore=.csv"]
    return _HOST + sep.join(pairs)


_rows = st.builds(
    _row,
    timestamp=st.integers(2004_01_01_000000, 2017_12_31_235959).map(str)
    | st.sampled_from(["20131213174436", "20090103230517"]),
    original=_originals(),
    digest=st.text("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567", min_size=1, max_size=3),
)


@st.composite
def _candidate_sets(draw: st.DrawFn) -> tuple[list[CdxRow], list[CdxRow], int]:
    rows = draw(st.lists(_rows, max_size=40))
    return rows, draw(st.permutations(rows)), draw(st.integers(1, 50))


# Feature: exhume, Property 3: Selection determinism
@settings(max_examples=100)
@given(_candidate_sets())
def test_property_3_selection_determinism(case: tuple[list[CdxRow], list[CdxRow], int]) -> None:
    """**Validates: Requirements 4.3, 4.4, 4.5**"""
    rows, shuffled, n = case
    picked = select(rows, n)
    assert select(shuffled, n) == picked
    assert len(picked) <= n
    digests = [row.digest for row in picked]
    assert len(digests) == len(set(digests))
    # Dedup survivors (earliest per digest) define the Groups.
    survivors: dict[str, CdxRow] = {}
    for row in rows:
        kept = survivors.get(row.digest)
        if kept is None or (row.timestamp, row.original) < (kept.timestamp, kept.original):
            survivors[row.digest] = row
    assert set(picked) <= set(survivors.values())
    groups = {_group(row) for row in survivors.values()}
    if n >= len(groups):
        assert {_group(row) for row in picked} == groups
