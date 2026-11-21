"""Contract_Inferrer: derives Contract facts from loaded evidence (Req 1.4, 2.2, 3.1, 7.5).

Pure: no time, path, locale or environment value enters the Contract, and no set or dict is
iterated without sorting first.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from urllib.parse import urlsplit

from revenant.autopsy.body import parse_body, parse_row_date
from revenant.autopsy.contract import Contract, Endpoint, Evidence, HostEvidence, Months, Source
from revenant.autopsy.evidence import Capture, capture_year
from revenant.autopsy.months import RANGE_PARAMS, MonthSample, Tally, detect
from revenant.autopsy.normalize import normalize_query
from revenant.exhume.select import parameter_shape

MAX_KEYS = 3


def _evidence(keys: Iterable[str]) -> Evidence:
    ordered = sorted(keys)
    return Evidence(count=len(ordered), keys=ordered[:MAX_KEYS])


def _from_tally(tally: Tally) -> Evidence:
    return Evidence(count=tally.count, keys=list(tally.keys))


def _first_values(pairs: Sequence[tuple[str, str]]) -> dict[str, str]:
    first: dict[str, str] = {}
    for name, value in pairs:
        first.setdefault(name, value)
    return first


def _source(index_bytes: bytes, captures: Sequence[Capture]) -> Source:
    return Source(index_sha256=hashlib.sha256(index_bytes).hexdigest(), entry_count=len(captures))


def _endpoints(data: Sequence[Capture]) -> list[Endpoint]:
    """Req 2.2: each URL path of `original` with its hosts and per-(host, path) Evidence."""
    by_path: dict[str, dict[str, list[str]]] = {}
    for capture in data:
        try:
            path = urlsplit(capture.entry.original).path
        except ValueError:
            path = ""
        by_path.setdefault(path, {}).setdefault(capture.entry.host, []).append(capture.key)
    return [
        Endpoint(
            path=path,
            hosts=[
                HostEvidence(host=host, evidence=_evidence(by_path[path][host]))
                for host in sorted(by_path[path])
            ],
        )
        for path in sorted(by_path)
    ]


def _month_sample(capture: Capture) -> MonthSample | None:
    """Req 3.1: a `full_range` Data_Capture with >= 1 Data_Row whose Row_Dates all parse."""
    pairs = normalize_query(capture.entry.original)
    if parameter_shape(pairs) != "full_range":
        return None
    parsed = parse_body(capture.body, capture.entry.path)
    if not parsed.rows:
        return None
    year = capture_year(capture.entry)
    dates = []
    for row in parsed.rows:
        result = parse_row_date(row.split(",", 1)[0], year)
        if result is None:
            return None
        dates.append(result[0])
    first = _first_values(pairs)
    params = {name: first[name] for name in RANGE_PARAMS if name in first}
    return MonthSample(key=capture.key, params=params, oldest=min(dates), newest=max(dates))


def _months(data: Sequence[Capture]) -> Months:
    samples = [sample for capture in data if (sample := _month_sample(capture)) is not None]
    result = detect(samples)
    return Months(
        indexing=result.indexing,
        decisive_h0=_from_tally(result.decisive_h0),
        decisive_h1=_from_tally(result.decisive_h1),
        ambiguous=_from_tally(result.ambiguous),
        unfit=_from_tally(result.unfit),
    )


def infer(slug: str, index_bytes: bytes, captures: Sequence[Capture]) -> Contract:
    """Build the Contract; captures are re-sorted by key, `error_page` entries are ignored."""
    ordered = sorted(captures, key=lambda capture: capture.key)
    data = [capture for capture in ordered if capture.entry.kind == "data"]
    # Every Data_Capture body must be UTF-8 (Req 4.3), even those outside the month check.
    for capture in data:
        parse_body(capture.body, capture.entry.path)
    return Contract(
        slug=slug,
        source=_source(index_bytes, ordered),
        endpoints=_endpoints(data),
        months=_months(data),
    )
