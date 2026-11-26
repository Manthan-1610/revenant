"""Live Reanimate tests against the real Internet Archive (Req 7.6).

Skipped by default (`addopts = "-m 'not live'"`); run with `pytest -m live`.

Archive etiquette: the Evidence_Store points at the repo's `evidence/`, so `get_listing(...,
refresh=False)` reuses the cached CDX_Listings under `evidence/<slug>/cdx/` and fetches a
Listing live only when it is missing. Every request goes through Exhume's rate-limited
ArchiveClient (>= 1 s spacing, backoff, Revenant User-Agent). Donor files go to `tmp_path`.
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pytest

from revenant.exhume.archive import (
    ArchiveClient,
    RateLimiter,
    SystemClock,
    make_client,
    user_agent,
)
from revenant.exhume.models import load_tombstone
from revenant.exhume.store import EvidenceStore
from revenant.reanimate.donor import CUTOFF, HEADER_LINE, fetch_donors, load_donor_index

SLUG = "yahoo-finance-ichart"
REPO = Path(__file__).resolve().parents[2]
DEMO_DATES = [b"2016-01-08", b"2016-01-07", b"2016-01-06", b"2016-01-05", b"2016-01-04"]


@pytest.mark.live
def test_live_aapl_donor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REVENANT_USER_AGENT", raising=False)  # use the Revenant default UA
    # The committed Tombstone, as the runner loads it, so its Donor_Cover reaches `accept`.
    tombstone = load_tombstone(SLUG, REPO / "tombstones")
    assert "AAPL" in tombstone.donor_required
    assert tombstone.cover() == (date(2016, 1, 4), date(2016, 1, 8))
    tombstone = tombstone.model_copy(update={"donor_symbols": ["AAPL"]})
    clock = SystemClock()
    capture_urls: list[str] = []
    with make_client(RateLimiter(clock), user_agent()) as client:
        archive = ArchiveClient(client, clock)
        real_get = archive.get

        def counting_get(url: str, *args: object, **kwargs: object) -> object:
            if "id_/" in url:
                capture_urls.append(url)
            return real_get(url, *args, **kwargs)

        monkeypatch.setattr(archive, "get", counting_get)
        report = fetch_donors(tombstone, archive, EvidenceStore(REPO / "evidence", SLUG), tmp_path)

    print("capture fetches:", capture_urls)
    assert report.stored == ["AAPL"], report
    assert report.required_missing == [], report
    entry = load_donor_index(tmp_path, SLUG).entries["AAPL"]
    print(entry.model_dump_json(indent=2))  # shown with `pytest -s`: the chosen capture
    body = (tmp_path / "donor" / entry.file).read_bytes()
    assert hashlib.sha256(body).hexdigest() == entry.sha256
    assert body.split(b"\n", 1)[0] == HEADER_LINE
    assert entry.served_timestamp < CUTOFF
    assert "id_/" in entry.source_url
    assert entry.first_date <= "2016-01-04" and entry.last_date >= "2016-01-08"
    row_dates = [line.split(b",", 1)[0] for line in body.split(b"\n")[1:] if line]
    demo = [d for d in row_dates if b"2016-01-04" <= d <= b"2016-01-08"]
    assert demo == DEMO_DATES  # F18: five trading days, newest first
    assert capture_urls[-1] == entry.source_url  # the accepted capture was the last fetch
    print("donor bytes:", len(body))
