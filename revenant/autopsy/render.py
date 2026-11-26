"""Spec_Renderer: EARS `requirements.md` for one revenant, from `contract.json` only (Req 8).

String templates only. `render` is pure: the same Contract always gives the same text, and every
choice follows a fixed tie-break (Req 8.3, 8.4, 8.6), never dict or set order.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from revenant.autopsy.contract import (
    Contract,
    Default,
    ErrorStatus,
    IntervalVariants,
    Parameter,
    Variant,
)
from revenant.exhume.store import atomic_write

SPEC_FILE = "requirements.md"

ROW_ORDER_TEXT = {
    "descending": "newest first (each Row_Date strictly earlier than the one before it)",
    "ascending": "oldest first (each Row_Date strictly later than the one before it)",
    "unordered": "in the Donor's order, with no required sort",
}
SHAPE_TEXT = {
    "s_only": "carries `s` (and optionally `ignore`) and no `a` to `g` parameter",
    "empty_range": "carries `a` to `g` all with empty values",
}
SPACING_TEXT = {"d": "daily", "w": "weekly", "m": "monthly", "unknown": "the Donor's"}


def _code(text: str) -> str:
    """Inline code that survives backticks and HTML comments in the value."""
    if "`" in text:
        return f"`` {text} ``"
    return f"`{text}`"


def _keys(keys: list[str]) -> str:
    return ", ".join(_code(key) for key in keys) if keys else "none"


# Selection (Req 8.3, 8.4, 8.6) ---------------------------------------------------------------


def served_variant(group: IntervalVariants) -> Variant:
    """Latest last Capture_Year, then higher Evidence_Count, then lowest header (Req 8.3)."""
    return min(group.variants, key=lambda v: (-v.last_year, -v.evidence.count, v.header))


@dataclass(frozen=True)
class NumberChoice:
    """The Number_Hypothesis selected for one served Response_Variant (Req 8.4).

    `hypothesis` is None when no hypothesis supports 100% of the latest year's values.
    `latest` and `overall` map each hypothesis name to its supported count.
    """

    hypothesis: str | None
    year: int
    latest: dict[str, int]
    latest_total: int
    overall: dict[str, int]
    overall_total: int
    volume_zero_000: int
    volume_zero_other: int


def _fixed_n(name: str) -> int:
    return int(name.removeprefix("fixed")) if name.startswith("fixed") else 0


def served_number_format(contract: Contract, interval: str, header: str) -> NumberChoice | None:
    """Req 8.4: the hypothesis at 100% in the latest year; ties to most supported over all
    years, then `yahoo`, then the smaller N. None when the variant has no Data_Row."""
    rows = [n for n in contract.numbers if n.interval == interval and n.header == header]
    if not rows:
        return None
    latest_row = max(rows, key=lambda n: n.year)
    latest = {h.name: h.supported for h in latest_row.hypotheses}
    overall: dict[str, int] = {}
    for row in rows:
        for h in row.hypotheses:
            overall[h.name] = overall.get(h.name, 0) + h.supported
    full = [
        name for name in sorted(latest) if latest_row.total and latest[name] == latest_row.total
    ]
    chosen = min(
        full,
        key=lambda name: (-overall[name], name != "yahoo", _fixed_n(name)),
        default=None,
    )
    return NumberChoice(
        hypothesis=chosen,
        year=latest_row.year,
        latest=latest,
        latest_total=latest_row.total,
        overall=overall,
        overall_total=sum(row.total for row in rows),
        volume_zero_000=sum(row.volume_zero_000 for row in rows),
        volume_zero_other=sum(row.volume_zero_other for row in rows),
    )


def _hypothesis_text(name: str) -> str:
    return "Yahoo_Number" if name == "yahoo" else f"fixed {_fixed_n(name)} decimals"


def _number_text(choice: NumberChoice) -> str:
    """The number-format and zero-Volume clauses of a Response format criterion (Req 8.4)."""
    if choice.hypothesis is None:
        fixed_names = [name for name in sorted(choice.latest) if name.startswith("fixed")]
        best = min(
            fixed_names,
            key=lambda n: (-choice.latest[n], -choice.overall.get(n, 0), _fixed_n(n)),
        )
        cited = [name for name in ("yahoo", best) if name in choice.latest]
        newest = ", ".join(
            f"{_hypothesis_text(n)} {choice.latest[n]} of {choice.latest_total}" for n in cited
        )
        every = ", ".join(
            f"{_hypothesis_text(n)} {choice.overall.get(n, 0)} of {choice.overall_total}"
            for n in cited
        )
        text = (
            f", with its number format undetermined ({choice.year}: {newest}; all years: {every})"
        )
    else:
        name = choice.hypothesis
        how = "as a Yahoo_Number" if name == "yahoo" else f"with exactly {_fixed_n(name)} decimals"
        text = (
            f", SHALL write every value outside `Date` and `Volume` {how} ({choice.year}:"
            f" {choice.latest[name]} of {choice.latest_total} values; all years:"
            f" {choice.overall[name]} of {choice.overall_total})"
        )
    zeros = choice.volume_zero_000 + choice.volume_zero_other
    if choice.volume_zero_000 and not choice.volume_zero_other:
        text += (
            f" and SHALL write a zero Volume as `000` ({choice.volume_zero_000} of {zeros} zero"
            " Volumes)"
        )
    elif choice.volume_zero_other:
        text += (
            f", with the zero Volume spelling undetermined (`000` {choice.volume_zero_000} of"
            f" {zeros} zero Volumes)"
        )
    return text


def _status_key(status: str) -> tuple[int, str]:
    return (int(status) if status.isdigit() else 10**9, status)


def top_error(errors: list[ErrorStatus]) -> tuple[ErrorStatus, str | None]:
    """Highest Evidence_Count (ties to lower code) and its top media type (Req 8.6)."""
    top = min(errors, key=lambda e: (-e.evidence.count, *_status_key(e.status)))
    media = min(top.media_types, key=lambda m: (-m.count, m.name)) if top.media_types else None
    return top, media.name if media else None


def top_row_order(contract: Contract) -> tuple[str, int]:
    """The row-order class with the highest count, ties in the fixed class order (Req 8.2)."""
    order = contract.row_order
    classes = [
        ("descending", order.descending.count),
        ("ascending", order.ascending.count),
        ("unordered", order.unordered.count),
    ]
    return min(classes, key=lambda c: -c[1])


# Sections ------------------------------------------------------------------------------------


def _intro(contract: Contract) -> list[str]:
    source = contract.source
    return [
        "# Requirements Document",
        "",
        "## Introduction",
        "",
        (
            f"This document specifies the revenant for the dead API `{contract.slug}`. It is"
            f" rendered by Autopsy from `crypt/{contract.slug}/contract.json`, which was"
            f" inferred from {source.entry_count} archived captures (Index SHA-256"
            f" `{source.index_sha256}`). Every requirement cites its Evidence_Count; regenerate"
            " this file from the contract instead of editing it."
        ),
        "",
        "## Glossary",
        "",
        "- **Revenant**: the FastAPI server that answers requests the dead API used to answer.",
        "- **Donor**: the living data source that supplies the rows the Revenant serves.",
        "- **Interval**: the value of `g`, or `none` when `g` is absent or empty.",
        "- **Header_Line**: the first line of a CSV response body.",
        "- **Data_Row**: a non-empty line after the Header_Line that is not a Comment_Line.",
        "- **Row_Date**: the first field of a Data_Row.",
        "- **Comment_Line**: a line of the form `<!-- ... -->` inside a body.",
        "- **Evidence_Count**: the number of archived captures that support a fact.",
        (
            "- **Yahoo_Number**: a value formatted with 6 decimals, trailing zeros stripped,"
            " keeping at least 2 decimals, so `60.860001`, `61.18`, `52.00`."
        ),
        "",
        "## Requirements",
    ]


def _requirement(number: int, title: str, story: str, criteria: list[str]) -> list[str]:
    lines = [
        "",
        f"### Requirement {number}: {title}",
        "",
        f"**User Story:** {story}",
        "",
        "#### Acceptance Criteria",
        "",
    ]
    lines += [f"{i}. {text}" for i, text in enumerate(criteria, start=1)]
    return lines


def _routes(contract: Contract) -> list[str]:
    criteria = []
    for endpoint in contract.endpoints:
        for host in endpoint.hosts:
            criteria.append(
                f"WHEN a client sends `GET http://{host.host}{endpoint.path}`, THE Revenant SHALL"
                f" answer it as the dead API did (Evidence_Count {host.evidence.count}:"
                f" {_keys(host.evidence.keys)})."
            )
    return criteria


def _parameter_criterion(parameter: Parameter) -> str:
    name = _code(parameter.name)
    status = "required" if parameter.required else "optional"
    article = "a" if parameter.required else "an"
    evidence = f"Evidence_Count {parameter.present.count}"
    if parameter.empty:
        evidence += f", {parameter.empty} with an empty value"
    if parameter.junk:
        evidence += f", {parameter.junk} with Template_Junk"
    kind = parameter.type
    if not parameter.documented:
        # Unexplained: accept and ignore only, never a value range (Req 8.2).
        return (
            f"WHEN a request carries the observed, unexplained parameter {name}, THE Revenant"
            f" SHALL accept it as {status} and ignore its value ({evidence})."
        )
    if kind.kind == "int":
        # The observed range is the minimum to accept, never a limit (Req 8.2).
        return (
            f"WHEN a request carries {name}, THE Revenant SHALL parse it as {article} {status}"
            f" int, SHALL accept at least every value from {kind.min} to {kind.max} (observed),"
            " and SHALL NOT reject an integer only because it lies outside the observed range"
            f" ({evidence})."
        )
    if kind.kind == "enum":
        values = ", ".join(f"{_code(v.value)} ({v.count})" for v in kind.values)
        return (
            f"WHEN a request carries parameter {name}, THE Revenant SHALL read it as {article} {status}"
            f" `enum` and accept every observed value: {values} ({evidence})."
        )
    return (
        f"WHEN a request carries parameter {name}, THE Revenant SHALL read it as {article} {status}"
        f" `string` ({kind.distinct} distinct values observed; {evidence})."
    )


def _parameters(contract: Contract) -> list[str]:
    criteria: list[str] = []
    for parameter in contract.parameters:
        criteria.append(_parameter_criterion(parameter))
    if contract.amp.count:
        criteria.append(
            "WHEN a request carries a stray `amp` name from double HTML escaping, THE Revenant"
            f" SHALL ignore it (Evidence_Count {contract.amp.count})."
        )
    return criteria


def _months(contract: Contract) -> list[str]:
    months = contract.months
    counts = (
        f"Decisive_Captures for 0-indexed {months.decisive_h0.count}, for 1-indexed"
        f" {months.decisive_h1.count}; Ambiguous {months.ambiguous.count}; Unfit"
        f" {months.unfit.count}"
    )
    if months.indexing == "0-indexed":
        rule = "read the month as the value + 1, so that `a=0` means January"
        keys = months.decisive_h0.keys
    else:
        rule = "read the month as the value itself, so that `a=1` means January"
        keys = months.decisive_h1.keys
    text = (
        f"WHEN a request carries `a` or `d`, THE Revenant SHALL {rule} ({months.indexing};"
        f" {counts}; e.g. {_keys(keys)})."
    )
    criteria = [text]
    overflow = _overflow_criterion(contract)
    if overflow:
        criteria.append(overflow)
    return criteria


def _overflow_criterion(contract: Contract) -> str | None:
    """F21: month value 12 under 0-indexing rolls over to January of the next year (Req 8.2)."""
    if contract.months.indexing != "0-indexed":
        return None
    at_12 = [
        p
        for p in contract.parameters
        if p.name in ("a", "d") and p.documented and p.type.kind == "int" and p.type.max == 12
    ]
    if not at_12:
        return None
    evidence = contract.months.overflow
    if evidence.count:
        noun = "capture" if evidence.count == 1 else "captures"
        source = f"{evidence.count} {noun}, {_keys(evidence.keys)}"
    else:
        source = "; ".join(
            f"the observed max 12 of {_code(p.name)}, Evidence_Count {p.present.count}"
            for p in at_12
        )
    return (
        "IF `a` or `d` is 12, THEN THE Revenant SHALL treat it as January of the following year"
        f" (inferred from {source}, which cannot tell rolling over from capping at December,"
        " since both give the same rows there)."
    )


def _format(contract: Contract) -> list[str]:
    criteria = []
    if contract.content_types:
        top = min(contract.content_types, key=lambda c: (-c.evidence.count, c.name))
        criteria.append(
            f"WHEN the Revenant returns rows, THE Revenant SHALL send `Content-Type: {top.name}`"
            f" (Evidence_Count {top.evidence.count})."
        )
    for group in contract.intervals:
        served = served_variant(group)
        when = (
            "has no `g` or an empty `g`"
            if group.interval == "none"
            else f"carries `g={group.interval}`"
        )
        text = (
            f"WHEN a request {when}, THE Revenant SHALL send the Header_Line {_code(served.header)}"
        )
        choice = served_number_format(contract, group.interval, served.header)
        if choice is not None:
            text += _number_text(choice)
        text += (
            f" (served {served.first_year} to {served.last_year}, Evidence_Count"
            f" {served.evidence.count})."
        )
        criteria.append(text)
    name, count = top_row_order(contract)
    criteria.append(
        f"WHEN the Revenant returns Data_Rows, THE Revenant SHALL order them {ROW_ORDER_TEXT[name]}"
        f" (`{name}` in {count} bodies)."
    )
    return criteria


def _default_criterion(default: Default) -> str:
    shape = SHAPE_TEXT[default.shape]
    return (
        f"WHEN a request {shape} (`{default.shape}`), THE Revenant SHALL return"
        f" {SPACING_TEXT[default.spacing]} rows over the Donor's full history up to its latest"
        f" day (observed {default.earliest} to {default.latest}; {default.recent_within_7d} of"
        f" {default.evidence.count} captures ended within 7 days of the capture date;"
        f" {_keys(default.evidence.keys)})."
    )


def _defaults(contract: Contract) -> list[str]:
    return [_default_criterion(d) for d in contract.defaults if d.evidence.count]


def _donor() -> list[str]:
    text = (
        "WHEN the Revenant sends any response, THE Revenant SHALL include an"
        " `X-Revenant-Donor` header that names the Donor supplying the rows."
    )
    return [text]


def _error(errors: list[ErrorStatus]) -> list[str]:
    top, media = top_error(errors)
    content = f" with `Content-Type: {media}`" if media else ""
    body = ""
    if top.evidence.keys:
        body = (
            f" and a body modelled on the newest archived {top.status} page,"
            f" {_code(top.evidence.keys[0])}"
        )
    text = (
        f"IF the Donor has no rows for a request, THEN THE Revenant SHALL respond with status"
        f" {top.status}{content}{body} (Evidence_Count {top.evidence.count}, newest first:"
        f" {_keys(top.evidence.keys)})."
    )
    return [text]


def _informational(contract: Contract) -> list[str]:
    lines = [
        "",
        "## Informational Notes",
        "",
        "These observations are not requirements. They record what the evidence shows.",
        "",
        "### Unselected Response Variants",
        "",
    ]
    unselected = []
    for group in contract.intervals:
        served = served_variant(group)
        for variant in group.variants:
            if variant.header != served.header:
                unselected.append(
                    f"- `g={group.interval}`: {_code(variant.header)} ({variant.first_year} to"
                    f" {variant.last_year}, Evidence_Count {variant.evidence.count})"
                )
    lines += unselected or ["- none"]
    lines += ["", "### Row_Date Formats", ""]
    formats = [
        f"- {_code(f.format)}: {f.first_year} to {f.last_year} (Evidence_Count {f.evidence.count})"
        for f in contract.date_formats
    ]
    lines += formats or ["- none"]
    lines += ["", "### Header-Only 200 Responses", ""]
    header_only = contract.header_only
    if header_only.count and header_only.first_year is not None:
        years = str(header_only.first_year)
        if header_only.last_year != header_only.first_year:
            years += f"–{header_only.last_year}"
        lines.append(
            f"- Header-only 200 responses ({years}, Evidence_Count {header_only.count}):"
            f" a Header_Line with no Data_Row is a valid response ({_keys(header_only.keys)})"
        )
    else:
        lines.append("- none observed")
    comments = contract.comments
    lines += ["", "### Comment_Line", ""]
    if comments.example is None:
        lines.append("- none observed")
    else:
        years = ", ".join(str(year) for year in comments.years)
        lines.append(
            f"- Example: {_code(comments.example)} ({comments.total} in bodies from {years};"
            f" {comments.after_last_row} after and {comments.before_last_row} before the last"
            " Data_Row)"
        )
    unexplained = [p.name for p in contract.parameters if not p.documented]
    names = ", ".join(_code(name) for name in unexplained) if unexplained else "none"
    lines += [
        "",
        "### Observed, Unexplained Parameters",
        "",
        f'- The Revenant ignores "observed, unexplained" parameters: {names}.',
    ]
    return lines


STORIES = {
    "routes": "As an unmodified old client, I want every dead hostname and path to answer again,"
    " so that my hard-coded URL works.",
    "parameters": "As an unmodified old client, I want every parameter I send accepted, so that"
    " no request the dead API served is rejected.",
    "months": "As an unmodified old client, I want months read the way the dead API read them,"
    " so that my date ranges select the same rows.",
    "format": "As an old CSV parser, I want the same header, number format and row order, so that my"
    " parsing code keeps working.",
    "defaults": "As an old client that sends no date range, I want the same default range, so"
    " that my under-specified requests still return data.",
    "donor": "As a user of the Revenant, I want each response to name its data source, so that"
    " I know where the rows come from.",
    "error": "As an old client, I want the same failure status when no data exists, so that my"
    " error handling still runs.",
}


def render(contract: Contract) -> str:
    """The EARS requirements document, fixed section order, one trailing newline (Req 8.1)."""
    sections: list[tuple[str, str, list[str]]] = [
        ("Routes", "routes", _routes(contract)),
        ("Parameters", "parameters", _parameters(contract)),
        ("Month indexing", "months", _months(contract)),
        ("Response format", "format", _format(contract)),
    ]
    defaults = _defaults(contract)
    if defaults:
        sections.append(("Default ranges", "defaults", defaults))
    sections.append(("Donor header", "donor", _donor()))
    if contract.errors:
        sections.append(("Error behaviour", "error", _error(contract.errors)))
    lines = _intro(contract)
    for number, (title, story, criteria) in enumerate(sections, start=1):
        lines += _requirement(number, title, STORIES[story], criteria)
    lines += _informational(contract)
    return "\n".join(lines) + "\n"


def spec_path(specs_dir: Path, slug: str) -> Path:
    return specs_dir / f"revenant-{slug}" / SPEC_FILE


def write_spec(contract: Contract, specs_dir: Path) -> Path:
    """Atomically write `<specs_dir>/revenant-<slug>/requirements.md`; return its path."""
    path = spec_path(specs_dir, contract.slug)
    atomic_write(path, render(contract).encode("utf-8"))
    return path
