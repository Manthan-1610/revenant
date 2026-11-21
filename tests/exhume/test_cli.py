"""CLI example tests: options, Run_Summary and exit codes (Req 10.1 to 10.4). No network."""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from rich.console import Console
from typer.testing import CliRunner, Result

from revenant import cli
from revenant.exhume.archive import RateLimiter
from revenant.exhume.content import wayback_digest
from revenant.exhume.models import HostSummary, RunResult, Tombstone
from tests.exhume.conftest import FakeClock

GOOD = "ichart.yahoo.com"
BAD = "real-chart.finance.yahoo.com"
CSV = (
    b"Date,Open,High,Low,Close,Volume,Adj Close\n2010-01-25,546.59,549.88,525.61,529.94,1,529.94\n"
)
HEADER = ["timestamp", "original", "mimetype", "statuscode", "digest", "length"]
DATA_ROW = [
    "20131213174436",
    "http://ichart.yahoo.com:80/table.csv?s=GOOG&a=0&b=1&c=2000&d=0&e=31&f=2010&g=w&ignore=.csv",
    "text/csv",
    "200",
    wayback_digest(CSV),
    "6731",
]
TOMBSTONE = f"""slug = "demo-api"
name = "Demo"
died = "2017-05"
hosts = ["{GOOD}", "{BAD}"]
paths = ["table.csv"]
mimetypes = ["text/csv"]
"""
WIDE = {"COLUMNS": "120"}

Handler = Callable[[httpx.Request], httpx.Response]


def handler(requests: list[httpx.Request]) -> Handler:
    """GOOD host: one data capture, no errors. BAD host: every CDX request gets a 503."""

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/cdx/search/cdx":
            if request.url.params["url"].startswith(BAD):
                return httpx.Response(503)
            if "statuscode:4.." in request.url.params.get_list("filter"):
                return httpx.Response(200, content=json.dumps([HEADER]).encode())
            return httpx.Response(200, content=json.dumps([HEADER, DATA_ROW]).encode())
        if request.url.path.startswith(f"/web/{DATA_ROW[0]}id_/"):
            return httpx.Response(200, content=CSV, headers={"Content-Type": "text/csv"})
        raise AssertionError(f"unexpected request {request.url}")

    return handle


@pytest.fixture
def requests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Chdir into a tmp repo with a Tombstone; route cli's client to a MockTransport."""
    (tmp_path / "tombstones").mkdir()
    (tmp_path / "tombstones" / "demo-api.toml").write_text(TOMBSTONE)
    monkeypatch.chdir(tmp_path)
    sent: list[httpx.Request] = []
    real_make_client = cli.make_client

    def mock_client(limiter: RateLimiter, ua: str, transport: object = None) -> httpx.Client:
        return real_make_client(limiter, ua, httpx.MockTransport(handler(sent)))

    monkeypatch.setattr(cli, "make_client", mock_client)
    monkeypatch.setattr(cli, "SystemClock", FakeClock)
    return sent


def run(*args: str) -> Result:
    return CliRunner().invoke(cli.app, ["exhume", *args], env=WIDE)


def test_help_exits_0_and_lists_exhume() -> None:
    result = CliRunner().invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    assert "exhume" in result.output


def test_exhume_help_lists_all_options() -> None:
    result = CliRunner().invoke(cli.app, ["exhume", "--help"], env=WIDE)
    assert result.exit_code == 0
    for option in ("--max-captures", "--evidence-dir", "--refresh"):
        assert option in result.output


def test_summary_table_error_line_and_failed_discovery(requests: list[httpx.Request]) -> None:
    result = run("demo-api", "--max-captures", "1")
    assert result.exit_code == 1
    out = result.output
    assert "Exhume: demo-api" in out
    for column in ("host", "found", "downloaded", "cached", "rejected"):
        assert column in out
    good_line = next(line for line in out.splitlines() if line.strip().startswith(GOOD))
    assert good_line.split()[:5] == [GOOD, "1", "1", "0", "0"]
    bad_line = next(line for line in out.splitlines() if line.strip().startswith(BAD))
    assert "discovery failed" in bad_line
    assert "error evidence: 0/10" in out
    assert f"discovery failed: {BAD} (data pass)" in out
    assert f"discovery failed: {BAD} (error pass)" in out
    # Hosts appear in Tombstone order.
    assert out.index(GOOD) < out.index(BAD)


def test_shortfall_is_marked(requests: list[httpx.Request]) -> None:
    result = run("demo-api", "--max-captures", "3")
    good_line = next(line for line in result.output.splitlines() if line.strip().startswith(GOOD))
    assert "short 1/3" in good_line


def test_successful_run_exits_0(requests: list[httpx.Request], tmp_path: Path) -> None:
    (tmp_path / "tombstones" / "demo-api.toml").write_text(TOMBSTONE.replace(f', "{BAD}"', ""))
    result = run("demo-api", "--max-captures", "1")
    assert result.exit_code == 0, result.output
    assert "discovery failed" not in result.output
    assert "short" not in result.output


def test_summary_table_fits_80_columns_without_ellipsis() -> None:
    hosts = ["ichart.yahoo.com", "ichart.finance.yahoo.com", "real-chart.finance.yahoo.com"]
    tombstone = Tombstone(
        slug="yahoo-finance-ichart",
        name="Yahoo Finance historical prices",
        died="2017-05",
        hosts=hosts,
        paths=["table.csv"],
        mimetypes=["text/csv"],
    )
    result = RunResult(
        hosts=[
            HostSummary(host=hosts[0], found=10620, downloaded=49, cached=1),
            HostSummary(host=hosts[1], found=19317, downloaded=49, cached=1),
            HostSummary(host=hosts[2], found=5015, downloaded=3),
        ],
        error_evidence=10,
    )
    console = Console(width=80, file=io.StringIO(), highlight=False)
    console.print(cli._summary_table(result, tombstone, 50))
    out = console.file.getvalue()  # type: ignore[attr-defined]
    print(out)
    assert "…" not in out
    lines = out.splitlines()
    for host in hosts:
        assert any(line.strip().startswith(f"{host} ") for line in lines), host
    short_line = next(line for line in lines if line.strip().startswith(hosts[2]))
    assert "short 3/50" in short_line


def test_max_captures_zero_is_rejected_without_request(requests: list[httpx.Request]) -> None:
    result = run("demo-api", "--max-captures", "0")
    assert result.exit_code != 0
    assert requests == []
