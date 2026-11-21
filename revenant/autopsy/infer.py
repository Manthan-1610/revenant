"""Contract_Inferrer: derives Contract facts from loaded evidence (Req 1.4, 2 to 6, 7.5).

Pure: no time, path, locale or environment value enters the Contract, and no set or dict is
iterated without sorting first.
"""

from __future__ import annotations

import hashlib
import itertools
import statistics
from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal
from urllib.parse import urlsplit

from revenant.autopsy.body import ParsedBody, body_precision, parse_body, parse_row_date, row_order
from revenant.autopsy.contract import (
    Comments,
    Contract,
    Default,
    DigitsCount,
    Endpoint,
    EnumType,
    ErrorStatus,
    Evidence,
    FormatEvidence,
    HostEvidence,
    IntervalVariants,
    IntType,
    Months,
    NameCount,
    NameEvidence,
    Parameter,
    Precision,
    RowOrder,
    Source,
    StringType,
    ValueCount,
    Variant,
    YearEvidence,
)
from revenant.autopsy.evidence import Capture, capture_date, capture_timestamp, capture_year
from revenant.autopsy.months import RANGE_PARAMS, MonthSample, Tally, detect
from revenant.autopsy.normalize import normalize_query
from revenant.exhume.select import interval, parameter_shape

MAX_KEYS = 3
MAX_EXAMPLES = 5
MAX_ENUM = 10
JUNK_MARKERS = ("{{", "}}", "{%")
MONTH_PARAMS = ("a", "d")
DOCUMENTED_PARAMS = frozenset({"s", "a", "b", "c", "d", "e", "f", "g", "ignore"})
RECENT_DAYS = 7  # Req 6.2: Capture_Date minus newest Row_Date in 0..7
DAILY_MAX = 4  # Req 6.3 spacing bands, in days, inclusive
WEEKLY = (5, 10)
MONTHLY = (25, 35)


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


def _media_type(capture: Capture) -> str:
    """Lowercased part before any `;` of `content_type`, else `mimetype`."""
    raw = capture.entry.content_type or capture.entry.mimetype
    return raw.split(";", 1)[0].strip().lower()


def _content_types(data: Sequence[Capture]) -> list[NameEvidence]:
    """Req 4.1: media type of each Data_Capture with its Evidence."""
    by_type: dict[str, list[str]] = {}
    for capture in data:
        by_type.setdefault(_media_type(capture), []).append(capture.key)
    return [NameEvidence(name=name, evidence=_evidence(by_type[name])) for name in sorted(by_type)]


@dataclass(frozen=True)
class _Body:
    """One Data_Capture with its parsed body, Capture_Year, Interval and Row_Dates."""

    capture: Capture
    parsed: ParsedBody
    year: int
    interval: str
    pairs: list[tuple[str, str]]
    row_dates: tuple[tuple[date, str] | None, ...]

    @property
    def key(self) -> str:
        return self.capture.key

    @property
    def unparsed(self) -> bool:
        """Req 5.3: at least one Data_Row whose Row_Date parses with neither format."""
        return any(item is None for item in self.row_dates)

    def dates(self) -> list[date]:
        return [item[0] for item in self.row_dates if item is not None]


def _bodies(data: Sequence[Capture]) -> list[_Body]:
    """Parse every Data_Capture body once; a non-UTF-8 body raises AutopsyError (Req 4.3)."""
    bodies = []
    for capture in data:
        parsed = parse_body(capture.body, capture.entry.path)
        year = capture_year(capture.entry)
        pairs = normalize_query(capture.entry.original)
        row_dates = tuple(parse_row_date(row.split(",", 1)[0], year) for row in parsed.rows)
        bodies.append(_Body(capture, parsed, year, interval(pairs), pairs, row_dates))
    return bodies


def _month_sample(body: _Body) -> MonthSample | None:
    """Req 3.1: a `full_range` Data_Capture with >= 1 Data_Row whose Row_Dates all parse."""
    if parameter_shape(body.pairs) != "full_range" or not body.parsed.rows or body.unparsed:
        return None
    dates = body.dates()
    first = _first_values(body.pairs)
    params = {name: first[name] for name in RANGE_PARAMS if name in first}
    return MonthSample(key=body.key, params=params, oldest=min(dates), newest=max(dates))


def _variant(header: str, group: Sequence[_Body]) -> Variant:
    years = [body.year for body in group]
    return Variant(
        header=header,
        columns=header.split(","),
        first_year=min(years),
        last_year=max(years),
        evidence=_evidence(body.key for body in group),
    )


