"""Example tests for the Evidence_Reader (Req 1.2, 1.3, 1.4)."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from revenant.autopsy.evidence import AutopsyError, capture_date, capture_year, load_evidence
from revenant.exhume.models import IndexEntry

SLUG = "yahoo-finance-ichart"
HOST = "ichart.yahoo.com"
REPO_EVIDENCE = Path(__file__).resolve().parents[2] / "evidence"


def _entry(timestamp: str, body: bytes, **overrides: object) -> dict[str, object]:
    digest = f"D{timestamp}"
    entry: dict[str, object] = {
        "host": HOST,
        "kind": "data",
        "requested_timestamp": timestamp,
        "served_timestamp": timestamp,
        "original": f"http://{HOST}/table.csv?s=AAPL",
        "mimetype": "text/csv",
        "statuscode": "200",
        "digest": digest,
        "length": "100",
        "final_url": f"https://web.archive.org/web/{timestamp}id_/http://{HOST}/table.csv?s=AAPL",
        "path": f"{HOST}/{timestamp}-{digest}.csv",
        "size": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "content_type": "text/csv",
        "digest_verified": True,
        "fetched_at": "2026-11-15T00:00:00Z",
    }
    entry.update(overrides)
    return entry


def _write(
    root: Path, entries: dict[str, tuple[dict[str, object], bytes]], slug: str = SLUG
) -> Path:
    """Write bodies and an index.json with entries in the given insertion order."""
    slug_dir = root / slug
    for entry, body in entries.values():
        path = slug_dir / str(entry["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    index = {"slug": slug, "entries": {key: entry for key, (entry, _) in entries.items()}}
    (slug_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")
    return slug_dir / "index.json"


def _sample(root: Path) -> Path:
    body_a = b"Date,Open\n2016-01-04,1.0\n"
    body_b = b"Date,Open\n2015-01-02,2.0\n"
    a = _entry("20160105000000", body_a)
    b = _entry("20150103000000", body_b, digest_verified=False)
    # Insertion order deliberately not sorted.
    return _write(
        root,
        {
            f"{HOST}/{a['requested_timestamp']}-{a['digest']}": (a, body_a),
            f"{HOST}/{b['requested_timestamp']}-{b['digest']}": (b, body_b),
        },
    )


def test_loads_in_sorted_key_order(tmp_path: Path) -> None:
    index_path = _sample(tmp_path)
    index_bytes, captures = load_evidence(tmp_path, SLUG)
    assert index_bytes == index_path.read_bytes()
    keys = [capture.key for capture in captures]
    assert keys == sorted(keys)
    assert keys[0].startswith(f"{HOST}/2015")
    assert captures[0].body == b"Date,Open\n2015-01-02,2.0\n"


def test_digest_verified_false_is_accepted(tmp_path: Path) -> None:
    _sample(tmp_path)
    _, captures = load_evidence(tmp_path, SLUG)
    assert [c.entry.digest_verified for c in captures] == [False, True]


def _expect_error(tmp_path: Path, name: str) -> None:
    with pytest.raises(AutopsyError) as info:
        load_evidence(tmp_path, SLUG)
    assert name in str(info.value)
    assert "\\" not in info.value.path


def test_missing_index(tmp_path: Path) -> None:
    _expect_error(tmp_path, "index.json")


def test_bad_json(tmp_path: Path) -> None:
    index_path = _sample(tmp_path)
    index_path.write_bytes(b"{not json")
    _expect_error(tmp_path, "index.json")


def test_invalid_index(tmp_path: Path) -> None:
    index_path = _sample(tmp_path)
    index_path.write_text(json.dumps({"slug": SLUG, "entries": {"k": {"host": HOST}}}))
    _expect_error(tmp_path, "index.json")


def test_slug_mismatch(tmp_path: Path) -> None:
    index_path = _sample(tmp_path)
    data = json.loads(index_path.read_text())
    data["slug"] = "other-slug"
    index_path.write_text(json.dumps(data))
    _expect_error(tmp_path, "index.json")


def test_missing_body(tmp_path: Path) -> None:
    _sample(tmp_path)
    body = tmp_path / SLUG / HOST / "20150103000000-D20150103000000.csv"
    body.unlink()
    _expect_error(tmp_path, "20150103000000-D20150103000000.csv")


def test_sha256_mismatch(tmp_path: Path) -> None:
    _sample(tmp_path)
    body = tmp_path / SLUG / HOST / "20160105000000-D20160105000000.csv"
    body.write_bytes(b"tampered\n")
    _expect_error(tmp_path, "20160105000000-D20160105000000.csv")


def test_capture_year_and_date_fall_back_to_requested() -> None:
    served = IndexEntry.model_validate(
        _entry("20160105000000", b"", served_timestamp="20170203120000")
    )
    assert capture_year(served) == 2017
    assert capture_date(served) == date(2017, 2, 3)
    fallback = IndexEntry.model_validate(_entry("20041129000000", b"", served_timestamp=None))
    assert capture_year(fallback) == 2004
    assert capture_date(fallback) == date(2004, 11, 29)


def test_committed_evidence_loads() -> None:
    index_bytes, captures = load_evidence(REPO_EVIDENCE, SLUG)
    assert index_bytes
    assert captures
    assert [c.key for c in captures] == sorted(c.key for c in captures)
