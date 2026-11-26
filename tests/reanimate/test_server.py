"""Property tests for the Revenant_Server (`crypt/<slug>/server.py`), Req 5.

The server under test is the built `crypt/yahoo-finance-ichart/server.py`; before the slice build
exists the hand-written `tests/reanimate/fixtures/server.py` stands in. Each example copies it into a
fresh directory beside a generated `donor/` and `error-404.html`, imports it with `importlib` and
drives it with `fastapi.testclient.TestClient`.
"""

from __future__ import annotations

import calendar
import datetime as dt
import importlib.util
import shutil
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from revenant.reanimate.donor import HEADER_LINE, donor_file_name
from revenant.reanimate.record import DonorEntry, DonorIndex, dump_model

REPO = Path(__file__).resolve().parents[2]
BUILT_SERVER = REPO / "crypt" / "yahoo-finance-ichart" / "server.py"
FIXTURE_SERVER = Path(__file__).resolve().parent / "fixtures" / "server.py"
SLUG = "yahoo-finance-ichart"
ERROR_PAGE = b"<html><head><title>404 Not Found</title></head><body>gone</body></html>\n"
HOSTS = {"AAPL": "ichart.yahoo.com", "^GSPC": "ichart.finance.yahoo.com"}
SERVED = {"AAPL": "20160109031500", "^GSPC": "20160110120000"}
JUNK = ["{{(-1 month).year}}", "abc", "1.5", "x1"]


def server_source() -> Path:
    """The built server when it exists, else the hand-written fixture."""
    return BUILT_SERVER if BUILT_SERVER.is_file() else FIXTURE_SERVER


def write_server_dir(directory: Path, donors: dict[str, bytes]) -> DonorIndex:
    """Copy the server into `directory` beside `donor/` (one body per symbol) and `error-404.html`."""
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(server_source(), directory / "server.py")
    (directory / "error-404.html").write_bytes(ERROR_PAGE)
    donor_dir = directory / "donor"
    donor_dir.mkdir(exist_ok=True)
    entries: dict[str, DonorEntry] = {}
    for symbol, body in donors.items():
        name = donor_file_name(symbol)
        (donor_dir / name).write_bytes(body)
        dates = [line.split(b",", 1)[0].decode() for line in body.split(b"\n")[1:] if line]
        host = HOSTS.get(symbol, "ichart.yahoo.com")
        served = SERVED.get(symbol, "20160109000000")
        entries[symbol] = DonorEntry(
            symbol=symbol,
            file=name,
            source_url=f"https://web.archive.org/web/{served}id_/http://{host}/table.csv?s={symbol}",
            host=host,
            served_timestamp=served,
            sha256="0" * 64,
            rows=len(dates),
            first_date=min(dates),
            last_date=max(dates),
        )
    index = DonorIndex(slug=SLUG, entries=entries)
    (donor_dir / "index.json").write_bytes(dump_model(index))
    return index


@contextmanager
def server_client(directory: Path) -> Iterator[TestClient]:
    """Import `directory/server.py` under a unique module name and yield a TestClient for its app."""
    name = f"revenant_server_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, directory / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        with TestClient(module.app) as client:
            yield client
    finally:
        sys.modules.pop(name, None)


def donor_header(index: DonorIndex, symbol: str | None) -> str:
    """The X-Revenant-Donor value Req 5.6 requires for `symbol`."""
    entry = index.entries.get(symbol) if symbol else None
    return f"wayback:{entry.host}/{entry.served_timestamp}" if entry else "none"


# --- generators -------------------------------------------------------------------------------

yahoo_number = st.one_of(
    st.integers(0, 999).map(str),
    st.decimals(0, 999, places=2, allow_nan=False, allow_infinity=False).map(str),
    st.decimals(0, 999, places=6, allow_nan=False, allow_infinity=False).map(str),
)
volume = st.one_of(st.just("000"), st.integers(1, 10**9).map(str))


@st.composite
def donor_body(draw: st.DrawFn) -> tuple[bytes, list[tuple[dt.date, bytes]]]:
    """A newest-first donor body over random weekdays, with its (Row_Date, line) rows."""
    base = dt.date(2015, 11, 1)
    offsets = draw(st.sets(st.integers(0, 150), min_size=1, max_size=25))
    days = sorted(
        (d for d in (base + dt.timedelta(o) for o in offsets) if d.weekday() < 5), reverse=True
    )
    if not days:
        days = [dt.date(2016, 1, 4)]
    rows = []
    for day in days:
        o, h, lo, c, adj = (draw(yahoo_number) for _ in range(5))
        line = f"{day.isoformat()},{o},{h},{lo},{c},{draw(volume)},{adj}".encode()
        rows.append((day, line))
    body = HEADER_LINE + b"\n" + b"".join(line + b"\n" for _, line in rows)
    return body, rows


# A date part: absent (None), empty, junk or an int string (in range, 12, out of range, day 31).
month_part = st.one_of(
    st.none(), st.just(""), st.sampled_from(JUNK), st.integers(-14, 26).map(str), st.just("12")
)
day_part = st.one_of(
    st.none(), st.just(""), st.sampled_from(JUNK), st.integers(-2, 40).map(str), st.just("31")
)
year_part = st.one_of(
    st.none(),
    st.just(""),
    st.sampled_from(JUNK),
    st.integers(2014, 2017).map(str),
    st.integers(-5, 12000).map(str),
)
symbol_choice = st.sampled_from(["AAPL", "^GSPC", "^GSPC", "MSFT", "", None])


