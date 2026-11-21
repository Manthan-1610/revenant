"""Spec_Renderer: EARS `requirements.md` for one revenant, from `contract.json` only (Req 8).

String templates only. `render` is pure: the same Contract always gives the same text, and every
choice follows a fixed tie-break (Req 8.3, 8.4, 8.6), never dict or set order.
"""

from __future__ import annotations

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


def served_precision(contract: Contract, interval: str, header: str) -> int | None:
    """Most frequent Body_Precision in the latest year, ties to more digits (Req 8.4)."""
    rows = [p for p in contract.precision if p.interval == interval and p.header == header]
    if not rows:
        return None
    latest = max(rows, key=lambda p: p.year)
    if not latest.values:
        return None
    return max(latest.values, key=lambda v: (v.count, v.digits)).digits


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


def _parameter_criteria(parameter: Parameter) -> list[str]:
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
        head = (
            f"WHEN a request carries the observed, unexplained parameter {name}, THE Revenant"
            f" SHALL accept it as {status} and ignore its value ({evidence})."
        )
    elif kind.kind == "int":
        head = (
            f"WHEN a request carries parameter {name}, THE Revenant SHALL read it as {article} {status}"
            f" `int` ({evidence})."
        )
    elif kind.kind == "enum":
        values = ", ".join(f"{_code(v.value)} ({v.count})" for v in kind.values)
        head = (
            f"WHEN a request carries parameter {name}, THE Revenant SHALL read it as {article} {status}"
            f" `enum` and accept every observed value: {values} ({evidence})."
        )
    else:
        head = (
            f"WHEN a request carries parameter {name}, THE Revenant SHALL read it as {article} {status}"
            f" `string` ({kind.distinct} distinct values observed; {evidence})."
        )
    criteria = [head]
    if kind.kind == "int":
        criteria.append(
            f"WHEN a request carries {name}, THE Revenant SHALL accept every value from"
            f" {kind.min} to {kind.max} and SHALL never reject a value the dead API accepted."
        )
    return criteria


def _parameters(contract: Contract) -> list[str]:
    criteria: list[str] = []
    for parameter in contract.parameters:
        criteria += _parameter_criteria(parameter)
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
    return [text]


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
        digits = served_precision(contract, group.interval, served.header)
        if digits is not None:
            text += (
                f" and write every numeric field except `Date` and `Volume` with {digits}"
                " fractional digits"
            )
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
    text = (
        f"IF the Donor has no rows for a request, THEN THE Revenant SHALL respond with status"
        f" {top.status}{content} (Evidence_Count {top.evidence.count}:"
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
    "format": "As an old CSV parser, I want the same header, precision and row order, so that my"
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
