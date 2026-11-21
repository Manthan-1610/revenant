"""Tests for `revenant verify`: offline re-hash of the Evidence_Store (Req 9.2, 7.6)."""

from pathlib import Path

import httpx
from typer.testing import CliRunner, Result

from revenant import cli
from revenant.exhume.models import CdxRow
from revenant.exhume.store import EvidenceStore
from revenant.exhume.verify import F19_HINT, verify

SLUG = "yahoo-finance-ichart"
HOST = "ichart.yahoo.com"
BODY = b"Date,Open,High,Low,Close,Volume,Adj Close\n"


def _save(store: EvidenceStore, timestamp: str, digest: str, verified: bool) -> Path:
    row = CdxRow(
        timestamp=timestamp,
        original=f"http://{HOST}/table.csv?s=AAPL",
        mimetype="text/csv",
        statuscode="200",
        digest=digest,
        length="100",
    )
    url = f"https://web.archive.org/web/{timestamp}id_/{row.original}"
    response = httpx.Response(200, content=BODY, request=httpx.Request("GET", url))
    entry = store.save_capture(HOST, row, "data", response, timestamp, verified)
    return store.slug_dir / entry.path


def _run(root: Path) -> Result:
    return CliRunner().invoke(cli.app, ["verify", SLUG, "--evidence-dir", str(root)])


def test_all_good_exits_0_with_counts(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path, SLUG)
    _save(store, "20160101000000", "AAAA", True)
    _save(store, "20160102000000", "BBBB", True)
    result = _run(tmp_path)
    assert result.exit_code == 0, result.output
    assert "checked: 2\n" in result.output
    assert "sha256 failures: 0\n" in result.output
    assert "digest_verified: true=2 false=0\n" in result.output
    assert "F19" not in result.output


def test_tampered_file_exits_1_naming_it(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path, SLUG)
    _save(store, "20160101000000", "AAAA", True)
    tampered = _save(store, "20160102000000", "BBBB", True)
    tampered.write_bytes(BODY + b"x")
    result = _run(tmp_path)
    assert result.exit_code == 1
    assert "sha256 failures: 1\n" in result.output
    assert f"{tampered.as_posix()} (sha256 mismatch)" in result.output


def test_missing_file_is_a_failure(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path, SLUG)
    missing = _save(store, "20160101000000", "AAAA", True)
    missing.unlink()
    report = verify(store)
    assert report.checked == 1
    assert report.failures == [f"{missing.as_posix()} (missing)"]


def test_false_digest_entries_listed_with_f19_hint(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path, SLUG)
    _save(store, "20160101000000", "AAAA", True)
    _save(store, "20160102000000", "BBBB", False)
    result = _run(tmp_path)
    assert result.exit_code == 0, result.output
    assert "digest_verified: true=1 false=1\n" in result.output
    assert f"{HOST}/20160102000000-BBBB  {F19_HINT}\n" in result.output
    assert f"{HOST}/20160101000000-AAAA  " not in result.output


def test_missing_index_exits_1(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.exit_code == 1
    assert "no index at" in result.output
