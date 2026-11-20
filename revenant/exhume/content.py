"""Content checks for fetched captures. Task 5 adds only the Wayback digest."""

from __future__ import annotations

import base64
import hashlib


def wayback_digest(body: bytes) -> str:
    """Unpadded upper-case base32 SHA-1 of the raw body, as in the CDX `digest` field (F8)."""
    return base64.b32encode(hashlib.sha1(body).digest()).decode("ascii").rstrip("=")
