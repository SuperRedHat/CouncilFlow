from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from councilflow.cli import discuss as discuss_module
from councilflow.cli.app import app
from councilflow.models.discussion import DiscussionRequest, ParticipantResponse

runner = CliRunner()


class FakeParticipant:
    def respond(self, request: DiscussionRequest) -> ParticipantResponse:
        return ParticipantResponse(
            model=request.participant,
            message="Proceed with the current architecture split.",
            key_options=["Split routing from orchestration"],
            agreements=["Use controller-led synthesis"],
            recommended_decision="Proceed with the split controller/orchestrator design.",
            next_step="Create the implementation tasks.",
            supports_current_direction=True,
            has_new_information=False,
        )


def test_discuss_command_returns_structured_summary(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(discuss_module, "get_participant", lambda _: FakeParticipant())

    result = runner.invoke(
        app,
        [
            "discuss",
            "How should we split the architecture?",
            "--models",
            "claude",
            "--project-root",
            str(tmp_path),
        ],
        env={"CODEX_SHELL": "1"},
    )

    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert payload["error"] is None
    assert payload["data"]["question"] == "How should we split the architecture?"
    assert payload["data"]["participants"] == ["codex", "claude"]
    assert payload["data"]["ended_reason"] == "converged"
    assert (tmp_path / payload["data"]["summary_path"]).is_file()


def test_discuss_command_warns_when_only_controller_is_requested(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "discuss",
            "Should we branch out to another model?",
            "--models",
            "codex",
            "--project-root",
            str(tmp_path),
        ],
        env={"CODEX_SHELL": "1"},
    )

    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert payload["error"] is None
    assert payload["data"]["rounds_completed"] == 0
    assert payload["data"]["warning"] is not None


def test_discuss_command_normalizes_controller_aliases(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "discuss",
            "Should Claude alias stay local?",
            "--models",
            "claude-code",
            "--project-root",
            str(tmp_path),
        ],
        env={
            "CLAUDE_CODE_SHELL": "1",
            "CODEX_SHELL": None,
            "CODEX_THREAD_ID": None,
            "CODEX_INTERNAL_ORIGINATOR_OVERRIDE": None,
        },
    )

    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert payload["error"] is None
    assert payload["data"]["external_models"] == []
    assert payload["data"]["ignored_models"] == ["claude"]


def test_discuss_command_normalizes_gemini_controller_aliases(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "discuss",
            "Should Gemini alias stay local?",
            "--models",
            "gemini-cli",
            "--project-root",
            str(tmp_path),
        ],
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
    assert payload["data"]["external_models"] == []
    assert payload["data"]["ignored_models"] == ["gemini"]
