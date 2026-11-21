"""CDX discovery: query building, page parsing, pagination and merging."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

from revenant.exhume.archive import ArchiveClient, ArchiveError
from revenant.exhume.ethics import has_auth_param
from revenant.exhume.models import CdxRow, Listing, PassKind, Tombstone
from revenant.exhume.store import EvidenceStore

CDX_URL = "https://web.archive.org/cdx/search/cdx"
PAGE_SIZE = 1000
FIELDS = ("timestamp", "original", "mimetype", "statuscode", "digest", "length")


class CdxParseError(Exception):
    """A CDX JSON page does not have the expected shape."""


class DiscoveryError(Exception):
    """CDX discovery failed for one Host and pass; no Listing was produced."""


def mimetype_regex(mimetypes: list[str]) -> str:
    """One regex matching exactly the given mimetypes: `a` or `(a|b)`, members escaped."""
    escaped = [re.escape(m) for m in mimetypes]
    if len(escaped) == 1:
        return escaped[0]
    return "(" + "|".join(escaped) + ")"


def build_params(
    host: str, path: str, kind: PassKind, mimetypes: list[str]
) -> list[tuple[str, str]]:
    """CDX query parameters for one Host, path and pass.

    Data pass: `statuscode:2..` plus one mimetype filter (Req 3.1). Error pass: `statuscode:4..`
    and no mimetype filter, because archived 4xx replies are `text/html` (Req 3.6, F3, F4).
    """
    if kind == "data":
        filters = [
            ("filter", "statuscode:2.."),
            ("filter", f"mimetype:{mimetype_regex(mimetypes)}"),
        ]
    else:
        filters = [("filter", "statuscode:4..")]
    return [
        ("url", f"{host}/{path}*"),
        ("output", "json"),
        ("collapse", "digest"),
        ("fl", ",".join(FIELDS)),
        *filters,
        ("limit", str(PAGE_SIZE)),
        ("showResumeKey", "true"),
    ]


def _is_str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def parse_page(payload: bytes) -> tuple[list[CdxRow], str | None]:
    """Parse one CDX JSON page into rows and an optional Resume_Key."""
    try:
        data = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CdxParseError(f"CDX page is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise CdxParseError("CDX page is not a JSON array")
    if not data:
        return [], None

    header = data[0]
    if not _is_str_list(header):
        raise CdxParseError("CDX header row is not a list of strings")
    missing = [name for name in FIELDS if name not in header]
    if missing:
        raise CdxParseError(f"CDX header lacks fields: {', '.join(missing)}")
    if len(set(header)) != len(header):
        raise CdxParseError("CDX header has duplicate fields")

    body = data[1:]
    key: str | None = None
    if len(body) >= 2 and body[-2] == [] and _is_str_list(body[-1]) and len(body[-1]) == 1:
        key = body[-1][0]
        body = body[:-2]

    rows: list[CdxRow] = []
    for number, raw in enumerate(body, start=1):
        if not _is_str_list(raw) or len(raw) != len(header):
            raise CdxParseError(f"CDX row {number} does not match the header")
        mapped = dict(zip(header, raw, strict=True))
        rows.append(CdxRow(**{name: mapped[name] for name in FIELDS}))
    return rows, key


def merge_rows(rows: Iterable[CdxRow]) -> list[CdxRow]:
    """One row per digest (earliest timestamp wins), sorted by (timestamp, digest)."""
    best: dict[str, CdxRow] = {}
    for row in rows:
        kept = best.get(row.digest)
        if kept is None or row.timestamp < kept.timestamp:
            best[row.digest] = row
    return sorted(best.values(), key=lambda r: (r.timestamp, r.digest))


def _fetch_page(
    archive: ArchiveClient, params: list[tuple[str, str]], host: str, kind: PassKind
) -> tuple[list[CdxRow], str | None]:
    try:
        response = archive.get(CDX_URL, params=params)
    except ArchiveError as exc:
        raise DiscoveryError(f"{host} ({kind} pass): {exc}") from exc
    if not 200 <= response.status_code <= 299:
        raise DiscoveryError(f"{host} ({kind} pass): CDX returned HTTP {response.status_code}")
    try:
        return parse_page(response.content)
    except CdxParseError as exc:
        raise DiscoveryError(f"{host} ({kind} pass): {exc}") from exc


def fetch_listing(
    archive: ArchiveClient, tombstone: Tombstone, host: str, kind: PassKind
) -> Listing:
    """List every page of every Tombstone path for one Host and pass, merged by digest.

    Rows with an Auth-like parameter are dropped and only counted (Req 8.1, 8.5).
    Raises `DiscoveryError` on any failure, so a partial Listing is never returned.
    """
    first_params: list[tuple[str, str]] | None = None
    collected: list[CdxRow] = []
    for path in tombstone.paths:
        params = build_params(host, path, kind, tombstone.mimetypes)
        if first_params is None:
            first_params = params
        key: str | None = None
        while True:
            page_params = params if key is None else [*params, ("resumeKey", key)]
            rows, key = _fetch_page(archive, page_params, host, kind)
            collected.extend(rows)
            if key is None:
                break
    # Ethics_Filter before merging (Req 8.1): a clean row is never lost to an earlier auth row
    # sharing its digest. `ethics_dropped` counts unique digests seen only in dropped rows, so
    # `len(rows) + ethics_dropped` is the number of unique captures the CDX listed.
    clean: list[CdxRow] = []
    dropped_digests: set[str] = set()
    for row in collected:
        if has_auth_param(row.original):
            dropped_digests.add(row.digest)
        else:
            clean.append(row)
    rows = merge_rows(clean)
    dropped_digests -= {row.digest for row in rows}
    return Listing(
        host=host,
        kind=kind,
        params=first_params or [],
        rows=rows,
        ethics_dropped=len(dropped_digests),
    )


def get_listing(
    archive: ArchiveClient,
    store: EvidenceStore,
    tombstone: Tombstone,
    host: str,
    kind: PassKind,
    refresh: bool,
) -> Listing:
    """The stored Listing unless `refresh` or none is stored; else fetch and save (Req 9.5).

    A stored Listing is re-filtered on load, because Listings cached before the Ethics_Filter
    existed may still hold Auth-like URLs. If any row is dropped, the clean Listing is re-saved.
    Raises `DiscoveryError` when a fresh fetch fails.
    """
    if not refresh:
        cached = store.load_listing(host, kind)
        if cached is not None:
            clean = [row for row in cached.rows if not has_auth_param(row.original)]
            dropped = len(cached.rows) - len(clean)
            if dropped == 0:
                return cached
            listing = cached.model_copy(
                update={"rows": clean, "ethics_dropped": cached.ethics_dropped + dropped}
            )
            store.save_listing(listing)
            return listing
    listing = fetch_listing(archive, tombstone, host, kind)
    store.save_listing(listing)
    return listing
