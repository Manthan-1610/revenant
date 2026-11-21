"""Contract_Inferrer: derives Contract facts from loaded evidence (Req 1.4, 2.2, 3.1, 7.5).

Pure: no time, path, locale or environment value enters the Contract, and no set or dict is
iterated without sorting first.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from urllib.parse import urlsplit

from revenant.autopsy.body import parse_body, parse_row_date
from revenant.autopsy.contract import (
    Contract,
    Endpoint,
    EnumType,
    Evidence,
    HostEvidence,
    IntType,
    Months,
    NameEvidence,
    Parameter,
    Source,
    StringType,
    ValueCount,
)
from revenant.autopsy.evidence import Capture, capture_year
from revenant.autopsy.months import RANGE_PARAMS, MonthSample, Tally, detect
from revenant.autopsy.normalize import normalize_query
from revenant.exhume.select import parameter_shape

MAX_KEYS = 3
MAX_EXAMPLES = 5
MAX_ENUM = 10
JUNK_MARKERS = ("{{", "}}", "{%")
DOCUMENTED_PARAMS = frozenset({"s", "a", "b", "c", "d", "e", "f", "g", "ignore"})


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


def _is_junk(name: str, value: str) -> bool:
    """Template_Junk: template markers (F17), or a non-digit `a` to `f` value such as `f6j1`."""
    if any(marker in value for marker in JUNK_MARKERS):
        return True
    return name in RANGE_PARAMS and value != "" and not (value.isascii() and value.isdigit())


def _param_type(counts: dict[str, int]) -> IntType | EnumType | StringType:
    """Req 2.4 over the non-empty, non-junk values and their counts."""
    values = sorted(counts)
    if values and all(value.isascii() and value.isdigit() for value in values):
        numbers = [int(value) for value in values]
        return IntType(min=min(numbers), max=max(numbers))
    if len(values) <= MAX_ENUM:
        return EnumType(values=[ValueCount(value=value, count=counts[value]) for value in values])
    return StringType(distinct=len(values))


def _parameters(data: Sequence[Capture]) -> tuple[list[Parameter], Evidence]:
    """Req 2.3 to 2.5: per name (first value per capture), plus the `amp` Evidence."""
    firsts = [
        (capture.key, _first_values(normalize_query(capture.entry.original))) for capture in data
    ]
    names = sorted({name for _, first in firsts for name in first} - {"amp"})
    parameters = []
    for name in names:
        present = [(key, first[name]) for key, first in firsts if name in first]
        empty = sum(1 for _, value in present if value == "")
        junk = sum(1 for _, value in present if _is_junk(name, value))
        counts: dict[str, int] = {}
        for _, value in present:
            if value and not _is_junk(name, value):
                counts[value] = counts.get(value, 0) + 1
        by_frequency = sorted(counts, key=lambda value: (-counts[value], value))
        parameters.append(
            Parameter(
                name=name,
                documented=name in DOCUMENTED_PARAMS,
                present=_evidence(key for key, _ in present),
                empty=empty,
                junk=junk,
                required=len(present) == len(data) and empty == 0,
                examples=by_frequency[:MAX_EXAMPLES],
                type=_param_type(counts),
            )
        )
    amp = _evidence(key for key, first in firsts if "amp" in first)
    return parameters, amp


def _content_types(data: Sequence[Capture]) -> list[NameEvidence]:
    """Req 4.1: lowercased media type before any `;` of `content_type`, else `mimetype`."""
    by_type: dict[str, list[str]] = {}
    for capture in data:
        raw = capture.entry.content_type or capture.entry.mimetype
        name = raw.split(";", 1)[0].strip().lower()
        by_type.setdefault(name, []).append(capture.key)
    return [NameEvidence(name=name, evidence=_evidence(by_type[name])) for name in sorted(by_type)]


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
    parameters, amp = _parameters(data)
    return Contract(
        slug=slug,
        source=_source(index_bytes, ordered),
        endpoints=_endpoints(data),
        parameters=parameters,
        amp=amp,
        months=_months(data),
        content_types=_content_types(data),
    )
