"""Contract model and Contract_Writer: `crypt/<slug>/contract.json` (Req 7.1, 7.3 to 7.5)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from revenant.exhume.store import atomic_write

CONTRACT_FILE = "contract.json"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Evidence(_Model):
    """Evidence_Count: supporting captures, with up to 3 Index keys in ascending order."""

    count: int
    keys: list[str]


class Source(_Model):
    index_sha256: str
    entry_count: int


class HostEvidence(_Model):
    host: str
    evidence: Evidence


class Endpoint(_Model):
    path: str
    hosts: list[HostEvidence]  # sorted by host


class Months(_Model):
    indexing: Literal["0-indexed", "1-indexed", "undetermined"]
    decisive_h0: Evidence
    decisive_h1: Evidence
    ambiguous: Evidence
    unfit: Evidence


class Contract(_Model):
    slug: str
    source: Source
    endpoints: list[Endpoint]  # sorted by path
    months: Months


def dump_contract(contract: Contract) -> bytes:
    """Byte-stable JSON: sorted keys, indent 2, `ensure_ascii=False`, trailing newline, UTF-8."""
    data = contract.model_dump(mode="json")
    text = json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def contract_path(crypt_dir: Path, slug: str) -> Path:
    return crypt_dir / slug / CONTRACT_FILE


def write_contract(contract: Contract, crypt_dir: Path) -> Path:
    """Re-validate, then atomically write `<crypt_dir>/<slug>/contract.json`; return its path."""
    Contract.model_validate(contract.model_dump())
    path = contract_path(crypt_dir, contract.slug)
    atomic_write(path, dump_contract(contract))
    return path


def load_contract(path: Path) -> Contract:
    return Contract.model_validate_json(path.read_bytes())
