"""Example tests for the Build_Workspace (Req 3.2, 3.5, 3.6)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from revenant.reanimate.build import copy_back, display, has_server, make_workspace
from revenant.reanimate.errors import ReanimateError
from revenant.reanimate.record import DonorEntry, DonorIndex, dump_model

EXPECTED = {
    "requirements.md",
    "contract.json",
    "donor/index.json",
    "donor/AAPL.csv",
    "error-404.html",
    "reanimate-prompt.md",
}


@pytest.fixture(autouse=True)
def _offline_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KIRO_API_KEY", raising=False)


@pytest.fixture
def slug(tmp_path: Path) -> tuple[Path, Path]:
    slug_dir = tmp_path / "crypt" / "x"
    (slug_dir / "donor").mkdir(parents=True)
    entry = DonorEntry(
        symbol="AAPL",
        file="AAPL.csv",
        source_url="https://web.archive.org/web/20160109000000id_/http://ichart.yahoo.com/table.csv",
        host="ichart.yahoo.com",
        served_timestamp="20160109000000",
        sha256="0" * 64,
        rows=1,
        first_date="2016-01-08",
        last_date="2016-01-08",
    )
    index = DonorIndex(slug="x", entries={"AAPL": entry})
    (slug_dir / "donor" / "index.json").write_bytes(dump_model(index))
    (slug_dir / "donor" / "AAPL.csv").write_bytes(b"Date,Open\r\n2016-01-08,1\n")
    (slug_dir / "donor" / "stray.csv").write_bytes(b"not indexed")
    (slug_dir / "contract.json").write_bytes(b"{}")
    (slug_dir / "error-404.html").write_bytes(b"<html>404</html>")
    (slug_dir / "reanimate-prompt.md").write_bytes(b"# prompt")
    (slug_dir / "reanimate.json").write_bytes(b"{}")
    (slug_dir / "reanimate.log").write_bytes(b"old log")
    (slug_dir / "server.py").write_bytes(b"# old server")
    spec = tmp_path / "spec" / "requirements.md"
    spec.parent.mkdir()
    spec.write_bytes(b"# spec")
    return slug_dir, spec


@pytest.fixture
def workspaces() -> Iterator[list[Path]]:
    made: list[Path] = []
    yield made
    for path in made:
        shutil.rmtree(path, ignore_errors=True)


def _files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def test_workspace_holds_only_listed_files(slug: tuple[Path, Path], workspaces: list[Path]) -> None:
    slug_dir, spec = slug
    workspace = make_workspace(slug_dir, spec)
    workspaces.append(workspace)
    assert workspace.name.startswith("revenant-build-")
    assert not workspace.resolve().is_relative_to(slug_dir.parent.parent.resolve())
    assert _files(workspace) == EXPECTED
    assert (workspace / "requirements.md").read_bytes() == spec.read_bytes()
    for name in EXPECTED - {"requirements.md"}:
        assert (workspace / name).read_bytes() == (slug_dir / name).read_bytes()
    assert not has_server(workspace)


def test_copy_back_is_byte_identical_and_deletes_workspace(
    slug: tuple[Path, Path], workspaces: list[Path]
) -> None:
    slug_dir, spec = slug
    workspace = make_workspace(slug_dir, spec)
    workspaces.append(workspace)
    body = b"# server\r\nprint('\xe2\x86\x92')\n\xff\n"
    (workspace / "server.py").write_bytes(body)
    assert has_server(workspace)
    target = copy_back(workspace, slug_dir)
    assert target == slug_dir / "server.py"
    assert target.read_bytes() == body
    assert not workspace.exists()


def test_failed_build_keeps_workspace(slug: tuple[Path, Path], workspaces: list[Path]) -> None:
    slug_dir, spec = slug
    workspace = make_workspace(slug_dir, spec)
    workspaces.append(workspace)
    with pytest.raises(ReanimateError, match="kiro-cli wrote no server") as info:
        copy_back(workspace, slug_dir)
    assert display(workspace) in str(info.value)
    assert workspace.is_dir() and _files(workspace) == EXPECTED
    assert (slug_dir / "server.py").read_bytes() == b"# old server"


def test_missing_input_raises_and_names_it(slug: tuple[Path, Path]) -> None:
    slug_dir, spec = slug
    (slug_dir / "error-404.html").unlink()
    with pytest.raises(ReanimateError, match="error-404.html"):
        make_workspace(slug_dir, spec)


def test_display_replaces_home() -> None:
    path = Path.home() / "revenant-build-abc"
    assert display(path) == "~" + str(path)[len(str(Path.home())) :]
    assert display(path.as_posix()) == "~/revenant-build-abc"
