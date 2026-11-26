"""Tests for the Write_Scope guard in revenant/reanimate/scope.py (Req 7.1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from revenant.reanimate.scope import diff, snapshot

_segment = st.text(alphabet="abcxyz019._-", min_size=1, max_size=6)
_paths = st.lists(_segment, min_size=1, max_size=3).map("/".join)
_hashes = st.text(alphabet="0123456789abcdef", min_size=64, max_size=64)


@st.composite
def _snapshot_and_edits(draw: st.DrawFn) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """A before-snapshot, the after-snapshot, and the expected path -> change type."""
    before = draw(st.dictionaries(_paths, _hashes, max_size=15))
    after = dict(before)
    expected: dict[str, str] = {}
    existing = sorted(before)
    for path in draw(st.lists(st.sampled_from(existing), unique=True) if existing else st.just([])):
        if draw(st.booleans()):
            del after[path]
            expected[path] = "deleted"
        else:
            after[path] = draw(_hashes.filter(lambda h, old=before[path]: h != old))
            expected[path] = "changed"
    for path in draw(st.lists(_paths.filter(lambda p: p not in before), unique=True, max_size=5)):
        after[path] = draw(_hashes)
        expected[path] = "created"
    return before, after, expected


# Feature: reanimate, Property 4: Scope diff is exact
@settings(max_examples=100)
@given(_snapshot_and_edits())
def test_diff_is_exact(case: tuple[dict[str, str], dict[str, str], dict[str, str]]) -> None:
    """**Validates: Requirements 7.1**"""
    before, after, expected = case
    changes = diff(before, after)
    assert [(c.path, c.change) for c in changes] == sorted(expected.items())
    assert diff(before, before) == []
    assert diff(after, after) == []


def _write(root: Path, rel: str, data: bytes = b"x") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


BUILD_LOG = "crypt/yahoo-finance-ichart/reanimate.log"


@pytest.mark.parametrize(
    "rel",
    [
        ".git/HEAD",
        ".venv/Lib/site.py",
        ".hypothesis/examples/abc",
        ".pytest_cache/v/cache/lastfailed",
        ".ruff_cache/0.1/cache",
        "revenant/reanimate/__pycache__/scope.cpython-312.pyc",
        BUILD_LOG,
    ],
)
def test_excluded_locations_yield_no_change(tmp_path: Path, rel: str) -> None:
    _write(tmp_path, "README.md", b"readme")
    _write(tmp_path, rel, b"before")
    before = snapshot(tmp_path, exclude=[BUILD_LOG])
    _write(tmp_path, rel, b"after")
    if rel != BUILD_LOG:  # the Build_Log exclusion covers that one file, not its siblings
        _write(tmp_path, str(Path(rel).parent / "created.new"), b"created")
    assert diff(before, snapshot(tmp_path, exclude=[BUILD_LOG])) == []


@pytest.mark.parametrize(
    "rel",
    [
        "README.md",
        "crypt/yahoo-finance-ichart/server.py",
        "tests/.venv/lib.py",
        "sub/.git/HEAD",
    ],
)
def test_other_files_are_reported(tmp_path: Path, rel: str) -> None:
    _write(tmp_path, rel, b"before")
    before = snapshot(tmp_path, exclude=[BUILD_LOG])
    assert rel in before
    _write(tmp_path, rel, b"after")
    _write(tmp_path, "new/file.txt", b"created")
    changes = diff(before, snapshot(tmp_path, exclude=[BUILD_LOG]))
    assert [(c.path, c.change) for c in changes] == sorted(
        [(rel, "changed"), ("new/file.txt", "created")]
    )


def test_deleted_file_is_reported(tmp_path: Path) -> None:
    _write(tmp_path, "a/b.txt")
    before = snapshot(tmp_path)
    (tmp_path / "a" / "b.txt").unlink()
    changes = diff(before, snapshot(tmp_path))
    assert [(c.path, c.change) for c in changes] == [("a/b.txt", "deleted")]
