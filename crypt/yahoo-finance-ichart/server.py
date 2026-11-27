import calendar
import json
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import Response

BASE = Path(__file__).parent
HEADER_LINE = b"Date,Open,High,Low,Close,Volume,Adj Close"

app = FastAPI()

_INDEX: dict = json.loads((BASE / "donor" / "index.json").read_text(encoding="utf-8")).get("entries", {})
_ERROR_404: bytes = (BASE / "error-404.html").read_bytes()
_DONORS: dict[str, list[tuple[date, bytes]]] = {}


def _parse_row_date(row: bytes) -> date | None:
    try:
        text = row[:10].decode("ascii")
        return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    except (ValueError, UnicodeDecodeError):
        return None


def _load(symbol: str) -> list[tuple[date, bytes]]:
    rows = _DONORS.get(symbol)
    if rows is None:
        data = (BASE / "donor" / _INDEX[symbol]["file"]).read_bytes()
        rows = []
        for line in data.split(b"\n")[1:]:
            if not line.strip():
                continue
            d = _parse_row_date(line)
            if d is not None:
                rows.append((d, line))
        _DONORS[symbol] = rows
    return rows


def _resolve_date(params, names: tuple[str, str, str]) -> date | None:
    try:
        month = int(params.get(names[0], ""))
        day = int(params.get(names[1], ""))
        year = int(params.get(names[2], ""))
        year += month // 12
        month = month % 12 + 1
        if not 1 <= year <= 9999:
            return None
        day = max(1, min(day, calendar.monthrange(year, month)[1]))
        return date(year, month, day)
    except (ValueError, TypeError, OverflowError):
        return None


def _donor_header(symbol: str | None) -> str:
    if symbol is None:
        return "none"
    entry = _INDEX[symbol]
    return f"wayback:{entry['host']}/{entry['served_timestamp']}"


def _not_found(symbol: str | None, extra: dict[str, str] | None = None) -> Response:
    headers = {"X-Revenant-Donor": _donor_header(symbol)}
    if extra:
        headers.update(extra)
    return Response(content=_ERROR_404, status_code=404, media_type="text/html", headers=headers)


@app.get("/table.csv")
def table_csv(request: Request) -> Response:
    params = request.query_params
    s = params.get("s", "")
    symbol = s if s in _INDEX else None

    g = params.get("g", "")
    if g != "" and g != "d":
        return _not_found(symbol, {"X-Revenant-Note": f"interval {g} is not reanimated yet"})

    if symbol is None:
        return _not_found(None)

    rows = _load(symbol)
    if not rows:
        return _not_found(symbol)

    start = _resolve_date(params, ("a", "b", "c"))
    end = _resolve_date(params, ("d", "e", "f"))
    if start is None:
        start = min(d for d, _ in rows)
    if end is None:
        end = max(d for d, _ in rows)

    kept = [line for d, line in rows if start <= d <= end]
    if not kept:
        return _not_found(symbol)

    body = HEADER_LINE + b"\n" + b"".join(line + b"\n" for line in kept)
    return Response(
        content=body,
        status_code=200,
        media_type="text/csv",
        headers={"X-Revenant-Donor": _donor_header(symbol)},
    )
