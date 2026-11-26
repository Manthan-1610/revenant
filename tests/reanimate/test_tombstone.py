"""Example tests for the Tombstone donor fields (Requirement 2.1)."""

from __future__ import annotations

from datetime import date
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


def test_committed_yahoo_tombstone_sets_the_demo_cover() -> None:
    tombstone = load_tombstone("yahoo-finance-ichart", root=REPO_TOMBSTONES)
    assert tombstone.cover() == (date(2016, 1, 4), date(2016, 1, 8))


def test_absent_donor_cover_is_none(tmp_path: Path) -> None:
    write(tmp_path, BASE)
    tombstone = load_tombstone("acme-widgets", root=tmp_path)
    assert tombstone.donor_cover is None and tombstone.cover() is None


def test_single_day_donor_cover_loads(tmp_path: Path) -> None:
    write(tmp_path, BASE + 'donor_cover = ["2016-01-04", "2016-01-04"]\n')
    assert load_tombstone("acme-widgets", root=tmp_path).cover() == (
        date(2016, 1, 4),
        date(2016, 1, 4),
    )


@pytest.mark.parametrize(
    ("cover", "needle"),
    [
        ("[]", "exactly two"),
        ('["2016-01-04"]', "exactly two"),
        ('["2016-01-04", "2016-01-05", "2016-01-06"]', "exactly two"),
        ('["2016-02-30", "2016-03-01"]', "2016-02-30"),
        ('["20160104", "2016-01-08"]', "20160104"),
        ('["Jan 4 2016", "2016-01-08"]', "Jan 4 2016"),
        ('["2016-01-08", "2016-01-04"]', "after"),
    ],
)
def test_invalid_donor_cover_is_rejected(tmp_path: Path, cover: str, needle: str) -> None:
    write(tmp_path, BASE + f"donor_cover = {cover}\n")
    with pytest.raises(TombstoneError) as info:
        load_tombstone("acme-widgets", root=tmp_path)
    assert "donor_cover" in str(info.value) and needle in str(info.value)
