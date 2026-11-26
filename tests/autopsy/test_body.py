"""Body_Parser tests (Req 4.2, 4.3, 5.2, 5.3, F12, F16)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from revenant.autopsy.body import (
    ISO_FORMAT,
    SHORT_FORMAT,
    NumberSupport,
    fixed,
    number_support,
    parse_body,
    parse_row_date,
    row_order,
    yahoo_number,
)
from revenant.autopsy.evidence import AutopsyError

MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _render(day: date, short: bool) -> str:
    if short:
        return f"{day.day}-{MONTH_NAMES[day.month - 1]}-{day.year % 100:02d}"
    return day.isoformat()


@st.composite
def descending_rows(draw: st.DrawFn) -> tuple[int, list[date], list[str]]:
    """Strictly descending dates within the 100 years up to the Capture_Year.

    Small gaps make month and year boundaries frequent, where string order fails.
    """
    capture_year = draw(st.integers(min_value=1950, max_value=2030))
    lowest = date(capture_year - 99, 1, 1)
    newest = draw(st.dates(min_value=lowest, max_value=date(capture_year, 12, 31)))
    gaps = draw(st.lists(st.integers(min_value=1, max_value=400), min_size=1, max_size=20))
    dates = [newest]
    for gap in gaps:
        older = dates[-1] - timedelta(days=gap)
        if older < lowest:
            break
        dates.append(older)
    if len(dates) < 2:
        dates = [lowest + timedelta(days=1), lowest]
    rendered = [_render(day, draw(st.booleans())) for day in dates]
    return capture_year, dates, rendered


# Feature: autopsy, Property 4: Parsed row order
@settings(max_examples=100)
@given(case=descending_rows())
def test_parsed_descending_rows_are_descending(case: tuple[int, list[date], list[str]]) -> None:
    """**Validates: Requirements 5.2**"""
    capture_year, dates, rendered = case
    parsed = [parse_row_date(field, capture_year) for field in rendered]
    assert all(item is not None for item in parsed)
    parsed_dates = [item[0] for item in parsed if item is not None]
    assert parsed_dates == dates
    assert row_order(parsed_dates) == "descending"


def test_f16_comment_after_last_row() -> None:
    body = (
        b"Date,Open,High,Low,Close,Volume,Adj. Close*\n"
        b"29-Nov-04,25.00,25.50,24.90,25.10,1000,25.10\n"
        b"26-Nov-04,24.80,25.10,24.70,25.00,900,25.00\n"
        b"<!-- ichart9.finance.scd.yahoo.com uncompressed Mon Nov 29 12:42:31 PST 2004 -->\n"
    )
    parsed = parse_body(body, "evidence/x/a.csv")
    assert parsed.header == "Date,Open,High,Low,Close,Volume,Adj. Close*"
    assert len(parsed.rows) == 2
    assert parsed.comments == (
        "<!-- ichart9.finance.scd.yahoo.com uncompressed Mon Nov 29 12:42:31 PST 2004 -->",
    )
    assert (parsed.comments_after_last_row, parsed.comments_before_last_row) == (1, 0)


def test_comment_before_last_row() -> None:
    parsed = parse_body(b"Date,Close\n<!-- x -->\n2016-01-08,1\n", "a.csv")
    assert (parsed.comments_after_last_row, parsed.comments_before_last_row) == (0, 1)


def test_header_only_body() -> None:
    parsed = parse_body(b"Date,Open,High,Low,Close,Volume,Adj Close\n", "a.csv")
    assert parsed.header == "Date,Open,High,Low,Close,Volume,Adj Close"
    assert parsed.rows == ()
    assert parsed.comments == ()


def test_non_utf8_body_names_the_file() -> None:
    with pytest.raises(AutopsyError) as info:
        parse_body(b"Date,Close\n\xff\xfe\n", "evidence\\slug\\host\\bad.csv")
    assert str(info.value).startswith("evidence/slug/host/bad.csv: ")


def test_iso_date() -> None:
    assert parse_row_date("2016-01-08", 2016) == (date(2016, 1, 8), ISO_FORMAT)


def test_short_date_two_digit_year_across_century() -> None:
    assert parse_row_date("29-Nov-04", 2004) == (date(2004, 11, 29), SHORT_FORMAT)
    assert parse_row_date("31-Dec-99", 2004) == (date(1999, 12, 31), SHORT_FORMAT)
    assert parse_row_date("3-Jan-00", 2000) == (date(2000, 1, 3), SHORT_FORMAT)


@pytest.mark.parametrize("field", ["Date", "", "2016-13-01", "30-Feb-04", "1-Foo-04", "1/2/04"])
def test_unparseable_row_date_is_none(field: str) -> None:
    assert parse_row_date(field, 2004) is None


@st.composite
def yahoo_strings(draw: st.DrawFn) -> str:
    """Strings built by the F23 rule: 2 to 6 decimals, no trailing zero beyond the second."""
    whole = str(draw(st.integers(min_value=0, max_value=10**7)))
    width = draw(st.integers(min_value=2, max_value=6))
    digits = draw(st.text(alphabet="0123456789", min_size=width, max_size=width))
    if width > 2 and digits.endswith("0"):
        digits = digits[:-1] + draw(st.sampled_from("123456789"))
    return f"{whole}.{digits}"


@settings(max_examples=100)
@given(text=yahoo_strings())
def test_yahoo_number_reproduces_f23_strings(text: str) -> None:
    """F23: every Yahoo_Number string round-trips through `yahoo_number(Decimal(s))`."""
    assert yahoo_number(Decimal(text)) == text


def test_yahoo_number_and_fixed_examples() -> None:
    examples = ["60.860001", "61.18", "52.00", "2105.22998", "0.00001"]
    assert [yahoo_number(Decimal(s)) for s in examples] == examples
    assert yahoo_number(Decimal(52)) == "52.00"
    assert yahoo_number(Decimal("100.500000")) == "100.50"
    assert fixed(Decimal("96.4"), 2) == "96.40"
    assert fixed(Decimal(97), 0) == "97"


def test_number_support_counts_values_outside_date_and_volume() -> None:
    header = "Date,Open,High,Low,Close,Volume,Adj Close"
    rows = [
        "2016-01-08,98.55,100.50,96.43,96.96,70798000,94.1213",
        "2016-01-07,98.68,100.13,96.43,null,000,93.620003",
    ]
    support = number_support(header, rows)
    counts = dict(support.hypotheses)
    assert [name for name, _ in support.hypotheses] == sorted(counts)
    assert support.total == 10  # `null` counts in total and is supported by no hypothesis
    assert counts["yahoo"] == 9
    assert counts["fixed2"] == 7  # 94.1213, null and 93.620003 do not fit
    assert counts["fixed4"] == 1 and counts["fixed6"] == 1 and counts["fixed0"] == 0
    assert number_support(header, []) == NumberSupport(
        hypotheses=tuple((name, 0) for name in counts),
        total=0,
        volume_zero_000=0,
        volume_zero_other=0,
    )


def test_number_support_zero_volume_spellings() -> None:
    """F24: a zero Volume is written `000`; `0` is counted as another spelling."""
    header = "Date,Close,Volume"
    rows = ["2016-01-08,1.00,000", "2016-01-07,1.00,0", "2016-01-06,1.00,000", "2016-01-05,1.00,5"]
    support = number_support(header, rows)
    assert (support.volume_zero_000, support.volume_zero_other) == (2, 1)
    assert support.total == 4
    assert number_support("Date,Dividends", ["2015-11-05,0.52"]).volume_zero_000 == 0


def test_row_order_classes() -> None:
    d1, d2, d3 = date(2016, 1, 6), date(2016, 1, 7), date(2016, 1, 8)
    assert row_order([d3, d2, d1]) == "descending"
    assert row_order([d1, d2, d3]) == "ascending"
    assert row_order([d1, d3, d2]) == "unordered"
    assert row_order([d1, d1]) == "unordered"
    with pytest.raises(ValueError):
        row_order([d1])
