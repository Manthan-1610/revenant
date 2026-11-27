"""Happy-path and exit-code tests for the Reanimate Runner (Req 1.1-1.6, 3.3, 3.5, 4.4, 4.6, 7.6).

One test (or parametrized case) per row of the design's Error Handling table: missing input (2),
kiro-cli preflight (2), required donor missing (1), kiro-cli build failure (1), scope change and
audit violation (1); Check failures (row 6) belong to task 9.

Offline: the Archive is an `httpx.MockTransport`, kiro-cli is `tests/reanimate/fake_kiro.py`, and the
repo is a `tmp_path` copy holding only the Runner's inputs. No AAPL capture in `evidence/` is both a
donor candidate and accepted (see `test_donor.py`), so the mock serves a synthetic AAPL full-history
body shaped like Yahoo's 2016 captures; the archived 404 page is the real one from `evidence/`.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
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
from revenant.reanimate.redact import Redactor

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
        self.serve_aapl = True  # False: the CDX listings hold no AAPL donor candidate

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/cdx/search/cdx":
            page: list[list[str]] = [CDX_HEADER]
            if self.serve_aapl and request.url.params.get("url", "").startswith(AAPL_HOST + "/"):
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
    spy(runner, "run_checks", "check")
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
    # The committed Tombstone also lists optional symbols the mock archive does not serve.
    assert "donors missing: MSFT, ^GSPC, YHOO" in result.output
    assert "build path: kiro-cli-headless" in result.output
    assert "check demo: pass" in result.output
    assert "check unknown_symbol: pass" in result.output
    assert "check weekly: pass" in result.output

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
    assert all(result is not None and result.result == "pass" for result in record.checks.values())
    assert set(record.checks) == {"demo", "unknown_symbol", "weekly"}
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
    assert deps.redactor(contract.as_posix()) in result.stderr  # Req 7.2: Home_Path shown as ~
    assert stages == ["preflight"]
    assert archive.requests == []
    assert not argv_file.exists()  # kiro-cli never ran
    assert not (repo / "crypt" / SLUG).exists() or not any((repo / "crypt" / SLUG).iterdir())


@pytest.mark.parametrize(
    ("mode", "exit_code", "timed_out", "note"),
    [
        ("fail", 1, False, "kiro-cli exited with code 1"),
        ("sleep", None, True, "kiro-cli was stopped after 1 seconds"),
        ("noserver", 0, False, "kiro-cli wrote no server"),
    ],
)
def test_kiro_build_failure_exits_1_keeps_workspace_and_records(
    repo: Path,
    deps: runner.Deps,
    stages: list[str],
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    exit_code: int | None,
    timed_out: bool,
    note: str,
) -> None:
    """Req 3.5, 4.4, 1.6: kiro-cli non-zero, timeout or no server.py -> exit 1, record, no Check."""
    monkeypatch.setenv("FAKE_KIRO_MODE", mode)
    monkeypatch.setenv("FAKE_KIRO_SLEEP", "30")
    short = dataclasses.replace(deps, chat_timeout=1.0)
    workspaces: list[Path] = []
    make = build.make_workspace
    monkeypatch.setattr(
        build, "make_workspace", lambda *a: workspaces.append(make(*a)) or workspaces[-1]
    )

    try:
        result = _invoke(monkeypatch, short)

        assert result.exit_code == 1, result.output
        assert f"error: build: {note}; workspace kept at " in result.stderr
        assert "copy_back" not in stages and "check" not in stages
        assert "check demo" not in result.output and "reanimate:" not in result.output
        slug_dir = repo / "crypt" / SLUG
        assert not (slug_dir / "server.py").exists()
        record = BuildRecord.model_validate_json((slug_dir / "reanimate.json").read_bytes())
        assert record.build_path == "kiro-cli-headless"
        assert record.kiro_version is not None and record.kiro_version.startswith("kiro-cli 3.5.0")
        assert record.kiro_exit_code == exit_code and record.timed_out is timed_out
        assert record.note == note
        assert record.model == "fake-model-1"  # reported before the stub misbehaved
        assert record.started_at.endswith("Z") and record.ended_at.endswith("Z")
        assert record.scope_changes == [] and record.import_violations == []
        assert record.checks == {"demo": None, "unknown_symbol": None, "weekly": None}
        prompt_bytes = (slug_dir / "reanimate-prompt.md").read_bytes()
        assert record.prompt_sha256 == hashlib.sha256(prompt_bytes).hexdigest()
        log = (slug_dir / "reanimate.log").read_text(encoding="utf-8")
        if mode == "fail":
            assert "stderr: stub failure" in log
        assert len(workspaces) == 1 and workspaces[0].exists()  # Req 3.5: kept on failure
        shown = result.stderr.split("workspace kept at ", 1)[1].strip()
        if workspaces[0].resolve().is_relative_to(Path.home().resolve()):
            assert shown.startswith("~"), shown
        assert shown.endswith(workspaces[0].name)
    finally:
        for workspace in workspaces:
            shutil.rmtree(workspace, ignore_errors=True)


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("not-on-path", "kiro-cli is not on the PATH"),
        ("whoami-fail", "kiro-cli whoami failed"),
        ("version-fail", "kiro-cli --version exited with code 3"),
        ("version-empty", "kiro-cli --version printed nothing"),
        ("version-slow", "kiro-cli --version ran longer than 0.5 seconds"),
    ],
)
def test_kiro_preflight_failure_exits_2_before_any_request(
    repo: Path,
    archive: MockArchive,
    deps: runner.Deps,
    stages: list[str],
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    message: str,
) -> None:
    """Req 3.3, 4.6: kiro-cli missing, logged out or versionless -> exit 2 naming the fallbacks."""
    if mode == "not-on-path":
        monkeypatch.setattr(deps.kiro, "command", [str(repo / "no-such-kiro-cli")])
    else:
        monkeypatch.setenv("FAKE_KIRO_MODE", mode)
    monkeypatch.setenv("FAKE_KIRO_SLEEP", "30")
    monkeypatch.setattr(deps.kiro, "version", functools.partial(deps.kiro.version, timeout=0.5))

    result = _invoke(monkeypatch, deps)

    assert result.exit_code == 2, result.output
    assert f"error: kiro: {message}" in result.stderr
    assert "--built-by kiro-ide-chat" in result.stderr
    if mode in ("not-on-path", "whoami-fail"):
        assert "--prompt-only" in result.stderr
    assert stages == ["preflight", "kiro_preflight"]
    assert archive.requests == []
    slug_dir = repo / "crypt" / SLUG
    assert not (slug_dir / "reanimate.json").exists()
    assert not (slug_dir / "reanimate-prompt.md").exists()


def test_required_donor_missing_exits_1_before_the_build(
    repo: Path,
    archive: MockArchive,
    deps: runner.Deps,
    stages: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Req 2.6: no qualifying AAPL capture -> exit 1 naming it; no prompt, build or record."""
    archive.serve_aapl = False
    argv_file = repo / "argv.json"
    monkeypatch.setenv("FAKE_KIRO_ARGV", str(argv_file))

    result = _invoke(monkeypatch, deps)

    assert result.exit_code == 1, result.output
    assert "error: donor: required donor missing:" in result.stderr
    assert "AAPL" in result.stderr
    assert stages == ["preflight", "kiro_preflight", "donors"]
    assert archive.requests  # the CDX listings were asked
    assert json.loads(argv_file.read_text(encoding="utf-8")) == ["--version"]  # no chat
    slug_dir = repo / "crypt" / SLUG
    assert not (slug_dir / "reanimate.json").exists()
    assert not (slug_dir / "reanimate-prompt.md").exists()
    assert not (slug_dir / "server.py").exists()


