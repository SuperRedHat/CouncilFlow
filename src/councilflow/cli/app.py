"""Main Typer application for CouncilFlow."""

from __future__ import annotations

import typer

from councilflow import __version__

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


def main() -> None:
    """Run the CouncilFlow CLI."""
    app()


if __name__ == "__main__":
    main()
