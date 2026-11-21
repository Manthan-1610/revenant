"""Query_Normalizer: decoded name-value pairs of a capture's `original` URL (Req 2.1, F15)."""

from __future__ import annotations

import html
from urllib.parse import urlsplit

from revenant.exhume.select import parse_query


def unescape_fixpoint(text: str) -> str:
    """Apply `html.unescape` until the text stops changing (each change shortens it)."""
    while True:
        unescaped = html.unescape(text)
        if unescaped == text:
            return text
        text = unescaped


def normalize_query(original: str) -> list[tuple[str, str]]:
    """Pairs of `original`'s query after repeated unescaping, so `&amp;amp;d=0` gives `d=0`.

    Capture_Shape and Interval come from Exhume's `parameter_shape` and `interval` on these pairs.
    At the fixpoint, `parse_query`'s own single unescape is a no-op.
    """
    try:
        query = urlsplit(original).query
    except ValueError:
        return []
    return parse_query("?" + unescape_fixpoint(query))
