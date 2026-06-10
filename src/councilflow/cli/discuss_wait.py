"""CLI surface for polling existing `council discuss` artifacts.

The `discuss` subcommand runs synchronously: the controller's shell is blocked
for as long as the multi-model discussion takes to converge. Real workloads
(5-round multi-model exchange with 2-3 critic models) routinely exceed a host
controller's shell command timeout (~3-4 min in most desktop UIs). This module
gives controllers a non-blocking recovery path:

  council discussion wait disc_20260418T234340487928Z --timeout 7200

The subcommand polls `.council/discuss/<id>/record.json` and the
`.council/discuss/<id>/summary.md` artifact until **both** are in the expected
terminal state:

  * `record.json` exists, `record.status == "completed"`, AND
    `summary.md` is present and readable → return the summary path.
  * `record.json` exists, `record.status == "failed"` → exit 1 with
    `error_kind=discussion_failed`.
  * `record.json` exists with `status="completed"` but `summary.md` is
    missing or unreadable → exit 1 with `error_kind=summary_missing`.
  * `record.json` exists but is corrupt (non-JSON / parse error) →
    exit 1 with `error_kind=record_corrupt`.
  * `.council/discuss/<id>/` directory missing → exit 1 with
    `error_kind=discussion_not_found`.
  * total wait exceeds `--timeout` → exit 1 with `error_kind=wait_timeout`.

The dual completion condition (record.status==completed AND summary.md
readable) is intentional: `DiscussionOrchestrator.run()` writes
`record.json(status="running")` immediately on start (see
`discussion_orchestrator.py:93-139`), so a single-condition check would
return prematurely while the discussion is still running. A second
between record.status flipping to "completed" and summary.md landing on
disk is rare but observable, so the polling loop also tolerates that
brief window.

The CLI is named `council discussion wait` (noun form) to mirror the
existing `council delegation wait` and to avoid restructuring the
`council discuss "question"` verb-form command. Controller skills are
expected to call `discussion wait` whenever their own shell call to
`council discuss` returned a timeout — a workflow_failure should only
be emitted when the record truly says failed or when the 2-hour budget
is spent.

Discussion id recovery after a shell timeout is handled by the calling
skill via `council status --json` reading
`state.json::last_discussion_id` (written by the orchestrator within
~50ms of `run()` start, before any LLM call). No stderr-parsing is
required.
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

_wait_discussion_app = typer.Typer(
    name="discussion",
    add_completion=False,
    no_args_is_help=True,
    help="Inspect and poll existing `council discuss` artifacts without re-invoking models.",
)

DEFAULT_PROJECT_ROOT = Path(".")
PROJECT_ROOT_OPTION = typer.Option(
    DEFAULT_PROJECT_ROOT,
    "--project-root",
    resolve_path=True,
    file_okay=False,
    dir_okay=True,
    help="Project root used to resolve .council/discuss/<id>.",
)
TIMEOUT_OPTION = typer.Option(
    DEFAULT_WAIT_TIMEOUT_SECONDS,
    "--timeout",
    min=1,
    help="Maximum seconds to wait for the discussion to finish. Defaults to 7200 (2h).",
)
POLL_INTERVAL_OPTION = typer.Option(
    DEFAULT_POLL_INTERVAL_SECONDS,
    "--poll-interval",
    min=MIN_POLL_INTERVAL_SECONDS,
    help="Seconds between filesystem polls while waiting. Defaults to 30.",
)


class _RecordCorruptError(Exception):
    """Raised when record.json exists but cannot be parsed."""


def _load_record(record_path: Path) -> dict | None:
    """Return parsed record.json contents, None if absent, raise on corrupt."""

    if not record_path.is_file():
        return None
    try:
        return json.loads(record_path.read_text(encoding="utf-8"))
    except OSError:
        return None
    except json.JSONDecodeError as exc:
        raise _RecordCorruptError(str(exc)) from exc


def _summary_readable(summary_path: Path) -> bool:
    """True when summary.md exists and can be opened for reading."""

    if not summary_path.is_file():
        return False
    try:
        summary_path.read_text(encoding="utf-8")
    except OSError:
        return False
    return True


def _emit_and_exit(payload: str, code: int) -> None:
    emit_console_text(payload)
    raise typer.Exit(code=code)


@_wait_discussion_app.command("wait")
def wait(
    discussion_id: str = typer.Argument(
        ...,
        help="Discussion identifier (e.g. disc_20260420T195908387651Z).",
    ),
    project_root: Path = PROJECT_ROOT_OPTION,
    timeout: int = TIMEOUT_OPTION,
    poll_interval: int = POLL_INTERVAL_OPTION,
) -> None:
    """Block until discussion record + summary are terminal, or timeout.

    Completion requires BOTH `record.status == "completed"` AND
    `summary.md` to be readable. See module docstring for the full
    error_kind matrix.
    """

    store = CouncilStateStore(project_root)
    discussion_dir = store.paths.discuss / discussion_id
    record_path = discussion_dir / "record.json"
    summary_path = discussion_dir / "summary.md"

    if not discussion_dir.is_dir():
        _emit_and_exit(
            emit_response(
                data=None,
                meta={
                    "command": "discussion wait",
                    "discussion_id": discussion_id,
                    "project_root": str(store.paths.project_root),
                },
                error={
                    "message": (
                        f"Discussion directory {discussion_dir} does not exist. "
                        "Confirm the discussion id and project root."
                    ),
                    "error_kind": "discussion_not_found",
                    "discussion_id": discussion_id,
                },
            ),
            code=1,
        )

    effective_interval = max(poll_interval, MIN_POLL_INTERVAL_SECONDS)
    start = time.monotonic()
    polled_iterations = 0
    # TASK-116: one grace re-poll before declaring summary_missing, so a reader
    # that lands between the writer's two file writes does not hard-fail.
    summary_grace_used = False

    while True:
        polled_iterations += 1
        elapsed = time.monotonic() - start

        try:
            record = _load_record(record_path)
        except _RecordCorruptError as exc:
            _emit_and_exit(
                emit_response(
                    data={
                        "discussion_id": discussion_id,
                        "record_exists": True,
                        "elapsed_seconds": round(elapsed, 3),
                        "polled_iterations": polled_iterations,
                    },
                    meta={
                        "command": "discussion wait",
                        "timeout_seconds": timeout,
                        "poll_interval_seconds": effective_interval,
                    },
                    error={
                        "message": (
                            f"record.json for {discussion_id} exists but cannot "
                            f"be parsed as JSON: {exc}"
                        ),
                        "error_kind": "record_corrupt",
                        "discussion_id": discussion_id,
                    },
                ),
                code=1,
            )

        if record is not None:
            status = str(record.get("status") or "unknown")
            if status == "failed":
                _emit_and_exit(
                    emit_response(
                        data={
                            "discussion_id": discussion_id,
                            "status": status,
                            "record": record,
                            "elapsed_seconds": round(elapsed, 3),
                            "polled_iterations": polled_iterations,
                        },
                        meta={
                            "command": "discussion wait",
                            "timeout_seconds": timeout,
                            "poll_interval_seconds": effective_interval,
                        },
                        error={
                            "message": str(
                                record.get("error") or "discussion failed"
                            ),
                            "error_kind": (
                                str(record.get("error_kind") or "discussion_failed")
                            ),
                            "discussion_id": discussion_id,
                        },
                    ),
                    code=1,
                )

            if status == "completed":
                if not _summary_readable(summary_path):
                    if not summary_grace_used:
                        summary_grace_used = True
                        time.sleep(min(effective_interval, 2.0))
                        continue
                    _emit_and_exit(
                        emit_response(
                            data={
                                "discussion_id": discussion_id,
                                "status": status,
                                "summary_path": str(summary_path),
                                "elapsed_seconds": round(elapsed, 3),
                                "polled_iterations": polled_iterations,
                            },
                            meta={
                                "command": "discussion wait",
                                "timeout_seconds": timeout,
                                "poll_interval_seconds": effective_interval,
                            },
                            error={
                                "message": (
                                    f"record.status=completed for {discussion_id} "
                                    f"but {summary_path} is missing or unreadable."
                                ),
                                "error_kind": "summary_missing",
                                "discussion_id": discussion_id,
                            },
                        ),
                        code=1,
                    )

                # Happy path: dual condition met.
                emit_console_text(
                    emit_response(
                        data={
                            "discussion_id": discussion_id,
                            "status": status,
                            "record": record,
                            "summary_path": str(summary_path),
                            "elapsed_seconds": round(elapsed, 3),
                            "polled_iterations": polled_iterations,
                        },
                        meta={
                            "command": "discussion wait",
                            "timeout_seconds": timeout,
                            "poll_interval_seconds": effective_interval,
                        },
                        error=None,
                    )
                )
                return

        # status is None (record missing) or "running" (still in progress) →
        # check timeout, then sleep and poll again.
        if elapsed >= timeout:
            _emit_and_exit(
                emit_response(
                    data={
                        "discussion_id": discussion_id,
                        "status": (
                            str(record.get("status")) if record is not None else None
                        ),
                        "record_exists": record is not None,
                        "summary_exists": summary_path.is_file(),
                        "elapsed_seconds": round(elapsed, 3),
                        "polled_iterations": polled_iterations,
                    },
                    meta={
                        "command": "discussion wait",
                        "timeout_seconds": timeout,
                        "poll_interval_seconds": effective_interval,
                    },
                    error={
                        "message": (
                            f"Discussion {discussion_id} did not reach "
                            f"status=completed with summary.md within {timeout}s."
                        ),
                        "error_kind": "wait_timeout",
                        "discussion_id": discussion_id,
                    },
                ),
                code=1,
            )

        time.sleep(effective_interval)


discussion_app = _wait_discussion_app
