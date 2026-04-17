from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from councilflow.cli import delegate as delegate_module
from councilflow.cli import discuss as discuss_module
from councilflow.cli.app import app
from councilflow.models.discussion import DiscussionRequest, ParticipantResponse
from councilflow.providers.base import ProviderRequest, ProviderResponse

runner = CliRunner()


class FakeCodexAdapter:
    model_name = "codex"

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(
            model="codex",
            content=f"Codex response to: {request.prompt}",
        )


class FakeParticipant:
    def __init__(self, model: str):
        self.model = model

    def respond(self, request: DiscussionRequest) -> ParticipantResponse:
        return ParticipantResponse(
            model=self.model,
            message=f"{self.model} agrees.",
            key_options=[],
            agreements=["Agreed"],
            recommended_decision="Yes",
            next_step="Move on",
            supports_current_direction=True,
            has_new_information=False,
        )


def test_delegate_from_gemini_to_codex(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        delegate_module,
        "get_provider_adapter",
        lambda *args, **kwargs: FakeCodexAdapter(),
    )

    env = {
        "GEMINI_CLI": "1",
        "CODEX_SHELL": None,
        "CODEX_THREAD_ID": None,
        "CODEX_INTERNAL_ORIGINATOR_OVERRIDE": None,
        "CLAUDECODE": None,
        "CLAUDE_CODE": None,
    }

    result = runner.invoke(
        app,
        [
            "delegate",
            "--role",
            "planner",
            "--objective",
            "Plan.",
            "--task-summary",
            "Planning.",
            "--project-root",
            str(tmp_path),
        ],
        env=env,
    )

    payload = json.loads(result.output)
    assert result.exit_code == 0
    assert payload["data"]["model"] == "codex"


def test_discuss_from_gemini_to_codex_and_claude(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        discuss_module,
        "get_participant",
        lambda model, *_args, **_kwargs: FakeParticipant(model),
    )

    env = {
        "GEMINI_CLI": "1",
        "CODEX_SHELL": None,
        "CODEX_THREAD_ID": None,
        "CODEX_INTERNAL_ORIGINATOR_OVERRIDE": None,
        "CLAUDECODE": None,
        "CLAUDE_CODE": None,
    }

    result = runner.invoke(
        app,
        [
            "discuss",
            "What is the meaning of life?",
            "--models",
            "codex,claude",
            "--project-root",
            str(tmp_path),
        ],
        env=env,
    )

    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert payload["error"] is None
    assert "gemini" in payload["data"]["participants"]
    assert "codex" in payload["data"]["participants"]
    assert "claude" in payload["data"]["participants"]
    assert payload["data"]["rounds_completed"] > 0
