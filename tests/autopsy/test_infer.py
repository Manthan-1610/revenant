"""Example tests for the Contract_Inferrer (Req 1.4, 2.2 to 2.5, 3.2, 4.1)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from revenant.autopsy.contract import Contract, EnumType, IntType, Parameter, StringType
from revenant.autopsy.evidence import Capture, load_evidence
from revenant.autopsy.infer import infer
from revenant.exhume.models import IndexEntry

SLUG = "yahoo-finance-ichart"
REPO_EVIDENCE = Path(__file__).resolve().parents[2] / "evidence"
HOST = "ichart.yahoo.com"
BODY = b"Date,Close\n2016-01-05,1.5\n2016-01-04,1.4\n"


def _capture(number: int, query: str, content_type: str | None = "text/csv") -> Capture:
    stamp = f"20160110{number:06d}"
    digest = f"D{number}"
    entry = IndexEntry(
        host=HOST,
        kind="data",
        requested_timestamp=stamp,
        served_timestamp=stamp,
        original=f"http://{HOST}/table.csv?{query}",
        mimetype="text/csv",
        statuscode="200",
        digest=digest,
        length=str(len(BODY)),
        final_url=f"https://web.archive.org/web/{stamp}id_/http://{HOST}/table.csv?{query}",
        path=f"{HOST}/{stamp}-{digest}.csv",
        size=len(BODY),
        sha256=hashlib.sha256(BODY).hexdigest(),
        content_type=content_type,
        digest_verified=True,
        fetched_at="2026-11-15T00:00:00Z",
    )
    return Capture(key=f"{HOST}/{stamp}-{digest}", entry=entry, body=BODY)


def _param(contract: Contract, name: str) -> Parameter:
    return next(p for p in contract.parameters if p.name == name)


QUERIES = [
    "s=AAPL&a=0&b=4&c=2016&d=0&e=5&f=2016&g=d&ignore=.csv",
    "s=IBM&a=11&b=1&c=2015&d=0&e=5&f=2016&g=w&ignore=.csv&x=1",
    "s=%5EDJI&a={{x}}&b=1&c=2016&d=0&e=5&f=2016&g=d&amp;ignore=.csv",
    "s=MSFT&a=&b=&c=&d=&e=&f=&g=&ignore=.csv",
    "s=GOOG&a=02&b=10&c=2003&f=f6j1&ignore=.csv",
] + [f"s=S{n:02d}&g=d" for n in range(10)]


def _contract() -> Contract:
    captures = [_capture(n, query) for n, query in enumerate(QUERIES)]
    return infer(SLUG, b"{}", captures)


def test_parameter_types() -> None:
    contract = _contract()
    a = _param(contract, "a")
    assert a.type == IntType(min=0, max=11)
    assert (a.present.count, a.empty, a.junk, a.required) == (5, 1, 1, False)
    f = _param(contract, "f")
    assert f.type == IntType(min=2016, max=2016)
    assert f.junk == 1  # `f6j1` is Template_Junk for a documented range parameter
    g = _param(contract, "g")
    assert isinstance(g.type, EnumType)
    assert [(v.value, v.count) for v in g.type.values] == [("d", 12), ("w", 1)]
    assert g.examples == ["d", "w"]
    s = _param(contract, "s")
    assert s.type == StringType(distinct=len(QUERIES))
    assert s.required and s.documented
    assert len(s.examples) == 5
    assert [p.name for p in contract.parameters] == sorted(p.name for p in contract.parameters)


def test_amp_counted_and_excluded() -> None:
    # The fixpoint turns every `&amp` into `&`, so only a percent-encoded name survives as `amp`.
    contract = infer(SLUG, b"{}", [_capture(0, "s=DISH&%61mp=1"), _capture(1, "s=IBM&amp;g=d")])
    assert contract.amp.count == 1
    assert "amp" not in [p.name for p in contract.parameters]


def test_undocumented_parameter_is_optional() -> None:
    x = _param(_contract(), "x")
    assert not x.documented and not x.required
    assert x.present.count == 1
    assert x.type == IntType(min=1, max=1)


def test_content_type_reduced_to_media_type() -> None:
    captures = [
        _capture(0, "s=A", "text/csv; charset=UTF-8"),
        _capture(1, "s=B", "Text/CSV"),
        _capture(2, "s=C", None),
    ]
    contract = infer(SLUG, b"{}", captures)
    assert [(c.name, c.evidence.count) for c in contract.content_types] == [("text/csv", 3)]


def test_committed_evidence_is_0_indexed() -> None:
    index_bytes, captures = load_evidence(REPO_EVIDENCE, SLUG)
    contract = infer(SLUG, index_bytes, captures)
    assert contract.months.indexing == "0-indexed"
    assert contract.months.decisive_h1.count == 0
    assert contract.months.decisive_h0.count >= 3
    hosts = [host.host for endpoint in contract.endpoints for host in endpoint.hosts]
    assert "ichart.yahoo.com" in hosts
    assert contract.source.entry_count == len(captures)


def test_committed_evidence_d_accepts_month_12() -> None:
    """F21: Yahoo accepted `d=12`, so the observed maximum of `d` is 12; `a` to `f` stay `int`."""
    index_bytes, captures = load_evidence(REPO_EVIDENCE, SLUG)
    contract = infer(SLUG, index_bytes, captures)
    d = _param(contract, "d")
    assert isinstance(d.type, IntType)
    assert d.type.max == 12
    for name in "abcdef":
        assert isinstance(_param(contract, name).type, IntType), name