def _group[K: Hashable](bodies: Iterable[_Body], key: Callable[[_Body], K]) -> dict[K, list[_Body]]:
    groups: dict[K, list[_Body]] = {}
    for body in bodies:
        groups.setdefault(key(body), []).append(body)
    return groups


def _variants(
    bodies: Sequence[_Body],
) -> tuple[list[IntervalVariants], list[Variant], YearEvidence]:
    """Req 4.4 to 4.6: Response_Variants per Interval, Header_Variants, Header_Only_Body count.

    Header_Only_Bodies count towards both variant tallies.
    """
    by_interval = _group(bodies, lambda body: body.interval)
    intervals = []
    for name in sorted(by_interval):
        by_header = _group(by_interval[name], lambda body: body.parsed.header)
        variants = [_variant(header, by_header[header]) for header in sorted(by_header)]
        intervals.append(IntervalVariants(interval=name, variants=variants))
    by_header = _group(bodies, lambda body: body.parsed.header)
    headers = [_variant(header, by_header[header]) for header in sorted(by_header)]
    empty = [body for body in bodies if not body.parsed.rows]
    evidence = _evidence(body.key for body in empty)
    years = [body.year for body in empty]
    header_only = YearEvidence(
        count=evidence.count,
        keys=evidence.keys,
        first_year=min(years) if years else None,
        last_year=max(years) if years else None,
    )
    return intervals, headers, header_only


def _date_formats(bodies: Sequence[_Body]) -> list[FormatEvidence]:
    """Req 5.1: each Row_Date format with the Capture_Years and bodies that use it."""
    by_format: dict[str, list[_Body]] = {}
    for body in bodies:
        formats = sorted({item[1] for item in body.row_dates if item is not None})
        for name in formats:
            by_format.setdefault(name, []).append(body)
    result = []
    for name in sorted(by_format):
        years = [body.year for body in by_format[name]]
        result.append(
            FormatEvidence(
                format=name,
                first_year=min(years),
                last_year=max(years),
                evidence=_evidence(body.key for body in by_format[name]),
            )
        )
    return result


def _row_order(bodies: Sequence[_Body]) -> RowOrder:
    """Req 5.2, 5.3: classify bodies with >= 2 Data_Rows; `unparsed_dates` bodies are excluded."""
    classes: dict[str, list[str]] = {"descending": [], "ascending": [], "unordered": []}
    unparsed = []
    for body in bodies:
        if body.unparsed:
            unparsed.append(body.key)
        elif len(body.row_dates) >= 2:
            classes[row_order(body.dates())].append(body.key)
    return RowOrder(
        descending=_evidence(classes["descending"]),
        ascending=_evidence(classes["ascending"]),
        unordered=_evidence(classes["unordered"]),
        unparsed_dates=_evidence(unparsed),
    )


def _precision(bodies: Sequence[_Body]) -> list[Precision]:
    """Req 5.4: Body_Precision counts per (Interval, Header_Variant, Capture_Year)."""
    groups = _group(
        (body for body in bodies if body.parsed.rows),
        lambda body: (body.interval, body.parsed.header, body.year),
    )
    result = []
    for group_key in sorted(groups):
        counts: dict[int, int] = {}
        for body in groups[group_key]:
            digits = body_precision(body.parsed.header, body.parsed.rows)
            counts[digits] = counts.get(digits, 0) + 1
        name, header, year = group_key
        values = [DigitsCount(digits=digits, count=counts[digits]) for digits in sorted(counts)]
        result.append(Precision(interval=name, header=header, year=year, values=values))
    return result


def _comments(bodies: Sequence[_Body]) -> Comments:
    """Req 5.5: Comment_Line totals, years, first example in key order, after/before (F16)."""
    carrying = [body for body in bodies if body.parsed.comments]
    return Comments(
        total=sum(len(body.parsed.comments) for body in carrying),
        years=sorted({body.year for body in carrying}),
        example=carrying[0].parsed.comments[0] if carrying else None,
        after_last_row=sum(body.parsed.comments_after_last_row for body in carrying),
        before_last_row=sum(body.parsed.comments_before_last_row for body in carrying),
        evidence=_evidence(body.key for body in carrying),
    )


def _spacing(gaps: Sequence[int]) -> Literal["d", "w", "m", "unknown"]:
    """Req 6.3: band of the median gap; a half-day median such as 4.5 falls in no band."""
    if not gaps:
        return "unknown"
    middle = statistics.median(gaps)
    if middle <= DAILY_MAX:
        return "d"
    if WEEKLY[0] <= middle <= WEEKLY[1]:
        return "w"
    if MONTHLY[0] <= middle <= MONTHLY[1]:
        return "m"
    return "unknown"