@st.composite
def daily_request(draw: st.DrawFn) -> tuple[str | None, dict[str, str | None], str | None, bool]:
    """(s, a..f parts, g, percent-encode s?) for a Daily_Request."""
    parts = {
        "a": draw(month_part),
        "b": draw(day_part),
        "c": draw(year_part),
        "d": draw(month_part),
        "e": draw(day_part),
        "f": draw(year_part),
    }
    return draw(symbol_choice), parts, draw(st.sampled_from(["d", "", None])), draw(st.booleans())


def build_query(
    symbol: str | None, parts: dict[str, str | None], g: str | None, encode: bool
) -> str:
    pairs: list[str] = []
    if symbol is not None:
        pairs.append("s=" + (quote(symbol, safe="") if encode else symbol))
    for key, value in parts.items():
        if value is not None:
            pairs.append(f"{key}={quote(value, safe='')}")
    if g is not None:
        pairs.append(f"g={g}")
    pairs.append("ignore=.csv")
    return "/table.csv?" + "&".join(pairs)


# --- reference selector (design Server rules 2-4) ---------------------------------------------


def resolve(month: str | None, day: str | None, year: str | None) -> dt.date | None:
    """A date from 0-indexed month, day, year; None when any part is absent, empty or not an int."""
    try:
        m, d, y = int(month), int(day), int(year)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    year_n = y + m // 12
    month_n = m % 12 + 1
    if not 1 <= year_n <= 9999:
        return None
    last = calendar.monthrange(year_n, month_n)[1]
    return dt.date(year_n, month_n, max(1, min(d, last)))


def expected_rows(rows: list[tuple[dt.date, bytes]], parts: dict[str, str | None]) -> list[bytes]:
    """The donor lines a Daily_Request selects, in donor (newest-first) order."""
    dates = [day for day, _ in rows]
    start = resolve(parts["a"], parts["b"], parts["c"]) or min(dates)
    end = resolve(parts["d"], parts["e"], parts["f"]) or max(dates)
    return [line for day, line in rows if start <= day <= end]


# --- Property 5 -------------------------------------------------------------------------------


# Feature: reanimate, Property 5: Served rows equal donor lines in range
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(aapl=donor_body(), gspc=donor_body(), req=daily_request())
def test_served_rows_equal_donor_lines_in_range(
    tmp_path_factory: pytest.TempPathFactory,
    aapl: tuple[bytes, list[tuple[dt.date, bytes]]],
    gspc: tuple[bytes, list[tuple[dt.date, bytes]]],
    req: tuple[str | None, dict[str, str | None], str | None, bool],
) -> None:
    """**Validates: Requirements 5.1, 5.2, 5.3, 5.4**"""
    symbol, parts, g, encode = req
    donors = {"AAPL": aapl, "^GSPC": gspc}
    directory = tmp_path_factory.mktemp("server")
    write_server_dir(directory, {sym: body for sym, (body, _) in donors.items()})

    with server_client(directory) as client:
        response = client.get(build_query(symbol, parts, g, encode))

    selected = expected_rows(donors[symbol][1], parts) if symbol in donors else []
    if selected:
        assert response.status_code == 200
        assert response.headers["content-type"].split(";")[0].strip() == "text/csv"
        assert response.content == HEADER_LINE + b"\n" + b"".join(r + b"\n" for r in selected)
    else:
        assert response.status_code == 404
        assert response.headers["content-type"].split(";")[0].strip() == "text/html"
        assert response.content == ERROR_PAGE


# --- Property 6 -------------------------------------------------------------------------------

# A non-empty interval other than `d`: the deferred ones plus arbitrary printable ASCII strings.
other_interval = st.one_of(
    st.sampled_from(["w", "m", "v"]),
    st.text(alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E), min_size=1).filter(
        lambda g: g != "d"
    ),
)
any_symbol = st.one_of(symbol_choice, st.from_regex(r"[A-Z^.]{1,6}", fullmatch=True))


# Feature: reanimate, Property 6: Donor header and interval gate
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    aapl=donor_body(),
    gspc=donor_body(),
    req=daily_request(),
    symbol=any_symbol,
    gate=st.booleans(),
    interval=other_interval,
)
def test_donor_header_and_interval_gate(
    tmp_path_factory: pytest.TempPathFactory,
    aapl: tuple[bytes, list[tuple[dt.date, bytes]]],
    gspc: tuple[bytes, list[tuple[dt.date, bytes]]],
    req: tuple[str | None, dict[str, str | None], str | None, bool],
    symbol: str | None,
    gate: bool,
    interval: str,
) -> None:
    """**Validates: Requirements 5.5, 5.6**"""
    _, parts, daily_g, encode = req
    g = quote(interval, safe="") if gate else daily_g
    directory = tmp_path_factory.mktemp("server")
    index = write_server_dir(directory, {"AAPL": aapl[0], "^GSPC": gspc[0]})

    with server_client(directory) as client:
        response = client.get(build_query(symbol, parts, g, encode))

    assert response.headers.get_list("x-revenant-donor") == [donor_header(index, symbol)]
    if gate:
        assert response.status_code == 404
        assert response.headers["content-type"].split(";")[0].strip() == "text/html"
        assert response.content == ERROR_PAGE
        assert response.headers.get("x-revenant-note", "").strip()
