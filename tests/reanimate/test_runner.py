"""Happy-path and early-failure tests for the Reanimate Runner (Req 1.1-1.6, 7.6).

Offline: the Archive is an `httpx.MockTransport`, kiro-cli is `tests/reanimate/fake_kiro.py`, and the
repo is a `tmp_path` copy holding only the Runner's inputs. No AAPL capture in `evidence/` is both a
donor candidate and accepted (see `test_donor.py`), so the mock serves a synthetic AAPL full-history
body shaped like Yahoo's 2016 captures; the archived 404 page is the real one from `evidence/`.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from revenant import cli
from revenant.autopsy.contract import contract_path, load_contract
from revenant.autopsy.render import spec_path
from revenant.reanimate import build, runner
from revenant.reanimate.donor import load_donor_index
from revenant.reanimate.kiro import KiroCli
from revenant.reanimate.record import BuildRecord

REPO = Path(__file__).resolve().parents[2]
SLUG = "yahoo-finance-ichart"
FAKE_KIRO = Path(__file__).resolve().parent / "fake_kiro.py"
HEADER = b"Date,Open,High,Low,Close,Volume,Adj Close"
ROWS = [
    b"2016-01-11,98.970001,99.059998,97.339996,98.529999,49739400,96.004707",
    b"2016-01-08,98.550003,99.110001,96.760002,96.959999,70798000,94.474945",
    b"2016-01-07,98.68,100.129997,96.43,96.449997,81094400,93.977997",
    b"2016-01-06,100.559998,102.370003,99.870003,100.699997,000,98.11907",
    b"2016-01-05,105.75,105.849998,102.410004,102.709999,55791000,100.077571",
    b"2016-01-04,102.610001,105.370003,102.00,105.349998,67649400,102.649994",
    b"2015-12-31,107.010002,107.029999,104.82,105.260002,40912300,102.562301",
]
AAPL_BODY = HEADER + b"\n" + b"\n".join(ROWS) + b"\n"
AAPL_HOST = "ichart.yahoo.com"
AAPL_ORIGINAL = f"http://{AAPL_HOST}/table.csv?s=AAPL"
AAPL_TIMESTAMP = "20160112000000"
CDX_HEADER = ["timestamp", "original", "mimetype", "statuscode", "digest", "length"]
WRITE_SCOPE = {
    "contract.json",  # input, copied into the tmp repo
    "server.py",
    "donor/index.json",
    "donor/AAPL.csv",
    "error-404.html",
    "reanimate-prompt.md",
    "reanimate.json",
    "reanimate.log",
}


class NoSleepClock:
    """Clock whose sleep only advances time, so the RateLimiter costs nothing."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def now_utc(self) -> datetime:
        return datetime(2026, 11, 22, tzinfo=UTC)


class MockArchive:
    """CDX pages (one AAPL `s_only` row on ichart.yahoo.com) and the AAPL `id_` capture."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/cdx/search/cdx":
            page: list[list[str]] = [CDX_HEADER]
            if request.url.params.get("url", "").startswith(AAPL_HOST + "/"):
                page.append([AAPL_TIMESTAMP, AAPL_ORIGINAL, "text/csv", "200", "AAPLDIGEST", "600"])
            return httpx.Response(200, json=page)
        wanted = f"/web/{AAPL_TIMESTAMP}id_/{AAPL_ORIGINAL.split('?')[0]}"
        if request.url.path == wanted and request.url.query == b"s=AAPL":
            return httpx.Response(200, content=AAPL_BODY, headers={"Content-Type": "text/csv"})
        return httpx.Response(404, content=b"not archived")


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tmp repo holding the Tombstone, Contract, Generated_Spec, Index and archived 404 page."""
    monkeypatch.delenv("KIRO_API_KEY", raising=False)
    for name in ("FAKE_KIRO_MODE", "FAKE_KIRO_ARGV", "FAKE_KIRO_MODEL"):
        monkeypatch.delenv(name, raising=False)
    error_page, _ = runner._error_capture(
        REPO, SLUG, load_contract(contract_path(REPO / "crypt", SLUG))
    )
    for path in (
        REPO / "tombstones" / f"{SLUG}.toml",
        contract_path(REPO / "crypt", SLUG),
        spec_path(REPO / ".kiro" / "specs", SLUG),
        REPO / "evidence" / SLUG / "index.json",
        error_page,
    ):
        _copy(path, tmp_path / path.relative_to(REPO))
    return tmp_path


@pytest.fixture
def archive() -> MockArchive:
    return MockArchive()


@pytest.fixture
def deps(repo: Path, archive: MockArchive) -> runner.Deps:
    return runner.Deps(
        kiro=KiroCli([sys.executable, str(FAKE_KIRO)]),
        transport=httpx.MockTransport(archive.handler),
        clock=NoSleepClock(),
        repo_root=repo,
        chat_timeout=60.0,
    )


@pytest.fixture
def stages(monkeypatch: pytest.MonkeyPatch, deps: runner.Deps) -> list[str]:
    """Wrap each stage entry point so the test sees the order the Runner calls them in."""
    calls: list[str] = []

    def spy(owner: object, attr: str, label: str) -> None:
        original = getattr(owner, attr)

        def wrapper(*args, **kwargs):
            calls.append(label)
            return original(*args, **kwargs)

        monkeypatch.setattr(owner, attr, wrapper)

    spy(runner, "preflight", "preflight")
    spy(runner, "kiro_preflight", "kiro_preflight")
    spy(runner, "fetch_donors", "donors")
    spy(runner, "write_prompt", "prompt")
    spy(build, "make_workspace", "workspace")
    spy(deps.kiro, "chat", "chat")
    spy(build, "copy_back", "copy_back")
    spy(runner, "run_demo_check", "check")
    return calls


