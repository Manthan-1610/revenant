"""Spec_Renderer examples (Req 8.1 to 8.6)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from revenant.autopsy.contract import (
    Contract,
    ErrorStatus,
    Evidence,
    HypothesisCount,
    IntervalVariants,
    NameCount,
    NumberFormat,
    Variant,
    load_contract,
    write_contract,
)
from revenant.autopsy.evidence import load_evidence
from revenant.autopsy.infer import infer
from revenant.autopsy.render import (
    render,
    served_number_format,
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


HYPOTHESES = [f"fixed{n}" for n in range(7)] + ["yahoo"]


def _numbers(
    header: str,
    year: int,
    total: int,
    supported: dict[str, int],
    zero_000: int = 0,
    zero_other: int = 0,
) -> dict[str, Any]:
    return NumberFormat(
        interval="d",
        header=header,
        year=year,
        hypotheses=[
            HypothesisCount(name=name, supported=supported.get(name, 0)) for name in HYPOTHESES
        ],
        total=total,
        volume_zero_000=zero_000,
        volume_zero_other=zero_other,
    ).model_dump()


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
            "overflow": _ev(1, "k2"),
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
        "header_only": {**_ev(2, "k1", "k2"), "first_year": 2004, "last_year": 2005},
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
        "numbers": [
            _numbers(NEW, 2016, 10, {"yahoo": 10, "fixed2": 8, "fixed6": 2}, zero_000=3),
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


def _choice(*rows: dict[str, Any]) -> str | None:
    choice = served_number_format(_contract(numbers=list(rows)), "d", NEW)
    assert choice is not None
    return choice.hypothesis


def test_number_format_uses_latest_year_and_most_supported_over_all_years() -> None:
    # 2016: fixed2, fixed3 and yahoo all at 100%; over all years fixed3 supports the most.
    latest = _numbers(NEW, 2016, 4, {"fixed2": 4, "fixed3": 4, "yahoo": 4})
    assert _choice(_numbers(NEW, 2015, 5, {"fixed3": 5, "yahoo": 2}), latest) == "fixed3"
    # An older year where only fixed2 is at 100% does not matter.
    older = _numbers(NEW, 2015, 5, {"fixed2": 5})
    assert _choice(older, _numbers(NEW, 2016, 3, {"yahoo": 3})) == "yahoo"
    assert served_number_format(_contract(), "d", OLD) is None


def test_number_format_ties_to_yahoo_then_smaller_n() -> None:
    assert _choice(_numbers(NEW, 2016, 4, {"fixed2": 4, "yahoo": 4})) == "yahoo"
    assert _choice(_numbers(NEW, 2016, 4, {"fixed3": 4, "fixed2": 4, "yahoo": 3})) == "fixed2"


def test_number_format_undetermined_cites_counts() -> None:
    contract = _contract(numbers=[_numbers(NEW, 2016, 10, {"yahoo": 9, "fixed2": 7})])
    choice = served_number_format(contract, "d", NEW)
    assert choice is not None and choice.hypothesis is None
    text = render(contract)
    assert (
        "with its number format undetermined (2016: Yahoo_Number 9 of 10, fixed 2 decimals 7 of"
        " 10; all years: Yahoo_Number 9 of 10, fixed 2 decimals 7 of 10)"
    ) in text
    assert "zero Volume" not in text


def test_render_number_format_and_glossary() -> None:
    text = render(_contract())
    assert (
        "SHALL write every value outside `Date` and `Volume` as a Yahoo_Number (2016: 10 of 10"
        " values; all years: 10 of 10) and SHALL write a zero Volume as `000` (3 of 3 zero"
        " Volumes)"
    ) in text
    glossary = text.split("## Glossary", 1)[1].split("## Requirements", 1)[0]
    assert "- **Yahoo_Number**: a value formatted with 6 decimals" in glossary
    assert "6 fractional digits" not in text
    fixed = render(_contract(numbers=[_numbers(NEW, 2016, 4, {"fixed2": 4}, 1, 1)]))
    assert "with exactly 2 decimals (2016: 4 of 4 values; all years: 4 of 4)" in fixed
    assert "zero Volume spelling undetermined (`000` 1 of 2 zero Volumes)" in fixed
    assert "fractional digits" not in fixed


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
    assert "carries `a`, THE Revenant SHALL parse it as an optional int" in text
    assert "SHALL accept at least every value from 0 to 11 (observed)" in text
    assert "SHALL accept at least every value from 0 to 12 (observed)" in text


def test_observed_range_is_a_minimum_and_unexplained_params_get_no_range() -> None:
    """Req 8.2: the victim sends c=2016 although c's observed max is 2015."""
    unexplained = {**_int_param("j", 2013, 2013), "documented": False}
    params = [_int_param("c", 1888, 2015), unexplained]
    text = render(_contract(parameters=params))
    assert (
        "WHEN a request carries `c`, THE Revenant SHALL parse it as an optional int, SHALL accept"
        " at least every value from 1888 to 2015 (observed), and SHALL NOT reject an integer only"
        " because it lies outside the observed range (Evidence_Count 3)."
    ) in text
    assert "SHALL NOT reject an integer only because it lies outside the observed range" in text
    assert "unexplained parameter `j`, THE Revenant SHALL accept it as optional and ignore" in text
    assert "from 2013 to 2013" not in text
    j_lines = [line for line in text.splitlines() if "`j`" in line and "SHALL" in line]
    assert len(j_lines) == 1


def test_month_12_rolls_over_only_when_observed() -> None:
    text = render(_contract())
    assert (
        "IF `a` or `d` is 12, THEN THE Revenant SHALL treat it as January of the following year"
        " (inferred from 1 capture, `k2`, which cannot tell rolling over from capping"
    ) in text
    no_12 = render(_contract(parameters=[_int_param("a", 0, 11), _int_param("d", 0, 11)]))
    assert "is 12, THEN" not in no_12


def test_header_only_responses_are_listed() -> None:
    notes = render(_contract()).split("## Informational Notes", 1)[1]
    assert "- Header-only 200 responses (2004–2005, Evidence_Count 2)" in notes


def test_committed_evidence_spec_states_every_int_range(tmp_path: Path) -> None:
    """F21: on the committed evidence `d` accepts 0 to 12; render reads the contract from disk."""
    index_bytes, captures = load_evidence(REPO_EVIDENCE, SLUG)
    path = write_contract(infer(SLUG, index_bytes, captures), tmp_path)
    contract = load_contract(path)
    text = render(contract)
    for parameter in contract.parameters:
        kind = parameter.type
        span = f"from {kind.min} to {kind.max}" if kind.kind == "int" else None
        if span and parameter.documented:
            assert f"at least every value {span} (observed)" in text
        elif span:
            assert span not in text
    assert "SHALL accept at least every value from 0 to 12 (observed)" in text
    assert "IF `a` or `d` is 12" in text
    assert "`ichart.finance.yahoo.com/20121217014635-DP2RNCXQZKYOFXDUCUXCL34SYCHTKAKU`" in text
    # Req 6.4: error keys newest first, so the 2016 real-chart 404 (SEYKM.IS) leads.
    newest = "newest first: `real-chart.finance.yahoo.com/20160719090815-"
    assert newest in text
