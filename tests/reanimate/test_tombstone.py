"""Example tests for the Tombstone donor fields (Requirement 2.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from revenant.exhume.models import TombstoneError, load_tombstone

REPO_TOMBSTONES = Path(__file__).resolve().parents[2] / "tombstones"

BASE = """\
slug = "acme-widgets"
name = "Acme widgets"
died = "2015-01"
hosts = ["api.acme.example"]
paths = ["widgets.csv"]
mimetypes = ["text/csv"]
"""


def write(root: Path, text: str) -> None:
    (root / "acme-widgets.toml").write_text(text, encoding="utf-8")


def test_absent_donor_fields_load_as_empty_lists(tmp_path: Path) -> None:
    write(tmp_path, BASE)
    tombstone = load_tombstone("acme-widgets", root=tmp_path)
    assert tombstone.donor_symbols == []
    assert tombstone.donor_required == []


def test_donor_fields_load_when_present(tmp_path: Path) -> None:
    write(tmp_path, BASE + 'donor_symbols = ["AAPL", "^GSPC"]\ndonor_required = ["AAPL"]\n')
    tombstone = load_tombstone("acme-widgets", root=tmp_path)
    assert tombstone.donor_symbols == ["AAPL", "^GSPC"]
    assert tombstone.donor_required == ["AAPL"]


def test_committed_yahoo_tombstone_loads_with_donors() -> None:
    tombstone = load_tombstone("yahoo-finance-ichart", root=REPO_TOMBSTONES)
    assert tombstone.slug == "yahoo-finance-ichart"
    assert "AAPL" in tombstone.donor_symbols
    assert tombstone.donor_required == ["AAPL"]
    assert set(tombstone.donor_required) <= set(tombstone.donor_symbols)


def test_required_symbol_missing_from_donor_symbols_is_named(tmp_path: Path) -> None:
    write(tmp_path, BASE + 'donor_symbols = ["AAPL"]\ndonor_required = ["AAPL", "MSFT"]\n')
    with pytest.raises(TombstoneError) as info:
        load_tombstone("acme-widgets", root=tmp_path)
    message = str(info.value)
    assert "acme-widgets.toml" in message
    assert "MSFT" in message
    assert "'AAPL'" not in message


def test_required_without_donor_symbols_is_rejected(tmp_path: Path) -> None:
    write(tmp_path, BASE + 'donor_required = ["^GSPC"]\n')
    with pytest.raises(TombstoneError) as info:
        load_tombstone("acme-widgets", root=tmp_path)
    assert "^GSPC" in str(info.value)