def _invoke(monkeypatch: pytest.MonkeyPatch, deps: runner.Deps):
    monkeypatch.setattr(cli, "Deps", lambda: deps)
    return CliRunner().invoke(cli.app, ["reanimate", SLUG])


def test_happy_path_exits_0_and_writes_every_output(
    repo: Path,
    archive: MockArchive,
    deps: runner.Deps,
    stages: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_before = _tree(repo / "evidence")
    outside_before = {
        path: data for path, data in _tree(repo).items() if not path.startswith("crypt/")
    }
    workspaces: list[Path] = []
    make = build.make_workspace
    monkeypatch.setattr(
        build, "make_workspace", lambda *a: workspaces.append(make(*a)) or workspaces[-1]
    )

    result = _invoke(monkeypatch, deps)

    assert result.exit_code == 0, result.output
    assert stages == [
        "preflight",
        "kiro_preflight",
        "donors",
        "prompt",
        "workspace",
        "chat",
        "copy_back",
        "check",
    ]
    assert "donors stored: AAPL" in result.output
    assert "donors missing: none" in result.output
    assert "build path: kiro-cli-headless" in result.output
    assert "check demo: pass" in result.output

    slug_dir = repo / "crypt" / SLUG
    assert set(_tree(slug_dir)) == WRITE_SCOPE
    fixture = (FAKE_KIRO.parent / "fixtures" / "server.py").read_bytes()
    assert (slug_dir / "server.py").read_bytes() == fixture
    assert (slug_dir / "donor" / "AAPL.csv").read_bytes() == AAPL_BODY
    entry = load_donor_index(slug_dir, SLUG).entries["AAPL"]
    assert entry.host == AAPL_HOST and entry.served_timestamp == AAPL_TIMESTAMP
    _, error_body = runner._error_capture(
        REPO, SLUG, load_contract(contract_path(REPO / "crypt", SLUG))
    )
    assert (slug_dir / "error-404.html").read_bytes() == error_body  # Req 1.3
    prompt = (slug_dir / "reanimate-prompt.md").read_text(encoding="utf-8")
    assert "server.py" in prompt and str(repo) not in prompt

    record = BuildRecord.model_validate_json((slug_dir / "reanimate.json").read_bytes())
    assert record.build_path == "kiro-cli-headless"
    assert record.kiro_version is not None and record.kiro_version.startswith("kiro-cli 3.5.0")
    assert record.kiro_exit_code == 0 and not record.timed_out and record.note is None
    assert record.model == "fake-model-1"
    assert record.checks["demo"] is not None and record.checks["demo"].result == "pass"
    log_lines = (slug_dir / "reanimate.log").read_text(encoding="utf-8").splitlines()
    assert log_lines and all(line.startswith(("stdout: ", "stderr: ")) for line in log_lines)

    # Req 1.3, 1.5: evidence/ gained only CDX listings; nothing else changed outside crypt/.
    evidence_after = _tree(repo / "evidence")
    added = set(evidence_after) - set(evidence_before)
    assert added and all(path.startswith(f"{SLUG}/cdx/") for path in added)
    assert all(evidence_after[path] == data for path, data in evidence_before.items())
    outside_after = {
        path: data
        for path, data in _tree(repo).items()
        if not path.startswith(("crypt/", f"evidence/{SLUG}/cdx/"))
    }
    assert outside_after == outside_before

    # Req 3.6: the Build_Workspace is deleted after the copy-back.
    assert len(workspaces) == 1 and not workspaces[0].exists()
    assert archive.requests  # the donor really came through the mock Archive


def test_missing_contract_exits_2_before_any_request(
    repo: Path,
    archive: MockArchive,
    deps: runner.Deps,
    stages: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = contract_path(repo / "crypt", SLUG)
    contract.unlink()
    argv_file = repo / "argv.json"
    monkeypatch.setenv("FAKE_KIRO_ARGV", str(argv_file))

    result = _invoke(monkeypatch, deps)

    assert result.exit_code == 2, result.output
    assert "error: preflight:" in result.stderr
    assert contract.as_posix() in result.stderr
    assert stages == ["preflight"]
    assert archive.requests == []
    assert not argv_file.exists()  # kiro-cli never ran
    assert not (repo / "crypt" / SLUG).exists() or not any((repo / "crypt" / SLUG).iterdir())


def test_chat_exit_1_exits_1_with_no_check(
    repo: Path,
    deps: runner.Deps,
    stages: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_KIRO_MODE", "fail")
    workspaces: list[Path] = []
    make = build.make_workspace
    monkeypatch.setattr(
        build, "make_workspace", lambda *a: workspaces.append(make(*a)) or workspaces[-1]
    )

    try:
        result = _invoke(monkeypatch, deps)

        assert result.exit_code == 1, result.output
        assert "error: build: kiro-cli exited with code 1" in result.stderr
        assert "check" not in stages and "copy_back" not in stages
        assert "check demo" not in result.output
        slug_dir = repo / "crypt" / SLUG
        assert not (slug_dir / "server.py").exists()
        record = json.loads((slug_dir / "reanimate.json").read_text(encoding="utf-8"))
        assert record["kiro_exit_code"] == 1
        assert record["checks"]["demo"] is None
        log = (slug_dir / "reanimate.log").read_text(encoding="utf-8")
        assert "stderr: stub failure" in log
        assert len(workspaces) == 1 and workspaces[0].exists()  # Req 3.5: kept on failure
    finally:
        for workspace in workspaces:
            shutil.rmtree(workspace, ignore_errors=True)
