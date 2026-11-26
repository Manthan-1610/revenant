"""Build_Workspace: the temporary directory kiro-cli runs in (Req 3.2, 3.5, 3.6).

Lifecycle: `make_workspace` creates it; after a successful kiro-cli run `copy_back` copies
`server.py` into the slug directory and then deletes the workspace. On any failure (non-zero
exit, timeout, no `server.py`, scope change) the Runner does not call `copy_back`, so the
workspace is kept for inspection and its path is printed via `display`.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from revenant.reanimate.donor import index_path
from revenant.reanimate.errors import ReanimateError
from revenant.reanimate.prompt import PROMPT_NAME
from revenant.reanimate.record import DonorIndex

WORKSPACE_PREFIX = "revenant-build-"
SPEC_NAME = "requirements.md"
CONTRACT_NAME = "contract.json"
ERROR_PAGE_NAME = "error-404.html"
SERVER_NAME = "server.py"


def _donor_files(slug_dir: Path) -> list[str]:
    """Relative paths (`donor/<file>`) of every donor file named in the Donor_Index."""
    path = index_path(slug_dir)
    try:
        index = DonorIndex.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ReanimateError("build", f"cannot read donor index {path}: {exc}") from exc
    return [f"donor/{entry.file}" for entry in index.entries.values()]


def _sources(slug_dir: Path, spec_path: Path) -> dict[str, Path]:
    """Workspace-relative name -> source path, for exactly the glossary files."""
    sources = {
        SPEC_NAME: spec_path,
        CONTRACT_NAME: slug_dir / CONTRACT_NAME,
        "donor/index.json": index_path(slug_dir),
        ERROR_PAGE_NAME: slug_dir / ERROR_PAGE_NAME,
        PROMPT_NAME: slug_dir / PROMPT_NAME,
    }
    for name in _donor_files(slug_dir):
        sources[name] = slug_dir / name
    return sources


def make_workspace(slug_dir: Path, spec_path: Path) -> Path:
    """A fresh `revenant-build-*` temp directory holding copies of only the glossary files."""
    sources = _sources(slug_dir, spec_path)
    missing = [str(src) for src in sources.values() if not src.is_file()]
    if missing:
        raise ReanimateError("build", "missing build input: " + ", ".join(missing))
    workspace = Path(tempfile.mkdtemp(prefix=WORKSPACE_PREFIX))
    try:
        for name, src in sources.items():
            dest = workspace / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
    except OSError as exc:
        shutil.rmtree(workspace, ignore_errors=True)  # nothing ran in it yet
        raise ReanimateError("build", f"cannot fill Build_Workspace: {exc}") from exc
    return workspace


def has_server(workspace: Path) -> bool:
    return (workspace / SERVER_NAME).is_file()


def copy_back(workspace: Path, slug_dir: Path) -> Path:
    """Copy `server.py` byte for byte to `slug_dir/server.py`, then delete the workspace (3.6).

    Raises ReanimateError and keeps the workspace when it holds no `server.py` (3.5).
    """
    source = workspace / SERVER_NAME
    if not source.is_file():
        raise ReanimateError(
            "build", f"kiro-cli wrote no server; workspace kept at {display(workspace)}"
        )
    target = slug_dir / SERVER_NAME
    target.write_bytes(source.read_bytes())
    shutil.rmtree(workspace, ignore_errors=True)
    return target


def display(path: Path | str) -> str:
    """`path` as text with the Home_Path (native and forward-slash spellings) replaced by `~`."""
    text = str(path)
    home = Path.home()
    for spelling in sorted({str(home), home.as_posix()}, key=len, reverse=True):
        text = text.replace(spelling, "~")
    return text
