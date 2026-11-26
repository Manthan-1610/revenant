"""Hand-written Revenant_Server fixture that follows the Reanimate Server rules (Req 5, 7.3).

The stub kiro-cli copies it into the Build_Workspace, so Runner tests never depend on Kiro.
Imports only fastapi and the standard library; reads files relative to this file only.
"""

from __future__ import annotations

import calendar
import datetime as dt
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import Response

HERE = Path(__file__).resolve().parent
HEADER_LINE = b"Date,Open,High,Low,Close,Volume,Adj Close"

INDEX = json.loads((HERE / "donor" / "index.json").read_text(encoding="utf-8"))
ERROR_PAGE = (HERE / "error-404.html").read_bytes()


def _row_date(line: bytes) -> dt.date | None:
    head = line.split(b",", 1)[0]
    try:
        return dt.date.fromisoformat(head.decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        return None


def _load_rows(file_name: str) -> list[tuple[dt.date, bytes]]:
    lines = (HERE / "donor" / file_name).read_bytes().split(b"\n")[1:]
    rows = []
    for line in lines:
        date = _row_date(line)
        if date is not None:
            rows.append((date, line))
    return rows


DONORS = {
    symbol: (f"wayback:{entry['host']}/{entry['served_timestamp']}", _load_rows(entry["file"]))
    for symbol, entry in INDEX.get("entries", {}).items()
}

app = FastAPI()


def _resolve(month: str | None, day: str | None, year: str | None) -> dt.date | None:
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


def _not_found(donor: str, note: str | None = None) -> Response:
    headers = {"X-Revenant-Donor": donor}
    if note:
        headers["X-Revenant-Note"] = note
    return Response(ERROR_PAGE, status_code=404, media_type="text/html", headers=headers)


def _first(request: Request, name: str) -> str | None:
    values = request.query_params.getlist(name)
    return values[0] if values else None


@app.get("/table.csv")
def table(request: Request) -> Response:
    symbol = _first(request, "s")
    found = DONORS.get(symbol) if symbol else None
    donor = found[0] if found else "none"
    interval = _first(request, "g")
    if interval and interval != "d":
        return _not_found(donor, f"interval {interval} is not reanimated yet")
    if found is None:
        return _not_found(donor)
    rows = found[1]
    if not rows:
        return _not_found(donor)
    dates = [date for date, _ in rows]
    start = _resolve(_first(request, "a"), _first(request, "b"), _first(request, "c"))
    end = _resolve(_first(request, "d"), _first(request, "e"), _first(request, "f"))
    start = start or min(dates)
    end = end or max(dates)
    kept = [line for date, line in rows if start <= date <= end]
    if not kept:
        return _not_found(donor)
    body = HEADER_LINE + b"\n" + b"".join(line + b"\n" for line in kept)
    return Response(
        body, status_code=200, media_type="text/csv", headers={"X-Revenant-Donor": donor}
    )
