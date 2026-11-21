"""Month_Detector tests (Req 3.1 to 3.4)."""

from __future__ import annotations

from datetime import date, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from revenant.autopsy.body import parse_body, parse_row_date
from revenant.autopsy.months import MonthSample, detect, fits
from revenant.autopsy.normalize import normalize_query

HEADER = "Date,Open,High,Low,Close,Volume,Adj Close"
MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
CAPTURE_YEAR = 2017
LOW = date(1995, 1, 1)
HIGH = date(2016, 12, 31)


def _render(day: date, short: bool) -> str:
    if short:
        return f"{day.day}-{MONTH_NAMES[day.month - 1]}-{day.year % 100:02d}"
    return day.isoformat()


def _body(rows: list[date], short: bool) -> bytes:
    lines = [HEADER] + [f"{_render(day, short)},1.00,1.10,0.90,1.05,100,1.05" for day in rows]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _sample(key: str, params: dict[str, str], body: bytes) -> MonthSample:
    """Build a MonthSample the way Autopsy does: from the URL and the parsed body."""
    query = "&".join(f"{name}={value}" for name, value in params.items())
    pairs = normalize_query(f"http://ichart.yahoo.com/table.csv?s=IBM&{query}&g=d&ignore=.csv")
    first: dict[str, str] = {}
    for name, value in pairs:
        first.setdefault(name, value)
    parsed = parse_body(body, key)
    dates = []
    for row in parsed.rows:
        result = parse_row_date(row.split(",")[0], CAPTURE_YEAR)
        assert result is not None
        dates.append(result[0])
    return MonthSample(key=key, params=first, oldest=min(dates), newest=max(dates))


def _encode(start: date, end: date, h: int) -> dict[str, str]:
    """Requested `a` to `f` for [start, end] under month convention `h`."""
    return {
        "a": str(start.month - 1 + h),
        "b": str(start.day),
        "c": str(start.year),
        "d": str(end.month - 1 + h),
        "e": str(end.day),
        "f": str(end.year),
    }


@st.composite
def decisive_body(draw: st.DrawFn, h: int) -> tuple[dict[str, str], bytes]:
    """Rows on the exact start and end dates: the other offset shifts the range a month."""
    start = draw(st.dates(min_value=LOW, max_value=HIGH - timedelta(days=1)))
    end = draw(st.dates(min_value=start + timedelta(days=1), max_value=HIGH))
    middle = draw(st.lists(st.dates(min_value=start, max_value=end), max_size=5))
    rows = sorted({start, end, *middle}, reverse=True)
    return _encode(start, end, h), _body(rows, draw(st.booleans()))


@st.composite
def ambiguous_body(draw: st.DrawFn) -> tuple[dict[str, str], bytes]:
    """Rows inside both readings: [date(c, a+1, b), date(f, d, e)] with `a`, `d` in 1..11."""
    a, d = draw(st.integers(1, 11)), draw(st.integers(1, 11))
    b, e = draw(st.integers(1, 28)), draw(st.integers(1, 28))
    c = draw(st.integers(1995, 2010))
    f = draw(st.integers(c + 1, 2016))
    low, high = date(c, a + 1, b), date(f, d, e)
    rows = sorted(set(draw(st.lists(st.dates(low, high), min_size=1, max_size=5))), reverse=True)
    params = {"a": str(a), "b": str(b), "c": str(c), "d": str(d), "e": str(e), "f": str(f)}
    return params, _body(rows, draw(st.booleans()))


@st.composite
def unfit_body(draw: st.DrawFn) -> tuple[dict[str, str], bytes]:
    """A non-integer `a`, or rows after the end of both readings."""
    a, d = draw(st.integers(1, 11)), draw(st.integers(1, 11))
    b, e = draw(st.integers(1, 28)), draw(st.integers(1, 28))
    c = draw(st.integers(1995, 2005))
    f = draw(st.integers(c, 2010))
    params = {"a": str(a), "b": str(b), "c": str(c), "d": str(d), "e": str(e), "f": str(f)}
    if draw(st.booleans()):
        params["a"] = draw(st.sampled_from(["", "x", "1.5", "-1", "{{a}}"]))
        rows = [date(f, 1, 1)]
    else:
        after = date(f, d + 1, e) + timedelta(days=1)
        rows = sorted(set(draw(st.lists(st.dates(after, HIGH), min_size=1, max_size=3))))
    return params, _body(rows, draw(st.booleans()))


