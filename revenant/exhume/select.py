"""Deterministic sampling of a Host's Candidates across (Interval, Parameter shape) Groups."""

from __future__ import annotations

import html
from collections.abc import Sequence
from urllib.parse import parse_qsl, urlsplit

from revenant.exhume.models import CdxRow, Shape

RANGE_NAMES = ("a", "b", "c", "d", "e", "f", "g")
NUMERIC_NAMES = ("a", "b", "c", "d", "e", "f")

GroupKey = tuple[str, Shape]


def parse_query(original: str) -> list[tuple[str, str]]:
    """Decoded name-value pairs of `original`'s query; [] when unparseable (Req 4.1, F15).

    The query is HTML-unescaped first, so `s=DISH&amp` gives `s=DISH` and `&amp;g=d` gives `g=d`.
    Fetching always uses `original` unchanged.
    """
    try:
        query = urlsplit(original).query
        return parse_qsl(html.unescape(query), keep_blank_values=True)
    except ValueError:
        return []


def _first(pairs: list[tuple[str, str]], name: str) -> str | None:
    for key, value in pairs:
        if key == name:
            return value
    return None


def parameter_shape(pairs: list[tuple[str, str]]) -> Shape:
    """`s_only`, `empty_range`, `full_range` or `other`; never raises (F17)."""
    names = {key for key, _ in pairs}
    if "s" in names and not names & set(RANGE_NAMES) and names <= {"s", "ignore"}:
        return "s_only"
    if not set(RANGE_NAMES) <= names:
        return "other"
    values = {name: _first(pairs, name) or "" for name in RANGE_NAMES}
    if all(value == "" for value in values.values()):
        return "empty_range"
    # F17: template junk such as `c={{(-1 month).year}}` must fall through to `other`.
    numeric = all(values[name].isascii() and values[name].isdigit() for name in NUMERIC_NAMES)
    if numeric and values["g"] != "":
        return "full_range"
    return "other"


def interval(pairs: list[tuple[str, str]]) -> str:
    """The first `g` value, case preserved, or `none` when absent or empty."""
    value = _first(pairs, "g")
    return value if value else "none"


def _sort_key(row: CdxRow) -> tuple[str, str]:
    return (row.timestamp, row.digest)


def _group_key(row: CdxRow) -> GroupKey:
    pairs = parse_query(row.original)
    return (interval(pairs), parameter_shape(pairs))


def _dedup_key(row: CdxRow) -> tuple[str, ...]:
    """Earliest timestamp wins; ties break on the remaining fields so input order never matters."""
    return (row.timestamp, row.original, row.mimetype, row.statuscode, row.length)


def _dedup(candidates: Sequence[CdxRow]) -> list[CdxRow]:
    """One row per digest, earliest timestamp wins; independent of input order."""
    best: dict[str, CdxRow] = {}
    for row in candidates:
        kept = best.get(row.digest)
        if kept is None or _dedup_key(row) < _dedup_key(kept):
            best[row.digest] = row
    return list(best.values())


def _groups(rows: Sequence[CdxRow]) -> list[list[CdxRow]]:
    """Groups in sorted (Interval, Parameter shape) order, members in (timestamp, digest) order."""
    grouped: dict[GroupKey, list[CdxRow]] = {}
    for row in rows:
        grouped.setdefault(_group_key(row), []).append(row)
    return [sorted(grouped[key], key=_sort_key) for key in sorted(grouped)]


def select(candidates: Sequence[CdxRow], n: int) -> list[CdxRow]:
    """At most `n` Candidates spread over Groups, deterministically (Req 4.2 to 4.5)."""
    groups = _groups(_dedup(candidates))
    picks = [0] * len(groups)
    allocated = 0
    while allocated < n:
        progressed = False
        for g, members in enumerate(groups):
            if allocated >= n:
                break
            if picks[g] < len(members):
                picks[g] += 1
                allocated += 1
                progressed = True
        if not progressed:
            break
    selected: list[CdxRow] = []
    for members, k in zip(groups, picks, strict=True):
        m = len(members)
        selected.extend(members[i * m // k] for i in range(k))
    return selected


def backfill_order(candidates: Sequence[CdxRow], selected: Sequence[CdxRow]) -> list[CdxRow]:
    """Unselected Candidates round-robin over sorted Groups, each in (timestamp, digest) order."""
    taken = {row.digest for row in selected}
    rows = [row for row in _dedup(candidates) if row.digest not in taken]
    queues = _groups(rows)
    order: list[CdxRow] = []
    depth = 0
    while True:
        layer = [members[depth] for members in queues if depth < len(members)]
        if not layer:
            return order
        order.extend(layer)
        depth += 1
