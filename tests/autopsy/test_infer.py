"""Example tests for the Contract_Inferrer (Req 1.4, 2.2 to 2.5, 3.2, 4 to 6)."""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from pathlib import Path

import pytest

from revenant.autopsy.contract import (
    Contract,
    Default,
    EnumType,
    IntType,
    NameCount,
    Parameter,
    StringType,
)
from revenant.autopsy.evidence import Capture, load_evidence
from revenant.autopsy.infer import infer
from revenant.exhume.models import IndexEntry, Kind

SLUG = "yahoo-finance-ichart"
REPO_EVIDENCE = Path(__file__).resolve().parents[2] / "evidence"
HOST = "ichart.yahoo.com"
BODY = b"Date,Close\n2016-01-05,1.5\n2016-01-04,1.4\n"


def _capture(
    number: int,
    query: str,
    content_type: str | None = "text/csv",
    body: bytes = BODY,
    year: int = 2016,
    kind: Kind = "data",
    status: str = "200",
    mimetype: str = "text/csv",
) -> Capture:
    stamp = f"{year}0110{number:06d}"  # Capture_Date: <year>-01-10
    digest = f"D{number}"
    entry = IndexEntry(
        host=HOST,
        kind=kind,
        requested_timestamp=stamp,
        served_timestamp=stamp,
        original=f"http://{HOST}/table.csv?{query}",
        mimetype=mimetype,
        statuscode=status,
        digest=digest,
        length=str(len(body)),
        final_url=f"https://web.archive.org/web/{stamp}id_/http://{HOST}/table.csv?{query}",
        path=f"{HOST}/{stamp}-{digest}.csv",
        size=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        content_type=content_type,
        digest_verified=True,
        fetched_at="2026-11-15T00:00:00Z",
    )
    return Capture(key=f"{HOST}/{stamp}-{digest}", entry=entry, body=body)


def _param(contract: Contract, name: str) -> Parameter:
    return next(p for p in contract.parameters if p.name == name)


QUERIES = [
    "s=AAPL&a=0&b=4&c=2016&d=0&e=5&f=2016&g=d&ignore=.csv",
    "s=IBM&a=11&b=1&c=2015&d=0&e=5&f=2016&g=w&ignore=.csv&x=1",
    "s=%5EDJI&a={{x}}&b=1&c=2016&d=0&e=5&f=2016&g=d&amp;ignore=.csv",
    "s=MSFT&a=&b=&c=&d=&e=&f=&g=&ignore=.csv",
    "s=GOOG&a=02&b=10&c=2003&f=f6j1&ignore=.csv",
] + [f"s=S{n:02d}&g=d" for n in range(10)]


def _contract() -> Contract:
    captures = [_capture(n, query) for n, query in enumerate(QUERIES)]
    return infer(SLUG, b"{}", captures)


def test_parameter_types() -> None:
    contract = _contract()
    a = _param(contract, "a")
    assert a.type == IntType(min=0, max=11)
    assert (a.present.count, a.empty, a.junk, a.required) == (5, 1, 1, False)
    f = _param(contract, "f")
    assert f.type == IntType(min=2016, max=2016)
    assert f.junk == 1  # `f6j1` is Template_Junk for a documented range parameter
    g = _param(contract, "g")
    assert isinstance(g.type, EnumType)
    assert [(v.value, v.count) for v in g.type.values] == [("d", 12), ("w", 1)]
    assert g.examples == ["d", "w"]
    s = _param(contract, "s")
    assert s.type == StringType(distinct=len(QUERIES))
    assert s.required and s.documented
    assert len(s.examples) == 5
    assert [p.name for p in contract.parameters] == sorted(p.name for p in contract.parameters)


def test_amp_counted_and_excluded() -> None:
    # The fixpoint turns every `&amp` into `&`, so only a percent-encoded name survives as `amp`.
    contract = infer(SLUG, b"{}", [_capture(0, "s=DISH&%61mp=1"), _capture(1, "s=IBM&amp;g=d")])
    assert contract.amp.count == 1
    assert "amp" not in [p.name for p in contract.parameters]


