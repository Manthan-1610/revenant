"""Example and property tests for the Donor_Fetcher (Req 2.2 to 2.6)."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from revenant.exhume.archive import (
    ArchiveClient,
    ArchiveError,
    RateLimiter,
    make_client,
    user_agent,
)
from revenant.exhume.models import CdxRow, Listing, Tombstone
from revenant.exhume.run import wayback_url
from revenant.exhume.store import EvidenceStore
from revenant.reanimate.donor import (
    MAX_TRIES,
    accept,
    candidates,
    donor_file_name,
    fetch_donors,
    index_path,
    load_donor_index,
)

HOST = "http://ichart.finance.yahoo.com/table.csv"
HEADER = b"Date,Open,High,Low,Close,Volume,Adj Close"


def _row(query: str, timestamp: str = "20160110000000", digest: str = "D1", **kw: str) -> CdxRow:
    fields = {"mimetype": "text/csv", "statuscode": "200", "length": "100"} | kw
    return CdxRow(timestamp=timestamp, original=f"{HOST}?{query}", digest=digest, **fields)


def test_candidates_filters_orders_and_dedups() -> None:
    keep_old = _row("s=AAPL", timestamp="20150101000000", digest="A")
    keep_new = _row("s=AAPL&a=0&b=1&c=1980&d=&e=&f=&g=d&ignore=.csv", digest="B")
    keep_tie = _row("s=AAPL&amp;g=d&amp;c=1990", digest="C")  # F15 artifacts decoded
    dup = _row("s=AAPL", timestamp="20140101000000", digest="A")
    rejected = [
        _row("s=AAPL", digest="X1", statuscode="404"),
        _row("s=AAPL", digest="X2", mimetype="text/html"),
        _row("s=AAPL", digest="X3", timestamp="20170501000000"),
        _row("s=AAPL&crumb=abc", digest="X4"),
        _row("s=MSFT", digest="X5"),
        _row("s=AAPL&c=2000&g=d", digest="X6"),
        _row("s=AAPL&c=1990&f=2015&g=d", digest="X7"),  # f before the capture year
        _row("s=AAPL&c=1990&g=w", digest="X8"),
    ]
    result = candidates([dup, keep_old, *rejected, keep_new, keep_tie], "AAPL", ["text/csv"])
    assert result == [keep_new, keep_tie, keep_old]  # same timestamp: `original` ascending


def test_candidates_full_history_queries() -> None:
    keep = [
        _row("s=AAPL&g=d&ignore=.csv", digest="F1"),  # the shape of capture 20161222215700
        _row("s=AAPL&a=&b=&c=&d=&e=&f=&g=&ignore=.csv", digest="F2"),  # empty_range
        _row("s=AAPL&g=&ignore=.csv", digest="F3"),
        _row("s=AAPL&ignore=.csv", digest="F4"),  # s_only
        _row("s=AAPL&amp;g=d&amp;b=", digest="F5"),
    ]
    rejected = [
        _row("s=AAPL&g=w&ignore=.csv", digest="R1"),
        _row("s=AAPL&a=0&g=d", digest="R2"),  # non-empty a without a Daily_Range
        _row("s=AAPL&g=d&x=1", digest="R3"),  # unknown parameter
        _row("g=d&ignore=.csv", digest="R4"),
    ]
    result = candidates([*rejected, *keep], "AAPL", ["text/csv"])
    assert {row.digest for row in result} == {"F1", "F2", "F3", "F4", "F5"}


def test_candidates_matches_percent_encoded_symbol() -> None:
    raw, encoded = _row("s=^GSPC", digest="R"), _row("s=%5EGSPC", digest="E")
    assert set(candidates([raw, encoded], "^GSPC", ["text/csv"])) == {raw, encoded}


def test_accept_good_and_bad_bodies() -> None:
    body = HEADER + b"\n2016-01-08,1,2,0.5,1.5,000,1.5\n2016-01-07,1,2,0.5,1.5,10,1.5\n"
    assert accept(body, "20160110120000") is None
    assert accept(body, "20160116000000") is not None  # newest row 8 days old
    assert accept(body, "20160107000000") is not None  # newest row after served date
    assert accept(body, "20170501000000") is not None
    assert accept(body, None) is not None
    assert accept(HEADER + b"\n", "20160110000000") is not None
    assert accept(b"Date,Open,High,Low,Close,Volume,Adj. Close*\n" + body, "20160110") is not None


def test_accept_rejects_any_unparseable_row_date() -> None:
    good = HEADER + b"\n2016-01-08,1,2,0.5,1.5,10,1.5\n"
    assert accept(good, "20160110000000") is None
    reason = accept(good + b"2016-02-30,1,2,0.5,1.5,10,1.5\n", "20160110000000")
    assert reason is not None and "unparseable" in reason
    assert accept(good + b"junk,1,2,0.5,1.5,10,1.5\n", "20160110000000") is not None


def test_accept_requires_the_donor_cover() -> None:
    days = [date(2016, 1, 8) - timedelta(days=i) for i in range(6)]  # 2016-01-08..03
    body = HEADER + b"\n" + b"".join(f"{d},1,2,0.5,1.5,10,1.5\n".encode() for d in days)
    served = "20160110000000"
    assert accept(body, served, (date(2016, 1, 4), date(2016, 1, 8))) is None
    assert accept(body, served, (date(2016, 1, 3), date(2016, 1, 8))) is None  # bounds inclusive
    assert accept(body, served, (date(2016, 1, 2), date(2016, 1, 8))) is not None  # too old
    assert accept(body, served, (date(2016, 1, 4), date(2016, 1, 9))) is not None  # too new
    assert accept(body, served) is None


def test_donor_file_name() -> None:
    assert donor_file_name("^GSPC") == "%5EGSPC.csv"
    assert donor_file_name("AAPL") == "AAPL.csv"
    assert donor_file_name("brk.b") == "%62%72%6B.%62.csv"
    assert donor_file_name("BRK.B") != donor_file_name("brk.b")


# --- Property 1 -----------------------------------------------------------------------------

SYMBOLS = ("AAPL", "^GSPC", "MSFT")
MIMETYPES = ["text/csv"]


@dataclass(frozen=True)
class Spec:
    """The generated structure of one CDX row; the oracle judges it without parsing the URL."""

    symbol: str
    encoding: str  # "raw", "%5E" or "%5e"
    shape: str  # "history" (s plus optional g, ignore and blank a-f) or "range"
    hist_g: str | None  # history shape: the `g` value, None means `g` is absent
    blanks: tuple[str, ...]  # history shape: names among a-f sent with an empty value
    filled: bool  # history shape: also send `a=0`, which no Full_History query has
    ignore: bool
    c: str
    f: str | None  # None means `f` is absent
    g: str
    auth: str | None
    sep: str  # "&", "&amp;" or "&amp" (F15)
    timestamp: str
    status: str
    mimetype: str
    digest: str

    def row(self) -> CdxRow:
        s = self.symbol if self.encoding == "raw" else self.symbol.replace("^", self.encoding)
        parts = [f"s={s}"]
        if self.shape == "history":
            parts += [f"{name}=" for name in self.blanks]
            if self.hist_g is not None:
                parts.append(f"g={self.hist_g}")
            if self.filled:
                parts.append("a=0")
        if self.shape == "range":
            parts += ["a=0", "b=1", f"c={self.c}", "d=0", "e=8"]
            if self.f is not None:
                parts.append(f"f={self.f}")
            parts.append(f"g={self.g}")
        if self.auth is not None:
            parts.append(f"{self.auth}=abc")
        if self.ignore:
            parts.append("ignore=.csv")
        return CdxRow(
            timestamp=self.timestamp,
            original=f"{HOST}?{self.sep.join(parts)}",
            mimetype=self.mimetype,
            statuscode=self.status,
            digest=self.digest,
            length="100",
        )

    def qualifies(self, symbol: str) -> bool:
        """Req 2.2, stated directly on the generated structure."""
        if not (self.status.startswith("2") and self.mimetype in MIMETYPES):
            return False
        if self.timestamp >= "20170501" or self.auth is not None or self.symbol != symbol:
            return False
        if self.shape == "history":
            return self.hist_g in (None, "", "d") and not self.filled
        if self.g != "d" or not self.c.isdigit() or int(self.c) > 1999:
            return False
        year = int(self.timestamp[:4])
        return self.f in (None, "") or (self.f.isdigit() and int(self.f) >= year)


specs = st.builds(
    Spec,
    symbol=st.sampled_from(SYMBOLS),
    encoding=st.sampled_from(["raw", "%5E", "%5e"]),
    shape=st.sampled_from(["history", "range"]),
    hist_g=st.sampled_from([None, "", "d", "w", "v"]),
    blanks=st.lists(st.sampled_from("abcdef"), unique=True, max_size=6).map(tuple),
    filled=st.booleans(),
    ignore=st.booleans(),
    c=st.sampled_from(["", "1900", "1980", "1999", "2000", "{{(-1 month).year}}"]),
    f=st.sampled_from([None, "", "2014", "2015", "2016", "2017", "x"]),
    g=st.sampled_from(["d", "w", "m", "v", ""]),
    auth=st.sampled_from([None, None, None, "crumb", "api_key", "Session", "notoken"]),
    sep=st.sampled_from(["&", "&amp;", "&amp"]),
    timestamp=st.sampled_from(
        [
            "20140101000000",
            "20150615120000",
            "20160110000000",
            "20161231235959",
            "20170430235959",
            "20170501000000",
            "20180101000000",
        ]
    ),
    status=st.sampled_from(["200", "206", "302", "404"]),
    mimetype=st.sampled_from(["text/csv", "text/html"]),
    digest=st.sampled_from(["D0", "D1", "D2", "D3", "D4", "D5"]),
)


# Feature: reanimate, Property 1: Donor candidate filter and order
@settings(max_examples=100)
@given(data=st.data(), items=st.lists(specs, max_size=25), symbol=st.sampled_from(SYMBOLS))
def test_property_candidate_filter_and_order(
    data: st.DataObject, items: list[Spec], symbol: str
) -> None:
    """**Validates: Requirements 2.2**"""
    rows = [item.row() for item in items]
    qualifying = [row for item, row in zip(items, rows, strict=True) if item.qualifies(symbol)]
    result = candidates(rows, symbol, MIMETYPES)

    # Every returned row meets each Req 2.2 condition.
    assert all(row in qualifying for row in result)
    # Digests are unique, and no qualifying digest is lost.
    digests = [row.digest for row in result]
    assert len(digests) == len(set(digests))
    assert set(digests) == {row.digest for row in qualifying}
    # Order: timestamp descending, ties broken by `original` ascending.
    keys = [(row.timestamp, row.original) for row in result]
    for (t1, o1), (t2, o2) in pairwise(keys):
        assert t1 > t2 or (t1 == t2 and o1 <= o2)
    # The row kept for a digest is its first in that order (newest, then smallest original).
    for row in result:
        same = [q for q in qualifying if q.digest == row.digest]
        best = min(same, key=lambda q: (-int(q.timestamp), q.original))
        assert (row.timestamp, row.original) == (best.timestamp, best.original)
    # Input order does not matter.
    shuffled = data.draw(st.permutations(rows))
    assert candidates(shuffled, symbol, MIMETYPES) == result


# --- Property 2 -----------------------------------------------------------------------------

CUTOFF_DATE = date(2017, 5, 1)
BAD_HEADERS = (
    b"Date,Open,High,Low,Close,Volume,Adj. Close*",
    b"Date,Open,High,Low,Close,Volume",
    b"date,open,high,low,close,volume,adj close",
    b"",
)


def _body(header: bytes, newest: date, rows: int, tag: int = 0) -> bytes:
    """Header plus `rows` newest-first Data_Rows ending at `newest`; `tag` makes bodies distinct."""
    lines = [header]
    for i in range(rows):
        day = (newest - timedelta(days=i)).isoformat()
        lines.append(f"{day},1.5,2.25,0.75,1.875,{tag:03d},1.875".encode())
    return b"\n".join(lines) + b"\n"


# Feature: reanimate, Property 2: Donor acceptance and the 5-try cap
@settings(max_examples=100)
@given(
    served_on=st.dates(min_value=date(2004, 1, 10), max_value=date(2018, 12, 31)),
    clock=st.sampled_from(["000000", "120000", "235959"]),
    offset=st.integers(min_value=-3, max_value=12),
    rows=st.integers(min_value=0, max_value=4),
    header=st.one_of(st.just(HEADER), st.sampled_from(BAD_HEADERS)),
    bad_date=st.sampled_from([None, b"junk", b"2016-02-30", b"2016-13-01"]),
    cover=st.one_of(
        st.none(),
        st.tuples(st.integers(min_value=-2, max_value=6), st.integers(min_value=0, max_value=4)),
    ),
)
def test_property_accept(
    served_on: date,
    clock: str,
    offset: int,
    rows: int,
    header: bytes,
    bad_date: bytes | None,
    cover: tuple[int, int] | None,
) -> None:
    """**Validates: Requirements 2.3**"""
    served = served_on.strftime("%Y%m%d") + clock
    newest = served_on - timedelta(days=offset)
    body = _body(header, newest, rows)
    if bad_date is not None:  # one Data_Row whose Row_Date does not parse
        body += bad_date + b",1.5,2.25,0.75,1.875,000,1.875\n"
    expected = served_on < CUTOFF_DATE and header == HEADER and rows >= 1 and 0 <= offset <= 7
    expected = expected and bad_date is None
    window = None
    if cover is not None:  # start `back` days before the newest row, `span` days long
        back, span = cover
        start = newest - timedelta(days=back)
        window = (start, start + timedelta(days=span))
        oldest = newest - timedelta(days=rows - 1)
        expected = expected and oldest <= window[0] and newest >= window[1]
    assert (accept(body, served, window) is None) == expected


class FakeArchive:
    """ArchiveClient stand-in: answers each capture URL with its scripted outcome, offline."""

    def __init__(self, outcomes: dict[str, tuple[str, bytes]]) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []

    def get(self, url: str, params: list[tuple[str, str]] | None = None) -> httpx.Response:
        assert url in self.outcomes, f"unexpected request {url}"  # never a CDX request
        self.calls.append(url)
        kind, body = self.outcomes[url]
        if kind == "error":
            raise ArchiveError(f"{url}: retries exhausted")
        status = 404 if kind == "not_found" else 200
        return httpx.Response(status, content=body, request=httpx.Request("GET", url))


OUTCOMES = (
    "qualifies",
    "stale",
    "bad_header",
    "header_only",
    "uncovered",
    "bad_date",
    "not_found",
    "error",
)
COVER = ["2016-01-01", "2016-01-05"]  # every candidate below is served 2016-01-12..20


def _scripted(timestamp: str, kind: str, tag: int) -> bytes:
    served_on = date(int(timestamp[:4]), int(timestamp[4:6]), int(timestamp[6:8]))
    covering = (served_on - date.fromisoformat(COVER[0])).days + 1
    if kind == "stale":
        return _body(HEADER, served_on - timedelta(days=9), 3, tag)
    if kind == "bad_header":
        return _body(BAD_HEADERS[0], served_on, covering, tag)
    if kind == "header_only":
        return HEADER + b"\n"
    if kind == "uncovered":
        return _body(HEADER, served_on, 3, tag)
    if kind == "bad_date":
        return _body(HEADER, served_on, covering, tag) + b"junk,1,2,0.5,1.5,000,1.5\n"
    return _body(HEADER, served_on, covering, tag)


# Feature: reanimate, Property 2: Donor acceptance and the 5-try cap
@settings(max_examples=100)
@given(
    kinds=st.lists(st.sampled_from(OUTCOMES), min_size=1, max_size=9),
    symbol=st.sampled_from(["AAPL", "^GSPC", "brk.b"]),
)
def test_property_five_try_cap(kinds: list[str], symbol: str) -> None:
    """**Validates: Requirements 2.3, 2.4, 2.6**"""
    host = "ichart.finance.yahoo.com"
    newest = date(2016, 1, 20)
    rows, outcomes, bodies = [], {}, []
    for i, kind in enumerate(kinds):  # distinct timestamps, newest first = candidate order
        timestamp = (newest - timedelta(days=i)).strftime("%Y%m%d") + "120000"
        row = CdxRow(
            timestamp=timestamp,
            original=f"http://{host}/table.csv?s={symbol}",
            mimetype="text/csv",
            statuscode="200",
            digest=f"D{i}",
            length="100",
        )
        body = _scripted(timestamp, kind, i)
        rows.append(row)
        bodies.append(body)
        outcomes[wayback_url(timestamp, row.original)] = (kind, body)
    tombstone = Tombstone(
        slug="t-slug",
        name="t",
        died="2017-05",
        hosts=[host],
        paths=["table.csv"],
        mimetypes=["text/csv"],
        donor_symbols=[symbol],
        donor_required=[symbol],
        donor_cover=COVER,
    )
    archive = FakeArchive(outcomes)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = EvidenceStore(root / "evidence", tombstone.slug)
        store.save_listing(Listing(host=host, kind="data", params=[], rows=rows, ethics_dropped=0))
        slug_dir = root / "crypt" / tombstone.slug
        report = fetch_donors(tombstone, archive, store, slug_dir)  # type: ignore[arg-type]

        first = next((i for i, kind in enumerate(kinds) if kind == "qualifies"), None)
        if first is not None and first < MAX_TRIES:
            assert len(archive.calls) == first + 1
            assert report.stored == [symbol] and not report.missing
            stored = slug_dir / "donor" / donor_file_name(symbol)
            assert stored.read_bytes() == bodies[first]  # unchanged, byte for byte
            entry = load_donor_index(slug_dir, tombstone.slug).entries[symbol]
            assert entry.file == donor_file_name(symbol)
            assert entry.source_url == wayback_url(rows[first].timestamp, rows[first].original)
        else:
            assert len(archive.calls) == min(MAX_TRIES, len(kinds))
            assert report.stored == [] and symbol in report.missing
            assert symbol in report.missing[symbol] and report.required_missing == [symbol]
            assert not index_path(slug_dir).exists()
            assert not (slug_dir / "donor" / donor_file_name(symbol)).exists()
        # Candidates are tried in Req 2.2 order: newest first.
        assert (
            archive.calls
            == [wayback_url(r.timestamp, r.original) for r in rows][: len(archive.calls)]
        )


# Feature: reanimate, Property 2: Donor acceptance and the 5-try cap
@settings(max_examples=100)
@given(a=st.text(min_size=1, max_size=8), b=st.text(min_size=1, max_size=8))
def test_property_donor_file_name(a: str, b: str) -> None:
    """**Validates: Requirements 2.4**"""
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-_%")
    for name in (donor_file_name(a), donor_file_name(b)):
        assert name.endswith(".csv") and set(name) <= allowed
    assert donor_file_name(a) == donor_file_name(a)
    if a != b:
        assert donor_file_name(a).casefold() != donor_file_name(b).casefold()


# --- Example tests: fetch_donors over a real ArchiveClient and httpx.MockTransport ------------
#
# No AAPL capture in `evidence/` is both a Req 2.2 candidate (s_only or g=d full range) and
# accepted by Req 2.3; the committed sample's AAPL captures are g=w or g=m. The fixture is the
# real YHOO full-history capture (s_only, 2016-05-03), YHOO being a Donor_Symbol of the slug.

REPO = Path(__file__).resolve().parents[2]
SLUG = "yahoo-finance-ichart"
FIXTURE_HOST = "real-chart.finance.yahoo.com"
FIXTURE_FILE = "real-chart.finance.yahoo.com/20160503141357-HG34ZJYAKQT36BTGFBZ43A5XCH4LOBNU.csv"
FIXTURE_ORIGINAL = "http://real-chart.finance.yahoo.com:80/table.csv?s=YHOO"
SERVED = "20160503141357"
REQUESTED = "20160503120000"  # the Archive redirects to the nearest capture it holds
FIXTURE_ROW = CdxRow(
    timestamp=REQUESTED,
    original=FIXTURE_ORIGINAL,
    mimetype="text/csv",
    statuscode="200",
    digest="HG34ZJYAKQT36BTGFBZ43A5XCH4LOBNU",
    length="92797",
)


class NoSleepClock:
    """Clock whose sleep only advances time, so the RateLimiter and backoff cost nothing."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def now_utc(self) -> datetime:
        return datetime(2026, 11, 22, tzinfo=UTC)