@st.composite
def month_case(draw: st.DrawFn) -> tuple[int, list[MonthSample], MonthSample]:
    h = draw(st.sampled_from([0, 1]))
    bodies = draw(st.lists(decisive_body(h), min_size=3, max_size=6))
    bodies += draw(st.lists(st.one_of(ambiguous_body(), unfit_body()), max_size=4))
    order = draw(st.permutations(range(len(bodies))))
    samples = [_sample(f"k{i:03d}", *bodies[i]) for i in order]
    other = _sample("z999", *draw(decisive_body(1 - h)))
    return h, samples, other


# Feature: autopsy, Property 1: Month recovery
@settings(max_examples=100)
@given(case=month_case())
def test_month_recovery(case: tuple[int, list[MonthSample], MonthSample]) -> None:
    """**Validates: Requirements 3.1, 3.2, 3.3, 3.4**"""
    h, samples, other = case
    result = detect(samples)
    assert result.indexing == ("0-indexed" if h == 0 else "1-indexed")
    total = (
        result.decisive_h0.count
        + result.decisive_h1.count
        + result.ambiguous.count
        + result.unfit.count
    )
    assert total == len(samples)
    assert (result.decisive_h1 if h == 0 else result.decisive_h0).count == 0
    assert detect([*samples, other]).indexing == "undetermined"


def _plain(key: str, a: str, b: str = "4", d: str = "0", e: str = "8") -> MonthSample:
    params = {"a": a, "b": b, "c": "2016", "d": d, "e": e, "f": "2016"}
    return MonthSample(key=key, params=params, oldest=date(2016, 1, 4), newest=date(2016, 1, 8))


def test_non_integer_and_empty_a_are_unfit() -> None:
    for value in ["", "x", "0.0", "+0", " 0"]:
        sample = _plain("k", value)
        assert not fits(sample, 0)
        assert not fits(sample, 1)
    missing = MonthSample("k", {"b": "4", "c": "2016"}, date(2016, 1, 4), date(2016, 1, 8))
    assert detect([missing]).unfit.count == 1


def test_day_31_with_invalid_month_is_unfit_for_that_h() -> None:
    # a=1, b=31: H=0 reads Feb 31 (invalid), H=1 reads Jan 31.
    sample = MonthSample(
        "k",
        {"a": "1", "b": "31", "c": "2016", "d": "2", "e": "29", "f": "2016"},
        date(2016, 1, 31),
        date(2016, 1, 31),
    )
    assert not fits(sample, 0)
    assert fits(sample, 1)


def test_month_12_is_invalid_under_h0() -> None:
    assert not fits(_plain("k", "0", d="12"), 0)


def test_two_decisive_is_undetermined() -> None:
    result = detect([_plain("k1", "0"), _plain("k2", "0")])
    assert result.indexing == "undetermined"
    assert result.decisive_h0.count == 2


def test_counts_and_keys() -> None:
    decisive = [_plain(f"k{i}", "0") for i in (5, 1, 4, 2, 3)]
    ambiguous = MonthSample(
        "amb",
        {"a": "1", "b": "1", "c": "2015", "d": "1", "e": "28", "f": "2016"},
        date(2016, 1, 4),
        date(2016, 1, 8),
    )
    result = detect([*decisive, ambiguous, _plain("bad", "x")])
    assert result.indexing == "0-indexed"
    assert (result.decisive_h0.count, result.decisive_h0.keys) == (5, ("k1", "k2", "k3"))
    assert (result.decisive_h1.count, result.decisive_h1.keys) == (0, ())
    assert (result.ambiguous.count, result.ambiguous.keys) == (1, ("amb",))
    assert (result.unfit.count, result.unfit.keys) == (1, ("bad",))
