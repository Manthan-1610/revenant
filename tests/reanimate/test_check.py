"""Example tests for the post-build Check (Req 6.1-6.6), including misbehaving fixture servers."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from click.testing import Result
from typer.testing import CliRunner

from revenant import cli
from revenant.autopsy.contract import contract_path, load_contract
from revenant.autopsy.render import spec_path
from revenant.reanimate import check, runner
from revenant.reanimate.errors import ReanimateError
from revenant.reanimate.kiro import KiroCli
from revenant.reanimate.record import BuildRecord, DonorEntry, DonorIndex, dump_model
from tests.reanimate import test_runner as tr

REPO = Path(__file__).resolve().parents[2]
FIXTURE_SERVER = Path(__file__).parent / "fixtures" / "server.py"
HEADER = b"Date,Open,High,Low,Close,Volume,Adj Close"

# Newest first, Yahoo_Number values, one `000` volume; rows outside 2016-01-04..08 on both sides.
ROWS = [
    b"2016-01-11,98.970001,99.059998,97.339996,98.529999,49739400,96.004707",
    b"2016-01-08,98.550003,99.110001,96.760002,96.959999,70798000,94.474945",
    b"2016-01-07,98.68,100.129997,96.43,96.449997,81094400,93.977997",
    b"2016-01-06,100.559998,102.370003,99.870003,100.699997,000,98.11907",
    b"2016-01-05,105.75,105.849998,102.410004,102.709999,55791000,100.077571",
    b"2016-01-04,102.610001,105.370003,102.00,105.349998,67649400,102.649994",
    b"2015-12-31,107.010002,107.029999,104.82,105.260002,40912300,102.562301",
]
DONOR_BYTES = HEADER + b"\n" + b"\n".join(ROWS) + b"\n"
DEMO_ROWS = ROWS[1:6]
ENTRY = DonorEntry(
    symbol="AAPL",
    file="AAPL.csv",
    source_url="https://web.archive.org/web/20160112000000id_/http://ichart.yahoo.com/table.csv?s=AAPL",
    host="ichart.yahoo.com",
    served_timestamp="20160112000000",
    sha256="0" * 64,
    rows=len(ROWS),
    first_date="2015-12-31",
    last_date="2016-01-11",
)
GOOD_BODY = HEADER + b"\n" + b"".join(row + b"\n" for row in DEMO_ROWS)
GOOD_HEADERS = {
    "content-type": "text/csv; charset=utf-8",
    "x-revenant-donor": check.donor_header(ENTRY),
}


def _slug_dir(tmp_path: Path) -> Path:
    slug_dir = tmp_path / "crypt" / "yahoo-finance-ichart"
    (slug_dir / "donor").mkdir(parents=True)
    shutil.copyfile(FIXTURE_SERVER, slug_dir / "server.py")
    (slug_dir / "donor" / "AAPL.csv").write_bytes(DONOR_BYTES)
    index = DonorIndex(slug="yahoo-finance-ichart", entries={"AAPL": ENTRY})
    (slug_dir / "donor" / "index.json").write_bytes(dump_model(index))
    (slug_dir / "error-404.html").write_bytes(b"<html><body>404 Not Found</body></html>\n")
    return slug_dir


def _response(
    status: int = 200, body: bytes = GOOD_BODY, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(
        status, content=body, headers=GOOD_HEADERS if headers is None else headers
    )


def test_demo_check_passes_against_fixture_server(tmp_path: Path) -> None:
    slug_dir = _slug_dir(tmp_path)
    port = check.free_port()
    proc = check.serve(slug_dir, port, REPO)
    try:
        check.wait_ready(proc, port)
        response = check.request(port, check.DEMO_PATH)
        result = check.eval_demo(response, ENTRY, DONOR_BYTES)
    finally:
        check.stop(proc)
    assert result.name == "demo"
    assert result.result == "pass", result
    assert proc.poll() is not None


def test_wait_ready_fails_when_server_exits_first(tmp_path: Path) -> None:
    slug_dir = _slug_dir(tmp_path)
    (slug_dir / "donor" / "index.json").unlink()  # the fixture server fails on import
    port = check.free_port()
    proc = check.serve(slug_dir, port, REPO)
    try:
        with pytest.raises(ReanimateError, match="exited"):
            check.wait_ready(proc, port)
    finally:
        check.stop(proc)
    assert proc.poll() is not None


def test_eval_demo_passes_good_response() -> None:
    assert check.eval_demo(_response(), ENTRY, DONOR_BYTES).result == "pass"


def test_eval_demo_wrong_status() -> None:
    result = check.eval_demo(_response(status=404), ENTRY, DONOR_BYTES)
    assert result.result == "fail"
    assert result.expected == "status 200"
    assert result.observed == "status 404"


def test_eval_demo_reformatted_row() -> None:
    reformatted = GOOD_BODY.replace(b",000,", b",0,")
    result = check.eval_demo(_response(body=reformatted), ENTRY, DONOR_BYTES)
    assert result.result == "fail"
    assert result.expected is not None and "000" in result.expected
    assert result.observed is not None and ",0," in result.observed


def test_eval_demo_missing_row() -> None:
    missing = HEADER + b"\n" + b"".join(row + b"\n" for row in DEMO_ROWS[:-1])
    result = check.eval_demo(_response(body=missing), ENTRY, DONOR_BYTES)
    assert result.result == "fail"
    assert result.expected == "5 Data_Rows"
    assert result.observed == "4 Data_Rows"


def test_eval_demo_wrong_donor_header() -> None:
    headers = {"content-type": "text/csv", "x-revenant-donor": "wayback:example.org/1"}
    result = check.eval_demo(_response(headers=headers), ENTRY, DONOR_BYTES)
    assert result.result == "fail"
    assert result.expected == f"X-Revenant-Donor {check.donor_header(ENTRY)}"
    assert result.observed is not None and "example.org" in result.observed


def test_eval_demo_no_response() -> None:
    result = check.eval_demo(None, ENTRY, DONOR_BYTES)
    assert result.result == "fail"
    assert result.observed == "no response"


def test_run_checks_passes_all_against_fixture_server(tmp_path: Path) -> None:
    slug_dir = _slug_dir(tmp_path)
    index = DonorIndex(slug="yahoo-finance-ichart", entries={"AAPL": ENTRY})
    results = check.run_checks(slug_dir, REPO, index, limits=check.Limits(ready=20.0))
    assert {name: r.result for name, r in results.items()} == {
        "demo": "pass",
        "unknown_symbol": "pass",
        "weekly": "pass",
    }


def test_unknown_symbol_avoids_donor_symbols() -> None:
    symbol = check.unknown_symbol([check.UNKNOWN_SYMBOL, "AAPL"])
    assert symbol not in {check.UNKNOWN_SYMBOL, "AAPL"}
    assert check.unknown_path(symbol).startswith(f"/table.csv?s={symbol}&a=0")


def test_eval_unknown() -> None:
    html = {"content-type": "text/html; charset=utf-8"}
    assert check.eval_unknown(_response(404, b"<html/>", html)).result == "pass"
    wrong = check.eval_unknown(_response(200))
    assert (wrong.name, wrong.result, wrong.observed) == ("unknown_symbol", "fail", "status 200")
    csv = check.eval_unknown(_response(404, b"", {"content-type": "text/csv"}))
    assert csv.result == "fail" and csv.expected == "Content-Type text/html"
    assert check.eval_unknown(None).observed == "no response"


def test_eval_weekly() -> None:
    noted = {"content-type": "text/html", "x-revenant-note": "interval w is not reanimated yet"}
    assert check.eval_weekly(_response(404, b"", noted)).result == "pass"
    bare = check.eval_weekly(_response(404, b"", {"content-type": "text/html"}))
    assert (bare.name, bare.result) == ("weekly", "fail")
    assert bare.observed == "no X-Revenant-Note"
    assert check.eval_weekly(_response(200)).observed == "status 200"
    assert check.eval_weekly(None).result == "fail"


FIXTURES = Path(__file__).parent / "fixtures"
SHORT = check.Limits(ready=20.0, request=5.0, stop=5.0)


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[subprocess.Popen[bytes]]:
    """Every server process `run_checks` starts, so a test can assert none remains (Req 6.5)."""
    procs: list[subprocess.Popen[bytes]] = []
    original = check.serve

    def spy(*args, **kwargs):
        procs.append(original(*args, **kwargs))
        return procs[-1]

    monkeypatch.setattr(check, "serve", spy)
    return procs


# (variant, Limits, expected result per Check, the printed failure line as a regex)
MISBEHAVING = [
    pytest.param(
        "server_silent.py",
        check.Limits(ready=2.0, request=5.0, stop=5.0),
        {"demo": "fail", "unknown_symbol": "not_run", "weekly": "not_run"},
        r"demo: expected server answering, observed Revenant_Server did not answer within 2 seconds",
        id="never-answers",
    ),
    pytest.param(
        "server_import_error.py",
        SHORT,
        {"demo": "fail", "unknown_symbol": "not_run", "weekly": "not_run"},
        r"demo: expected server answering, observed Revenant_Server exited with code -?\d+ "
        r"before answering",
        id="exits-on-import",
    ),
    pytest.param(
        "server_unknown_200.py",
        SHORT,
        {"demo": "pass", "unknown_symbol": "fail", "weekly": "pass"},
        r"unknown_symbol: expected status 404, observed status 200",
        id="unknown-symbol-200",
    ),
    pytest.param(
        "server_no_note.py",
        SHORT,
        {"demo": "pass", "unknown_symbol": "pass", "weekly": "fail"},
        r"weekly: expected a non-empty X-Revenant-Note, observed no X-Revenant-Note",
        id="no-revenant-note",
    ),
]


@pytest.mark.parametrize(("variant", "limits", "expected", "line"), MISBEHAVING)
def test_run_checks_records_misbehaving_server(
    tmp_path: Path,
    served: list[subprocess.Popen[bytes]],
    variant: str,
    limits: check.Limits,
    expected: dict[str, str],
    line: str,
) -> None:
    """Req 6.1, 6.3-6.6: each Check gets pass, fail or not_run; the server is always stopped."""
    slug_dir = _slug_dir(tmp_path)
    shutil.copyfile(FIXTURES / variant, slug_dir / "server.py")
    index = DonorIndex(slug="yahoo-finance-ichart", entries={"AAPL": ENTRY})

    results = check.run_checks(slug_dir, REPO, index, limits=limits)

    assert {name: r.result for name, r in results.items()} == expected
    assert [re.fullmatch(line, f) is not None for f in check.failures(results)] == [True]
    assert len(served) == 1 and served[0].poll() is not None


def _ide_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str, limits: check.Limits
) -> tuple[Path, Result]:
    """A `--built-by kiro-ide-chat` run (Req 4.2) of a misbehaving server through the CLI."""
    monkeypatch.delenv("KIRO_API_KEY", raising=False)
    error_page, _ = runner._error_capture(
        REPO, tr.SLUG, load_contract(contract_path(REPO / "crypt", tr.SLUG))
    )
    for path in (
        REPO / "tombstones" / f"{tr.SLUG}.toml",
        contract_path(REPO / "crypt", tr.SLUG),
        spec_path(REPO / ".kiro" / "specs", tr.SLUG),
        REPO / "evidence" / tr.SLUG / "index.json",
        error_page,
    ):
        tr._copy(path, tmp_path / path.relative_to(REPO))
    slug_dir = tmp_path / "crypt" / tr.SLUG
    shutil.copyfile(FIXTURES / variant, slug_dir / "server.py")
    (slug_dir / "reanimate-prompt.md").write_bytes(b"# prompt pasted into Kiro IDE chat\n")
    deps = runner.Deps(
        kiro=KiroCli([sys.executable, str(tr.FAKE_KIRO)]),
        transport=httpx.MockTransport(tr.MockArchive().handler),
        clock=tr.NoSleepClock(),
        repo_root=tmp_path,
        check_limits=limits,
    )
    monkeypatch.setattr(cli, "Deps", lambda: deps)
    args = ["reanimate", tr.SLUG, "--built-by", "kiro-ide-chat"]
    return slug_dir, CliRunner().invoke(cli.app, args)


@pytest.mark.parametrize(("variant", "limits", "expected", "line"), MISBEHAVING)
def test_runner_exits_1_and_prints_failed_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    served: list[subprocess.Popen[bytes]],
    variant: str,
    limits: check.Limits,
    expected: dict[str, str],
    line: str,
) -> None:
    """Req 6.6: expected and observed values printed, every result recorded, no success, exit 1."""
    slug_dir, result = _ide_run(tmp_path, monkeypatch, variant, limits)

    assert result.exit_code == 1, result.output
    assert re.search(r"error: check: failed Check\(s\): " + line, result.stderr), result.stderr
    assert "check demo: pass" not in result.stdout  # no success summary
    assert "build path:" not in result.stdout
    record = BuildRecord.model_validate_json((slug_dir / "reanimate.json").read_bytes())
    assert record.build_path == "kiro-ide-chat"
    assert {name: r.result if r else None for name, r in record.checks.items()} == expected
    assert len(served) == 1 and served[0].poll() is not None


def test_stop_force_terminates_a_server_that_ignores_the_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Req 6.5: a server that will not stop is force-terminated after the stop wait.

    Platform caveat: on POSIX `terminate()` sends SIGTERM, which the fixture ignores, so `stop`
    must fall through to `kill()`. On Windows `terminate()` is already TerminateProcess (a hard
    kill), so the process exits within the wait and `kill()` is never needed.
    """
    slug_dir = _slug_dir(tmp_path)
    shutil.copyfile(FIXTURES / "server_stubborn.py", slug_dir / "server.py")
    kills: list[int] = []
    original_kill = subprocess.Popen.kill

    def spy_kill(self: subprocess.Popen[bytes]) -> None:
        kills.append(self.pid)
        original_kill(self)

    monkeypatch.setattr(subprocess.Popen, "kill", spy_kill)
    port = check.free_port()
    proc = check.serve(slug_dir, port, REPO)
    try:
        check.wait_ready(proc, port, timeout=20.0)
        assert check.eval_demo(
            check.request(port, check.DEMO_PATH), ENTRY, DONOR_BYTES
        ).observed == ("status 503")
    finally:
        check.stop(proc, timeout=1.0)

    assert proc.poll() is not None
    assert kills == ([] if sys.platform == "win32" else [proc.pid])


def test_failures_lists_expected_and_observed() -> None:
    results = {
        "demo": check.CheckResult(name="demo", result="pass"),
        "unknown_symbol": check.eval_unknown(_response(200)),
        "weekly": check.not_run("weekly"),
    }
    assert check.failures(results) == ["unknown_symbol: expected status 404, observed status 200"]
