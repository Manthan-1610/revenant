"""Reanimate data models: the Donor_Index and its entries."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict


class DonorEntry(BaseModel):
    """One stored Donor_Capture. `host` is the hostname of the capture's original URL."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str
    file: str
    source_url: str
    host: str
    served_timestamp: str
    sha256: str
    rows: int
    first_date: str
    last_date: str


class DonorIndex(BaseModel):
    """`crypt/<slug>/donor/index.json`, keyed by symbol."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slug: str
    entries: dict[str, DonorEntry] = {}


class CheckResult(BaseModel):
    """The outcome of one post-build Check (Req 6.2-6.4, 6.6)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Literal["demo", "unknown_symbol", "weekly"]
    result: Literal["pass", "fail", "not_run"]
    expected: str | None = None
    observed: str | None = None


class ScopeChange(BaseModel):
    """One repository file created, changed or deleted while kiro-cli ran (Req 7.1)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str  # POSIX path relative to the repository root
    change: Literal["created", "changed", "deleted"]


BuildPath = Literal["kiro-cli-headless", "kiro-ide-chat"]


class BuildRecord(BaseModel):
    """`crypt/<slug>/reanimate.json`: provenance of one finished build (Req 4.4)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    build_path: BuildPath
    prompt_sha256: str
    kiro_version: str | None
    kiro_exit_code: int | None
    timed_out: bool = False
    note: str | None = None
    model: str | None  # id reported by a stream-json event, else null; never guessed
    started_at: str  # ISO 8601 UTC with "Z"
    ended_at: str
    scope_changes: list[ScopeChange] = []  # empty = clean (Req 7.1)
    import_violations: list[str] = []  # imports, evidence/ paths, py_compile, ruff F (Req 7.4)
    checks: dict[str, CheckResult | None]  # null = did not run


def dump_model(model: BaseModel) -> bytes:
    """Byte-stable JSON: sorted keys, indent 2, trailing newline, UTF-8."""
    text = json.dumps(model.model_dump(mode="json"), sort_keys=True, indent=2, ensure_ascii=False)
    return (text + "\n").encode("utf-8")
