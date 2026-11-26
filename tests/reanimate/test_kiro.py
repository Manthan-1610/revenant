"""Example tests for KiroCli, the stub kiro-cli and the fixture server (Req 3.2, 3.4, 3.5, 7.2)."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from revenant.reanimate.errors import ReanimateError
from revenant.reanimate.kiro import CHAT_ARGS, KiroCli

HERE = Path(__file__).resolve().parent
STUB = [sys.executable, str(HERE / "fake_kiro.py")]
WHOAMI_MARKER = "Logged in as ghost (stub)"


@pytest.fixture(autouse=True)
def _offline_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KIRO_API_KEY", raising=False)
    for name in ("FAKE_KIRO_MODE", "FAKE_KIRO_MODEL", "FAKE_KIRO_ARGV", "FAKE_KIRO_SLEEP"):
        monkeypatch.delenv(name, raising=False)


def test_stub_chat_copies_server_and_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    argv_file = tmp_path / "argv.json"
    monkeypatch.setenv("FAKE_KIRO_ARGV", str(argv_file))
    work = tmp_path / "work"
    work.mkdir()
    log = tmp_path / "reanimate.log"
    kiro = KiroCli(STUB)

    assert kiro.available()
    assert kiro.whoami() == 0
    assert kiro.version().startswith("kiro-cli 3.5.0")
    result = kiro.chat(work, log)

    assert (result.exit_code, result.timed_out, result.model) == (0, False, "fake-model-1")
    assert json.loads(argv_file.read_text(encoding="utf-8")) == list(CHAT_ARGS)
    assert (work / "server.py").read_bytes() == (HERE / "fixtures" / "server.py").read_bytes()
    lines = log.read_text(encoding="utf-8").splitlines()
    assert lines and all(line.startswith(("stdout: ", "stderr: ")) for line in lines)
    assert any(line.startswith("stderr: ") for line in lines)


EVENT_LINES = [
    json.dumps({"type": "session_start", "session": "stub"}),
    json.dumps({"type": "session_info", "params": {"modelId": "fake-model-1"}}),
]
THINKING = "thinking → done ✓ \ufffd"  # the stub's invalid \xff byte decodes as U+FFFD


def _streams(log: Path) -> tuple[list[str], list[str]]:
    lines = log.read_text(encoding="utf-8").splitlines()
    assert all(line.startswith(("stdout: ", "stderr: ")) for line in lines)
    out = [line.removeprefix("stdout: ") for line in lines if line.startswith("stdout: ")]
    err = [line.removeprefix("stderr: ") for line in lines if line.startswith("stderr: ")]
    return out, err


def test_build_log_complete_after_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_KIRO_MODE", "fail")
    log = tmp_path / "reanimate.log"
    log.write_text("stdout: earlier run\n", encoding="utf-8")
    result = KiroCli(STUB).chat(tmp_path, log)

    assert (result.exit_code, result.timed_out) == (1, False)
    out, err = _streams(log)
    assert out == [*EVENT_LINES, THINKING]
    assert err == ["stderr note → ✓", "stub failure"]
    assert not (tmp_path / "server.py").exists()


def test_build_log_keeps_partial_output_after_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_KIRO_MODE", "sleep")
    monkeypatch.setenv("FAKE_KIRO_SLEEP", "30")
    log = tmp_path / "reanimate.log"
    started = time.monotonic()
    result = KiroCli(STUB).chat(tmp_path, log, timeout=2.0)

    assert time.monotonic() - started < 15
    assert (result.exit_code, result.timed_out) == (None, True)
    assert result.model == "fake-model-1"
    out, err = _streams(log)
    assert out == [*EVENT_LINES, THINKING]
    assert err == ["stderr note → ✓"]


def test_full_log_with_non_cp1252_bytes(tmp_path: Path) -> None:
    log = tmp_path / "reanimate.log"
    result = KiroCli(STUB).chat(tmp_path, log)
    assert result.exit_code == 0
    out, err = _streams(log)
    assert out == [*EVENT_LINES, THINKING, json.dumps({"type": "end_turn"})]
    assert err == ["stderr note → ✓"]


def test_version_with_non_cp1252_text() -> None:
    assert KiroCli(STUB).version() == "kiro-cli 3.5.0 → fake ✓"


def test_model_is_none_when_no_event_reports_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_KIRO_MODEL", "none")
    result = KiroCli(STUB).chat(tmp_path, tmp_path / "reanimate.log")
    assert result.exit_code == 0 and result.model is None


def test_model_equals_stub_event_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_KIRO_MODEL", "claude-test-42")
    result = KiroCli(STUB).chat(tmp_path, tmp_path / "reanimate.log")
    assert result.model == "claude-test-42"


def test_chat_argv_is_exact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    argv_file = tmp_path / "argv.json"
    monkeypatch.setenv("FAKE_KIRO_ARGV", str(argv_file))
    KiroCli(STUB).chat(tmp_path, tmp_path / "reanimate.log")
    assert json.loads(argv_file.read_text(encoding="utf-8")) == [
        "chat",
        "--v3",
        "--no-interactive",
        "--trust-workspace",
        "--trust-tools=fs_read,fs_write",
        "--output-format",
        "stream-json",
        "Read reanimate-prompt.md in this directory and follow it exactly.",
    ]


def test_whoami_stdout_appears_nowhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    kiro = KiroCli(STUB)
    assert kiro.whoami() == 0
    monkeypatch.setenv("FAKE_KIRO_MODE", "whoami-fail")
    assert kiro.whoami() == 1
    kiro.chat(tmp_path, tmp_path / "reanimate.log")

    captured = capfd.readouterr()
    assert WHOAMI_MARKER not in captured.out + captured.err
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert WHOAMI_MARKER.encode() not in path.read_bytes(), path


def test_version_failures_raise_code_2(monkeypatch: pytest.MonkeyPatch) -> None:
    kiro = KiroCli(STUB)
    for mode in ("version-fail", "version-empty"):
        monkeypatch.setenv("FAKE_KIRO_MODE", mode)
        with pytest.raises(ReanimateError) as info:
            kiro.version()
        assert info.value.code == 2
    monkeypatch.setenv("FAKE_KIRO_MODE", "version-slow")
    monkeypatch.setenv("FAKE_KIRO_SLEEP", "30")
    with pytest.raises(ReanimateError, match="longer than") as info:
        kiro.version(timeout=1.0)
    assert info.value.code == 2


def test_fixture_server_answers_demo_request(tmp_path: Path) -> None:
    donor = tmp_path / "donor"
    donor.mkdir()
    rows = [b"2016-01-08,1,2,3,4,000,5", b"2016-01-04,1,2,3,4,100,5", b"2015-12-31,1,2,3,4,1,5"]
    header = b"Date,Open,High,Low,Close,Volume,Adj Close"
    (donor / "AAPL.csv").write_bytes(header + b"\n" + b"\n".join(rows) + b"\n")
    entry = {"file": "AAPL.csv", "host": "ichart.yahoo.com", "served_timestamp": "20160109000000"}
    index = {"slug": "x", "entries": {"AAPL": entry}}
    (donor / "index.json").write_text(json.dumps(index), encoding="utf-8")
    (tmp_path / "error-404.html").write_bytes(b"<html>404</html>")
    shutil.copyfile(HERE / "fixtures" / "server.py", tmp_path / "server.py")
    spec = importlib.util.spec_from_file_location("fixture_server_smoke", tmp_path / "server.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client = TestClient(module.app)

    ok = client.get("/table.csv?s=AAPL&a=0&b=4&c=2016&d=0&e=8&f=2016&g=d&ignore=.csv")
    assert ok.status_code == 200
    assert ok.content == header + b"\n" + rows[0] + b"\n" + rows[1] + b"\n"
    assert ok.headers["x-revenant-donor"] == "wayback:ichart.yahoo.com/20160109000000"

    weekly = client.get("/table.csv?s=AAPL&g=w")
    assert weekly.status_code == 404 and weekly.headers["x-revenant-note"]
    unknown = client.get("/table.csv?s=NOPE")
    assert unknown.status_code == 404 and unknown.headers["x-revenant-donor"] == "none"
