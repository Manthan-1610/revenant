"""Evidence_Reader: load Exhume's Index and capture bodies for one slug (Req 1.2 to 1.4)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from revenant.exhume.models import Index, IndexEntry


class AutopsyError(Exception):
    """An input error: `str()` is `<path>: <message>`, with the path in POSIX form."""

    def __init__(self, path: str | Path, message: str) -> None:
        self.path = Path(path).as_posix()
        self.message = message
        super().__init__(f"{self.path}: {message}")


@dataclass(frozen=True)
class Capture:
    """One Index entry with its raw, SHA-256-checked body bytes."""

    key: str
    entry: IndexEntry
    body: bytes


def _validation_message(error: ValidationError) -> str:
    if any(item["type"] == "json_invalid" for item in error.errors()):
        return "invalid JSON"
    parts = []
    for item in error.errors():
        loc = ".".join(str(part) for part in item["loc"]) or "<root>"
        parts.append(f"{loc}: {item['msg']}")
    return "invalid index: " + "; ".join(parts)


def load_evidence(evidence_dir: Path, slug: str) -> tuple[bytes, list[Capture]]:
    """Return the raw `index.json` bytes and every capture in sorted Index key order."""
    root = evidence_dir / slug
    index_path = root / "index.json"
    try:
        index_bytes = index_path.read_bytes()
    except FileNotFoundError as exc:
        raise AutopsyError(index_path, "index file not found") from exc
    except OSError as exc:
        raise AutopsyError(index_path, f"cannot read index ({exc})") from exc
    try:
        index = Index.model_validate_json(index_bytes)
    except ValidationError as exc:
        raise AutopsyError(index_path, _validation_message(exc)) from exc
    if index.slug != slug:
        raise AutopsyError(
            index_path, f"slug: index slug {index.slug!r} does not match requested slug {slug!r}"
        )

    captures = []
    for key in sorted(index.entries):
        entry = index.entries[key]
        body_path = root / entry.path
        try:
            body = body_path.read_bytes()
        except FileNotFoundError as exc:
            raise AutopsyError(body_path, f"capture file not found (index key {key})") from exc
        except OSError as exc:
            raise AutopsyError(body_path, f"cannot read capture ({exc})") from exc
        actual = hashlib.sha256(body).hexdigest()
        if actual != entry.sha256:
            raise AutopsyError(
                body_path, f"sha256 mismatch: index has {entry.sha256}, file has {actual}"
            )
        captures.append(Capture(key=key, entry=entry, body=body))
    return index_bytes, captures


def capture_timestamp(entry: IndexEntry) -> str:
    """`served_timestamp`, else `requested_timestamp`."""
    return entry.served_timestamp or entry.requested_timestamp


def capture_year(entry: IndexEntry) -> int:
    """Capture_Year: first 4 digits of `served_timestamp`, else `requested_timestamp`."""
    return int(capture_timestamp(entry)[:4])


def capture_date(entry: IndexEntry) -> date:
    """Capture_Date: first 8 digits of the same timestamp as a date."""
    stamp = capture_timestamp(entry)
    return date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))
