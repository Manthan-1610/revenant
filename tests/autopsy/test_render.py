"""Spec_Renderer examples (Req 8.1 to 8.6)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from revenant.autopsy.contract import (
    Contract,
    DigitsCount,
    ErrorStatus,
    Evidence,
    IntervalVariants,
    NameCount,
    Precision,
    Variant,
    load_contract,
    write_contract,
)
from revenant.autopsy.evidence import load_evidence
from revenant.autopsy.infer import infer
from revenant.autopsy.render import (
    render,
    served_precision,
    served_variant,
    top_error,
    write_spec,
)

SLUG = "yahoo-finance-ichart"
REPO_EVIDENCE = Path(__file__).resolve().parents[2] / "evidence"
OLD = "Date,Open,High,Low,Close,Volume,Adj. Close*"
NEW = "Date,Open,High,Low,Close,Volume,Adj Close"


def _ev(count: int, *keys: str) -> dict[str, Any]:
    return {"count": count, "keys": list(keys)}


def _variant(header: str, first: int, last: int, count: int) -> Variant:
    return Variant(
        header=header,
        columns=header.split(","),
        first_year=first,
        last_year=last,
        evidence=Evidence(count=count, keys=[]),
    )


def _int_param(name: str, low: int, high: int) -> dict[str, Any]:
    return {
        "name": name,
        "documented": True,
        "present": _ev(3, "k1"),
        "empty": 0,
        "junk": 0,
        "required": False,
        "examples": [str(low)],
        "type": {"kind": "int", "min": low, "max": high},
    }


def _contract(**update: Any) -> Contract:
    data: dict[str, Any] = {
        "slug": SLUG,
        "source": {"index_sha256": "ab" * 32, "entry_count": 3},
        "endpoints": [
            {
                "path": "/table.csv",
                "hosts": [
                    {"host": "ichart.yahoo.com", "evidence": _ev(2, "k1", "k2")},
                    {"host": "real-chart.finance.yahoo.com", "evidence": _ev(1, "k3")},
                ],
            }
        ],
        "parameters": [
            _int_param("a", 0, 11),
            _int_param("d", 0, 12),
            {
                "name": "s",
                "documented": True,
                "present": _ev(3, "k1"),
                "empty": 0,
                "junk": 0,
                "required": True,
                "examples": ["AAPL"],
                "type": {"kind": "string", "distinct": 1},
            },
            {
                "name": "x",
                "documented": False,
                "present": _ev(1, "k3"),
                "empty": 0,
                "junk": 0,
                "required": False,
                "examples": [".csv"],
                "type": {"kind": "enum", "values": [{"value": ".csv", "count": 1}]},
            },
        ],
        "amp": _ev(0),
        "months": {
            "indexing": "0-indexed",
            "decisive_h0": _ev(3, "k1", "k2", "k3"),
            "decisive_h1": _ev(0),
            "ambiguous": _ev(0),
            "unfit": _ev(0),
        },
        "content_types": [{"name": "text/csv", "evidence": _ev(3, "k1")}],
        "intervals": [
            {
                "interval": "d",
                "variants": [
                    _variant(NEW, 2007, 2016, 2).model_dump(),
                    _variant(OLD, 2004, 2007, 1).model_dump(),
                ],
            }
        ],
        "headers": [],
        "header_only": _ev(0),
        "date_formats": [
            {"format": "%Y-%m-%d", "first_year": 2007, "last_year": 2016, "evidence": _ev(2)},
            {"format": "%d-%b-%y", "first_year": 2004, "last_year": 2007, "evidence": _ev(1)},
        ],
        "row_order": {
            "descending": _ev(3),
            "ascending": _ev(0),
            "unordered": _ev(0),
            "unparsed_dates": _ev(0),
        },
        "precision": [
            {"interval": "d", "header": NEW, "year": 2016, "values": [{"digits": 6, "count": 2}]},
        ],
        "comments": {
            "total": 1,
            "years": [2004],
            "example": "<!-- ichart9 uncompressed -->",
            "after_last_row": 1,
            "before_last_row": 0,
            "evidence": _ev(1, "k1"),
        },
        "defaults": [
            {
                "shape": "s_only",
                "evidence": _ev(1, "k1"),
                "earliest": "1986-07-09",
                "latest": "2016-10-12",
                "recent_within_7d": 1,
                "spacing": "d",
            }
        ],
        "errors": [
            {
                "status": "404",
                "evidence": _ev(2, "e1"),
                "media_types": [{"name": "text/html", "count": 2}],
                "shapes": [{"name": "other", "count": 2}],
            }
        ],
    }
    data.update(update)
    return Contract.model_validate(data)


def _group(*variants: Variant) -> IntervalVariants:
    return IntervalVariants(interval="d", variants=list(variants))


def _error(status: str, count: int, *media: tuple[str, int]) -> ErrorStatus:
    return ErrorStatus(
        status=status,
        evidence=Evidence(count=count, keys=[]),
        media_types=[NameCount(name=n, count=c) for n, c in media],
        shapes=[],
    )


def test_render_is_byte_identical_with_one_trailing_newline(tmp_path: Path) -> None:
    contract = _contract()
    first = render(contract)
    assert first == render(contract)
    assert first.startswith("# Requirements Document\n")
    assert first.endswith("\n") and not first.endswith("\n\n")
    path = write_spec(contract, tmp_path)
    assert path == tmp_path / f"revenant-{SLUG}" / "requirements.md"
    assert path.read_bytes() == first.encode("utf-8")
    assert path.read_bytes() == write_spec(contract, tmp_path).read_bytes()


def test_render_covers_routes_months_donor_and_defaults() -> None:
    text = render(_contract())
    assert "`GET http://ichart.yahoo.com/table.csv`" in text
    assert "`GET http://real-chart.finance.yahoo.com/table.csv`" in text
    assert "value + 1, so that `a=0` means January" in text
    assert "`X-Revenant-Donor`" in text
    assert "(`s_only`)" in text and "1986-07-09 to 2016-10-12" in text
    assert "newest first" in text
    assert "read it as a required `string`" in text


def test_served_variant_prefers_latest_last_year() -> None:
    newer = _variant(NEW, 2007, 2016, 1)
    older = _variant(OLD, 2004, 2007, 50)
    assert served_variant(_group(older, newer)) == newer


def test_served_variant_ties_to_higher_evidence_then_lowest_header() -> None:
    few = _variant("B,C", 2010, 2016, 1)
    many = _variant("C,D", 2010, 2016, 5)
    assert served_variant(_group(few, many)) == many
    low = _variant("A,B", 2010, 2016, 5)
    assert served_variant(_group(many, low)) == low


def test_served_precision_uses_latest_year_and_ties_to_more_digits() -> None:
    rows = [
        Precision(interval="d", header=NEW, year=2015, values=[DigitsCount(digits=2, count=9)]),
        Precision(
            interval="d",
            header=NEW,
            year=2016,
            values=[
                DigitsCount(digits=2, count=1),
                DigitsCount(digits=5, count=3),
                DigitsCount(digits=6, count=3),
            ],
        ),
    ]
    contract = _contract(precision=[row.model_dump() for row in rows])
    assert served_precision(contract, "d", NEW) == 6
    assert served_precision(contract, "d", OLD) is None


def test_top_error_ties_to_lower_code_and_code_point_media_type() -> None:
    status, media = top_error(
        [_error("404", 3, ("text/plain", 1)), _error("400", 3, ("text/xml", 2), ("text/html", 2))]
    )
    assert status.status == "400" and media == "text/html"
    status, _ = top_error([_error("400", 1), _error("404", 2, ("text/html", 2))])
    assert status.status == "404"


def test_error_requirement_rendered_only_when_errors_present() -> None:
    assert "respond with status 404 with `Content-Type: text/html`" in render(_contract())
    text = render(_contract(errors=None))
    assert "Error behaviour" not in text
    assert "respond with status" not in text


def test_informational_section_lists_unselected_variants_formats_and_comment() -> None:
    text = render(_contract())
    notes = text.split("## Informational Notes", 1)[1]
    assert f"`g=d`: `{OLD}` (2004 to 2007" in notes
    assert f"`{NEW}`" not in notes
    assert "`%Y-%m-%d`" in notes and "`%d-%b-%y`" in notes
    assert "`<!-- ichart9 uncompressed -->`" in notes
    assert 'ignores "observed, unexplained" parameters: `x`' in notes


def test_every_int_parameter_states_its_full_range() -> None:
    text = render(_contract())
    assert "carries `a`, THE Revenant SHALL accept every value from 0 to 11" in text
    assert "carries `d`, THE Revenant SHALL accept every value from 0 to 12" in text
    assert "never reject a value the dead API accepted" in text


def test_committed_evidence_spec_states_every_int_range(tmp_path: Path) -> None:
    """F21: on the committed evidence `d` accepts 0 to 12; render reads the contract from disk."""
    index_bytes, captures = load_evidence(REPO_EVIDENCE, SLUG)
    path = write_contract(infer(SLUG, index_bytes, captures), tmp_path)
    contract = load_contract(path)
    text = render(contract)
    for parameter in contract.parameters:
        kind = parameter.type
        if kind.kind == "int":
            expected = f"`{parameter.name}`, THE Revenant SHALL accept every value from"
            assert f"{expected} {kind.min} to {kind.max}" in text
    assert "carries `d`, THE Revenant SHALL accept every value from 0 to 12" in text
