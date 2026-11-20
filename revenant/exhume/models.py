"""Exhume data models and the Tombstone loader."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

PassKind = Literal["data", "error"]
Kind = Literal["data", "error", "error_page"]
Shape = Literal["s_only", "empty_range", "full_range", "other"]


class TombstoneError(Exception):
    """A Tombstone file is missing, is not valid TOML or fails validation."""


class Tombstone(BaseModel):
    """Manifest of one dead API, read from `tombstones/<slug>.toml`."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    died: str
    hosts: list[str] = Field(min_length=1)
    paths: list[str] = Field(min_length=1)
    mimetypes: list[str] = Field(min_length=1)

    @field_validator("hosts")
    @classmethod
    def _lowercase_hosts(cls, hosts: list[str]) -> list[str]:
        return [host.lower() for host in hosts]


class CdxRow(BaseModel, frozen=True):
    """One CDX row; every field is the CDX string, kept verbatim."""

    timestamp: str
    original: str
    mimetype: str
    statuscode: str
    digest: str
    length: str


class Listing(BaseModel):
    """Deduplicated CDX rows of one Host and pass; rows exclude ethics-dropped URLs."""

    host: str
    kind: PassKind
    params: list[tuple[str, str]]
    rows: list[CdxRow]
    ethics_dropped: int


class IndexEntry(BaseModel):
    """One stored capture. `path` is POSIX, relative to `<root>/<slug>/`."""

    host: str
    kind: Kind
    requested_timestamp: str
    served_timestamp: str | None
    original: str
    mimetype: str
    statuscode: str
    digest: str
    length: str
    final_url: str
    path: str
    size: int
    sha256: str
    content_type: str | None
    digest_verified: bool
    fetched_at: str


class Index(BaseModel):
    """`evidence/<slug>/index.json`, keyed `<host>/<timestamp>-<digest>`."""

    slug: str
    entries: dict[str, IndexEntry] = {}


@dataclass
class HostSummary:
    """Per-Host counts for the Run_Summary. `error_evidence` counts this run only."""

    host: str
    found: int = 0
    downloaded: int = 0
    cached: int = 0
    rejected: int = 0
    error_evidence: int = 0
    discovery_failed: list[PassKind] = field(default_factory=list)


@dataclass
class RunResult:
    """Outcome of one run. `error_evidence` is the Slug total, read from the Index."""

    hosts: list[HostSummary]
    error_evidence: int


def _format_validation_error(error: ValidationError) -> str:
    parts = []
    for item in error.errors():
        loc = ".".join(str(part) for part in item["loc"]) or "<root>"
        parts.append(f"{loc}: {item['msg']}")
    return "; ".join(parts)


def load_tombstone(slug: str, root: Path = Path("tombstones")) -> Tombstone:
    """Read and validate `<root>/<slug>.toml`, raising `TombstoneError` on any problem."""
    path = root / f"{slug}.toml"
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise TombstoneError(f"{path}: tombstone file not found") from exc
    except OSError as exc:
        raise TombstoneError(f"{path}: cannot read tombstone ({exc})") from exc
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise TombstoneError(f"{path}: invalid TOML ({exc})") from exc
    try:
        tombstone = Tombstone.model_validate(data)
    except ValidationError as exc:
        raise TombstoneError(f"{path}: invalid tombstone: {_format_validation_error(exc)}") from exc
    if tombstone.slug != slug:
        raise TombstoneError(
            f"{path}: slug: field value {tombstone.slug!r} does not match file name slug {slug!r}"
        )
    return tombstone