@pytest.mark.parametrize(
    ("mode", "target", "change"),
    [
        ("touch-repo", "intruder.txt", "created"),
        ("delete-repo", f"tombstones/{SLUG}.toml", "deleted"),
    ],
)
def test_repo_change_during_chat_exits_1_with_no_check(
    repo: Path,
    deps: runner.Deps,
    stages: list[str],
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    target: str,
    change: str,
) -> None:
    """Req 7.1: a file created or deleted while kiro-cli ran is listed, recorded and left as is."""
    monkeypatch.setenv("FAKE_KIRO_MODE", mode)
    monkeypatch.setenv("FAKE_KIRO_TARGET", str(repo / target))
    workspaces: list[Path] = []
    make = build.make_workspace
    monkeypatch.setattr(
        build, "make_workspace", lambda *a: workspaces.append(make(*a)) or workspaces[-1]
    )

    try:
        result = _invoke(monkeypatch, deps)

        assert result.exit_code == 1, result.output
        assert "error: scope:" in result.stderr
        assert f"{target} ({change})" in result.stderr
        assert "copy_back" not in stages and "check" not in stages
        assert "check demo" not in result.output
        slug_dir = repo / "crypt" / SLUG
        assert not (slug_dir / "server.py").exists()  # no copy-back
        assert (repo / target).exists() == (change == "created")  # left as it is
        record = BuildRecord.model_validate_json((slug_dir / "reanimate.json").read_bytes())
        assert [(c.path, c.change) for c in record.scope_changes] == [(target, change)]
        assert record.checks["demo"] is None
    finally:
        for workspace in workspaces:
            shutil.rmtree(workspace, ignore_errors=True)


