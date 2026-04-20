from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from councilflow.cli.app import app
from councilflow.state.store import CouncilStateStore

runner = CliRunner()


def test_status_reports_recent_discussion_and_delegation(tmp_path: Path) -> None:
    store = CouncilStateStore(tmp_path)
    store.initialize()
    store.write_state({"current_phase": "idle", "current_controller": "codex"})
    store.append_run_record(
        "discussion",
        {"discussion_id": "disc_001", "summary_path": ".council/discuss/disc_001/summary.md"},
    )
    store.append_run_record(
        "delegation",
        {"delegation_id": "del_001", "result_path": ".council/delegations/del_001/result.md"},
    )

    result = runner.invoke(
        app,
        ["status", "--project-root", str(tmp_path)],
        env={"CODEX_SHELL": "1"},
    )

    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert payload["error"] is None
    assert payload["data"]["current_controller"] == "codex"
    assert payload["data"]["recent_discussion"]["kind"] == "discussion"
    assert payload["data"]["recent_delegation"]["kind"] == "delegation"
    assert payload["meta"]["command"] == "status"


def test_status_recovers_from_corrupted_state_file(tmp_path: Path) -> None:
    store = CouncilStateStore(tmp_path)
    paths = store.initialize()
    paths.state.write_text("", encoding="utf-8")

    result = runner.invoke(
        app,
        ["status", "--project-root", str(tmp_path)],
        env={"CODEX_SHELL": "1"},
    )

    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert payload["error"] is None
    assert payload["data"]["state"]["current_phase"] is None
    assert payload["data"]["state"]["current_controller"] is None
    assert json.loads(paths.state.read_text(encoding="utf-8"))["updated_at"] is not None


def test_status_reports_gemini_controller(tmp_path: Path) -> None:
    store = CouncilStateStore(tmp_path)
    store.initialize()

    result = runner.invoke(
        app,
        ["status", "--project-root", str(tmp_path)],
        env={
            "GEMINI_CLI": "1",
            "CODEX_SHELL": None,
            "CODEX_THREAD_ID": None,
            "CODEX_INTERNAL_ORIGINATOR_OVERRIDE": None,
            "CLAUDE_CODE_SHELL": None,
        },
    )

    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert payload["error"] is None
    assert payload["data"]["current_controller"] == "gemini"


# ---------------------------------------------------------------------------
# TASK-082: routing + convergence distribution segments
# ---------------------------------------------------------------------------


def test_status_includes_recent_window_days_default(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["status", "--project-root", str(tmp_path)],
        env={"CODEX_SHELL": "1"},
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["data"]["recent_window_days"] == 30


def test_status_custom_recent_window(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["status", "--project-root", str(tmp_path), "--recent", "7"],
        env={"CODEX_SHELL": "1"},
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["data"]["recent_window_days"] == 7


def test_status_empty_runs_dir_no_crash(tmp_path: Path) -> None:
    """No .council/runs/ dir → routing_distribution degrades to total=0."""
    result = runner.invoke(
        app,
        ["status", "--project-root", str(tmp_path)],
        env={"CODEX_SHELL": "1"},
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    routing = payload["data"]["routing_distribution"]
    assert routing["total_records"] == 0
    assert routing["roles"] == {}


def test_status_empty_discuss_dir_no_crash(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["status", "--project-root", str(tmp_path)],
        env={"CODEX_SHELL": "1"},
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    convergence = payload["data"]["convergence_distribution"]
    assert convergence["total_records"] == 0
    assert convergence["ended_reason_distribution"] == {}


def test_status_aggregates_routing_json_entries(tmp_path: Path) -> None:
    """Routing records are summarized by role → model counts."""
    runs_dir = tmp_path / ".council" / "runs" / "run_001"
    runs_dir.mkdir(parents=True)
    (runs_dir / "routing.json").write_text(
        json.dumps(
            [
                {
                    "timestamp": "2026-04-20T00:00:00+00:00",
                    "role": "implementer",
                    "primary_model": "claude",
                },
                {
                    "timestamp": "2026-04-20T01:00:00+00:00",
                    "role": "implementer",
                    "primary_model": "gemini",
                },
                {
                    "timestamp": "2026-04-20T02:00:00+00:00",
                    "role": "implementer",
                    "primary_model": "claude",
                },
                {
                    "timestamp": "2026-04-20T03:00:00+00:00",
                    "role": "tester",
                    "primary_model": "claude-haiku",
                },
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["status", "--project-root", str(tmp_path), "--recent", "365"],
        env={"CODEX_SHELL": "1"},
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    routing = payload["data"]["routing_distribution"]
    assert routing["total_records"] == 4
    assert routing["roles"]["implementer"] == {"claude": 2, "gemini": 1}
    assert routing["roles"]["tester"] == {"claude-haiku": 1}


def test_status_aggregates_discussion_ended_reasons(tmp_path: Path) -> None:
    """Discussion record.json files are summarized by ended_reason."""
    for i, reason in enumerate(("converged", "converged", "max_rounds_reached")):
        dir_ = tmp_path / ".council" / "discuss" / f"disc_{i:03d}"
        dir_.mkdir(parents=True)
        (dir_ / "record.json").write_text(
            json.dumps(
                {
                    "id": f"disc_{i:03d}",
                    "created_at": "2026-04-20T00:00:00+00:00",
                    "completed_rounds": 2 + i,
                    "ended_reason": reason,
                }
            ),
            encoding="utf-8",
        )

    result = runner.invoke(
        app,
        ["status", "--project-root", str(tmp_path), "--recent", "365"],
        env={"CODEX_SHELL": "1"},
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    convergence = payload["data"]["convergence_distribution"]
    assert convergence["total_records"] == 3
    assert convergence["ended_reason_distribution"] == {
        "converged": 2,
        "max_rounds_reached": 1,
    }
    # (2 + 3 + 4) / 3 = 3.0
    assert convergence["average_rounds_completed"] == 3.0


def test_status_recent_window_excludes_old_records(tmp_path: Path) -> None:
    """Records older than the cutoff are filtered out."""
    runs_dir = tmp_path / ".council" / "runs" / "run_old"
    runs_dir.mkdir(parents=True)
    (runs_dir / "routing.json").write_text(
        json.dumps(
            [
                {
                    "timestamp": "2020-01-01T00:00:00+00:00",  # very old
                    "role": "implementer",
                    "primary_model": "claude",
                }
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["status", "--project-root", str(tmp_path), "--recent", "7"],
        env={"CODEX_SHELL": "1"},
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    routing = payload["data"]["routing_distribution"]
    assert routing["total_records"] == 0
