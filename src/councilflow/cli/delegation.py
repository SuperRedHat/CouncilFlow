"""CLI surface for inspecting and polling existing delegation artifacts.

The `delegate` subcommand runs synchronously: the controller's shell is blocked
for as long as the sidecar CLI takes to finish. Real workloads (Canvas UI
generation, multi-file refactors, full test suites) can easily exceed a host
controller's shell command timeout (~3–4 min in some desktop UIs). This module
gives controllers a non-blocking recovery path:

  council delegation wait del_20260418T234340487928Z --timeout 7200

The subcommand polls `.council/delegations/<id>/record.json` until one of:
  * `record.json` exists → return the final status / paths
  * total wait exceeds `--timeout` → exit 1 with `error_kind=wait_timeout`
  * project state missing (no delegations dir or bad id) → exit 1 with
    `error_kind=delegation_not_found`

The controller skill is expected to call `delegation wait` whenever its own
shell call to `council delegate` returned timeout, so workflow_failure is only
emitted when the record truly says failed or when the 2-hour budget is spent.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import typer

from councilflow.state.store import CouncilStateStore
from councilflow.utils.lang import emit_console_text, emit_response

DEFAULT_WAIT_TIMEOUT_SECONDS = 7200
DEFAULT_POLL_INTERVAL_SECONDS = 30
MIN_POLL_INTERVAL_SECONDS = 1

_wait_delegation_app = typer.Typer(
    name="delegation",
    add_completion=False,
    no_args_is_help=True,
    help="Inspect and poll existing `council delegate` artifacts without re-invoking a model.",
)

DEFAULT_PROJECT_ROOT = Path(".")
PROJECT_ROOT_OPTION = typer.Option(
    DEFAULT_PROJECT_ROOT,
    "--project-root",
    resolve_path=True,
    file_okay=False,
    dir_okay=True,
    help="Project root used to resolve .council/delegations/<id>.",
)
TIMEOUT_OPTION = typer.Option(
    DEFAULT_WAIT_TIMEOUT_SECONDS,
    "--timeout",
    min=1,
    help="Maximum seconds to wait for the delegation to finish. Defaults to 7200 (2h).",
)
POLL_INTERVAL_OPTION = typer.Option(
    DEFAULT_POLL_INTERVAL_SECONDS,
    "--poll-interval",
    min=MIN_POLL_INTERVAL_SECONDS,
    help="Seconds between filesystem polls while waiting. Defaults to 30.",
)


def _load_record(record_path: Path) -> dict | None:
    """Return parsed record.json contents or None if absent / unreadable."""

    if not record_path.is_file():
        return None
    try:
        return json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _emit_and_exit(payload: str, code: int) -> None:
    emit_console_text(payload)
    raise typer.Exit(code=code)


@_wait_delegation_app.command("wait")
def wait(
    delegation_id: str = typer.Argument(
        ...,
        help="Delegation identifier (e.g. del_20260418T234340487928Z).",
    ),
    project_root: Path = PROJECT_ROOT_OPTION,
    timeout: int = TIMEOUT_OPTION,
    poll_interval: int = POLL_INTERVAL_OPTION,
) -> None:
    """Block until `.council/delegations/<id>/record.json` appears, or timeout."""

    store = CouncilStateStore(project_root)
    delegation_dir = store.paths.delegations / delegation_id
    record_path = delegation_dir / "record.json"
    handoff_path = delegation_dir / "handoff.yaml"

    if not delegation_dir.is_dir():
        _emit_and_exit(
            emit_response(
                data=None,
                meta={
                    "command": "delegation wait",
                    "delegation_id": delegation_id,
                    "project_root": str(store.paths.project_root),
                },
                error={
                    "message": (
                        f"Delegation directory {delegation_dir} does not exist. "
                        "Confirm the delegation id and project root."
                    ),
                    "error_kind": "delegation_not_found",
                    "delegation_id": delegation_id,
                },
            ),
            code=1,
        )

    effective_interval = max(poll_interval, MIN_POLL_INTERVAL_SECONDS)
    start = time.monotonic()
    record = _load_record(record_path)
    polled_iterations = 0
    while record is None:
        polled_iterations += 1
        elapsed = time.monotonic() - start
        if elapsed >= timeout:
            _emit_and_exit(
                emit_response(
                    data={
                        "delegation_id": delegation_id,
                        "handoff_exists": handoff_path.is_file(),
                        "record_exists": False,
                        "elapsed_seconds": round(elapsed, 3),
                        "polled_iterations": polled_iterations,
                    },
                    meta={
                        "command": "delegation wait",
                        "timeout_seconds": timeout,
                        "poll_interval_seconds": effective_interval,
                    },
                    error={
                        "message": (
                            f"Delegation {delegation_id} did not produce record.json "
                            f"within {timeout}s."
                        ),
                        "error_kind": "wait_timeout",
                        "delegation_id": delegation_id,
                    },
                ),
                code=1,
            )
        time.sleep(effective_interval)
        record = _load_record(record_path)

    elapsed = time.monotonic() - start
    delegation_status = str(record.get("status") or "unknown")
    error_kind = record.get("error_kind")
    # TASK-120: a failed attempt that the `delegate` run is retrying on a fallback
    # model is NOT terminal. The retry executes under a *new* delegation id, so
    # THIS record never resolves further — surface `retry_pending` (no error,
    # exit 0) so a controller polling this id does not conclude terminal failure
    # mid-retry. `retried_with_model` tells it which model the retry is on.
    retry_pending = delegation_status == "failed" and bool(
        record.get("fallback_retry_pending")
    )
    surfaced_status = "retry_pending" if retry_pending else delegation_status
    is_terminal_failure = delegation_status == "failed" and not retry_pending
    emit_console_text(
        emit_response(
            data={
                "delegation_id": delegation_id,
                "status": surfaced_status,
                "retry_pending": retry_pending,
                "retried_with_model": record.get("retried_with_model"),
                "record": record,
                "handoff_path": record.get("handoff_path"),
                "result_path": record.get("result_path"),
                "elapsed_seconds": round(elapsed, 3),
                "polled_iterations": polled_iterations,
            },
            meta={
                "command": "delegation wait",
                "timeout_seconds": timeout,
                "poll_interval_seconds": effective_interval,
            },
            error=(
                {
                    "message": str(record.get("error") or "delegation failed"),
                    "error_kind": error_kind or "delegation_failed",
                    "delegation_id": delegation_id,
                }
                if is_terminal_failure
                else None
            ),
        )
    )
    if is_terminal_failure:
        raise typer.Exit(code=1)


delegation_app = _wait_delegation_app
