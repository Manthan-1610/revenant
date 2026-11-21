"""Evidence_Store: capture files, Listings and the Index below `<root>/<slug>/`."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

from revenant.exhume.models import CdxRow, Index, IndexEntry, Kind, Listing, PassKind

_EXTENSIONS = {
    "text/csv": "csv",
    "text/xml": "xml",
    "application/xml": "xml",
    "application/json": "json",
    "text/html": "html",
}


def atomic_write(path: Path, data: bytes) -> None:
    """Write `data` to a temp file in `path`'s directory, then rename it over `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def extension(mimetype: str, kind: Kind) -> str:
    """File extension for a capture: Error pages are always `html`, unknown types `bin`."""
    if kind == "error_page":
        return "html"
    return _EXTENSIONS.get(mimetype.split(";", 1)[0].strip().lower(), "bin")


def entry_key(host: str, timestamp: str, digest: str) -> str:
    """Index key `<host>/<timestamp>-<digest>`."""
    return f"{host}/{timestamp}-{digest}"


def dump_index(index: Index) -> bytes:
    """Byte-stable Index JSON: sorted keys, indent 2, trailing newline, UTF-8."""
    text = json.dumps(index.model_dump(mode="json"), sort_keys=True, indent=2, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


class EvidenceStore:
    """Layout: `<root>/<slug>/index.json`, `<slug>/cdx/<host>[.errors].json`, `<slug>/<host>/`."""

    def __init__(self, root: Path, slug: str) -> None:
        self.root = root
        self.slug = slug
        self.slug_dir = root / slug
        self.index_path = self.slug_dir / "index.json"
        self._index_cache: Index | None = None  # read-only view for is_cached, kept in sync

    def _listing_path(self, host: str, kind: str) -> Path:
        name = f"{host}.json" if kind == "data" else f"{host}.errors.json"
        return self.slug_dir / "cdx" / name

    def load_listing(self, host: str, kind: PassKind) -> Listing | None:
        """The stored Listing for a Host and pass, or None if missing, unparseable or not it."""
        try:
            raw = self._listing_path(host, kind).read_bytes()
            listing = Listing.model_validate_json(raw)
        except (OSError, ValueError):
            return None
        if listing.host != host or listing.kind != kind:
            return None
        return listing

    def is_cached(self, host: str, row: CdxRow) -> bool:
        """Index entry exists for the row and its file exists with the recorded size."""
        if self._index_cache is None:
            self._index_cache = self.load_index()
        entry = self._index_cache.entries.get(entry_key(host, row.timestamp, row.digest))
        if entry is None:
            return False
        try:
            return (self.slug_dir / entry.path).stat().st_size == entry.size
        except OSError:
            return False

    def save_listing(self, listing: Listing) -> None:
        """Write the Listing as compact JSON with an Atomic write."""
        data = json.dumps(listing.model_dump(mode="json"), separators=(",", ":"))
        atomic_write(self._listing_path(listing.host, listing.kind), data.encode("utf-8"))

    def load_index(self) -> Index:
        """Read `index.json`, or return an empty Index when it does not exist yet."""
        try:
            raw = self.index_path.read_bytes()
        except FileNotFoundError:
            return Index(slug=self.slug)
        return Index.model_validate_json(raw)

    def save_capture(
        self,
        host: str,
        row: CdxRow,
        kind: Kind,
        response: httpx.Response,
        served_timestamp: str | None,
        digest_verified: bool,
    ) -> IndexEntry:
        """Write the body byte for byte, then rewrite the Index; return the new entry."""
        body = response.content
        relative = f"{host}/{row.timestamp}-{row.digest}.{extension(row.mimetype, kind)}"
        atomic_write(self.slug_dir / relative, body)
        entry = IndexEntry(
            host=host,
            kind=kind,
            requested_timestamp=row.timestamp,
            served_timestamp=served_timestamp,
            original=row.original,
            mimetype=row.mimetype,
            statuscode=row.statuscode,
            digest=row.digest,
            length=row.length,
            final_url=str(response.url),
            path=relative,
            size=len(body),
            sha256=hashlib.sha256(body).hexdigest(),
            content_type=response.headers.get("content-type"),
            digest_verified=digest_verified,
            fetched_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        index = self.load_index()
        index.entries[entry_key(host, row.timestamp, row.digest)] = entry
        atomic_write(self.index_path, dump_index(index))
        self._index_cache = index
        return entry

    def error_evidence_count(self) -> int:
        """Number of Index entries of kind `error` or `error_page` for the Slug."""
        entries = self.load_index().entries.values()
        return sum(1 for entry in entries if entry.kind in ("error", "error_page"))
