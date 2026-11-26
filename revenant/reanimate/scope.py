"""Write_Scope guard: hash every repository file before and after kiro-cli runs (Req 7.1)."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable, Mapping
from pathlib import Path

from revenant.reanimate.record import ScopeChange

# Skipped only directly under the repository root.
ROOT_EXCLUDED_DIRS = frozenset({".git", ".venv", ".hypothesis", ".pytest_cache", ".ruff_cache"})
# Skipped at any depth.
ANY_DEPTH_EXCLUDED_DIRS = frozenset({"__pycache__"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(root: Path, exclude: Iterable[str] = ()) -> dict[str, str]:
    """Map each file's POSIX path relative to `root` to its SHA-256.

    `exclude` holds extra POSIX paths relative to `root` to skip (the Build_Log).
    Symlinked directories are not followed.
    """
    skipped = set(exclude)
    result: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        at_root = current == root
        dirnames[:] = [
            name
            for name in dirnames
            if name not in ANY_DEPTH_EXCLUDED_DIRS and not (at_root and name in ROOT_EXCLUDED_DIRS)
        ]
        for name in filenames:
            path = current / name
            rel = path.relative_to(root).as_posix()
            if rel in skipped:
                continue
            result[rel] = _sha256(path)
    return result


def diff(before: Mapping[str, str], after: Mapping[str, str]) -> list[ScopeChange]:
    """Every created, changed or deleted path, in path order; empty when nothing changed."""
    changes: list[ScopeChange] = []
    for path in sorted(before.keys() | after.keys()):
        if path not in before:
            changes.append(ScopeChange(path=path, change="created"))
        elif path not in after:
            changes.append(ScopeChange(path=path, change="deleted"))
        elif before[path] != after[path]:
            changes.append(ScopeChange(path=path, change="changed"))
    return changes
