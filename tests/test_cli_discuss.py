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


def write_project_config(tmp_path: Path, content: str) -> Path:
    config_path = tmp_path / ".council" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(content, encoding="utf-8")
    return config_path


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
    assert payload["data"]["initial_position"] == "Proceed with the current architecture split."
    assert (
        payload["data"]["current_controller_position"]
        == "Proceed with the current architecture split."
    )
    assert payload["data"]["ended_reason"] == "converged"
    assert payload["data"]["min_rounds"] == 2
    assert payload["data"]["effective_min_rounds"] == 2
    assert payload["data"]["rounds_completed"] == 2
    assert (tmp_path / payload["data"]["summary_path"]).is_file()
    assert payload["data"]["models_source"] == "explicit"
    assert payload["data"]["effective_max_rounds"] == 5


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
    assert payload["data"]["models_source"] == "explicit"


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


def test_discuss_command_uses_project_default_models_when_option_is_omitted(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(discuss_module, "get_participant", lambda _: FakeParticipant())
    write_project_config(
        tmp_path,
        "\n".join(
            [
                "config_version: 1",
                "discussion:",
                "  default_models:",
                "    - gemini-cli",
                "  max_rounds: 3",
                "",
            ]
        ),
    )

    result = runner.invoke(
        app,
        [
            "discuss",
            "Should config defaults pick the discussion model?",
            "--project-root",
            str(tmp_path),
        ],
        env={"CODEX_SHELL": "1"},
    )

    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert payload["error"] is None
    assert payload["data"]["participants"] == ["codex", "gemini"]
    assert payload["data"]["models_source"] == "project_default"
    assert payload["data"]["configured_default_models"] == ["gemini"]
    assert payload["data"]["effective_min_rounds"] == 1
    assert payload["data"]["effective_max_rounds"] == 3


def test_discuss_command_prefers_explicit_models_over_project_defaults(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(discuss_module, "get_participant", lambda _: FakeParticipant())
    write_project_config(
        tmp_path,
        "\n".join(
            [
                "config_version: 1",
                "discussion:",
                "  default_models:",
                "    - gemini",
                "  max_rounds: 4",
                "",
            ]
        ),
    )

    result = runner.invoke(
        app,
        [
            "discuss",
            "Should explicit models override defaults?",
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
    assert payload["data"]["participants"] == ["codex", "claude"]
    assert payload["data"]["models_source"] == "explicit"
    assert payload["data"]["configured_default_models"] == ["gemini"]
    assert payload["data"]["effective_min_rounds"] == 1
    assert payload["data"]["effective_max_rounds"] == 4


def test_discuss_command_warns_when_no_explicit_or_default_models_exist(
    tmp_path: Path,
) -> None:
    result = runner.invoke(
        app,
        [
            "discuss",
            "Will CouncilFlow explain missing discuss defaults?",
            "--project-root",
            str(tmp_path),
        ],
        env={"CODEX_SHELL": "1"},
    )

    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert payload["error"] is None
    assert payload["data"]["external_models"] == []
    assert "No additional discuss models" in payload["data"]["warning"]
    assert payload["data"]["models_source"] == "project_default"
    assert payload["data"]["effective_min_rounds"] == 2


def test_discuss_command_can_use_locally_generated_controller_position(
    monkeypatch, tmp_path: Path
) -> None:
    def fake_participant(model: str) -> FakeParticipant:
        if model == "codex":
            raise AssertionError("Controller subprocess should be skipped in local mode.")
        return FakeParticipant()

    monkeypatch.setattr(discuss_module, "get_participant", fake_participant)

    result = runner.invoke(
        app,
        [
            "discuss",
            "What is the smallest safe MVP change?",
            "--models",
            "claude",
            "--controller-position",
            "Keep the current MVP structure and only tighten the state boundary.",
            "--project-root",
            str(tmp_path),
        ],
        env={"CODEX_SHELL": "1"},
    )

    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert payload["error"] is None
    assert payload["data"]["participants"] == ["codex", "claude"]
    assert (
        payload["data"]["initial_position"]
        == "Keep the current MVP structure and only tighten the state boundary."
    )
    assert (
        payload["data"]["current_controller_position"]
        == "Keep the current MVP structure and only tighten the state boundary."
    )
    assert payload["data"]["controller_mode"] == "local_initial_position"
    assert payload["data"]["effective_max_rounds"] == 1
    assert payload["data"]["effective_min_rounds"] == 1
    assert payload["data"]["rounds_completed"] == 1