def _default(shape: Literal["s_only", "empty_range"], group: Sequence[_Body]) -> Default:
    """Req 6.1 to 6.3 over bodies with >= 1 Data_Row and no `unparsed_dates`."""
    oldest = [min(body.dates()) for body in group]
    newest = [max(body.dates()) for body in group]
    recent = sum(
        1
        for body, last in zip(group, newest, strict=True)
        if 0 <= (capture_date(body.capture.entry) - last).days <= RECENT_DAYS
    )
    gaps = [
        abs((later - earlier).days)
        for body in group
        for earlier, later in itertools.pairwise(body.dates())
    ]
    return Default(
        shape=shape,
        evidence=_evidence(body.key for body in group),
        earliest=min(oldest).isoformat() if group else None,
        latest=max(newest).isoformat() if group else None,
        recent_within_7d=recent,
        spacing=_spacing(gaps),
    )


def _defaults(bodies: Sequence[_Body]) -> list[Default]:
    eligible = [body for body in bodies if body.parsed.rows and not body.unparsed]
    by_shape = _group(eligible, lambda body: parameter_shape(body.pairs))
    shapes: tuple[Literal["s_only", "empty_range"], ...] = ("empty_range", "s_only")
    return [_default(shape, by_shape.get(shape, [])) for shape in shapes]


def _name_counts(names: Iterable[str]) -> list[NameCount]:
    counts: dict[str, int] = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    return [NameCount(name=name, count=counts[name]) for name in sorted(counts)]


def _newest_first(captures: Sequence[Capture]) -> Evidence:
    """Evidence whose keys run newest Capture timestamp first, ties by ascending key."""
    ordered = sorted(captures, key=lambda c: c.key)
    ordered.sort(key=lambda c: capture_timestamp(c.entry), reverse=True)  # stable: keys tie-break
    return Evidence(count=len(ordered), keys=[c.key for c in ordered[:MAX_KEYS]])


def _errors(errors: Sequence[Capture]) -> list[ErrorStatus] | None:
    """Req 6.4, 6.5: per status code from Error_Captures only; null when there are none."""
    if not errors:
        return None
    by_status: dict[str, list[Capture]] = {}
    for capture in errors:
        by_status.setdefault(capture.entry.statuscode, []).append(capture)
    return [
        ErrorStatus(
            status=status,
            evidence=_newest_first(by_status[status]),
            media_types=_name_counts(_media_type(capture) for capture in by_status[status]),
            shapes=_name_counts(
                parameter_shape(normalize_query(capture.entry.original))
                for capture in by_status[status]
            ),
        )
        for status in sorted(by_status)
    ]


def _is_month_12(body: _Body) -> bool:
    """F21: the first `a` or `d` value is the integer 12."""
    first = _first_values(body.pairs)
    return any(
        (value := first.get(name, "")).isascii() and value.isdigit() and int(value) == 12
        for name in MONTH_PARAMS
    )


def _months(bodies: Sequence[_Body]) -> Months:
    samples = [sample for body in bodies if (sample := _month_sample(body)) is not None]
    result = detect(samples)
    return Months(
        indexing=result.indexing,
        decisive_h0=_from_tally(result.decisive_h0),
        decisive_h1=_from_tally(result.decisive_h1),
        ambiguous=_from_tally(result.ambiguous),
        unfit=_from_tally(result.unfit),
        overflow=_evidence(body.key for body in bodies if _is_month_12(body)),
    )


def infer(slug: str, index_bytes: bytes, captures: Sequence[Capture]) -> Contract:
    """Build the Contract; captures are re-sorted by key, `error_page` entries are ignored."""
    ordered = sorted(captures, key=lambda capture: capture.key)
    data = [capture for capture in ordered if capture.entry.kind == "data"]
    bodies = _bodies(data)  # sorted by key, like `data`
    parameters, amp = _parameters(data)
    intervals, headers, header_only = _variants(bodies)
    return Contract(
        slug=slug,
        source=_source(index_bytes, ordered),
        endpoints=_endpoints(data),
        parameters=parameters,
        amp=amp,
        months=_months(bodies),
        content_types=_content_types(data),
        intervals=intervals,
        headers=headers,
        header_only=header_only,
        date_formats=_date_formats(bodies),
        row_order=_row_order(bodies),
        precision=_precision(bodies),
        comments=_comments(bodies),
        defaults=_defaults(bodies),
        errors=_errors([capture for capture in ordered if capture.entry.kind == "error"]),
    )
