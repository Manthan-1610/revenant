"""Reanimate_Prompt: the instruction Kiro follows to write `server.py` (Req 3.1, 5, 7.3)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from revenant.exhume.store import atomic_write
from revenant.reanimate.record import DonorEntry

PROMPT_NAME = "reanimate-prompt.md"

SERVER_RULES = (
    (
        "Route `GET /table.csv` whatever the Host header (Gen 1.1, 1.2, 1.3). Accept and ignore "
        "`ignore`, `j`, `q`, `x`, `y` and `z` (Gen 2.8, 2.9, 2.10, 2.12, 2.13, 2.14)."
    ),
    (
        "Load `donor/index.json`, the donor files it names and `error-404.html` relative to "
        "`Path(__file__).parent`, so responses are identical whatever directory the server starts "
        "from. Import only `fastapi`, `uvicorn` and the Python standard library. Make no outbound "
        "network request and read no file under `evidence/` (Gen 4.1, 6.1, 7.1)."
    ),
    (
        "Check `g` first: a non-empty `g` other than `d` (including `w`, `m`, `v`) answers status 404, "
        "`Content-Type: text/html`, the `error-404.html` body and an `X-Revenant-Note: interval <g> is "
        "not reanimated yet` header; these intervals are deferred (Gen 2.7)."
    ),
    (
        "Then, if `s` is absent, empty or has no entry in `donor/index.json`, answer status 404, "
        "`Content-Type: text/html` and the `error-404.html` body, with no CSV content. Query values "
        "arrive percent-decoded, so `s=^GSPC` and `s=%5EGSPC` select the same donor and give "
        "identical responses (Gen 2.11, 7.1)."
    ),
    (
        "Resolve the start date from `a`, `b`, `c` and the end date from `d`, `e`, `f`. If any one of "
        "the three is absent, empty or not `int()`-able (for example `c={{(-1 month).year}}`), the whole "
        "date is missing: use the earliest Row_Date of the donor for the start and the latest Row_Date "
        "for the end (Gen 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 5.1, 5.2)."
    ),
    (
        "Otherwise months are 0-indexed (`a=0` is January): `year = c + a // 12`, "
        "`month = a % 12 + 1`, so 12 rolls over to January of the next year and other out-of-range "
        "integers roll the same way (inferred); never reject an out-of-range integer. Clamp the day to "
        "`1..days_in_month` (inferred). A year outside 1..9999 counts as a missing date (inferred). "
        "Never raise an unhandled exception (Gen 3.1, 3.2)."
    ),
    (
        'Split the donor file bytes on `b"\\n"`. Keep the Data_Rows whose Row_Date lies in '
        "`[start, end]`, both inclusive, each copied byte for byte with no reformatting of any number "
        "(a zero Volume stays `000`), in the donor's order (newest first) (Gen 4.2, 4.4, 4.7)."
    ),
    (
        "Answer status 200, `Content-Type: text/csv`, with the body Header_Line "
        "`Date,Open,High,Low,Close,Volume,Adj Close` + `\\n` + each kept row + `\\n` (Gen 4.1, 4.2, 4.4)."
    ),
    (
        "If no Data_Row lies in the range (a start after the end included), answer status 404, "
        "`Content-Type: text/html` and the `error-404.html` body (Gen 7.1)."
    ),
    (
        "Every response, 404 included, carries exactly one `X-Revenant-Donor` header: "
        "`wayback:<host>/<served_timestamp>` taken from the `s` entry in `donor/index.json` (its "
        "`host` field, not the request's Host header), else `none` (Gen 6.1)."
    ),
)


def _donor_lines(donors: Iterable[DonorEntry]) -> list[str]:
    """One line per donor: symbol, relative file and covered dates, sorted by symbol."""
    lines = [
        f"- `{entry.symbol}`: `donor/{entry.file}`, {entry.rows} Data_Rows from "
        f"{entry.first_date} to {entry.last_date}, served by `{entry.host}` at "
        f"{entry.served_timestamp}"
        for entry in sorted(donors, key=lambda entry: entry.symbol)
    ]
    return lines or ["- (none)"]


def render_prompt(slug: str, donors: Iterable[DonorEntry]) -> str:
    """The Reanimate_Prompt text; it names files only by their Build_Workspace-relative names."""
    rules = [f"{number}. {rule}" for number, rule in enumerate(SERVER_RULES, start=1)]
    parts = [
        f"# Reanimate `{slug}`",
        "",
        (
            "Write a FastAPI server that answers as the dead API did. All files named here are in "
            "this directory; use only these relative names."
        ),
        "",
        "## Inputs (read only)",
        "",
        (
            '- `requirements.md`: the generated spec. Criteria cited below as "Gen x.y" are its '
            "acceptance criteria."
        ),
        "- `contract.json`: the inferred API contract.",
        (
            "- `donor/index.json`: the donor index, keyed by symbol. Each entry names its donor file "
            "under `donor/` and its `host` and `served_timestamp`."
        ),
        "- `error-404.html`: the archived 404 body, served as is for every 404.",
        "",
        "Donors available now:",
        "",
        *_donor_lines(donors),
        "",
        "## Output",
        "",
        (
            "Write exactly one file: `server.py` in this directory, exposing the FastAPI app as `app` "
            "(served by `uvicorn server:app`). Create, change or delete no other file."
        ),
        "",
        "## Tools",
        "",
        (
            "No shell or command tool is available. Do not run, test or install anything. Only read "
            "the inputs and write `server.py`."
        ),
        "",
        "## Server rules",
        "",
        *rules,
        "",
    ]
    return "\n".join(parts)


def write_prompt(slug_dir: Path, text: str) -> Path:
    """Write the Reanimate_Prompt to `<slug_dir>/reanimate-prompt.md`, replacing any earlier one."""
    path = slug_dir / PROMPT_NAME
    atomic_write(path, text.encode("utf-8"))
    return path
