"""Main Typer application for CouncilFlow."""

from __future__ import annotations

import os

import typer

from councilflow import __version__
from councilflow.cli.delegate import delegate
from councilflow.cli.discuss import discuss
from councilflow.cli.status import status
from councilflow.cli.synthesize import synthesize
from councilflow.providers.base import (
    DELEGATED_STAGE_ENV_FLAG,
    DELEGATION_ID_ENV_KEY,
)
from councilflow.utils.lang import emit_console_text, emit_response

app = typer.Typer(
    name="council",
    add_completion=False,
    no_args_is_help=True,
    help="CouncilFlow CLI-first sidecar for multi-model collaboration.",
)

# Commands that remain callable inside a delegated sidecar. `status` stays
# available for inspection/debugging but may not mutate the workflow state.
_ALLOWED_RECURSIVE_SUBCOMMANDS: frozenset[str] = frozenset({"status", "version"})


def _is_delegated_stage() -> bool:
    return os.environ.get(DELEGATED_STAGE_ENV_FLAG) == "1"


def _reject_recursive_workflow(subcommand: str) -> None:
    delegation_id = os.environ.get(DELEGATION_ID_ENV_KEY)
    emit_console_text(
        emit_response(
            data=None,
            meta={"command": subcommand},
            error={
                "message": (
                    "CouncilFlow refuses to execute workflow-entry subcommands "
                    f"({subcommand}) inside a delegated sidecar."
                ),
                "error_kind": "recursive_workflow_violation",
                "delegation_id": delegation_id,
            },
        )
    )
    raise typer.Exit(code=2)


@app.callback()
def root(ctx: typer.Context) -> None:
    """CouncilFlow CLI-first sidecar for multi-model collaboration."""

    invoked = ctx.invoked_subcommand or ""
    if _is_delegated_stage() and invoked and invoked not in _ALLOWED_RECURSIVE_SUBCOMMANDS:
        _reject_recursive_workflow(invoked)


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

    from councilflow.utils.logging import configure_logging

    configure_logging()
    app()


if __name__ == "__main__":
    main()
