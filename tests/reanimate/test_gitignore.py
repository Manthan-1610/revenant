"""The revenant's committed files are not gitignored, and its Donor/error bytes stay raw.

Requirements 2.6 and 7.5. Runs git locally; never touches the network.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SLUG_DIR = "crypt/yahoo-finance-ichart"

COMMITTED = [
    f"{SLUG_DIR}/server.py",
    f"{SLUG_DIR}/donor/index.json",
    f"{SLUG_DIR}/error-404.html",
    f"{SLUG_DIR}/reanimate-prompt.md",
    f"{SLUG_DIR}/reanimate.json",
    f"{SLUG_DIR}/reanimate.log",
]
RAW = [f"{SLUG_DIR}/donor/AAPL.csv", f"{SLUG_DIR}/error-404.html"]

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not available")


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False, timeout=30
    )


@pytest.mark.parametrize("path", COMMITTED)
def test_revenant_file_is_not_ignored(path: str) -> None:
    result = git("check-ignore", "--no-index", "-v", path)
    # check-ignore exits 1 when the path is not ignored, 0 when it is, 128 on error.
    assert result.returncode == 1, result.stdout + result.stderr


@pytest.mark.parametrize("path", RAW)
def test_donor_and_error_bytes_are_not_text(path: str) -> None:
    result = git("check-attr", "text", "--", path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"{path}: text: unset"
