"""Revenant command-line interface."""

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich import box
from rich.console import Console
from rich.table import Table

from revenant.autopsy.contract import CONTRACT_FILE, load_contract, write_contract
from revenant.autopsy.evidence import AutopsyError, load_evidence
from revenant.autopsy.infer import infer
from revenant.autopsy.render import write_spec
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
from revenant.exhume.verify import F19_HINT
from revenant.exhume.verify import verify as run_verify
from revenant.reanimate.errors import ReanimateError
from revenant.reanimate.runner import HEADLESS, Deps
from revenant.reanimate.runner import reanimate as run_reanimate

app = typer.Typer()

# Fits the longest hero host (28 chars).
HOST_MIN_WIDTH = len("real-chart.finance.yahoo.com")


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


@app.command()
def verify(slug: str, evidence_dir: Path = Path("evidence")) -> None:
    """Re-hash stored captures against the Index (no network)."""
    store = EvidenceStore(evidence_dir, slug)
    if not store.index_path.is_file():
        typer.echo(f"error: no index at {store.index_path.as_posix()}", err=True)
        raise typer.Exit(1)
    report = run_verify(store)
    typer.echo(f"checked: {report.checked}")
    typer.echo(f"sha256 failures: {len(report.failures)}")
    for failure in report.failures:
        typer.echo(f"  {failure}")
    typer.echo(f"digest_verified: true={report.verified_true} false={len(report.verified_false)}")
    for key in report.verified_false:
        typer.echo(f"{key}  {F19_HINT}")
    if report.failures:
        raise typer.Exit(1)


@app.command()
def autopsy(
    slug: str,
    evidence_dir: Path = Path("evidence"),
    crypt_dir: Path = Path("crypt"),
    specs_dir: Path = Path(".kiro/specs"),
) -> None:
    """Infer the dead API's contract from stored evidence (no network)."""
    try:
        index_bytes, captures = load_evidence(evidence_dir, slug)
        contract = infer(slug, index_bytes, captures)
        # write_contract re-validates before its atomic write, so a failure keeps the old file.
        path = write_contract(contract, crypt_dir)
    except AutopsyError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    except ValidationError as exc:
        typer.echo(f"error: {CONTRACT_FILE}: {_validation_message(exc)}", err=True)
        raise typer.Exit(1) from exc
    months = contract.months
    typer.echo(f"month indexing: {months.indexing}")
    typer.echo(f"decisive: H=0 {months.decisive_h0.count}, H=1 {months.decisive_h1.count}")
    typer.echo(f"wrote: {path.as_posix()}")
    if months.indexing == "undetermined":
        typer.echo("error: month indexing undetermined; no spec rendered", err=True)
        raise typer.Exit(2)
    # Req 8.1: the renderer reads only the contract.json just written, never the in-memory model.
    spec = write_spec(load_contract(path), specs_dir)
    typer.echo(f"wrote: {spec.as_posix()}")


@app.command()
def reanimate(
    slug: str,
    prompt_only: Annotated[
        bool, typer.Option(help="Write the Reanimate_Prompt and stop (no kiro-cli).")
    ] = False,
    built_by: Annotated[
        str, typer.Option(help="kiro-cli-headless, or kiro-ide-chat for an IDE-built server.")
    ] = HEADLESS,
) -> None:
    """Build and check a revenant server from the generated spec."""
    try:
        summary = run_reanimate(slug, prompt_only, built_by, Deps())
    except ReanimateError as exc:
        typer.echo(f"error: {exc.stage}: {exc.message}", err=True)
        raise typer.Exit(exc.code) from exc
    for line in summary.lines():
        typer.echo(line)


def _validation_message(exc: ValidationError) -> str:
    """`<loc>: <message>` of the first Contract validation error (Req 7.2)."""
    first = exc.errors()[0]
    loc = ".".join(str(part) for part in first["loc"]) or "<root>"
    return f"{loc}: {first['msg']}"


def _summary_table(result: RunResult, tombstone: Tombstone, n: int) -> Table:
    """Run_Summary: one row per Host in Tombstone order (Req 10.2, 10.3)."""
    # Never let Rich truncate with "…": the Windows console cannot render it (Req 10.2).
    # Tight padding, so the note column still fits "short 49/50" at 80 columns.
    table = Table(
        title=f"Exhume: {tombstone.slug}",
        box=box.SIMPLE_HEAD,
        show_edge=False,
        pad_edge=False,
        collapse_padding=True,
    )
    table.add_column("host", no_wrap=True, min_width=HOST_MIN_WIDTH, overflow="crop")
    for column in ("found", "downloaded", "cached", "rejected"):
        table.add_column(column, justify="right", no_wrap=True, overflow="crop")
    table.add_column("note", overflow="fold")
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