class MockArchive:
    """Archive endpoints behind `httpx.MockTransport`: CDX pages and `id_` captures."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/cdx/search/cdx":
            header = ["timestamp", "original", "mimetype", "statuscode", "digest", "length"]
            page: list[list[str]] = [header]
            if request.url.params.get("url", "").startswith(FIXTURE_HOST + "/"):
                page.append([getattr(FIXTURE_ROW, name) for name in header])
            return httpx.Response(200, json=page)
        wanted = f"/web/{REQUESTED}id_/{FIXTURE_ORIGINAL.split('?')[0]}"
        if path == wanted and request.url.query == b"s=YHOO":
            target = f"https://web.archive.org/web/{SERVED}id_/{FIXTURE_ORIGINAL}"
            return httpx.Response(302, headers={"Location": target})
        if path == wanted.replace(REQUESTED, SERVED):
            return httpx.Response(200, content=self.body, headers={"Content-Type": "text/csv"})
        return httpx.Response(404, content=b"not archived")

    @property
    def capture_requests(self) -> int:
        return sum(1 for r in self.requests if r.url.path.startswith("/web/"))


def _tombstone(
    symbols: list[str], required: list[str], cover: list[str] | None = None
) -> Tombstone:
    return Tombstone(
        donor_cover=cover,
        slug=SLUG,
        name="Yahoo Finance historical prices",
        died="2017-05",
        hosts=["ichart.yahoo.com", "ichart.finance.yahoo.com", FIXTURE_HOST],
        paths=["table.csv"],
        mimetypes=["text/csv"],
        donor_symbols=symbols,
        donor_required=required,
    )


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def env(tmp_path: Path) -> tuple[Path, EvidenceStore, MockArchive, ArchiveClient]:
    """A tmp repo copy holding the fixture capture under `evidence/`; no CDX listing cached."""
    source = REPO / "evidence" / SLUG / FIXTURE_FILE
    copy = tmp_path / "evidence" / SLUG / FIXTURE_FILE
    copy.parent.mkdir(parents=True)
    shutil.copyfile(source, copy)
    mock = MockArchive(source.read_bytes())
    clock = NoSleepClock()
    client = make_client(RateLimiter(clock), user_agent(), httpx.MockTransport(mock.handler))
    store = EvidenceStore(tmp_path / "evidence", SLUG)
    return tmp_path, store, mock, ArchiveClient(client, clock)


def test_fetch_stores_entry_then_reuses_with_zero_requests(env) -> None:
    root, store, mock, archive = env
    slug_dir = root / "crypt" / SLUG
    before = _tree(root / "evidence")
    body = mock.body

    report = fetch_donors(_tombstone(["YHOO"], ["YHOO"]), archive, store, slug_dir)

    assert report.stored == ["YHOO"] and not report.missing and not report.required_missing
    stored = slug_dir / "donor" / "YHOO.csv"
    assert stored.read_bytes() == body
    entry = load_donor_index(slug_dir, SLUG).entries["YHOO"]
    assert entry.file == "YHOO.csv"
    assert entry.source_url == f"https://web.archive.org/web/{REQUESTED}id_/{FIXTURE_ORIGINAL}"
    assert entry.host == FIXTURE_HOST
    assert entry.served_timestamp == SERVED  # the redirect target, not the requested one
    assert entry.sha256 == hashlib.sha256(body).hexdigest()
    assert entry.rows == len(body.rstrip(b"\n").split(b"\n")) - 1
    assert entry.last_date == "2016-05-02"
    assert entry.first_date == body.rstrip(b"\n").rsplit(b"\n", 1)[1].split(b",")[0].decode()
    assert all(r.headers["User-Agent"] == user_agent() for r in mock.requests)

    # Only CDX listings were added under evidence/; every other file is unchanged.
    after = _tree(root / "evidence")
    added = set(after) - set(before)
    assert added and all(path.startswith(f"{SLUG}/cdx/") for path in added)
    assert all(after[path] == data for path, data in before.items())

    # Req 2.5: a hash-valid entry is reused with zero Archive requests.
    count = len(mock.requests)
    again = fetch_donors(_tombstone(["YHOO"], ["YHOO"]), archive, store, slug_dir)
    assert again.stored == ["YHOO"] and len(mock.requests) == count
    assert load_donor_index(slug_dir, SLUG).entries["YHOO"] == entry


def test_corrupted_donor_file_is_refetched(env) -> None:
    root, store, mock, archive = env
    slug_dir = root / "crypt" / SLUG
    fetch_donors(_tombstone(["YHOO"], ["YHOO"]), archive, store, slug_dir)
    stored = slug_dir / "donor" / "YHOO.csv"
    stored.write_bytes(b"Date,Open,High,Low,Close,Volume,Adj Close\ncorrupt\n")
    captures = mock.capture_requests
    cdx = len(mock.requests) - captures

    report = fetch_donors(_tombstone(["YHOO"], ["YHOO"]), archive, store, slug_dir)

    assert report.stored == ["YHOO"]
    assert stored.read_bytes() == mock.body
    assert mock.capture_requests == captures + 2  # one redirect hop plus the served capture
    assert len(mock.requests) - mock.capture_requests == cdx  # cached listings: no CDX request


def test_missing_optional_symbol_continues(env) -> None:
    root, store, _, archive = env
    slug_dir = root / "crypt" / SLUG
    report = fetch_donors(_tombstone(["MSFT", "YHOO"], ["YHOO"]), archive, store, slug_dir)
    assert report.stored == ["YHOO"] and report.required_missing == []
    assert "MSFT" in report.missing["MSFT"] and "no capture qualified" in report.missing["MSFT"]
    assert set(load_donor_index(slug_dir, SLUG).entries) == {"YHOO"}
    assert not (slug_dir / "donor" / "MSFT.csv").exists()


def test_missing_required_symbol_sets_required_missing(env) -> None:
    root, store, _, archive = env
    slug_dir = root / "crypt" / SLUG
    report = fetch_donors(_tombstone(["MSFT", "YHOO"], ["MSFT"]), archive, store, slug_dir)
    assert report.required_missing == ["MSFT"] and "MSFT" in report.missing
    assert report.stored == ["YHOO"]
    assert not (slug_dir / "donor" / "MSFT.csv").exists()


def test_corrupted_donor_without_replacement_loses_its_entry(env) -> None:
    root, store, mock, archive = env
    slug_dir = root / "crypt" / SLUG
    fetch_donors(_tombstone(["YHOO"], ["YHOO"]), archive, store, slug_dir)
    stored = slug_dir / "donor" / "YHOO.csv"
    corrupt = b"Date,Open,High,Low,Close,Volume,Adj Close\ncorrupt\n"
    stored.write_bytes(corrupt)
    mock.body = b"<html>not a csv</html>"  # the only candidate no longer qualifies

    report = fetch_donors(_tombstone(["YHOO"], ["YHOO"]), archive, store, slug_dir)

    assert report.stored == [] and report.required_missing == ["YHOO"]
    assert "no capture qualified" in report.missing["YHOO"]
    assert "removed" in report.missing["YHOO"]
    assert load_donor_index(slug_dir, SLUG).entries == {}
    assert stored.read_bytes() == corrupt  # the file's bytes stay on disk


def test_donor_cover_rejects_a_capture_that_misses_it(env) -> None:
    root, store, mock, archive = env
    slug_dir = root / "crypt" / SLUG
    # The YHOO fixture's newest Row_Date is 2016-05-02, so it cannot cover 2016-05-03.
    report = fetch_donors(
        _tombstone(["YHOO"], ["YHOO"], ["2016-04-25", "2016-05-03"]), archive, store, slug_dir
    )
    assert report.required_missing == ["YHOO"] and mock.capture_requests == 2
    assert not (slug_dir / "donor" / "YHOO.csv").exists()

    covered = fetch_donors(
        _tombstone(["YHOO"], ["YHOO"], ["2016-04-25", "2016-05-02"]), archive, store, slug_dir
    )
    assert covered.stored == ["YHOO"]
