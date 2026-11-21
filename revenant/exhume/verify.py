"""Offline integrity check of the Evidence_Store: re-hash every Index entry's file."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from revenant.exhume.store import EvidenceStore

F19_HINT = "orig transfer-encoding may be chunked (F19)"


@dataclass
class VerifyReport:
    """Entries checked, failing file paths, and Index keys by `digest_verified`."""

    checked: int = 0
    failures: list[str] = field(default_factory=list)
    verified_true: int = 0
    verified_false: list[str] = field(default_factory=list)


def verify(store: EvidenceStore) -> VerifyReport:
    """Missing files and SHA-256 mismatches are failures naming the file (no network)."""
    report = VerifyReport()
    for key, entry in sorted(store.load_index().entries.items()):
        report.checked += 1
        path = store.slug_dir / entry.path
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            report.failures.append(f"{path.as_posix()} (missing)")
        else:
            if actual != entry.sha256:
                report.failures.append(f"{path.as_posix()} (sha256 mismatch)")
        if entry.digest_verified:
            report.verified_true += 1
        else:
            report.verified_false.append(key)
    return report
