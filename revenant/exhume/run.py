"""Exhume orchestration: discovery, selection, download and storage per Host."""

from __future__ import annotations

import re
from datetime import UTC
from email.utils import parsedate_to_datetime

import httpx

from revenant.exhume.archive import ArchiveClient, ArchiveError
from revenant.exhume.cdx import DiscoveryError, get_listing
from revenant.exhume.content import classify, is_offline_page, wayback_digest
from revenant.exhume.models import CdxRow, HostSummary, RunResult, Tombstone
from revenant.exhume.select import backfill_order, select
from revenant.exhume.store import EvidenceStore, entry_key

WAYBACK_PREFIX = "https://web.archive.org/web/"
ERROR_EVIDENCE_CAP = 10
_SERVED_RE = re.compile(r"^/web/(\d{14})id_/")


def wayback_url(timestamp: str, original: str) -> str:
    """Raw-capture URL; `original` is copied unchanged (keeps `:80` and raw `^`, F5, F11)."""
    return f"{WAYBACK_PREFIX}{timestamp}id_/{original}"


def served_timestamp(response: httpx.Response) -> str | None:
    """Timestamp actually served: final URL path, else `Memento-Datetime` in UTC, else None."""
    match = _SERVED_RE.match(response.url.path)
    if match:
        return match.group(1)
    memento = response.headers.get("Memento-Datetime")
    if memento:
        try:
            when = parsedate_to_datetime(memento)
        except (TypeError, ValueError, IndexError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return when.astimezone(UTC).strftime("%Y%m%d%H%M%S")
    return None


def _is_substituted(row: CdxRow, response: httpx.Response) -> bool:
    """Req 5.6, F14: served a different, non-null timestamp whose body digest does not match."""
    served = served_timestamp(response)
    return (
        served is not None
        and served != row.timestamp
        and wayback_digest(response.content) != row.digest
    )


def _fetch_capture(archive: ArchiveClient, row: CdxRow) -> httpx.Response | None:
    """Fetch a Data capture; re-fetch once if substituted. None means reject (Req 5.4, 5.6).

    Raises `ArchiveError` when the Retry_Policy gives up.
    """
    url = wayback_url(row.timestamp, row.original)
    for _ in range(2):
        response = archive.get(url)
        if not 200 <= response.status_code <= 299:
            return None
        if not _is_substituted(row, response):
            return response
    return None


def _download(
    store: EvidenceStore, archive: ArchiveClient, host: str, row: CdxRow, summary: HostSummary
) -> bool:
    """Fetch and store one Data capture; True only when it was stored with kind `data`."""
    try:
        response = _fetch_capture(archive, row)
    except ArchiveError:
        summary.rejected += 1
        return False
    if response is None:
        summary.rejected += 1
        return False
    kind = classify(response.content, response.headers.get("content-type"), row.mimetype)
    if kind == "error_page":
        # Req 7.5: keep it as Error_Evidence while the Slug cap allows; never as data.
        summary.rejected += 1
        if store.error_evidence_count() >= ERROR_EVIDENCE_CAP:
            return False
    store.save_capture(
        host,
        row,
        kind,
        response,
        served_timestamp(response),
        wayback_digest(response.content) == row.digest,
    )
    if kind == "error_page":
        summary.error_evidence += 1
        return False
    summary.downloaded += 1
    return True


def _data_pass(
    store: EvidenceStore,
    archive: ArchiveClient,
    host: str,
    candidates: list[CdxRow],
    max_captures: int,
    summary: HostSummary,
) -> None:
    """Selected Candidates first, then backfill, until N `data` captures exist (Req 5.5, 9.4)."""
    entries = store.load_index().entries

    def cached_kind(row: CdxRow) -> str | None:
        if not store.is_cached(host, row):
            return None
        return entries[entry_key(host, row.timestamp, row.digest)].kind

    # Rerun short-cut: enough cached `data` captures already, so send no request at all.
    cached_data = sum(1 for row in candidates if cached_kind(row) == "data")
    if cached_data >= max_captures:
        summary.cached = max_captures
        return

    selected = select(candidates, max_captures)
    stored = 0
    # `select` and `backfill_order` are disjoint and deduplicated: each Capture is tried once.
    for row in [*selected, *backfill_order(candidates, selected)]:
        if stored >= max_captures:
            return
        kind = cached_kind(row)
        if kind == "data":
            summary.cached += 1
            stored += 1
        elif kind is not None:
            # A cached Error page: no request, and it never counts as data.
            summary.rejected += 1
        elif _download(store, archive, host, row, summary):
            stored += 1


def _fetch_error_capture(archive: ArchiveClient, row: CdxRow) -> httpx.Response | None:
    """Fetch one Error capture; None means reject (Req 3.6, F10).

    Accepted only when the replay status equals the CDX status and `Memento-Datetime` is
    present, which tells an archived 404 apart from the Archive's own "not archived" 404.
    No retry on a mismatch: `ArchiveClient.get` already returns non-429 4xx after one attempt.
    """
    try:
        response = archive.get(wayback_url(row.timestamp, row.original))
    except ArchiveError:
        return None
    if str(response.status_code) != row.statuscode:
        return None
    if not response.headers.get("Memento-Datetime"):
        return None
    if is_offline_page(response.headers.get("content-type"), response.content):
        return None  # defensive: the client never returns an Offline page as a response
    return response


def _error_pass(
    tombstone: Tombstone,
    store: EvidenceStore,
    archive: ArchiveClient,
    refresh: bool,
    summaries: list[HostSummary],
) -> None:
    """Fetch Error captures round-robin over Hosts until the Slug has 10 Error_Evidence items.

    Each Host's turn takes its next non-cached row in (timestamp, digest) order. Cached
    captures send no request; they already count through `error_evidence_count` (Req 9.4).
    """
    count = store.error_evidence_count()
    if count >= ERROR_EVIDENCE_CAP:
        return  # cap already reached: no error-pass discovery or download at all
    queues: list[tuple[str, HostSummary, list[CdxRow]]] = []
    for host, summary in zip(tombstone.hosts, summaries, strict=True):
        try:
            listing = get_listing(archive, store, tombstone, host, "error", refresh)
        except DiscoveryError:
            summary.discovery_failed.append("error")
            continue
        rows = sorted(listing.rows, key=lambda r: (r.timestamp, r.digest))
        queues.append((host, summary, rows))

    positions = [0] * len(queues)
    while count < ERROR_EVIDENCE_CAP:
        progressed = False
        for i, (host, summary, rows) in enumerate(queues):
            if count >= ERROR_EVIDENCE_CAP:
                return
            while positions[i] < len(rows) and store.is_cached(host, rows[positions[i]]):
                positions[i] += 1
            if positions[i] >= len(rows):
                continue
            row = rows[positions[i]]
            positions[i] += 1
            progressed = True
            response = _fetch_error_capture(archive, row)
            if response is None:
                continue  # not counted as data `rejected` (design: error column deferred)
            store.save_capture(
                host,
                row,
                "error",
                response,
                served_timestamp(response),
                wayback_digest(response.content) == row.digest,
            )
            summary.error_evidence += 1
            count += 1
        if not progressed:
            return


def exhume(
    tombstone: Tombstone,
    store: EvidenceStore,
    archive: ArchiveClient,
    max_captures: int,
    refresh: bool,
) -> RunResult:
    """Data pass for every Host (Listing, select, backfill), then the error pass (Req 3.6)."""
    summaries: list[HostSummary] = []
    for host in tombstone.hosts:
        summary = HostSummary(host=host)
        summaries.append(summary)
        try:
            listing = get_listing(archive, store, tombstone, host, "data", refresh)
        except DiscoveryError:
            summary.discovery_failed.append("data")
            continue
        # Req 10.3: Ethics_Filter drops count as found and as rejected.
        summary.found = len(listing.rows) + listing.ethics_dropped
        summary.rejected += listing.ethics_dropped
        _data_pass(store, archive, host, listing.rows, max_captures, summary)
    _error_pass(tombstone, store, archive, refresh, summaries)
    return RunResult(hosts=summaries, error_evidence=store.error_evidence_count())
