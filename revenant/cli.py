"""Revenant command-line interface."""

from pathlib import Path
from typing import Annotated

import typer
from rich import box
from rich.console import Console
from rich.table import Table

from revenant.exhume.archive import ArchiveClient, RateLimiter, SystemClock, make_client, user_agent
from revenant.exhume.models import (
    HostSummary,
    RunResult,
    Tombstone,
    TombstoneError,
    load_tombstone,
)
from revenant.exhume.run import ERROR_EVIDENCE_CAP
from revenant.exhume.run import exhume as run_exhume
from revenant.exhume.store import EvidenceStore

app = typer.Typer()


@app.callback()
def callback() -> None:
    """Revenant: resurrect dead cloud APIs from the Internet Archive."""


@app.command()
def exhume(
    slug: str,
    max_captures: Annotated[int, typer.Option(min=1)] = 50,
    evidence_dir: Path = Path("evidence"),
    refresh: bool = False,
) -> None:
    """Collect archived evidence for a dead API slug."""
    try:
        tombstone = load_tombstone(slug)
    except TombstoneError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc

    clock = SystemClock()
    limiter = RateLimiter(clock)
    store = EvidenceStore(evidence_dir, slug)
    with make_client(limiter, user_agent()) as client:
        result = run_exhume(tombstone, store, ArchiveClient(client, clock), max_captures, refresh)

    console = Console(highlight=False)
    console.print(_summary_table(result, tombstone, max_captures))
    console.print(f"error evidence: {result.error_evidence}/{ERROR_EVIDENCE_CAP}")
    failed = [(host.host, kind) for host in result.hosts for kind in host.discovery_failed]
    for host_name, kind in failed:
        console.print(f"discovery failed: {host_name} ({kind} pass)")
    if failed:
        raise typer.Exit(1)


def _summary_table(result: RunResult, tombstone: Tombstone, n: int) -> Table:
    """Run_Summary: one row per Host in Tombstone order (Req 10.2, 10.3)."""
    table = Table(title=f"Exhume: {tombstone.slug}", box=box.SIMPLE_HEAD)
    table.add_column("host")
    for column in ("found", "downloaded", "cached", "rejected"):
        table.add_column(column, justify="right")
    table.add_column("note")
    by_host = {summary.host: summary for summary in result.hosts}
    for host_name in tombstone.hosts:
        summary = by_host.get(host_name, HostSummary(host=host_name))
        stored = summary.downloaded + summary.cached
        if summary.discovery_failed:
            note = "discovery failed"
        elif stored < n:
            note = f"short {stored}/{n}"
        else:
            note = ""
        table.add_row(
            host_name,
            str(summary.found),
            str(summary.downloaded),
            str(summary.cached),
            str(summary.rejected),
            note,
        )
    return table


def main() -> None:
    """Console-script entry point."""
    app()
