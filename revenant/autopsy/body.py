"""Body_Parser and row helpers for Yahoo CSV bodies (Req 4.2, 4.3, 5.2 to 5.4, F12, F16, F23, F24)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Literal

from revenant.autopsy.evidence import AutopsyError

COMMENT_RE = re.compile(r"^<!--.*-->\s*$")
ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
SHORT_RE = re.compile(r"^(\d{1,2})-([A-Za-z]{3})-(\d{2})$")
NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
YAHOO_DECIMALS = 6  # F23
MIN_YAHOO_DECIMALS = 2
MAX_FIXED = 6
# Number_Hypothesis names in code-point order: `fixed0` to `fixed6`, then `yahoo`.
HYPOTHESES = tuple(sorted([f"fixed{n}" for n in range(MAX_FIXED + 1)] + ["yahoo"]))

ISO_FORMAT = "%Y-%m-%d"
SHORT_FORMAT = "%d-%b-%y"

# Fixed English month table: parsing never depends on the locale.
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")

RowOrder = Literal["descending", "ascending", "unordered"]


@dataclass(frozen=True)
class ParsedBody:
    """One body split into its Header_Line, Data_Rows and Comment_Lines."""

    header: str
    rows: tuple[str, ...]
    comments: tuple[str, ...]
    comments_after_last_row: int
    comments_before_last_row: int


def parse_body(body: bytes, path: str | Path) -> ParsedBody:
    """Strict UTF-8 decode, split at `\\n` only, classify lines after the Header_Line.

    With no Data_Row (a Header_Only_Body), every Comment_Line counts as after the last row.
    """
    try:
        text = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise AutopsyError(path, f"body is not valid UTF-8 (byte {exc.start})") from exc
    lines = text.split("\n")
    rows: list[str] = []
    comments: list[str] = []
    comment_positions: list[int] = []
    last_row = 0
    for position, line in enumerate(lines[1:], start=1):
        if COMMENT_RE.match(line):
            comments.append(line)
            comment_positions.append(position)
        elif line:
            rows.append(line)
            last_row = position
    after = sum(1 for position in comment_positions if position > last_row)
    return ParsedBody(
        header=lines[0],
        rows=tuple(rows),
        comments=tuple(comments),
        comments_after_last_row=after,
        comments_before_last_row=len(comment_positions) - after,
    )


def _valid_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_row_date(field: str, capture_year: int) -> tuple[date, str] | None:
    """The Row_Date and its format (`%Y-%m-%d` or `%d-%b-%y`), or None when neither parses.

    A two-digit year `yy` resolves to the latest year not after `capture_year`.
    """
    iso = ISO_RE.match(field)
    if iso:
        parsed = _valid_date(int(iso[1]), int(iso[2]), int(iso[3]))
        return (parsed, ISO_FORMAT) if parsed else None
    short = SHORT_RE.match(field)
    if short:
        name = short[2].lower()
        if name not in MONTHS:
            return None
        yy = int(short[3])
        year = capture_year - ((capture_year - yy) % 100)
        parsed = _valid_date(year, MONTHS.index(name) + 1, int(short[1]))
        return (parsed, SHORT_FORMAT) if parsed else None
    return None


def fixed(value: Decimal, n: int) -> str:
    """`value` with exactly `n` decimals (Decimal formatting, never float)."""
    return f"{value:.{n}f}"


def yahoo_number(value: Decimal) -> str:
    """Yahoo_Number (F23): 6 decimals, trailing zeros stripped, at least 2 decimals kept."""
    whole, fraction = fixed(value, YAHOO_DECIMALS).split(".")
    return f"{whole}.{fraction.rstrip('0').ljust(MIN_YAHOO_DECIMALS, '0')}"


@dataclass(frozen=True)
class NumberSupport:
    """Number_Hypothesis support over the values of some bodies (Req 5.4, F23, F24).

    `hypotheses` holds `(name, supported)` pairs sorted by name, like `NumberFormat`.
    """

    hypotheses: tuple[tuple[str, int], ...]
    total: int
    volume_zero_000: int
    volume_zero_other: int

    def __add__(self, other: NumberSupport) -> NumberSupport:
        mine, theirs = dict(self.hypotheses), dict(other.hypotheses)
        return NumberSupport(
            hypotheses=tuple(
                (name, mine.get(name, 0) + theirs.get(name, 0)) for name in HYPOTHESES
            ),
            total=self.total + other.total,
            volume_zero_000=self.volume_zero_000 + other.volume_zero_000,
            volume_zero_other=self.volume_zero_other + other.volume_zero_other,
        )


def _supporting(field: str) -> list[str]:
    """Names of the hypotheses that reproduce `field` exactly; none for a non-numeric field."""
    if not NUMBER_RE.match(field):
        return []
    value = Decimal(field)
    names = [f"fixed{n}" for n in range(MAX_FIXED + 1) if fixed(value, n) == field]
    if yahoo_number(value) == field:
        names.append("yahoo")
    return names


def number_support(header: str, rows: Sequence[str]) -> NumberSupport:
    """Per Number_Hypothesis, the values outside `Date` and `Volume` it reproduces exactly.

    Every such field counts in `total`; a non-numeric field (not `-?digits[.digits]`) is
    supported by no hypothesis. Zero Volume values are split into `000` and any other spelling.
    """
    columns = [name.strip() for name in header.split(",")]
    counts = dict.fromkeys(HYPOTHESES, 0)
    total = zero_000 = zero_other = 0
    for row in rows:
        for index, field in enumerate(row.split(",")):
            name = columns[index] if index < len(columns) else ""
            if name == "Volume":
                if NUMBER_RE.match(field) and Decimal(field) == 0:
                    if field == "000":
                        zero_000 += 1
                    else:
                        zero_other += 1
                continue
            if name == "Date":
                continue
            total += 1
            for hypothesis in _supporting(field):
                counts[hypothesis] += 1
    return NumberSupport(
        hypotheses=tuple((name, counts[name]) for name in HYPOTHESES),
        total=total,
        volume_zero_000=zero_000,
        volume_zero_other=zero_other,
    )


def row_order(dates: Sequence[date]) -> RowOrder:
    """`descending` or `ascending` when strictly monotonic, else `unordered`; needs >= 2 dates."""
    if len(dates) < 2:
        raise ValueError("row_order needs at least 2 dates")
    pairs = list(pairwise(dates))
    if all(later < earlier for earlier, later in pairs):
        return "descending"
    if all(later > earlier for earlier, later in pairs):
        return "ascending"
    return "unordered"
