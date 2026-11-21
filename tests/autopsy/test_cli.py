"""CLI tests for `revenant autopsy` (Req 1.1, 1.3, 1.5, 3.5, 4.3, 7.2, 7.6)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from revenant import cli
from revenant.autopsy.contract import Contract
from revenant.cli import app

SLUG = "yahoo-finance-ichart"
HOST = "ichart.yahoo.com"
QUERY = "s=AAPL&a=0&b=4&c=2016&d=0&e=8&f=2016&g=d&ignore=.csv"
BODY = (
    b"Date,Open,High,Low,Close,Volume,Adj Close\n"
    b"2016-01-08,98.55,99.11,96.76,96.96,70798000,94.06\n"
    b"2016-01-07,98.68,100.13,96.43,96.45,81094400,93.56\n"
    b"2016-01-04,102.61,105.37,102.00,105.35,67649400,102.20\n"
)

runner = CliRunner()


def _entry(timestamp: str, body: bytes) -> dict[str, object]:
    digest = f"D{timestamp}"
    original = f"http://{HOST}/table.csv?{QUERY}"
    return {
        "host": HOST,
        "kind": "data",
        "requested_timestamp": timestamp,
        "served_timestamp": timestamp,
        "original": original,
        "mimetype": "text/csv",
        "statuscode": "200",
        "digest": digest,
        "length": "100",
        "final_url": f"https://web.archive.org/web/{timestamp}id_/{original}",
        "path": f"{HOST}/{timestamp}-{digest}.csv",
        "size": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "content_type": "text/csv",
        "digest_verified": True,
        "fetched_at": "2026-11-15T00:00:00Z",
    }


def _evidence(root: Path, count: int = 3, body: bytes = BODY) -> Path:
    """Write `count` Decisive H=0 captures (0-indexed when count >= 3) under `root`."""
    slug_dir = root / SLUG
    entries: dict[str, dict[str, object]] = {}
    for i in range(count):
        entry = _entry(f"2016011{i}000000", body)
        path = slug_dir / str(entry["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        entries[str(entry["path"]).removesuffix(".csv")] = entry
    index = {"slug": SLUG, "entries": entries}
    (slug_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")
    return slug_dir


def _invoke(tmp_path: Path, *extra: str) -> Result:
    return runner.invoke(
        app,
        [
            "autopsy",
            SLUG,
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--crypt-dir",
            str(tmp_path / "crypt"),
            "--specs-dir",
            str(tmp_path / "specs"),
            *extra,
        ],
    )


def _contract_path(tmp_path: Path) -> Path:
    return tmp_path / "crypt" / SLUG / "contract.json"


def _spec_path(tmp_path: Path) -> Path:
    return tmp_path / "specs" / f"revenant-{SLUG}" / "requirements.md"


def test_success_writes_both_files_and_prints(tmp_path: Path) -> None:
    _evidence(tmp_path / "evidence")
    result = _invoke(tmp_path)
    assert result.exit_code == 0, result.output
    contract, spec = _contract_path(tmp_path), _spec_path(tmp_path)
    assert contract.is_file()
    assert spec.is_file()
    assert "month indexing: 0-indexed" in result.output
    assert "decisive: H=0 3, H=1 0" in result.output
    assert f"wrote: {contract.as_posix()}" in result.output
    assert f"wrote: {spec.as_posix()}" in result.output


def _missing_index(slug_dir: Path) -> None:
    (slug_dir / "index.json").unlink()


def _bad_json(slug_dir: Path) -> None:
    (slug_dir / "index.json").write_bytes(b"{not json")


def _invalid_index(slug_dir: Path) -> None:
    (slug_dir / "index.json").write_text(json.dumps({"slug": SLUG, "entries": {"k": {}}}))


def _slug_mismatch(slug_dir: Path) -> None:
    index = slug_dir / "index.json"
    data = json.loads(index.read_text(encoding="utf-8"))
    data["slug"] = "other-slug"
    index.write_text(json.dumps(data), encoding="utf-8")


def _first_body(slug_dir: Path) -> Path:
    return min((slug_dir / HOST).iterdir())


def _missing_body(slug_dir: Path) -> None:
    _first_body(slug_dir).unlink()


def _sha_mismatch(slug_dir: Path) -> None:
    _first_body(slug_dir).write_bytes(b"tampered\n")


@pytest.mark.parametrize(
    ("corrupt", "named"),
    [
        (_missing_index, "index.json"),
        (_bad_json, "index.json"),
        (_invalid_index, "index.json"),
        (_slug_mismatch, "index.json"),
        (_missing_body, "20160110000000-D20160110000000.csv"),
        (_sha_mismatch, "20160110000000-D20160110000000.csv"),
    ],
)
def test_input_error_exits_1_without_writing(
    tmp_path: Path, corrupt: Callable[[Path], None], named: str
) -> None:
    corrupt(_evidence(tmp_path / "evidence"))
    existing = _contract_path(tmp_path)
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"previous\n")
    result = _invoke(tmp_path)
    assert result.exit_code == 1
    assert "error: " in result.output
    assert named in result.output
    assert existing.read_bytes() == b"previous\n"
    assert list(existing.parent.iterdir()) == [existing]
    assert not (tmp_path / "specs").exists()


def test_non_utf8_body_exits_1(tmp_path: Path) -> None:
    _evidence(tmp_path / "evidence", body=b"Date,Open\n2016-01-04,\xff\n")
    result = _invoke(tmp_path)
    assert result.exit_code == 1
    assert "error: " in result.output
    assert ".csv" in result.output
    assert not (tmp_path / "crypt").exists()
    assert not (tmp_path / "specs").exists()


def test_undetermined_exits_2_with_contract_only(tmp_path: Path) -> None:
    _evidence(tmp_path / "evidence", count=2)
    result = _invoke(tmp_path)
    assert result.exit_code == 2
    assert "month indexing: undetermined" in result.output
    assert "decisive: H=0 2, H=1 0" in result.output
    assert _contract_path(tmp_path).is_file()
    assert not (tmp_path / "specs").exists()


def test_contract_validation_error_keeps_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _evidence(tmp_path / "evidence")
    real_infer = cli.infer

    def bad_infer(*args: object) -> Contract:
        contract = real_infer(*args)  # type: ignore[arg-type]
        months = contract.months.model_copy(update={"indexing": "bogus"})
        return contract.model_copy(update={"months": months})

    monkeypatch.setattr(cli, "infer", bad_infer)
    existing = _contract_path(tmp_path)
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"previous\n")
    result = _invoke(tmp_path)
    assert result.exit_code == 1
    assert "error: contract.json: months.indexing: " in result.output
    assert existing.read_bytes() == b"previous\n"
    assert not (tmp_path / "specs").exists()


def test_contract_identical_across_working_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _evidence(tmp_path / "evidence")
    monkeypatch.chdir(tmp_path)
    relative = runner.invoke(
        app,
        ["autopsy", SLUG, "--evidence-dir", "evidence", "--crypt-dir", "crypt1"]
        + ["--specs-dir", "specs1"],
    )
    assert relative.exit_code == 0, relative.output
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    absolute = runner.invoke(
        app,
        ["autopsy", SLUG, "--evidence-dir", str(tmp_path / "evidence")]
        + ["--crypt-dir", str(tmp_path / "crypt2"), "--specs-dir", str(tmp_path / "specs2")],
    )
    assert absolute.exit_code == 0, absolute.output
    first = (tmp_path / "crypt1" / SLUG / "contract.json").read_bytes()
    second = (tmp_path / "crypt2" / SLUG / "contract.json").read_bytes()
    assert first == second


def test_help_lists_the_three_options() -> None:
    result = runner.invoke(app, ["autopsy", "--help"], env={"COLUMNS": "200"})
    assert result.exit_code == 0
    for option in ("--evidence-dir", "--crypt-dir", "--specs-dir"):
        assert option in result.output
