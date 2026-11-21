"""Month_Detector: decides the month indexing of parameters `a` and `d` (Req 3.1 to 3.4)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

Indexing = Literal["0-indexed", "1-indexed", "undetermined"]

RANGE_PARAMS = ("a", "b", "c", "d", "e", "f")
MIN_DECISIVE = 3
MAX_KEYS = 3


@dataclass(frozen=True)
class MonthSample:
    """One `full_range` Data_Capture: its requested `a` to `f` and its Row_Date span."""

    key: str
    params: Mapping[str, str]
    oldest: date
    newest: date


@dataclass(frozen=True)
class Tally:
    """A count with up to 3 supporting Index keys in ascending order."""

    count: int
    keys: tuple[str, ...]


@dataclass(frozen=True)
class MonthResult:
    indexing: Indexing
    decisive_h0: Tally
    decisive_h1: Tally
    ambiguous: Tally
    unfit: Tally


def _int(value: str | None) -> int | None:
    if value is None or not value.isascii() or not value.isdigit():
        return None
    return int(value)


def _date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except (ValueError, OverflowError):
        return None


def fits(sample: MonthSample, h: int) -> bool:
    """True when the requested range under offset `h` is valid and holds every Row_Date."""
    values = [_int(sample.params.get(name)) for name in RANGE_PARAMS]
    if any(value is None for value in values):
        return False
    a, b, c, d, e, f = (value for value in values if value is not None)
    start = _date(c, a + 1 - h, b)
    end = _date(f, d + 1 - h, e)
    if start is None or end is None:
        return False
    return start <= sample.oldest <= sample.newest <= end


def _tally(keys: list[str]) -> Tally:
    return Tally(count=len(keys), keys=tuple(sorted(keys)[:MAX_KEYS]))


def detect(samples: Sequence[MonthSample]) -> MonthResult:
    """Classify each sample; only Decisive_Captures vote (Req 3.2, 3.3)."""
    h0: list[str] = []
    h1: list[str] = []
    ambiguous: list[str] = []
    unfit: list[str] = []
    for sample in samples:
        fit0, fit1 = fits(sample, 0), fits(sample, 1)
        if fit0 and fit1:
            ambiguous.append(sample.key)
        elif fit0:
            h0.append(sample.key)
        elif fit1:
            h1.append(sample.key)
        else:
            unfit.append(sample.key)
    indexing: Indexing = "undetermined"
    if len(h0) >= MIN_DECISIVE and not h1:
        indexing = "0-indexed"
    elif len(h1) >= MIN_DECISIVE and not h0:
        indexing = "1-indexed"
    return MonthResult(
        indexing=indexing,
        decisive_h0=_tally(h0),
        decisive_h1=_tally(h1),
        ambiguous=_tally(ambiguous),
        unfit=_tally(unfit),
    )
