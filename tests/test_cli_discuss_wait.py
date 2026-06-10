"""Tests for `council discussion wait <id>` (TASK-107).

Covers all 7 scenarios from the 0.1.6 release gate criteria:

1. record.status=completed AND summary.md readable → exit 0
2. record.status=running → keep polling (verified by sleep monkeypatch)
3. record.status=failed → exit 1, error_kind=discussion_failed
4. summary.md missing despite status=completed → error_kind=summary_missing
5. record.json corrupt JSON → error_kind=record_corrupt
6. discussion directory missing → error_kind=discussion_not_found
7. real timeout → error_kind=wait_timeout

The dual completion contract (record.status==completed AND summary.md
readable) is the explicit reason `discuss wait` cannot share the
`delegation wait` implementation: discussion writes
`record.json(status=running)` immediately on start, so a single-condition
check would return prematurely.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from councilflow.cli.app import app

runner = CliRunner()


def _seed_discussion_dir(
    project_root: Path,
    discussion_id: str,
    *,
    record: dict | None = None,
    record_raw: str | None = None,
    summary: str | None = "# summary\n\nbody.\n",
) -> Path:
    """Create .council/discuss/<id>/ with optional record and summary."""

    discussion_dir = project_root / ".council" / "discuss" / discussion_id
    discussion_dir.mkdir(parents=True, exist_ok=True)
    if record_raw is not None:
        (discussion_dir / "record.json").write_text(record_raw, encoding="utf-8")
    elif record is not None:
        (discussion_dir / "record.json").write_text(
            json.dumps(record, ensure_ascii=False),
            encoding="utf-8",
        )
    if summary is not None:
        (discussion_dir / "summary.md").write_text(summary, encoding="utf-8")
    return discussion_dir


# ---------------------------------------------------------------------------
# 1. happy path
# ---------------------------------------------------------------------------


def test_discuss_wait_returns_when_completed_and_summary_readable(
    tmp_path: Path,
) -> None:
    discussion_id = "disc_test_completed"
    _seed_discussion_dir(
        tmp_path,
        discussion_id,
        record={
            "id": discussion_id,
            "status": "completed",
            "controller": "claude",
            "ended_reason": "converged",
            "completed_rounds": 3,
            "participants": ["claude", "codex"],
            # A full turn transcript that `wait` must NOT echo back (TASK-123:
            # the controller reads content from summary_path, not the record).
            "turns": [{"round": 1, "message": "x" * 5000}],
        },
        summary="# Discussion summary\n\n- agreed point\n",
    )

    result = runner.invoke(
        app,
        [
            "discussion",
            "wait",
            discussion_id,
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
    data = payload["data"]
    # Outcome fields the controller needs (locks the TASK-123 happy-path shape).
    assert data["discussion_id"] == discussion_id
    assert data["status"] == "completed"
    assert data["ended_reason"] == "converged"
    assert data["completed_rounds"] == 3
    assert data["participants"] == ["claude", "codex"]
    assert data["summary_path"].endswith("summary.md")
    # The heavy turn transcript is intentionally dropped from the wait response.
    assert "turns" not in data
    assert "record" not in data


# ---------------------------------------------------------------------------
# 2. polling continues while status=running
# ---------------------------------------------------------------------------


def test_discuss_wait_polls_while_running_then_completes(
    tmp_path: Path, monkeypatch
) -> None:
    discussion_id = "disc_test_polling"
    discussion_dir = _seed_discussion_dir(
        tmp_path,
        discussion_id,
        record={"id": discussion_id, "status": "running", "controller": "claude"},
        summary=None,
    )
    record_path = discussion_dir / "record.json"

    sleep_calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        # On the second sleep, simulate the discussion finishing.
        if len(sleep_calls) >= 2:
            record_path.write_text(
                json.dumps(
                    {
                        "id": discussion_id,
                        "status": "completed",
                        "controller": "claude",
                        "rounds_completed": 4,
                    }
                ),
                encoding="utf-8",
            )
            (discussion_dir / "summary.md").write_text(
                "# polled to completion\n",
                encoding="utf-8",
            )

    monkeypatch.setattr("councilflow.cli.discuss_wait.time.sleep", fake_sleep)

    result = runner.invoke(
        app,
        [
            "discussion",
            "wait",
            discussion_id,
            "--project-root",
            str(tmp_path),
            "--timeout",
            "60",
            "--poll-interval",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["data"]["status"] == "completed"
    assert payload["data"]["polled_iterations"] >= 2
    assert len(sleep_calls) >= 2


# ---------------------------------------------------------------------------
# 3. status=failed
# ---------------------------------------------------------------------------


def test_discuss_wait_returns_failed_kind_when_record_status_failed(
    tmp_path: Path,
) -> None:
    discussion_id = "disc_test_failed"
    _seed_discussion_dir(
        tmp_path,
        discussion_id,
        record={
            "id": discussion_id,
            "status": "failed",
            "controller": "claude",
            "error": "participant unavailable",
        },
        summary=None,
    )

    result = runner.invoke(
        app,
        [
            "discussion",
            "wait",
            discussion_id,
            "--project-root",
            str(tmp_path),
            "--timeout",
            "5",
            "--poll-interval",
            "1",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"]["error_kind"] == "discussion_failed"
    assert payload["error"]["discussion_id"] == discussion_id


# ---------------------------------------------------------------------------
# 4. status=completed but summary missing
# ---------------------------------------------------------------------------


def test_discuss_wait_reports_summary_missing(tmp_path: Path) -> None:
    discussion_id = "disc_test_summary_missing"
    _seed_discussion_dir(
        tmp_path,
        discussion_id,
        record={"id": discussion_id, "status": "completed", "controller": "claude"},
        summary=None,
    )

    result = runner.invoke(
        app,
        [
            "discussion",
            "wait",
            discussion_id,
            "--project-root",
            str(tmp_path),
            "--timeout",
            "1",
            "--poll-interval",
            "1",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"]["error_kind"] == "summary_missing"


# ---------------------------------------------------------------------------
# 5. record.json corrupt
# ---------------------------------------------------------------------------


def test_discuss_wait_reports_record_corrupt(tmp_path: Path) -> None:
    discussion_id = "disc_test_corrupt"
    _seed_discussion_dir(
        tmp_path,
        discussion_id,
        record_raw="this is not { valid json ::",
        summary=None,
    )

    result = runner.invoke(
        app,
        [
            "discussion",
            "wait",
            discussion_id,
            "--project-root",
            str(tmp_path),
            "--timeout",
            "5",
            "--poll-interval",
            "1",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"]["error_kind"] == "record_corrupt"


# ---------------------------------------------------------------------------
# 6. discussion directory missing
# ---------------------------------------------------------------------------


def test_discuss_wait_reports_discussion_not_found(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "discussion",
            "wait",
            "disc_does_not_exist",
            "--project-root",
            str(tmp_path),
            "--timeout",
            "5",
            "--poll-interval",
            "1",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"]["error_kind"] == "discussion_not_found"


# ---------------------------------------------------------------------------
# 7. real timeout
# ---------------------------------------------------------------------------


def test_discuss_wait_reports_wait_timeout(tmp_path: Path, monkeypatch) -> None:
    """Force a timeout by leaving record.status=running and patching time."""

    discussion_id = "disc_test_timeout"
    _seed_discussion_dir(
        tmp_path,
        discussion_id,
        record={"id": discussion_id, "status": "running", "controller": "claude"},
        summary=None,
    )

    # Make time.monotonic advance past the 1-second timeout on the second call,
    # and turn time.sleep into a no-op so the test doesn't actually wait.
    advance_calls = iter([0.0, 0.5, 2.0, 3.0, 4.0, 5.0])

    def fake_monotonic() -> float:
        try:
            return next(advance_calls)
        except StopIteration:
            return 99.0

    monkeypatch.setattr(
        "councilflow.cli.discuss_wait.time.monotonic", fake_monotonic
    )
    monkeypatch.setattr("councilflow.cli.discuss_wait.time.sleep", lambda _: None)

    result = runner.invoke(
        app,
        [
            "discussion",
            "wait",
            discussion_id,
            "--project-root",
            str(tmp_path),
            "--timeout",
            "1",
            "--poll-interval",
            "1",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"]["error_kind"] == "wait_timeout"


# ---------------------------------------------------------------------------
# CLI surface check (verification_command requires `--help` to work)
# ---------------------------------------------------------------------------


def test_discussion_wait_help_works() -> None:
    result = runner.invoke(app, ["discussion", "wait", "--help"])
    assert result.exit_code == 0
    assert "Block until discussion record" in result.output


# ---------------------------------------------------------------------------
# TASK-116: writer-order race — a poller that reads record.json(completed)
# BETWEEN the writer's two file writes gets one grace re-poll instead of a
# false summary_missing hard failure.
# ---------------------------------------------------------------------------
def test_discuss_wait_grace_repoll_survives_writer_order_race(
    tmp_path: Path, monkeypatch
) -> None:
    discussion_id = "disc_test_write_race"
    discussion_dir = _seed_discussion_dir(
        tmp_path,
        discussion_id,
        record={"id": discussion_id, "status": "completed", "controller": "claude"},
        summary=None,  # summary.md not on disk yet — mid-write window
    )

    import councilflow.cli.discuss_wait as dw

    def sleep_writes_summary(_seconds: float) -> None:
        # The writer finishes during the grace window.
        (discussion_dir / "summary.md").write_text("# late summary", encoding="utf-8")

    monkeypatch.setattr(dw.time, "sleep", sleep_writes_summary)

    result = runner.invoke(
        app,
        [
            "discussion",
            "wait",
            discussion_id,
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
    assert payload["data"]["status"] == "completed"
