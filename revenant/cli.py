"""Revenant command-line interface."""

from pathlib import Path
from typing import Annotated

import typer

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
    typer.echo("not implemented")


def main() -> None:
    """Console-script entry point."""
    app()
