"""Body_Parser tests (Req 4.2, 4.3, 5.2, 5.3, F12, F16)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from revenant.autopsy.body import (
    ISO_FORMAT,
    SHORT_FORMAT,
    body_precision,
    parse_body,
    parse_row_date,
    row_order,
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


def test_body_precision_skips_date_and_volume() -> None:
    header = "Date,Open,High,Low,Close,Volume,Adj Close"
    rows = [
        "2016-01-08,98.55,100.50,96.43,96.96,70798000,94.1213",
        "2016-01-07,98.68,100.13,96.43,96.45,81094400.12345,93.62",
    ]
    # Volume's 5 digits are skipped; Adj Close's 4 digits win.
    assert body_precision(header, rows) == 4
    assert body_precision("Date,Dividends", ["2015-11-05,0.52"]) == 2
    assert body_precision("Date,Close,Volume", ["2016-01-08,97,100"]) == 0
    assert body_precision(header, []) == 0


def test_row_order_classes() -> None:
    d1, d2, d3 = date(2016, 1, 6), date(2016, 1, 7), date(2016, 1, 8)
    assert row_order([d3, d2, d1]) == "descending"
    assert row_order([d1, d2, d3]) == "ascending"
    assert row_order([d1, d3, d2]) == "unordered"
    assert row_order([d1, d1]) == "unordered"
    with pytest.raises(ValueError):
        row_order([d1])
