"""Content checks: HTML sniffing, the Offline detector (P2), Error pages and digest pairs."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from hypothesis import given, settings
from hypothesis import strategies as st

from revenant.exhume.content import classify, is_html, is_offline_page, wayback_digest

FIXTURES = Path(__file__).parent / "fixtures"
F5_HEAD = (FIXTURES / "f5_csv_head.csv").read_bytes()
F9_OFFLINE = (FIXTURES / "f9_offline.html").read_bytes()
F10_404 = (FIXTURES / "f10_yahoo_404_head.html").read_bytes()
F12_HEADER_ONLY = (FIXTURES / "f12_header_only.csv").read_bytes()
F14_DISH = (FIXTURES / "f14_dish_20041129.csv").read_bytes()

# ---- generators for P2 -------------------------------------------------------------------

_CELL = st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcxyz0123456789.-^* ", max_size=12)
_CSV = st.lists(st.lists(_CELL, min_size=1, max_size=7), max_size=8).map(
    lambda rows: "".join(",".join(row) + "\n" for row in rows).encode()
)
_JSON_VALUE = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=20),
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=8), inner),
    max_leaves=10,
)
_JSON = _JSON_VALUE.map(lambda value: json.dumps(value).encode())
_XML_NAME = st.sampled_from(["query", "results", "quote", "row", "data", "Symbol"])
_XML_TEXT = st.text(alphabet="abcXYZ 0123456789.,-", max_size=16)
_XML = st.tuples(
    st.booleans(), _XML_NAME, st.lists(st.tuples(_XML_NAME, _XML_TEXT), max_size=5)
).map(
    lambda t: (
        ('<?xml version="1.0" encoding="UTF-8"?>\n' if t[0] else "")
        + f"<{t[1]}>"
        + "".join(f"<{name}>{text}</{name}>" for name, text in t[2])
        + f"</{t[1]}>"
    ).encode()
)
_NON_HTML_TYPES = st.sampled_from(
    [
        "text/csv",
        "text/csv; charset=utf-8",
        "application/json",
        "text/xml",
        "application/xml; charset=UTF-8",
        "text/plain",
    ]
)

_STATUS = st.integers(min_value=100, max_value=599)
_HTML_TYPES = st.sampled_from(
    ["text/html", "text/html; charset=utf-8", "TEXT/HTML; Charset=ISO-8859-1", None, "text/plain"]
)


@st.composite
def _offline_pages(draw: st.DrawFn) -> bytes:
    """F9-style Offline pages with varied BOM, whitespace and tag casing around a fixed title."""
    bom = draw(st.sampled_from([b"", b"\xef\xbb\xbf"]))
    space = draw(st.sampled_from([b"", b" ", b"\n", b"\r\n\t "]))
    doctype = draw(st.sampled_from([b"", b"<!DOCTYPE html>\n", b"<!doctype HTML>"]))
    html_tag = draw(st.sampled_from([b"<html>", b"<HTML>", b'<html lang="en">']))
    title_tag = draw(st.sampled_from([b"<title>", b"<TITLE>", b"<Title >"]))
    close_title = draw(st.sampled_from([b"</title>", b"</TITLE>"]))
    title = b"Internet Archive: Temporarily Offline"
    return (
        bom
        + space
        + doctype
        + html_tag
        + b"<head>"
        + title_tag
        + title
        + close_title
        + b"</head><body></body></html>"
    )


# Feature: exhume, Property 2: Offline detector
@settings(max_examples=100)
@given(
    data_body=st.one_of(_CSV, _JSON, _XML),
    data_type=_NON_HTML_TYPES,
    offline_body=st.one_of(st.just(F9_OFFLINE), _offline_pages()),
    offline_type=_HTML_TYPES,
    status=_STATUS,
)
def test_offline_detector_property(
    data_body: bytes,
    data_type: str,
    offline_body: bytes,
    offline_type: str | None,
    status: int,
) -> None:
    """**Validates: Requirements 7.1, 7.2**"""
    data = httpx.Response(status, content=data_body, headers={"Content-Type": data_type})
    assert not is_offline_page(data.headers.get("content-type"), data.content)

    headers = {} if offline_type is None else {"Content-Type": offline_type}
    offline = httpx.Response(status, content=offline_body, headers=headers)
    assert is_offline_page(offline.headers.get("content-type"), offline.content)


# ---- examples ----------------------------------------------------------------------------


def test_is_html_by_content_type_or_body_sniff() -> None:
    assert is_html("text/html; charset=iso-8859-1", b"anything")
    assert is_html(None, b"\xef\xbb\xbf  \n<!DocType html><html></html>")
    assert is_html("text/csv", F10_404)
    assert not is_html("text/csv", F5_HEAD)
    assert not is_html(None, b"")


def test_yahoo_404_is_not_offline() -> None:
    assert not is_offline_page("text/html; charset=iso-8859-1", F10_404)
    # A "Temporarily Offline" outside the first <title> does not count.
    late = b"<html><head><title>Yahoo!</title></head><body>Temporarily Offline</body></html>"
    assert not is_offline_page("text/html", late)


def test_yahoo_404_under_csv_mimetype_is_error_page() -> None:
    assert classify(F10_404, "text/html; charset=iso-8859-1", "text/csv") == "error_page"
    assert classify(F10_404, None, "text/csv") == "error_page"  # body sniff alone
    # When the CDX says text/html, HTML is the expected content, not an Error page.
    assert classify(F10_404, "text/html", "text/html") == "data"


def test_csv_bodies_are_data() -> None:
    assert classify(F12_HEADER_ONLY, "text/csv", "text/csv") == "data"
    assert classify(F5_HEAD, "text/csv", "text/csv") == "data"
    # F16: a trailing server comment line does not make the body HTML.
    assert classify(F14_DISH, "text/csv", "text/csv") == "data"


def test_digest_known_pairs() -> None:
    # F11: the 44-byte header-only 2005 body, LF-terminated.
    assert F12_HEADER_ONLY == b"Date,Open,High,Low,Close,Volume,Adj. Close*\n"
    assert len(F12_HEADER_ONLY) == 44
    assert wayback_digest(F12_HEADER_ONLY) == "ASWL2AKBV45KRJN7BD5UYGRV4GPEDJRR"
    # F14: the 125-byte DISH body stored by the live task 5.5 run.
    assert len(F14_DISH) == 125
    assert wayback_digest(F14_DISH) == "2ADTBRSLGIS5YZLXF4LRCFLO363WOUXW"


def test_digest_known_pair_f8_full_f5_body() -> None:
    # F8: the full 15479-byte F5 body hashes to its F1 CDX digest.
    body = (FIXTURES / "f5_goog_weekly.csv").read_bytes()
    assert len(body) == 15479
    assert b"\r" not in body
    assert body.startswith(F5_HEAD)
    assert wayback_digest(body) == "M37VRFD74CQFJ6RCU52MNGMWIP5YDNFY"
