"""Donor_Fetcher: choose, check and name Yahoo's archived full-history captures (Req 2.2 to 2.6)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from revenant.autopsy.body import parse_body, parse_row_date
from revenant.autopsy.evidence import AutopsyError
from revenant.exhume.archive import ArchiveClient, ArchiveError
from revenant.exhume.cdx import DiscoveryError, get_listing
from revenant.exhume.ethics import has_auth_param
from revenant.exhume.models import CdxRow, Tombstone
from revenant.exhume.run import served_timestamp, wayback_url
from revenant.exhume.select import NUMERIC_NAMES, interval, parse_query
from revenant.exhume.store import EvidenceStore, atomic_write
from revenant.reanimate.errors import ReanimateError
from revenant.reanimate.record import DonorEntry, DonorIndex, dump_model

HEADER_LINE = b"Date,Open,High,Low,Close,Volume,Adj Close"
CUTOFF = "20170501"  # the API died in 2017-05; later captures are not Yahoo's rows
MAX_START_YEAR = 1999
MAX_STALENESS = timedelta(days=7)  # contract default `recent_within_7d`
MAX_TRIES = 5  # Req 2.3
SAFE_CHARS = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_")


def _first(pairs: list[tuple[str, str]], name: str) -> str | None:
    return next((value for key, value in pairs if key == name), None)


def _digits(value: str) -> bool:
    return value.isascii() and value.isdigit()


def _daily_range(pairs: list[tuple[str, str]], year: int) -> bool:
    """`g=d` with a non-empty `c` <= 1999 and `f` absent, empty or >= the capture year (F20)."""
    if interval(pairs) != "d":
        return False
    start = _first(pairs, "c") or ""
    if not _digits(start) or int(start) > MAX_START_YEAR:
        return False
    end = _first(pairs, "f") or ""
    return end == "" or (_digits(end) and int(end) >= year)


def full_history(pairs: list[tuple[str, str]]) -> bool:
    """Full_History: `s`, optional `ignore`, `g` empty or `d`, and `a`-`f` only when empty (Req 2.2)."""
    if not any(key == "s" for key, _ in pairs):
        return False
    for key, value in pairs:
        if key in ("s", "ignore"):
            continue
        if key == "g" and value in ("", "d"):
            continue
        if key in NUMERIC_NAMES and value == "":
            continue
        return False
    return True


def _qualifies(row: CdxRow, symbol: str, mimetypes: list[str]) -> bool:
    if not (row.statuscode.startswith("2") and len(row.statuscode) == 3):
        return False
    if row.mimetype not in mimetypes or not row.timestamp < CUTOFF:
        return False
    if has_auth_param(row.original):
        return False
    pairs = parse_query(row.original)  # HTML-unescaped (F15) and percent-decoded
    if _first(pairs, "s") != symbol:
        return False
    if full_history(pairs):
        return True
    year = row.timestamp[:4]
    return _digits(year) and _daily_range(pairs, int(year))


def candidates(rows: Sequence[CdxRow], symbol: str, mimetypes: list[str]) -> list[CdxRow]:
    """Qualifying rows, newest first (ties by `original`), first row per digest kept (Req 2.2)."""
    kept = [row for row in rows if _qualifies(row, symbol, mimetypes)]
    # Full-tuple key so equal (timestamp, original) pairs never depend on input order.
    kept.sort(key=lambda r: (r.original, r.mimetype, r.statuscode, r.digest, r.length))
    kept.sort(key=lambda r: r.timestamp, reverse=True)  # stable: ties keep the order above
    seen: set[str] = set()
    unique: list[CdxRow] = []
    for row in kept:
        if row.digest not in seen:
            seen.add(row.digest)
            unique.append(row)
    return unique


def _served_date(served: str) -> date | None:
    try:
        return date(int(served[:4]), int(served[4:6]), int(served[6:8]))
    except ValueError:
        return None


def accept(body: bytes, served: str | None, cover: tuple[date, date] | None = None) -> str | None:
    """None when `body` qualifies as a Donor_Capture, else the reason it does not (Req 2.3)."""
    if served is None or len(served) < 8 or not _digits(served):
        return f"served timestamp {served!r} is not a capture timestamp"
    if not served < CUTOFF:
        return f"served timestamp {served} is not earlier than {CUTOFF}"
    served_on = _served_date(served)
    if served_on is None:
        return f"served timestamp {served} is not a valid date"
    if body.split(b"\n", 1)[0] != HEADER_LINE:
        return "first line is not the Header_Line"
    try:
        parsed = parse_body(body, "donor")
    except AutopsyError:
        return "body is not valid UTF-8"
    if not parsed.rows:
        return "body has no Data_Row"
    dates = _row_dates(parsed.rows, served_on.year)
    if dates is None:
        return "a Data_Row has an unparseable Row_Date"
    oldest, newest = min(dates), max(dates)
    if not served_on - MAX_STALENESS <= newest <= served_on:
        return f"newest Row_Date {newest} is not within 7 days before {served_on}"
    if cover is not None and not (oldest <= cover[0] and newest >= cover[1]):
        return f"Row_Dates {oldest}..{newest} do not cover {cover[0]}..{cover[1]}"
    return None


def _row_dates(rows: Sequence[str], year: int) -> list[date] | None:
    """Every Data_Row's Row_Date, or None when any one fails to parse (strict, Req 2.3)."""
    dates: list[date] = []
    for row in rows:
        found = parse_row_date(row.split(",", 1)[0], year)
        if found is None:
            return None
        dates.append(found[0])
    return dates


