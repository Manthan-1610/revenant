"""Tests for CDX discovery (revenant/exhume/cdx.py)."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from revenant.exhume.archive import ArchiveClient, RateLimiter, make_client
from revenant.exhume.cdx import (
    CDX_URL,
    FIELDS,
    CdxParseError,
    DiscoveryError,
    build_params,
    fetch_listing,
    merge_rows,
    mimetype_regex,
    parse_page,
)
from revenant.exhume.models import CdxRow, Tombstone
from tests.exhume.conftest import FakeClock

FIXTURES = Path(__file__).parent / "fixtures"
F1_KEY = "eJwVyk0KgCAQQOGrtBoIwmYMIRdDZ1EzlX4Ek6Dbl8uP91w-h9fEnIfkoim1H6uxhxfufhbDCJYJHEvECdafniXB1qwh8AopXLl4bjvcjIhKxL1rGUlqmpVU9AEE9hxp"
F2_KEY = "eJwVylsKgCAQQNGt9DUQSI2PpD6G1mJmKT2ElKDdp5-He2282Gd8jCxYb57c9tksp-tsemdDCAtxsCQQJayFjsQAWzHnsNMKYb_j46jukAinUXf-aGpGgYproeT0AwWDHG4"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def tombstone(paths: list[str] | None = None) -> Tombstone:
    return Tombstone(
        slug="yahoo-finance-ichart",
        name="Yahoo Finance historical prices",
        died="2017-05",
        hosts=["ichart.yahoo.com"],
        paths=paths or ["table.csv"],
        mimetypes=["text/csv"],
    )


def archive_for(handler, clock: FakeClock | None = None) -> ArchiveClient:
    clock = clock or FakeClock()
    client = make_client(RateLimiter(clock), "test-agent", transport=httpx.MockTransport(handler))
    return ArchiveClient(client, clock)


def row(ts: str, digest: str, original: str = "http://h/table.csv?s=A") -> CdxRow:
    return CdxRow(
        timestamp=ts,
        original=original,
        mimetype="text/csv",
        statuscode="200",
        digest=digest,
        length="1",
    )


# --- Property 1 ---------------------------------------------------------------

_value = st.text(max_size=20)


@st.composite
def cdx_pages(draw):
    header = draw(st.permutations(list(FIELDS)))
    records = draw(st.lists(st.fixed_dictionaries({f: _value for f in FIELDS}), max_size=8))
    key = draw(st.one_of(st.none(), st.text(min_size=1, max_size=40)))
    page: list[list[str]] = [list(header)]
    page += [[rec[f] for f in header] for rec in records]
    if key is not None:
        page += [[], [key]]
    return json.dumps(page).encode(), records, key


# Feature: exhume, Property 1: CDX page parse
@settings(max_examples=100)
@given(cdx_pages())
def test_p1_parse_page_maps_by_name_and_extracts_key(page) -> None:
    """**Validates: Requirements 3.2**"""
    payload, records, key = page
    rows, got_key = parse_page(payload)
    # Same count and same values as the generated records: the key never becomes a row.
    assert len(rows) == len(records)
    assert [r.model_dump() for r in rows] == records
    assert got_key == key


def test_p1_fixtures_parse_as_expected() -> None:
    rows, key = parse_page(fixture("cdx_f1.json"))
    assert key == F1_KEY
    assert [r.timestamp for r in rows] == ["20131213174436", "20090103230517", "20090129101731"]
    assert rows[0].original.startswith("http://ichart.yahoo.com:80/table.csv?s=GOOG")
    assert rows[0].digest == "M37VRFD74CQFJ6RCU52MNGMWIP5YDNFY"
    assert rows[0].length == "6731"

    rows, key = parse_page(fixture("cdx_f2.json"))
    assert key == F2_KEY
    assert [r.digest for r in rows] == ["IVEFWI4ZNPMWXQOB7U7MQCBKDTPDSNPN"]

    rows, key = parse_page(fixture("cdx_last_page.json"))
    assert key is None
    assert len(rows) == 3

    # F3 used fl=timestamp,statuscode,digest; CdxRow needs all six fields.
    with pytest.raises(CdxParseError, match="original"):
        parse_page(fixture("cdx_f3.json"))


# --- parse_page edge cases ----------------------------------------------------


def test_parse_page_empty_array_has_no_rows_and_no_key() -> None:
    assert parse_page(b"[]") == ([], None)


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b'{"a": 1}',
        b"[[1, 2]]",
        json.dumps([list(FIELDS), ["only", "three", "values"]]).encode(),
        json.dumps([list(FIELDS), [], ["k"], list(FIELDS)]).encode(),
    ],
)
def test_parse_page_rejects_malformed_pages(payload: bytes) -> None:
    with pytest.raises(CdxParseError):
        parse_page(payload)


# --- Query building -------------------------------------------------------------


def test_mimetype_regex_single_and_several() -> None:
    assert mimetype_regex(["text/csv"]) == "text/csv"
    assert mimetype_regex(["text/csv", "text/xml"]) == "(text/csv|text/xml)"
    assert mimetype_regex(["application/vnd.ms-excel"]) == r"application/vnd\.ms\-excel"


def test_build_params_data_pass_matches_req_3_1() -> None:
    assert build_params("ichart.yahoo.com", "table.csv", "data", ["text/csv"]) == [
        ("url", "ichart.yahoo.com/table.csv*"),
        ("output", "json"),
        ("collapse", "digest"),
        ("fl", "timestamp,original,mimetype,statuscode,digest,length"),
        ("filter", "statuscode:2.."),
        ("filter", "mimetype:text/csv"),
        ("limit", "1000"),
        ("showResumeKey", "true"),
    ]


# --- Merging --------------------------------------------------------------------


def test_merge_rows_keeps_earliest_timestamp_per_digest_and_sorts() -> None:
    rows = [
        row("20130101000000", "BBB"),
        row("20090101000000", "AAA", "http://h/late"),
        row("20050101000000", "AAA", "http://h/early"),
        row("20090101000000", "CCC"),
    ]
    merged = merge_rows(rows)
    assert [(r.timestamp, r.digest) for r in merged] == [
        ("20050101000000", "AAA"),
        ("20090101000000", "CCC"),
        ("20130101000000", "BBB"),
    ]
    assert merged[0].original == "http://h/early"


# --- fetch_listing --------------------------------------------------------------


def test_fetch_listing_paginates_f1_f2_last_page() -> None:
    requests: list[httpx.Request] = []
    pages = {None: "cdx_f1.json", F1_KEY: "cdx_f2.json", F2_KEY: "cdx_last_page.json"}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        key = request.url.params.get("resumeKey")
        return httpx.Response(200, content=fixture(pages[key]))

    listing = fetch_listing(archive_for(handler), tombstone(), "ichart.yahoo.com", "data")

    assert len(requests) == 3
    expected = build_params("ichart.yahoo.com", "table.csv", "data", ["text/csv"])
    sent = [parse_qsl(urlsplit(str(r.url)).query) for r in requests]
    assert sent[0] == expected
    assert sent[1] == [*expected, ("resumeKey", F1_KEY)]
    assert sent[2] == [*expected, ("resumeKey", F2_KEY)]
    assert all(str(r.url).startswith(CDX_URL + "?") for r in requests)

    assert listing.host == "ichart.yahoo.com"
    assert listing.kind == "data"
    assert listing.params == expected
    assert listing.ethics_dropped == 0
    # F1 rows repeat on the derived last page; merge keeps one per digest, sorted.
    assert [r.timestamp for r in listing.rows] == [
        "20090103230517",
        "20090129101731",
        "20090202003604",
        "20131213174436",
    ]


def test_fetch_listing_loops_paths_in_order() -> None:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(request.url.params["url"])
        return httpx.Response(200, content=fixture("cdx_last_page.json"))

    listing = fetch_listing(
        archive_for(handler), tombstone(["table.csv", "x.csv"]), "ichart.yahoo.com", "data"
    )
    assert urls == ["ichart.yahoo.com/table.csv*", "ichart.yahoo.com/x.csv*"]
    assert listing.params[0] == ("url", "ichart.yahoo.com/table.csv*")
    assert len(listing.rows) == 3


def test_fetch_listing_parse_failure_on_later_page_is_discovery_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("resumeKey") is None:
            return httpx.Response(200, content=fixture("cdx_f1.json"))
        return httpx.Response(200, content=b"<html>not json</html>")

    with pytest.raises(DiscoveryError, match="ichart.yahoo.com"):
        fetch_listing(archive_for(handler), tombstone(), "ichart.yahoo.com", "data")


def test_fetch_listing_exhausted_retries_is_discovery_error() -> None:
    clock = FakeClock()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    with pytest.raises(DiscoveryError, match="data pass"):
        fetch_listing(archive_for(handler, clock), tombstone(), "ichart.yahoo.com", "data")
    assert calls == 5


def test_fetch_listing_non_2xx_status_is_discovery_error_without_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400)

    with pytest.raises(DiscoveryError, match="HTTP 400"):
        fetch_listing(archive_for(handler), tombstone(), "ichart.yahoo.com", "data")
    assert calls == 1
