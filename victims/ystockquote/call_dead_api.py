"""Run an untouched 2013 Yahoo Finance client and record whether it lives or dies.

ystockquote 0.2.4 (PyPI, Aug 2013, LGPLv2+) gets price history from
http://ichart.yahoo.com/table.csv, an API Yahoo shut down in 2017.

This script does not modify the library. It:
  1. checks that the installed ystockquote.py matches the published 0.2.4 source (SHA-256),
  2. watches outbound URLs through Python's built-in `urllib.Request` audit event,
  3. calls the library exactly as a 2013 user would, and
  4. writes a timestamped evidence log (DEAD or ALIVE) to ./evidence/.

Run it before Revenant to show the death. Run it again with HTTP_PROXY pointing at the
Haunt proxy to show the resurrection.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import platform
import sys
import traceback

import ystockquote

# SHA-256 of ystockquote.py inside the original ystockquote-0.2.4.tar.gz from PyPI.
PUBLISHED_SHA256 = "32bbd7962549dd1be83b86359aa686d5949055bce3243dd2d7d9dd7224bd19f2"

SYMBOL, START, END = "AAPL", "2016-01-04", "2016-01-08"
EVIDENCE_DIR = pathlib.Path(__file__).resolve().parent / "evidence"

seen_urls: list[str] = []


def _audit(event: str, args: tuple) -> None:
    # Fired by urllib.request.urlopen with (url, data, headers, method).
    if event == "urllib.Request":
        seen_urls.append(str(args[0]))


def main() -> int:
    sys.addaudithook(_audit)

    src = pathlib.Path(ystockquote.__file__)
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    now = dt.datetime.now(dt.timezone.utc)

    record: dict = {
        "ran_at_utc": now.isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "library": "ystockquote 0.2.4",
        "library_sha256": sha,
        "library_unmodified": sha == PUBLISHED_SHA256,
        "http_proxy": proxy,
        "call": f"ystockquote.get_historical_prices({SYMBOL!r}, {START!r}, {END!r})",
    }

    try:
        prices = ystockquote.get_historical_prices(SYMBOL, START, END)
        record["status"] = "ALIVE"
        record["rows"] = len(prices)
        record["sample"] = dict(sorted(prices.items())[:2])
    except Exception as exc:  # noqa: BLE001 - we want to record any failure
        record["status"] = "DEAD"
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["traceback"] = traceback.format_exc()

    record["urls_called"] = seen_urls

    EVIDENCE_DIR.mkdir(exist_ok=True)
    out = EVIDENCE_DIR / f"{now:%Y-%m-%dT%H%M%SZ}-{record['status'].lower()}.json"
    out.write_text(json.dumps(record, indent=2), encoding="utf-8")

    print(f"[{record['status']}] {record['call']}")
    for url in seen_urls:
        print(f"  called: {url}")
    if record["status"] == "DEAD":
        print(f"  error:  {record['error']}")
    else:
        print(f"  rows:   {record['rows']}")
    print(f"  library unmodified (sha256 matches PyPI 0.2.4): {record['library_unmodified']}")
    print(f"  evidence: {out.relative_to(pathlib.Path.cwd()) if out.is_relative_to(pathlib.Path.cwd()) else out}")
    return 0 if record["status"] == "ALIVE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
