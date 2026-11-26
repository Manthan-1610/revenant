"""Reanimate data models: the Donor_Index and its entries."""

from __future__ import annotations

import json

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


def dump_model(model: BaseModel) -> bytes:
    """Byte-stable JSON: sorted keys, indent 2, trailing newline, UTF-8."""
    text = json.dumps(model.model_dump(mode="json"), sort_keys=True, indent=2, ensure_ascii=False)
    return (text + "\n").encode("utf-8")
