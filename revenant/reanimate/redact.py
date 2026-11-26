"""Redaction of secrets before anything is written or printed (Req 7.2)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import quote

REDACTED = "[REDACTED]"
HOME = "~"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

_DRIVE_RE = re.compile(r"^([A-Za-z]):[\\/]")
_PERCENT_RE = re.compile(r"%([0-9A-Fa-f]{2})")
_COLONS = (":", "%3A")
_WINDOWS_SEPS = ("\\", "/", "\\\\", "%5C")


def _literal(text: str) -> str:
    """`text` as a regex that matches it exactly, with `%XX` hex digits case-insensitive."""
    out: list[str] = []
    pos = 0
    for match in _PERCENT_RE.finditer(text):
        out.append(re.escape(text[pos : match.start()]))
        hex_digits = "".join(
            f"[{c.lower()}{c.upper()}]" if c.isalpha() else c for c in match.group(1)
        )
        out.append("%" + hex_digits)
        pos = match.end()
    out.append(re.escape(text[pos:]))
    return "".join(out)


def _segment_forms(segments: list[str]) -> list[list[str]]:
    """Raw segments, plus their percent-encoded form when it differs (as in `file://` URIs)."""
    forms = [segments]
    encoded = [quote(seg, safe="") for seg in segments]
    if encoded != segments:
        forms.append(encoded)
    return forms


def home_spellings(home: str) -> list[str]:
    """Regex alternatives for every Home_Path spelling, longest spelling first."""
    spellings: dict[str, int] = {}  # pattern -> length of the literal it matches
    drive = _DRIVE_RE.match(home)
    if drive:
        letter = drive.group(1)
        segments = [s for s in re.split(r"[\\/]+", home[drive.end() :]) if s]
        for colon in _COLONS:
            for sep in _WINDOWS_SEPS:
                for segs in _segment_forms(segments):
                    literal = letter + colon + sep + sep.join(segs)
                    pattern = f"[{letter.lower()}{letter.upper()}]" + _literal(literal[1:])
                    spellings[pattern] = max(spellings.get(pattern, 0), len(literal))
    else:
        segments = [s for s in home.split("/") if s]
        if not segments:  # a home of "/" would redact every slash
            return []
        for segs in _segment_forms(segments):
            literal = "/" + "/".join(segs)
            spellings[_literal(literal)] = len(literal)
    return sorted(spellings, key=lambda p: (-spellings[p], p))


class Redactor:
    """Replaces secrets in text before it reaches a file or the console (Req 7.2).

    Order: the `KIRO_API_KEY` value (when set and non-empty), then every Email_Like_String,
    become `[REDACTED]`; then every Home_Path spelling becomes `~`, longest spelling first.
    Home_Path spellings: native, forward-slash, JSON-escaped (backslashes doubled) and
    percent-encoded as in `file://` URIs (`c%3A/Users/<name>`, `C%3A%5CUsers%5C<name>`),
    with the drive letter and percent-escape hex digits matched case-insensitively.

    Accepted over-redaction: the email pattern also matches text that merely looks like an
    address, for example `n@app.get` inside an escaped `\\n@app.get` in a JSON-encoded
    `server.py`; that text becomes `[REDACTED]` too.
    """

    def __init__(self, api_key: str | None, home: Path | str) -> None:
        self.api_key = api_key or None
        alternatives = home_spellings(str(home))
        self._home_re = re.compile("|".join(alternatives)) if alternatives else None

    @classmethod
    def from_env(cls) -> Redactor:
        return cls(os.environ.get("KIRO_API_KEY"), Path.home())

    def __call__(self, text: str) -> str:
        if self.api_key:
            text = text.replace(self.api_key, REDACTED)
        text = EMAIL_RE.sub(REDACTED, text)
        if self._home_re is not None:
            text = self._home_re.sub(HOME, text)
        return text
