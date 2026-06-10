"""Tests for the `council delegation wait` subcommand."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from typer.testing import CliRunner

from councilflow.cli.app import app

runner = CliRunner()


def _make_delegation_dir(project_root: Path, delegation_id: str) -> Path:
    delegation_dir = project_root / ".council" / "delegations" / delegation_id
    delegation_dir.mkdir(parents=True, exist_ok=True)
    (delegation_dir / "handoff.yaml").write_text("role: implementer\n", encoding="utf-8")
    return delegation_dir


def _write_record(
    delegation_dir: Path,
    *,
    status: str = "completed",
    error_kind: str | None = None,
    fallback_retry_pending: bool = False,
    retried_with_model: str | None = None,
) -> None:
    payload = {
        "id": delegation_dir.name,
        "role": "implementer",
        "target_model": "claude",
        "status": status,
        "handoff_path": str(
            (delegation_dir / "handoff.yaml").relative_to(delegation_dir.parents[2])
        ),
    }
    if status == "completed":
        payload["result_path"] = str(
            (delegation_dir / "result.md").relative_to(delegation_dir.parents[2])
        )
    if error_kind:
        payload["error_kind"] = error_kind
        payload["error"] = "Delegated stage modified protected workflow paths."
    if fallback_retry_pending:
        payload["fallback_retry_pending"] = True
    if retried_with_model:
        payload["retried_with_model"] = retried_with_model
    (delegation_dir / "record.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_wait_returns_immediately_when_record_already_exists(tmp_path: Path) -> None:
    delegation_id = "del_fixture_completed"
    delegation_dir = _make_delegation_dir(tmp_path, delegation_id)
    (delegation_dir / "result.md").write_text("# result\n", encoding="utf-8")
    _write_record(delegation_dir, status="completed")

    result = runner.invoke(
        app,
        [
            "delegation",
            "wait",
            delegation_id,
            "--project-root",
            str(tmp_path),
            "--timeout",
            "5",
            "--poll-interval",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["data"]["status"] == "completed"
    assert payload["data"]["delegation_id"] == delegation_id
    assert payload["data"]["polled_iterations"] == 0
    assert payload["data"]["record"]["status"] == "completed"
    assert payload["error"] is None


def test_wait_reports_failed_record_with_error_metadata(tmp_path: Path) -> None:
    delegation_id = "del_fixture_guardrail"
    delegation_dir = _make_delegation_dir(tmp_path, delegation_id)
    _write_record(delegation_dir, status="failed", error_kind="guardrail_violation")

    result = runner.invoke(
        app,
        [
            "delegation",
            "wait",
            delegation_id,
            "--project-root",
            str(tmp_path),
            "--timeout",
            "5",
            "--poll-interval",
            "1",
        ],
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["data"]["status"] == "failed"
    assert payload["error"]["error_kind"] == "guardrail_violation"
    assert payload["error"]["delegation_id"] == delegation_id


def test_wait_reports_retry_pending_not_terminal_failure(tmp_path: Path) -> None:
    # TASK-120: a failed attempt that `delegate` is retrying on a fallback model
    # is stamped fallback_retry_pending. `wait` on this id must NOT conclude
    # terminal failure — it surfaces retry_pending (exit 0, no error) so a polling
    # controller keeps waiting for the retry instead of giving up.
    delegation_id = "del_fixture_retrying"
    delegation_dir = _make_delegation_dir(tmp_path, delegation_id)
    _write_record(
        delegation_dir,
        status="failed",
        error_kind="idle_timeout",
        fallback_retry_pending=True,
        retried_with_model="gpt-5.1-codex",
    )

    result = runner.invoke(
        app,
        [
            "delegation",
            "wait",
            delegation_id,
            "--project-root",
            str(tmp_path),
            "--timeout",
            "5",
            "--poll-interval",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["error"] is None
    assert payload["data"]["status"] == "retry_pending"
    assert payload["data"]["retry_pending"] is True
    assert payload["data"]["retried_with_model"] == "gpt-5.1-codex"
    # The raw record still carries the underlying failed attempt for inspection.
    assert payload["data"]["record"]["status"] == "failed"


def test_wait_errors_when_delegation_directory_missing(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "delegation",
            "wait",
            "del_does_not_exist",
            "--project-root",
            str(tmp_path),
            "--timeout",
            "2",
            "--poll-interval",
            "1",
        ],
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["error"]["error_kind"] == "delegation_not_found"


def test_wait_times_out_when_record_never_appears(tmp_path: Path) -> None:
    delegation_id = "del_fixture_pending"
    _make_delegation_dir(tmp_path, delegation_id)

    start = time.monotonic()
    result = runner.invoke(
        app,
        [
            "delegation",
            "wait",
            delegation_id,
            "--project-root",
            str(tmp_path),
            "--timeout",
            "2",
            "--poll-interval",
            "1",
        ],
    )
    elapsed = time.monotonic() - start

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["error"]["error_kind"] == "wait_timeout"
    assert payload["data"]["record_exists"] is False
    assert payload["data"]["handoff_exists"] is True
    # `--timeout 2` must be respected — shouldn't run forever.
    assert elapsed < 10


def test_wait_detects_record_written_during_poll_loop(tmp_path: Path) -> None:
    delegation_id = "del_fixture_late"
    delegation_dir = _make_delegation_dir(tmp_path, delegation_id)

    def late_writer() -> None:
        time.sleep(1.5)
        (delegation_dir / "result.md").write_text("# late\n", encoding="utf-8")
        _write_record(delegation_dir, status="completed")

    writer = threading.Thread(target=late_writer, daemon=True)
    writer.start()
    try:
        result = runner.invoke(
            app,
            [
                "delegation",
                "wait",
                delegation_id,
                "--project-root",
                str(tmp_path),
                "--timeout",
                "10",
                "--poll-interval",
                "1",
            ],
        )
    finally:
        writer.join(timeout=5)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["data"]["status"] == "completed"
    assert payload["data"]["polled_iterations"] >= 1
