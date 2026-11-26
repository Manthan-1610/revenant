import calendar
import json
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import Response

BASE = Path(__file__).parent
HEADER_LINE = b"Date,Open,High,Low,Close,Volume,Adj Close"

app = FastAPI()

_index = json.loads((BASE / "donor" / "index.json").read_text(encoding="utf-8"))
_entries = _index.get("entries", _index)
_404_BODY = (BASE / "error-404.html").read_bytes()

_donors = {}
for _sym, _entry in _entries.items():
    _raw = (BASE / "donor" / _entry["file"]).read_bytes()
    _rows = []
    for _line in _raw.split(b"\n"):
        _field = _line.split(b",", 1)[0].strip()
        try:
            _d = date.fromisoformat(_field.decode("ascii"))
        except Exception:
            continue
        _rows.append((_d, _line))
    _donors[_sym] = _rows


def _donor_header(symbol: Optional[str]) -> str:
    entry = _entries.get(symbol) if symbol else None
    if entry is None:
        return "none"
    return "wayback:%s/%s" % (entry["host"], entry["served_timestamp"])


def _not_found(symbol: Optional[str], note: Optional[str] = None) -> Response:
    headers = {
        "X-Revenant-Donor": _donor_header(symbol),
        "Content-Type": "text/html",
    }
    if note:
        headers["X-Revenant-Note"] = note
    return Response(content=_404_BODY, status_code=404, headers=headers)


def _to_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _resolve(params, month_key, day_key, year_key) -> Optional[date]:
    m = _to_int(params.get(month_key))
    d = _to_int(params.get(day_key))
    y = _to_int(params.get(year_key))
    if m is None or d is None or y is None:
        return None
    year = y + m // 12
    month = m % 12 + 1
    if year < 1 or year > 9999:
        return None
    dim = calendar.monthrange(year, month)[1]
    day = min(max(d, 1), dim)
    return date(year, month, day)


@app.get("/table.csv")
async def table_csv(request: Request):
    params = request.query_params
    g = params.get("g")
    s = params.get("s")

    if g:
        if g != "d":
            return _not_found(
                s if s in _entries else None,
                "interval %s is not reanimated yet" % g,
            )

    if not s or s not in _entries:
        return _not_found(None)

    rows = _donors[s]
    if not rows:
        return _not_found(s)

    dates = [r[0] for r in rows]
    start = _resolve(params, "a", "b", "c") or min(dates)
    end = _resolve(params, "d", "e", "f") or max(dates)

    kept = [line for d, line in rows if start <= d <= end]
    if not kept:
        return _not_found(s)

    body = HEADER_LINE + b"\n" + b"\n".join(kept) + b"\n"
    return Response(
        content=body,
        status_code=200,
        headers={
            "X-Revenant-Donor": _donor_header(s),
            "Content-Type": "text/csv",
        },
    )
