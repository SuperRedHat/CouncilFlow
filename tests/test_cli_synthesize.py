from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from councilflow.cli.app import app
from councilflow.state.store import CouncilStateStore

runner = CliRunner()


def test_synthesize_combines_artifact_contents(tmp_path: Path) -> None:
    store = CouncilStateStore(tmp_path)
    store.initialize()
    summary_path = tmp_path / ".council" / "discuss" / "disc_001" / "summary.md"
    result_path = tmp_path / ".council" / "delegations" / "del_001" / "result.md"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("Discussion summary body", encoding="utf-8")
    result_path.write_text("Delegation result body", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "synthesize",
            "--artifact",
            str(summary_path),
            "--artifact",
            str(result_path),
            "--project-root",
            str(tmp_path),
        ],
    )

    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert payload["error"] is None
    assert len(payload["data"]["sources"]) == 2
    assert "Discussion summary body" in payload["data"]["synthesis"]
    assert "Delegation result body" in payload["data"]["synthesis"]
    assert payload["meta"]["command"] == "synthesize"


def test_synthesize_works_from_gemini_controlled_session(tmp_path: Path) -> None:
    store = CouncilStateStore(tmp_path)
    store.initialize()
    summary_path = tmp_path / ".council" / "discuss" / "disc_gemini" / "summary.md"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("Gemini summary body", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "synthesize",
            "--artifact",
            str(summary_path),
            "--project-root",
            str(tmp_path),
        ],
        env={"GEMINI_CLI": "1"},
    )

    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert payload["error"] is None
    assert payload["data"]["output_language"] == "zh-CN"
    assert "Gemini summary body" in payload["data"]["synthesis"]