def test_undocumented_parameter_is_optional() -> None:
    x = _param(_contract(), "x")
    assert not x.documented and not x.required
    assert x.present.count == 1
    assert x.type == IntType(min=1, max=1)


def test_content_type_reduced_to_media_type() -> None:
    captures = [
        _capture(0, "s=A", "text/csv; charset=UTF-8"),
        _capture(1, "s=B", "Text/CSV"),
        _capture(2, "s=C", None),
    ]
    contract = infer(SLUG, b"{}", captures)
    assert [(c.name, c.evidence.count) for c in contract.content_types] == [("text/csv", 3)]


def test_committed_evidence_is_0_indexed() -> None:
    index_bytes, captures = load_evidence(REPO_EVIDENCE, SLUG)
    contract = infer(SLUG, index_bytes, captures)
    assert contract.months.indexing == "0-indexed"
    assert contract.months.decisive_h1.count == 0
    assert contract.months.decisive_h0.count >= 3
    hosts = [host.host for endpoint in contract.endpoints for host in endpoint.hosts]
    assert "ichart.yahoo.com" in hosts
    assert contract.source.entry_count == len(captures)


def test_committed_evidence_d_accepts_month_12() -> None:
    """F21: Yahoo accepted `d=12`, so the observed maximum of `d` is 12; `a` to `f` stay `int`."""
    index_bytes, captures = load_evidence(REPO_EVIDENCE, SLUG)
    contract = infer(SLUG, index_bytes, captures)
    d = _param(contract, "d")
    assert isinstance(d.type, IntType)
    assert d.type.max == 12
    for name in "abcdef":
        assert isinstance(_param(contract, name).type, IntType), name


OLD_HEADER = "Date,Open,High,Low,Close,Volume,Adj. Close*"
NEW_HEADER = "Date,Open,High,Low,Close,Volume,Adj Close"
F16_COMMENT = "<!-- ichart9.finance.scd.yahoo.com uncompressed Mon Nov 29 12:42:31 PST 2004 -->"
OLD_BODY = (
    f"{OLD_HEADER}\n29-Nov-04,25.00,25.50,24.90,25.10,1000,25.10\n"
    f"26-Nov-04,24.80,25.10,24.70,25.00,900,25.00\n{F16_COMMENT}\n"
).encode()
NEW_BODY = (
    f"{NEW_HEADER}\n2016-01-08,98.55,100.50,96.43,96.96,70798000,94.1213\n"
    "2016-01-07,98.68,100.13,96.43,96.45,81094400,93.62\n"
).encode()
HEADER_ONLY = f"{NEW_HEADER}\n".encode()
DIVIDENDS = b"Date,Dividends\n2015-11-05,0.52\n2015-08-06,0.52\n"


def _variant_contract() -> Contract:
    full = "s=AAPL&a=0&b=4&c=2016&d=0&e=8&f=2016&g="
    captures = [
        _capture(0, full + "d", body=OLD_BODY, year=2004),
        _capture(1, full + "d", body=OLD_BODY, year=2005),
        _capture(2, full + "d", body=NEW_BODY, year=2016),
        _capture(3, full + "d", body=HEADER_ONLY, year=2016),
        _capture(4, full + "v", body=DIVIDENDS, year=2016),
        _capture(5, "s=AAPL", body=b"Date,Close\nnot-a-date,1\n2016-01-04,2\n", year=2016),
    ]
    return infer(SLUG, b"{}", captures)


def test_g_v_maps_to_dividends() -> None:
    contract = _variant_contract()
    by_interval = {group.interval: group.variants for group in contract.intervals}
    assert [group.interval for group in contract.intervals] == ["d", "none", "v"]
    [dividends] = by_interval["v"]
    assert dividends.columns == ["Date", "Dividends"]
    assert [v.header for v in by_interval["d"]] == sorted([OLD_HEADER, NEW_HEADER])


