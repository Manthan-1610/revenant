"""Property test P2 and writer examples for the Contract (Req 7.1, 7.4, 7.6)."""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from revenant.autopsy.contract import dump_contract, load_contract, write_contract
from revenant.autopsy.evidence import Capture
from revenant.autopsy.infer import infer
from revenant.exhume.models import IndexEntry

SLUG = "yahoo-finance-ichart"
HOSTS = ("ichart.finance.yahoo.com", "ichart.yahoo.com", "real-chart.finance.yahoo.com")


def _query(start: date, end: date, h: int, g: str) -> str:
    return (
        f"s=AAPL&a={start.month - 1 + h}&b={start.day}&c={start.year}"
        f"&d={end.month - 1 + h}&e={end.day}&f={end.year}&g={g}&ignore=.csv"
    )


@st.composite
def captures(draw: st.DrawFn) -> list[Capture]:
    """Synthetic evidence: data, error and error_page entries over several hosts and shapes."""
    count = draw(st.integers(min_value=0, max_value=12))
    result: dict[str, Capture] = {}
    for number in range(count):
        host = draw(st.sampled_from(HOSTS))
        kind = draw(st.sampled_from(["data", "data", "data", "error", "error_page"]))
        newest = draw(st.dates(min_value=date(2004, 1, 1), max_value=date(2016, 12, 1)))
        span = draw(st.integers(min_value=0, max_value=60))
        oldest = newest - timedelta(days=span)
        rows = [newest - timedelta(days=step) for step in range(0, span + 1, 7)]
        shape = draw(st.sampled_from(["full", "s_only", "empty", "junk"]))
        if shape == "full":
            query = _query(oldest, newest, draw(st.integers(0, 1)), draw(st.sampled_from("dwm")))
        elif shape == "s_only":
            query = "s=AAPL"
        elif shape == "empty":
            query = "s=AAPL&a=&b=&c=&d=&e=&f=&g=&ignore=.csv"
        else:
            query = "s=AAPL&a={{x}}&b=1&c=2016&d=0&e=1&f=2016&g=d"
        path = draw(st.sampled_from(["/table.csv", "/table.csv", "/other.csv"]))
        body = ("Date,Close\n" + "".join(f"{day.isoformat()},1.5\n" for day in rows)).encode()
        stamp = f"{newest.year + 1}0101{number:06d}"
        digest = f"D{number}"
        entry = IndexEntry(
            host=host,
            kind=kind,
            requested_timestamp=stamp,
            served_timestamp=draw(st.sampled_from([stamp, None])),
            original=f"http://{host}{path}?{query}",
            mimetype="text/csv",
            statuscode="200" if kind == "data" else "404",
            digest=digest,
            length=str(len(body)),
            final_url=f"https://web.archive.org/web/{stamp}id_/http://{host}{path}?{query}",
            path=f"{host}/{stamp}-{digest}.csv",
            size=len(body),
            sha256=hashlib.sha256(body).hexdigest(),
            content_type="text/csv",
            digest_verified=draw(st.booleans()),
            fetched_at="2026-11-15T00:00:00Z",
        )
        key = f"{host}/{stamp}-{digest}"
        result[key] = Capture(key=key, entry=entry, body=body)
    return list(result.values())


def _index_bytes(items: list[Capture]) -> bytes:
    entries = {c.key: c.entry.model_dump(mode="json") for c in sorted(items, key=lambda c: c.key)}
    return json.dumps({"slug": SLUG, "entries": entries}).encode()


# Feature: autopsy, Property 2: Byte-identical contract
@settings(max_examples=100)
@given(data=st.data(), items=captures())
def test_byte_identical_contract(data: st.DataObject, items: list[Capture]) -> None:
    """**Validates: Requirements 7.4, 7.6**"""
    index_bytes = _index_bytes(items)
    permuted = data.draw(st.permutations(items))
    assert dump_contract(infer(SLUG, index_bytes, items)) == dump_contract(
        infer(SLUG, index_bytes, permuted)
    )


def test_dump_format_and_round_trip(tmp_path: Path) -> None:
    contract = infer(SLUG, b"{}", [])
    raw = dump_contract(contract)
    assert raw.endswith(b"}\n") and not raw.endswith(b"\n\n")
    assert b"\r" not in raw
    assert json.loads(raw) == json.loads(json.dumps(json.loads(raw), sort_keys=True))
    path = write_contract(contract, tmp_path)
    assert path == tmp_path / SLUG / "contract.json"
    assert path.read_bytes() == raw
    assert load_contract(path) == contract
    assert contract.months.indexing == "undetermined"
    assert contract.source.index_sha256 == hashlib.sha256(b"{}").hexdigest()
