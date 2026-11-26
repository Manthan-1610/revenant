"""Misbehaving Revenant_Server fixture: passes the demo and unknown-symbol Checks, but answers
`g=w` with a 404 that carries no `X-Revenant-Note`, so the weekly Check fails (Req 6.4, 6.6).

Imports only fastapi and the standard library and reads files next to itself, so it passes the audit.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import Response

HERE = Path(__file__).resolve().parent
HEADER_LINE = b"Date,Open,High,Low,Close,Volume,Adj Close"
INDEX = json.loads((HERE / "donor" / "index.json").read_text(encoding="utf-8"))["entries"]
ERROR_PAGE = (HERE / "error-404.html").read_bytes()

app = FastAPI()


def _date(month: str, day: str, year: str) -> dt.date:
    return dt.date(int(year), int(month) + 1, int(day))


@app.get("/table.csv")
def table(request: Request) -> Response:
    q = request.query_params
    entry = INDEX.get(q.get("s", ""))
    donor = f"wayback:{entry['host']}/{entry['served_timestamp']}" if entry else "none"
    headers = {"X-Revenant-Donor": donor}
    if q.get("g", "d") != "d" or entry is None:  # the bug: no X-Revenant-Note for other intervals
        return Response(ERROR_PAGE, status_code=404, media_type="text/html", headers=headers)
    start = _date(q["a"], q["b"], q["c"])
    end = _date(q["d"], q["e"], q["f"])
    lines = (HERE / "donor" / entry["file"]).read_bytes().split(b"\n")[1:]
    kept = [
        line for line in lines if line and start <= dt.date.fromisoformat(line[:10].decode()) <= end
    ]
    body = HEADER_LINE + b"\n" + b"".join(line + b"\n" for line in kept)
    return Response(body, media_type="text/csv", headers=headers)
