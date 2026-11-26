"""Example tests for the import and path audit of `server.py` (Req 7.3, 7.4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from revenant.reanimate.audit import audit
from revenant.reanimate.runner import audit_server

FIXTURE_SERVER = Path(__file__).resolve().parent / "fixtures" / "server.py"
CLEAN_HEAD = "from pathlib import Path\n\nfrom fastapi import FastAPI\n\napp = FastAPI()\n"


def _server(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "server.py"
    path.write_text(source, encoding="utf-8")
    return path


def test_fixture_server_passes() -> None:
    assert audit(FIXTURE_SERVER) == []


def test_style_only_issue_passes(tmp_path: Path) -> None:
    # Long line, odd spacing, single quotes and Optional-free style: not a Pyflakes finding.
    source = CLEAN_HEAD + "X  =  'a'   # " + "x" * 120 + "\nROOT = Path(__file__).parent\n"
    assert audit(_server(tmp_path, source)) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import requests\n", "disallowed import `requests`"),
        ("from httpx import get\n", "disallowed import `httpx`"),
        ("from . import helpers\n", "relative import `.`"),
        ("from .donor import load\n", "relative import `.donor`"),
        ("P = 'evidence/yahoo-finance-ichart/index.json'\n", "path under evidence/"),
        ("P = 'evidence\\\\x.json'\n", "path under evidence/"),
    ],
)
def test_import_and_path_violations_are_named(tmp_path: Path, source: str, expected: str) -> None:
    violations = audit(_server(tmp_path, CLEAN_HEAD + source))
    assert any(expected in v for v in violations), violations


def test_syntax_error_fails_py_compile(tmp_path: Path) -> None:
    violations = audit(_server(tmp_path, CLEAN_HEAD + "def broken(:\n"))
    assert any(v.startswith("py_compile:") for v in violations), violations


def test_undefined_name_fails_ruff_f_check(tmp_path: Path) -> None:
    violations = audit(_server(tmp_path, CLEAN_HEAD + "print(undefined_name)\n"))
    assert any(v.startswith("ruff F:") and "F821" in v for v in violations), violations


def test_audit_server_strips_the_absolute_path(tmp_path: Path) -> None:
    slug_dir = tmp_path / "crypt" / "slug"
    slug_dir.mkdir(parents=True)
    server = _server(slug_dir, CLEAN_HEAD + "print(undefined_name)\n")
    violations = audit_server(server, tmp_path)
    assert violations and all(str(tmp_path) not in v for v in violations)
    assert all(tmp_path.as_posix() not in v for v in violations)
    assert any("crypt/slug/server.py" in v for v in violations), violations