def test_adj_close_variants_with_year_ranges() -> None:
    """F12: `Adj. Close*` and `Adj Close` are separate Header_Variants."""
    headers = {v.header: v for v in _variant_contract().headers}
    old, new = headers[OLD_HEADER], headers[NEW_HEADER]
    assert (old.first_year, old.last_year, old.evidence.count) == (2004, 2005, 2)
    # The Header_Only_Body counts towards its Header_Variant.
    assert (new.first_year, new.last_year, new.evidence.count) == (2016, 2016, 2)
    assert new.columns[-1] == "Adj Close"


def test_header_only_counted_but_not_in_row_order() -> None:
    contract = _variant_contract()
    assert contract.header_only.count == 1
    order = contract.row_order
    # 2 OLD_BODY + NEW_BODY + DIVIDENDS are descending; header-only and unparsed are excluded.
    assert (order.descending.count, order.ascending.count, order.unordered.count) == (4, 0, 0)
    assert order.unparsed_dates.count == 1


def test_f16_comment_after_last_row_with_example() -> None:
    comments = _variant_contract().comments
    assert (comments.total, comments.after_last_row, comments.before_last_row) == (2, 2, 0)
    assert comments.years == [2004, 2005]
    assert comments.example == F16_COMMENT
    assert comments.evidence.count == 2


def test_date_formats_and_precision() -> None:
    contract = _variant_contract()
    formats = {
        f.format: (f.first_year, f.last_year, f.evidence.count) for f in contract.date_formats
    }
    assert formats == {"%Y-%m-%d": (2016, 2016, 3), "%d-%b-%y": (2004, 2005, 2)}
    precision = {(p.interval, p.header, p.year): p.values for p in contract.precision}
    # Count 1: the Header_Only_Body of the same group adds no precision value.
    assert [(v.digits, v.count) for v in precision[("d", NEW_HEADER, 2016)]] == [(4, 1)]
    assert [(v.digits, v.count) for v in precision[("d", OLD_HEADER, 2004)]] == [(2, 1)]
    keys = [(p.interval, p.header, p.year) for p in contract.precision]
    assert keys == sorted(keys)


def test_committed_evidence_header_variants() -> None:
    index_bytes, captures = load_evidence(REPO_EVIDENCE, SLUG)
    contract = infer(SLUG, index_bytes, captures)
    headers = {v.header for v in contract.headers}
    assert any("Adj. Close*" in h for h in headers)
    assert any(h.endswith("Adj Close") for h in headers)


EMPTY_RANGE = "s=AAPL&a=&b=&c=&d=&e=&f=&g=&ignore=.csv"


def _dated(*days: date) -> bytes:
    return ("Date,Close\n" + "".join(f"{day.isoformat()},1.5\n" for day in days)).encode()


def _series(newest: date, gaps: list[int]) -> bytes:
    days = [newest]
    for gap in gaps:
        days.append(days[-1] - timedelta(days=gap))
    return _dated(*days)


def _default(contract: Contract, shape: str) -> Default:
    return next(d for d in contract.defaults if d.shape == shape)


@pytest.mark.parametrize(
    ("gaps", "spacing"),
    [
        ([1, 1, 3], "d"),
        ([7, 7, 5], "w"),
        ([31, 29, 30], "m"),
        ([4, 5], "unknown"),  # median 4.5 falls in no band
        ([], "unknown"),  # one row: no gap at all
        ([15, 15], "unknown"),
    ],
)
def test_default_spacing(gaps: list[int], spacing: str) -> None:
    body = _series(date(2016, 1, 5), gaps)
    contract = infer(SLUG, b"{}", [_capture(0, "s=AAPL", body=body)])
    assert _default(contract, "s_only").spacing == spacing


