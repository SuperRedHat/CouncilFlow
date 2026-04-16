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

