"""Example tests for the Reanimate_Prompt (Req 3.1, 7.2)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from revenant.reanimate.prompt import PROMPT_NAME, SERVER_RULES, render_prompt, write_prompt
from revenant.reanimate.record import DonorEntry

REPO = Path(__file__).resolve().parents[2]
GEN_CITATION = re.compile(r"\(Gen \d+\.\d+(?:, \d+\.\d+)*\)\.?$")
FILE_TOKEN = re.compile(r"`([^`\s]+\.(?:md|json|html|py|csv))`")
ALLOWED_FILES = {
    "requirements.md",
    "contract.json",
    "donor/index.json",
    "error-404.html",
    "server.py",
    "donor/AAPL.csv",
}

AAPL = DonorEntry(
    symbol="AAPL",
    file="AAPL.csv",
    source_url="https://web.archive.org/web/20160109000000id_/http://ichart.yahoo.com/table.csv?s=AAPL",
    host="ichart.yahoo.com",
    served_timestamp="20160109000000",
    sha256="0" * 64,
    rows=5,
    first_date="2016-01-04",
    last_date="2016-01-08",
)


@pytest.fixture(autouse=True)
def _offline_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KIRO_API_KEY", raising=False)


def _prompt() -> str:
    return render_prompt("yahoo-finance-ichart", [AAPL])


def test_prompt_names_only_relative_files() -> None:
    text = _prompt()
    files = set(FILE_TOKEN.findall(text))
    assert {"requirements.md", "contract.json", "donor/index.json", "error-404.html"} <= files
    assert "server.py" in files
    assert files <= ALLOWED_FILES
    assert not re.search(r"[A-Za-z]:[\\/]", text)
    home = Path.home()
    for absolute in (str(home), home.as_posix(), str(REPO), REPO.as_posix()):
        assert absolute not in text
    assert not any(name.startswith(("/", "~")) for name in files)
    assert "web.archive.org" not in text  # the donor source URL is not handed to Kiro


def test_prompt_forbids_tools_and_names_single_output() -> None:
    text = _prompt()
    assert "No shell or command tool is available." in text
    assert "Do not run, test or install anything." in text
    assert "Write exactly one file: `server.py`" in text
    assert "Create, change or delete no other file." in text


def test_every_server_rule_cites_gen() -> None:
    text = _prompt()
    for number, rule in enumerate(SERVER_RULES, start=1):
        assert GEN_CITATION.search(rule.strip()), rule
        assert f"{number}. {rule}" in text


def test_write_prompt_replaces_earlier_prompt(tmp_path: Path) -> None:
    (tmp_path / PROMPT_NAME).write_text("old prompt", encoding="utf-8")
    path = write_prompt(tmp_path, _prompt())
    assert path == tmp_path / PROMPT_NAME
    assert path.read_bytes() == _prompt().encode("utf-8")