def test_audit_violation_exits_1_with_no_check(
    repo: Path,
    deps: runner.Deps,
    stages: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Req 7.4: a copied-back server.py with a disallowed import is recorded and not Checked."""
    original = build.copy_back

    def bad_copy_back(workspace: Path, slug_dir: Path) -> Path:
        (workspace / "server.py").write_text("import requests\n", encoding="utf-8")
        return original(workspace, slug_dir)

    monkeypatch.setattr(build, "copy_back", bad_copy_back)

    result = _invoke(monkeypatch, deps)

    assert result.exit_code == 1, result.output
    assert "error: audit:" in result.stderr and "`requests`" in result.stderr
    assert "check" not in stages
    slug_dir = repo / "crypt" / SLUG
    record = BuildRecord.model_validate_json((slug_dir / "reanimate.json").read_bytes())
    assert record.import_violations and all(str(repo) not in v for v in record.import_violations)
    assert any("requests" in v for v in record.import_violations)
    assert record.checks["demo"] is None


FAKE_KEY = "fake-kiro-key-0123456789abcdef"
FAKE_EMAIL = "ghost@example.invalid"
FAKE_HOME_NAME = "ghostuser"


def test_secrets_never_reach_write_scope_or_console(
    repo: Path, deps: runner.Deps, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Req 7.2: a stub printing a key, an email and the Home_Path in every spelling leaks none."""
    home = f"C:\\Users\\{FAKE_HOME_NAME}" if sys.platform == "win32" else f"/home/{FAKE_HOME_NAME}"
    monkeypatch.setenv("KIRO_API_KEY", FAKE_KEY)
    monkeypatch.setenv("FAKE_KIRO_MODE", "leak")
    monkeypatch.setenv("FAKE_KIRO_HOME", home)
    leaky = dataclasses.replace(deps, redactor=Redactor(FAKE_KEY, home))

    result = _invoke(monkeypatch, leaky)

    assert result.exit_code == 0, result.output
    slug_dir = repo / "crypt" / SLUG
    texts = {path: data.decode("utf-8", "replace") for path, data in _tree(slug_dir).items()}
    texts["<stdout>"] = result.stdout
    texts["<stderr>"] = result.stderr
    for name, text in texts.items():
        for secret in (FAKE_KEY, FAKE_EMAIL):
            assert secret not in text, (name, secret)
        assert FAKE_HOME_NAME not in text.lower(), name
    log = texts["reanimate.log"]
    assert log.count("[REDACTED]") >= 2 and "~" in log  # the stub really printed the secrets
    record = BuildRecord.model_validate_json((slug_dir / "reanimate.json").read_bytes())
    assert record.kiro_version is not None and "[REDACTED]" in record.kiro_version
    prompt_bytes = (slug_dir / "reanimate-prompt.md").read_bytes()
    assert record.prompt_sha256 == hashlib.sha256(prompt_bytes).hexdigest()


# --- IDE fallback options (task 8.2, Req 4.1, 4.2, 4.3) ---


def _invoke_args(monkeypatch: pytest.MonkeyPatch, deps: runner.Deps, *args: str):
    monkeypatch.setattr(cli, "Deps", lambda: deps)
    return CliRunner().invoke(cli.app, ["reanimate", SLUG, *args])


def test_prompt_only_passes_without_kiro_cli(
    repo: Path,
    archive: MockArchive,
    deps: runner.Deps,
    stages: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Req 4.1: --prompt-only fetches donors, writes the prompt and prints its path; no kiro, no Check."""
    monkeypatch.setattr(deps.kiro, "command", [str(repo / "no-such-kiro-cli")])
    assert not deps.kiro.available()

    result = _invoke_args(monkeypatch, deps, "--prompt-only")

    assert result.exit_code == 0, result.output
    assert stages == ["preflight", "donors", "prompt"]
    prompt_rel = f"crypt/{SLUG}/reanimate-prompt.md"
    assert f"prompt: {prompt_rel}" in result.output
    assert "check demo" not in result.output
    slug_dir = repo / "crypt" / SLUG
    assert (repo / prompt_rel).is_file()
    assert not (slug_dir / "server.py").exists()
    assert not (slug_dir / "reanimate.json").exists()
    assert archive.requests


def _place_ide_build(slug_dir: Path) -> tuple[bytes, bytes]:
    """Stand in for a Kiro IDE chat build: the fixture server and a prompt already on disk."""
    server = (FAKE_KIRO.parent / "fixtures" / "server.py").read_bytes()
    prompt = b"# prompt pasted into Kiro IDE chat\n"
    slug_dir.mkdir(parents=True, exist_ok=True)
    (slug_dir / "server.py").write_bytes(server)
    (slug_dir / "reanimate-prompt.md").write_bytes(prompt)
    return server, prompt


def test_built_by_ide_chat_checks_without_kiro_and_keeps_files(
    repo: Path,
    deps: runner.Deps,
    stages: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Req 4.2: server.py and the prompt stay byte-identical; record kiro-ide-chat with nulls."""
    slug_dir = repo / "crypt" / SLUG
    server, prompt = _place_ide_build(slug_dir)
    argv_file = repo / "argv.json"
    monkeypatch.setenv("FAKE_KIRO_ARGV", str(argv_file))

    result = _invoke_args(monkeypatch, deps, "--built-by", "kiro-ide-chat")

    assert result.exit_code == 0, result.output
    assert stages == ["preflight", "donors", "check"]
    assert not argv_file.exists()  # kiro-cli never invoked
    assert "build path: kiro-ide-chat" in result.output
    assert "check demo: pass" in result.output
    assert (slug_dir / "server.py").read_bytes() == server
    assert (slug_dir / "reanimate-prompt.md").read_bytes() == prompt
    raw = json.loads((slug_dir / "reanimate.json").read_bytes())
    assert raw["build_path"] == "kiro-ide-chat"
    assert raw["kiro_version"] is None and raw["kiro_exit_code"] is None and raw["model"] is None
    assert raw["prompt_sha256"] == hashlib.sha256(prompt).hexdigest()
    assert raw["checks"]["demo"]["result"] == "pass"


@pytest.mark.parametrize(
    "missing",
    [("server.py",), ("reanimate-prompt.md",), ("server.py", "reanimate-prompt.md")],
)
def test_built_by_ide_chat_missing_files_exit_2(
    repo: Path,
    archive: MockArchive,
    deps: runner.Deps,
    stages: list[str],
    monkeypatch: pytest.MonkeyPatch,
    missing: tuple[str, ...],
) -> None:
    """Req 4.3: each missing file is named; no Check, no Build_Record, exit 2."""
    slug_dir = repo / "crypt" / SLUG
    _place_ide_build(slug_dir)
    for name in missing:
        (slug_dir / name).unlink()

    result = _invoke_args(monkeypatch, deps, "--built-by", "kiro-ide-chat")

    assert result.exit_code == 2, result.output
    assert "error: ide-chat:" in result.stderr
    for name in missing:
        assert f"crypt/{SLUG}/{name}" in result.stderr
    for name in {"server.py", "reanimate-prompt.md"} - set(missing):
        assert f"crypt/{SLUG}/{name}" not in result.stderr
    assert stages == ["preflight"]
    assert archive.requests == []
    assert not (slug_dir / "reanimate.json").exists()


def test_help_lists_both_ide_fallback_options() -> None:
    result = CliRunner().invoke(cli.app, ["reanimate", "--help"])

    assert result.exit_code == 0, result.output
    assert "--prompt-only" in result.output
    assert "--built-by" in result.output
