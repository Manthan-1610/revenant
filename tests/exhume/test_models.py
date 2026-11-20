"""Example tests for the Tombstone loader (Requirements 2.1 to 2.5)."""

from pathlib import Path

import pytest

from revenant.exhume.models import Tombstone, TombstoneError, load_tombstone

REPO_TOMBSTONES = Path(__file__).resolve().parents[2] / "tombstones"

VALID = """\
slug = "acme-widgets"
name = "Acme widgets API"
died = "2019-01"
hosts = ["API.Acme.com", "old.acme.com"]
paths = ["widgets.json"]
mimetypes = ["application/json"]
"""


def write(root: Path, slug: str, text: str) -> Path:
    path = root / f"{slug}.toml"
    path.write_text(text, encoding="utf-8")
    return path


def without_line(prefix: str) -> str:
    return "".join(line for line in VALID.splitlines(keepends=True) if not line.startswith(prefix))


def test_valid_tombstone_loads_and_lowercases_hosts(tmp_path: Path) -> None:
    write(tmp_path, "acme-widgets", VALID)
    tombstone = load_tombstone("acme-widgets", root=tmp_path)
    assert isinstance(tombstone, Tombstone)
    assert tombstone.slug == "acme-widgets"
    assert tombstone.hosts == ["api.acme.com", "old.acme.com"]
    assert tombstone.paths == ["widgets.json"]
    assert tombstone.mimetypes == ["application/json"]


def test_repo_yahoo_tombstone_loads() -> None:
    tombstone = load_tombstone("yahoo-finance-ichart", root=REPO_TOMBSTONES)
    assert tombstone.name == "Yahoo Finance historical prices"
    assert tombstone.died == "2017-05"
    assert tombstone.hosts == [
        "ichart.yahoo.com",
        "ichart.finance.yahoo.com",
        "real-chart.finance.yahoo.com",
    ]
    assert tombstone.paths == ["table.csv"]
    assert tombstone.mimetypes == ["text/csv"]


@pytest.mark.parametrize("field", ["slug", "name", "died", "hosts", "paths", "mimetypes"])
def test_missing_field_is_rejected(tmp_path: Path, field: str) -> None:
    write(tmp_path, "acme-widgets", without_line(f"{field} ="))
    with pytest.raises(TombstoneError) as info:
        load_tombstone("acme-widgets", root=tmp_path)
    message = str(info.value)
    assert "acme-widgets.toml" in message
    assert field in message


def test_extra_field_is_rejected(tmp_path: Path) -> None:
    write(tmp_path, "acme-widgets", VALID + 'owner = "someone"\n')
    with pytest.raises(TombstoneError) as info:
        load_tombstone("acme-widgets", root=tmp_path)
    assert "acme-widgets.toml" in str(info.value)
    assert "owner" in str(info.value)


@pytest.mark.parametrize("field", ["hosts", "paths", "mimetypes"])
def test_empty_list_is_rejected(tmp_path: Path, field: str) -> None:
    write(tmp_path, "acme-widgets", without_line(f"{field} =") + f"{field} = []\n")
    with pytest.raises(TombstoneError) as info:
        load_tombstone("acme-widgets", root=tmp_path)
    assert "acme-widgets.toml" in str(info.value)
    assert field in str(info.value)


def test_bad_toml_is_rejected(tmp_path: Path) -> None:
    write(tmp_path, "acme-widgets", 'slug = "acme-widgets\nhosts = [\n')
    with pytest.raises(TombstoneError) as info:
        load_tombstone("acme-widgets", root=tmp_path)
    assert "acme-widgets.toml" in str(info.value)
    assert "TOML" in str(info.value)


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(TombstoneError) as info:
        load_tombstone("no-such-api", root=tmp_path)
    assert "no-such-api.toml" in str(info.value)


def test_slug_mismatch_names_both_values(tmp_path: Path) -> None:
    write(tmp_path, "other-name", VALID)
    with pytest.raises(TombstoneError) as info:
        load_tombstone("other-name", root=tmp_path)
    message = str(info.value)
    assert "other-name.toml" in message
    assert "acme-widgets" in message
    assert "other-name" in message
    assert "slug" in message
