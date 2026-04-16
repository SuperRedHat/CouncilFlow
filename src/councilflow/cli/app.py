"""Main Typer application for CouncilFlow."""

from __future__ import annotations

import typer

from councilflow import __version__
from councilflow.cli.delegate import delegate
from councilflow.cli.discuss import discuss
from councilflow.cli.status import status
from councilflow.cli.synthesize import synthesize

app = typer.Typer(
    name="council",
    add_completion=False,
    no_args_is_help=True,
    help="CouncilFlow CLI-first sidecar for multi-model collaboration.",
)


@app.callback()
def root() -> None:
    """CouncilFlow CLI-first sidecar for multi-model collaboration."""


@app.command()
def version() -> None:
    """Show the installed CouncilFlow version."""
    typer.echo(__version__)


app.command(name="discuss")(discuss)
app.command(name="delegate")(delegate)
app.command(name="status")(status)
app.command(name="synthesize")(synthesize)


def main() -> None:
    """Run the CouncilFlow CLI."""
    app()


if __name__ == "__main__":
    main()
