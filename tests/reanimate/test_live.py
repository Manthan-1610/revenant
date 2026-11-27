"""Live Reanimate tests against the real Internet Archive (Req 7.6).

Skipped by default (`addopts = "-m 'not live'"`); run with `pytest -m live`.

Archive etiquette: the Evidence_Store points at the repo's `evidence/`, so `get_listing(...,
refresh=False)` reuses the cached CDX_Listings under `evidence/<slug>/cdx/` and fetches a
Listing live only when it is missing. Every request goes through Exhume's rate-limited
ArchiveClient (>= 1 s spacing, backoff, Revenant User-Agent). Donor files go to `tmp_path`.
"""

from __future__ import annotations

import hashlib
import shutil
from datetime import date
from pathlib import Path

import httpx
import pytest

from revenant.autopsy.contract import contract_path, load_contract
from revenant.autopsy.render import spec_path
from revenant.exhume.archive import (
    ArchiveClient,
    RateLimiter,
    SystemClock,
    make_client,
    user_agent,
)
from revenant.exhume.models import load_tombstone
from revenant.exhume.store import EvidenceStore
from revenant.reanimate import runner
from revenant.reanimate.donor import CUTOFF, HEADER_LINE, fetch_donors, load_donor_index
from revenant.reanimate.kiro import KiroCli
from revenant.reanimate.record import BuildRecord

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


@pytest.mark.live
def test_live_build(tmp_path: Path) -> None:
    """Req 3.2, 3.6, 4.4, 4.5, 6.2: a real `kiro-cli chat --v3` headless build passes the demo Check.

    Runs in a `tmp_path` repo copy, so the committed `crypt/<slug>/` is untouched. The committed
    donor files are copied in, so the Donor_Fetcher reuses them (Req 2.5) and makes no Archive
    request.
    Needs a stored kiro-cli login (`kiro-cli whoami` exits 0).
    """
    kiro = KiroCli()
    if not kiro.available() or kiro.whoami() != 0:
        pytest.skip("kiro-cli is not installed or not logged in")
    error_page, _ = runner._error_capture(
        REPO, SLUG, load_contract(contract_path(REPO / "crypt", SLUG))
    )
    donor_dir = REPO / "crypt" / SLUG / "donor"
    for path in (
        REPO / "tombstones" / f"{SLUG}.toml",
        contract_path(REPO / "crypt", SLUG),
        spec_path(REPO / ".kiro" / "specs", SLUG),
        REPO / "evidence" / SLUG / "index.json",
        error_page,
        *sorted(p for p in donor_dir.iterdir() if p.is_file()),
    ):
        target = tmp_path / path.relative_to(REPO)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)

    def no_network(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected Archive request: {request.url}")

    deps = runner.Deps(kiro=kiro, transport=httpx.MockTransport(no_network), repo_root=tmp_path)
    summary = runner.reanimate(SLUG, prompt_only=False, built_by=runner.HEADLESS, deps=deps)

    slug_dir = tmp_path / "crypt" / SLUG
    # Every committed donor (AAPL plus the optional symbols of task 10.1) is reused offline.
    assert summary.stored == load_tombstone(SLUG, REPO / "tombstones").donor_symbols
    assert summary.checks["demo"] is not None and summary.checks["demo"].result == "pass"
    assert (slug_dir / "server.py").is_file()
    record = BuildRecord.model_validate_json((slug_dir / runner.RECORD_NAME).read_bytes())
    assert record.build_path == "kiro-cli-headless"
    assert record.kiro_exit_code == 0 and not record.timed_out
    assert record.kiro_version and record.kiro_version.startswith("kiro-cli")
    assert record.model is None or record.model.strip()
    assert (slug_dir / runner.LOG_NAME).read_text(encoding="utf-8").startswith("stdout: ")
    print(record.model_dump_json(indent=2))
