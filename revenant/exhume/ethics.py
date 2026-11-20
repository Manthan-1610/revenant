"""Ethics filter: drop archived URLs that carry Auth-like parameters (necromancy-ethics)."""

from __future__ import annotations

import html
from urllib.parse import parse_qsl, urlsplit

AUTH_SUBSTRINGS = ("crumb", "cookie", "token", "key", "session", "email")


def _names(query: str) -> list[str]:
    """Percent-decoded parameter names, including names without a value."""
    return [name for name, _ in parse_qsl(query, keep_blank_values=True)]


def has_auth_param(original: str) -> bool:
    """True when a decoded parameter name contains an Auth substring, case-insensitively.

    Only names count; values, the path and the fragment never do (Req 8.2, 8.3). The query
    is checked both as archived and HTML-unescaped (F15 `&amp;` artifacts), so neither form
    can hide a name: `&amp;crumb=x` is caught, and so is `notoken=x`,
    which `html.unescape` would turn into `¬oken=x`. An unparseable URL is rejected.
    """
    try:
        query = urlsplit(original).query
        names = _names(query) + _names(html.unescape(query))
    except ValueError:
        return True
    return any(sub in name.lower() for name in names for sub in AUTH_SUBSTRINGS)