def donor_file_name(symbol: str) -> str:
    """Keep `A-Z 0-9 . - _`, write every other UTF-8 byte as `%XX`, add `.csv` (Req 2.4)."""
    encoded = "".join(chr(b) if b in SAFE_CHARS else f"%{b:02X}" for b in symbol.encode())
    return f"{encoded}.csv"


@dataclass(frozen=True)
class DonorReport:
    """Outcome of `fetch_donors`: stored symbols, missing ones (with messages), required misses."""

    stored: list[str] = field(default_factory=list)
    missing: dict[str, str] = field(default_factory=dict)
    required_missing: list[str] = field(default_factory=list)


def index_path(slug_dir: Path) -> Path:
    return slug_dir / "donor" / "index.json"


def load_donor_index(slug_dir: Path, slug: str) -> DonorIndex:
    """The stored Donor_Index, or an empty one when absent or unreadable."""
    path = index_path(slug_dir)
    try:
        return DonorIndex.model_validate_json(path.read_bytes())
    except (OSError, ValueError):
        return DonorIndex(slug=slug)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _reusable(slug_dir: Path, entry: DonorEntry | None) -> bool:
    """Req 2.5: the entry exists and its stored file still has the recorded SHA-256."""
    if entry is None:
        return False
    try:
        return _sha256((slug_dir / "donor" / entry.file).read_bytes()) == entry.sha256
    except OSError:
        return False


def _make_entry(symbol: str, row: CdxRow, url: str, served: str, body: bytes) -> DonorEntry:
    parsed = parse_body(body, "donor")
    dates = sorted(_row_dates(parsed.rows, int(served[:4])) or [])  # accept() parsed them all
    return DonorEntry(
        symbol=symbol,
        file=donor_file_name(symbol),
        source_url=url,
        host=urlsplit(row.original).hostname or "",
        served_timestamp=served,
        sha256=_sha256(body),
        rows=len(parsed.rows),
        first_date=dates[0].isoformat(),
        last_date=dates[-1].isoformat(),
    )


def _try_candidates(
    archive: ArchiveClient,
    symbol: str,
    rows: Sequence[CdxRow],
    cover: tuple[date, date] | None = None,
) -> tuple[DonorEntry, bytes] | None:
    """Fetch at most MAX_TRIES candidates; the first that `accept`s wins (Req 2.3)."""
    for row in rows[:MAX_TRIES]:
        url = wayback_url(row.timestamp, row.original)
        try:
            response = archive.get(url)
        except ArchiveError:
            continue  # a tried candidate that does not qualify
        if not 200 <= response.status_code <= 299:
            continue
        served = served_timestamp(response)
        body = response.content
        if served is None or accept(body, served, cover) is not None:
            continue
        return _make_entry(symbol, row, url, served, body), body
    return None


def _pool_rows(archive: ArchiveClient, store: EvidenceStore, tombstone: Tombstone) -> list[CdxRow]:
    """Every host's cached data Listing (fetched live only when missing, Req 2.2)."""
    pooled: list[CdxRow] = []
    for host in tombstone.hosts:
        try:
            listing = get_listing(archive, store, tombstone, host, "data", refresh=False)
        except (DiscoveryError, ArchiveError) as exc:
            raise ReanimateError("donor", f"CDX listing for {host} failed: {exc}") from exc
        pooled.extend(listing.rows)
    return pooled


def fetch_donors(
    tombstone: Tombstone, archive: ArchiveClient, store: EvidenceStore, slug_dir: Path
) -> DonorReport:
    """Store one Donor_Capture per Donor_Symbol under `slug_dir/donor/` (Req 2.2 to 2.6)."""
    index = load_donor_index(slug_dir, tombstone.slug)
    entries = dict(index.entries)
    report = DonorReport()
    pooled: list[CdxRow] | None = None
    for symbol in tombstone.donor_symbols:
        if _reusable(slug_dir, entries.get(symbol)):
            report.stored.append(symbol)  # Req 2.5: zero Archive requests
            continue
        if pooled is None:
            pooled = _pool_rows(archive, store, tombstone)
        rows = candidates(pooled, symbol, tombstone.mimetypes)
        found = _try_candidates(archive, symbol, rows, tombstone.cover())
        if found is None:
            message = f"{symbol}: no capture qualified as a donor"
            if entries.pop(symbol, None) is not None:  # stale entry; its file stays on disk
                message += "; its stale Donor_Index entry was removed"
                _write_index(slug_dir, tombstone.slug, entries)
            report.missing[symbol] = message
            if symbol in tombstone.donor_required:
                report.required_missing.append(symbol)
            continue
        entry, body = found
        atomic_write(slug_dir / "donor" / entry.file, body)
        entries[symbol] = entry
        _write_index(slug_dir, tombstone.slug, entries)
        report.stored.append(symbol)
    return report


def _write_index(slug_dir: Path, slug: str, entries: dict[str, DonorEntry]) -> None:
    atomic_write(index_path(slug_dir), dump_model(DonorIndex(slug=slug, entries=entries)))
