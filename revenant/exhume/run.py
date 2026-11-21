"""Exhume orchestration: discovery, selection, download and storage per Host."""

from __future__ import annotations

import re
from datetime import UTC
from email.utils import parsedate_to_datetime

import httpx

from revenant.exhume.archive import ArchiveClient, ArchiveError
from revenant.exhume.cdx import DiscoveryError, fetch_listing
from revenant.exhume.content import classify, wayback_digest
from revenant.exhume.models import CdxRow, HostSummary, RunResult, Tombstone
from revenant.exhume.select import select
from revenant.exhume.store import EvidenceStore

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


def exhume(
    tombstone: Tombstone,
    store: EvidenceStore,
    archive: ArchiveClient,
    max_captures: int,
    refresh: bool,
) -> RunResult:
    """Run the data pass for every Host, downloading the deterministic `select` sample.

    Backfill after rejections arrives in task 9.

    `refresh` is accepted now; Listing cache reuse arrives in task 9.
    """
    summaries: list[HostSummary] = []
    for host in tombstone.hosts:
        summary = HostSummary(host=host)
        summaries.append(summary)
        try:
            listing = fetch_listing(archive, tombstone, host, "data")
        except DiscoveryError:
            summary.discovery_failed.append("data")
            continue
        store.save_listing(listing)
        # Req 10.3: Ethics_Filter drops count as found and as rejected.
        summary.found = len(listing.rows) + listing.ethics_dropped
        summary.rejected += listing.ethics_dropped
        for row in select(listing.rows, max_captures):
            try:
                response = _fetch_capture(archive, row)
            except ArchiveError:
                summary.rejected += 1
                continue
            if response is None:
                summary.rejected += 1
                continue
            kind = classify(response.content, response.headers.get("content-type"), row.mimetype)
            if kind == "error_page":
                # Req 7.5: keep it as Error_Evidence while the Slug cap allows; never as data.
                summary.rejected += 1
                if store.error_evidence_count() >= ERROR_EVIDENCE_CAP:
                    continue
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
            else:
                summary.downloaded += 1
    return RunResult(hosts=summaries, error_evidence=store.error_evidence_count())
