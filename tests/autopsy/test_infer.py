"""Example tests for the Contract_Inferrer (Req 1.4, 2.2, 3.2)."""

from __future__ import annotations

from pathlib import Path

from revenant.autopsy.evidence import load_evidence
from revenant.autopsy.infer import infer

SLUG = "yahoo-finance-ichart"
REPO_EVIDENCE = Path(__file__).resolve().parents[2] / "evidence"


def test_committed_evidence_is_0_indexed() -> None:
    index_bytes, captures = load_evidence(REPO_EVIDENCE, SLUG)
    contract = infer(SLUG, index_bytes, captures)
    assert contract.months.indexing == "0-indexed"
    assert contract.months.decisive_h1.count == 0
    assert contract.months.decisive_h0.count >= 3
    hosts = [host.host for endpoint in contract.endpoints for host in endpoint.hosts]
    assert "ichart.yahoo.com" in hosts
    assert contract.source.entry_count == len(captures)