def test_default_spacing_pools_gaps_across_captures() -> None:
    # Gaps [1] and [7, 7]: pooled median is 7, so weekly, though one capture alone is daily.
    captures = [
        _capture(0, "s=AAPL", body=_series(date(2016, 1, 5), [1])),
        _capture(1, "s=IBM", body=_series(date(2016, 1, 5), [7, 7])),
    ]
    assert _default(infer(SLUG, b"{}", captures), "s_only").spacing == "w"


def test_default_ranges_and_recent_within_7d() -> None:
    # Capture_Date is 2016-01-10: newest 2016-01-03 is 7 days old, 2016-01-02 is 8.
    captures = [
        _capture(0, "s=AAPL", body=_dated(date(2016, 1, 3), date(2016, 1, 1))),
        _capture(1, "s=IBM", body=_dated(date(2016, 1, 2), date(2015, 12, 31))),
        _capture(2, EMPTY_RANGE, body=_dated(date(2016, 1, 10), date(2016, 1, 9))),
        _capture(3, "s=MSFT", body=b"Date,Close\n"),  # Header_Only_Body: excluded
        _capture(4, "s=GOOG", body=b"Date,Close\nn/a,1\n"),  # unparsed_dates: excluded
    ]
    contract = infer(SLUG, b"{}", captures)
    assert [d.shape for d in contract.defaults] == ["empty_range", "s_only"]
    s_only = _default(contract, "s_only")
    assert s_only.evidence.count == 2
    assert (s_only.earliest, s_only.latest) == ("2015-12-31", "2016-01-03")
    assert s_only.recent_within_7d == 1
    empty = _default(contract, "empty_range")
    assert (empty.evidence.count, empty.recent_within_7d) == (1, 1)


def test_default_without_captures_is_zero_and_null() -> None:
    contract = infer(SLUG, b"{}", [_capture(0, "s=AAPL")])
    empty = _default(contract, "empty_range")
    assert (empty.evidence.count, empty.earliest, empty.latest) == (0, None, None)
    assert (empty.recent_within_7d, empty.spacing) == (0, "unknown")


def test_errors_per_status_with_counts() -> None:
    def error(number: int, query: str, status: str, content_type: str | None) -> Capture:
        return _capture(
            number,
            query,
            content_type,
            b"<html/>",
            kind="error",
            status=status,
            mimetype="text/html",
        )

    captures = [
        _capture(0, "s=AAPL"),
        error(1, "s=NOPE", "404", "text/html; charset=utf-8"),
        error(2, EMPTY_RANGE, "404", None),
        error(3, "s=X&a=0&b=1&c=2016&d=0&e=5&f=2016&g=d", "404", "Text/Plain"),
        error(4, "s=", "400", "text/html"),
        _capture(5, "s=Z", "text/html", b"<html/>", kind="error_page", mimetype="text/html"),
    ]
    contract = infer(SLUG, b"{}", captures)
    assert contract.errors is not None
    assert [e.status for e in contract.errors] == ["400", "404"]
    bad, missing = contract.errors
    assert bad.evidence.count == 1
    assert missing.evidence.count == 3
    assert missing.media_types == [
        NameCount(name="text/html", count=2),
        NameCount(name="text/plain", count=1),
    ]
    assert missing.shapes == [
        NameCount(name="empty_range", count=1),
        NameCount(name="full_range", count=1),
        NameCount(name="s_only", count=1),
    ]
    # Error and error_page captures never feed data facts.
    assert [c.name for c in contract.content_types] == ["text/csv"]
    assert _param(contract, "s").present.count == 1


def test_errors_null_without_error_captures() -> None:
    captures = [
        _capture(0, "s=AAPL"),
        _capture(1, "s=Z", "text/html", b"<html/>", kind="error_page", mimetype="text/html"),
    ]
    contract = infer(SLUG, b"{}", captures)
    assert contract.errors is None
    assert contract.source.entry_count == 2
