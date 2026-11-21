"""Contract model and Contract_Writer: `crypt/<slug>/contract.json` (Req 7.1, 7.3 to 7.5)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

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


class ValueCount(_Model):
    value: str
    count: int


class IntType(_Model):
    kind: Literal["int"] = "int"
    min: int
    max: int


class EnumType(_Model):
    kind: Literal["enum"] = "enum"
    values: list[ValueCount]  # sorted by value


class StringType(_Model):
    kind: Literal["string"] = "string"
    distinct: int


ParameterType = Annotated[IntType | EnumType | StringType, Field(discriminator="kind")]


class Parameter(_Model):
    """Req 2.3 to 2.5: one query parameter name observed in Data_Captures (`amp` excluded)."""

    name: str
    documented: bool
    present: Evidence
    empty: int
    junk: int
    required: bool
    examples: list[str]  # sorted by (count desc, value asc), at most 5
    type: ParameterType


class NameEvidence(_Model):
    name: str
    evidence: Evidence


class Variant(_Model):
    """Req 4.4, 4.5: one Header_Variant, with its columns and Capture_Year range."""

    header: str
    columns: list[str]  # header order: the order is the fact
    first_year: int
    last_year: int
    evidence: Evidence


class IntervalVariants(_Model):
    """Req 4.4: the Response_Variants of one Interval."""

    interval: str
    variants: list[Variant]  # sorted by header


class FormatEvidence(_Model):
    """Req 5.1: one Row_Date format with its Capture_Year range."""

    format: str
    first_year: int
    last_year: int
    evidence: Evidence


class RowOrder(_Model):
    """Req 5.2, 5.3: row-order classes and the bodies excluded for unparsed Row_Dates."""

    descending: Evidence
    ascending: Evidence
    unordered: Evidence
    unparsed_dates: Evidence


class DigitsCount(_Model):
    digits: int
    count: int


class Precision(_Model):
    """Req 5.4: Body_Precision distribution per (Interval, Header_Variant, Capture_Year)."""

    interval: str
    header: str
    year: int
    values: list[DigitsCount]  # sorted by digits


class Comments(_Model):
    """Req 5.5: Comment_Lines over all Data_Captures (F16)."""

    total: int
    years: list[int]  # sorted
    example: str | None
    after_last_row: int
    before_last_row: int
    evidence: Evidence


class Contract(_Model):
    slug: str
    source: Source
    endpoints: list[Endpoint]  # sorted by path
    parameters: list[Parameter]  # sorted by name; `amp` excluded
    amp: Evidence
    months: Months
    content_types: list[NameEvidence]  # sorted by name
    intervals: list[IntervalVariants]  # sorted by interval
    headers: list[Variant]  # sorted by header
    header_only: Evidence
    date_formats: list[FormatEvidence]  # sorted by format
    row_order: RowOrder
    precision: list[Precision]  # sorted by (interval, header, year)
    comments: Comments


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
