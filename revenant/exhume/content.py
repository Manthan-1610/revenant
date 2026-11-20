"""Content checks for fetched captures: HTML sniffing, Offline pages, Error pages, digests."""

from __future__ import annotations

import base64
import hashlib
import re
from typing import Literal

_BOM = b"\xef\xbb\xbf"
_HTML_STARTS = (b"<!doctype", b"<html")
_TITLE_RE = re.compile(rb"<title\b[^>]*>([^<]*)", re.IGNORECASE)
OFFLINE_MARKER = b"Temporarily Offline"


def _media_type(content_type: str | None) -> str:
    """Lower-cased media type without parameters; empty when absent."""
    if not content_type:
        return ""
    return content_type.split(";", 1)[0].strip().lower()


def is_html(content_type: str | None, body: bytes) -> bool:
    """HTML by Content-Type `text/html`, or a body starting `<!DOCTYPE`/`<html` (Req 7.1)."""
    if _media_type(content_type) == "text/html":
        return True
    head = body.removeprefix(_BOM).lstrip()[:16].lower()
    return head.startswith(_HTML_STARTS)


def is_offline_page(content_type: str | None, body: bytes) -> bool:
    """The Archive's "Temporarily Offline" page: HTML whose first `<title>` names it (F9).

    The HTTP status is deliberately not an input: the page can arrive with status 200.
    """
    if not is_html(content_type, body):
        return False
    match = _TITLE_RE.search(body)
    return match is not None and OFFLINE_MARKER in match.group(1)


def wayback_digest(body: bytes) -> str:
    """Unpadded upper-case base32 SHA-1 of the raw body, as in the CDX `digest` field (F8)."""
    return base64.b32encode(hashlib.sha1(body).digest()).decode("ascii").rstrip("=")


def classify(
    body: bytes, content_type: str | None, cdx_mimetype: str
) -> Literal["data", "error_page"]:
    """`error_page` for non-Offline HTML under a CDX mimetype other than `text/html` (Req 7.4)."""
    if (
        is_html(content_type, body)
        and not is_offline_page(content_type, body)
        and _media_type(cdx_mimetype) != "text/html"
    ):
        return "error_page"
    return "data"
