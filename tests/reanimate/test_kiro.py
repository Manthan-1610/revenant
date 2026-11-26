"""Smoke tests for KiroCli, the stub kiro-cli and the fixture server (task 2.2; task 2.4 expands)."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from revenant.reanimate.kiro import CHAT_ARGS, KiroCli

HERE = Path(__file__).resolve().parent
STUB = [sys.executable, str(HERE / "fake_kiro.py")]


@pytest.fixture(autouse=True)
def _offline_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KIRO_API_KEY", raising=False)
    monkeypatch.delenv("FAKE_KIRO_MODE", raising=False)


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
