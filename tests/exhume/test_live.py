"""Live smoke test against the real Internet Archive (Req 10.5, 10.6).

Skipped by default (`addopts = "-m 'not live'"`); run with `pytest -m live`.

Archive etiquette: when the repo already holds stored data Listings under
`evidence/yahoo-finance-ichart/cdx/`, they are copied into the temporary Evidence_Root first,
so the test reuses them (Req 9.5) instead of re-downloading about 48 CDX pages. Without them,
the run fetches the Listings itself. Every request goes through the rate-limited client.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from revenant import cli
from revenant.exhume.models import Index, load_tombstone
from revenant.exhume.select import interval, parse_query

SLUG = "yahoo-finance-ichart"
HOST = "ichart.yahoo.com"
REPO = Path(__file__).resolve().parents[2]
CACHED_CDX = REPO / "evidence" / SLUG / "cdx"
WIDE = {"COLUMNS": "200"}


def _run(evidence_root: Path) -> Result:
    args = ["exhume", SLUG, "--max-captures", "20", "--evidence-dir", str(evidence_root)]
    return CliRunner().invoke(cli.app, args, env=WIDE)


def _downloaded_by_host(output: str, hosts: list[str]) -> dict[str, int]:
    """`downloaded` column of each Host row in the Run_Summary table."""
    result: dict[str, int] = {}
    for line in output.splitlines():
        fields = line.split()
        if fields and fields[0] in hosts:
            result[fields[0]] = int(fields[2])
    return result


@pytest.mark.live
def test_live_exhume_yahoo_finance_ichart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO)  # the CLI reads tombstones/<slug>.toml relative to the cwd
    hosts = load_tombstone(SLUG).hosts
    if CACHED_CDX.is_dir():
        shutil.copytree(CACHED_CDX, tmp_path / SLUG / "cdx")

    first = _run(tmp_path)
    assert first.exit_code == 0, first.output

    index = Index.model_validate_json((tmp_path / SLUG / "index.json").read_bytes())
    data = [e for e in index.entries.values() if e.host == HOST and e.kind == "data"]
    assert len(data) == 20, first.output
    intervals = {interval(parse_query(e.original)) for e in data} - {"none"}
    assert len(intervals) >= 2, intervals
    years = {e.requested_timestamp[:4] for e in data}
    assert len(years) >= 3, years

    second = _run(tmp_path)
    assert second.exit_code == 0, second.output
    downloaded = _downloaded_by_host(second.output, hosts)
    assert downloaded == dict.fromkeys(hosts, 0), second.output
