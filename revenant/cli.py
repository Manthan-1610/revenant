"""Revenant command-line interface."""

from pathlib import Path
from typing import Annotated

import typer

from revenant.exhume.archive import ArchiveClient, RateLimiter, SystemClock, make_client, user_agent
from revenant.exhume.models import TombstoneError, load_tombstone
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

    failed: list[str] = []
    for host in result.hosts:
        typer.echo(
            f"{host.host}: found={host.found} downloaded={host.downloaded} "
            f"cached={host.cached} rejected={host.rejected}"
        )
        failed.extend(f"{host.host} ({kind} pass)" for kind in host.discovery_failed)
    typer.echo(f"error evidence: {result.error_evidence}")
    for item in failed:
        typer.echo(f"discovery failed: {item}", err=True)
    if failed:
        raise typer.Exit(1)


def main() -> None:
    """Console-script entry point."""
    app()
