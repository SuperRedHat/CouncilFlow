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
