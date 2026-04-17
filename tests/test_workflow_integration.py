from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from councilflow.cli import discuss as discuss_module
from councilflow.cli.app import app
from councilflow.config.loader import build_default_config
from councilflow.controller.delegation_orchestrator import DelegationOrchestrator
from councilflow.controller.discussion_orchestrator import DiscussionOrchestrator
from councilflow.handoff.packages import build_delegation_contract, load_handoff_package
from councilflow.handoff.summaries import build_discussion_contract
from councilflow.models.discussion import DiscussionRequest, ParticipantResponse
from councilflow.models.roles import RoleName
from councilflow.providers.base import ProviderRequest, ProviderResponse
from councilflow.state.store import CouncilStateStore

runner = CliRunner()


class IntegrationDiscussionParticipant:
    def respond(self, request: DiscussionRequest) -> ParticipantResponse:
        return ParticipantResponse(
            model=request.participant,
            message="Use explicit artifacts for embedded workflow integration.",
            key_options=["Persist summary artifacts under .council/discuss"],
            agreements=["Controller owns final synthesis"],
            recommended_decision="Read summary artifacts from disk before continuing.",
            next_step="Pass the summary artifact into the next project-* phase.",
            supports_current_direction=True,
            has_new_information=False,
        )


class IntegrationDelegationProvider:
    model_name = "claude"

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(
            model="claude",
            content="Delegated result based on the explicit handoff package.",
        )


@pytest.mark.parametrize(
    ("controller", "target_model"),
    [
        ("codex", "claude"),
        ("gemini", "codex"),
    ],
)
def test_workflow_integration_contracts_are_machine_readable(
    tmp_path: Path,
    controller: str,
    target_model: str,
) -> None:
    store = CouncilStateStore(tmp_path)
    discussion_orchestrator = DiscussionOrchestrator(
        store=store,
        config=build_default_config(),
        participant_factory=lambda _: IntegrationDiscussionParticipant(),
    )
    delegation_orchestrator = DelegationOrchestrator(
        store=store,
        participant_factory=lambda _: IntegrationDelegationProvider(),
    )

    summary = discussion_orchestrator.run(
        question="How should project-plan consume discuss output?",
        controller=controller,
        external_models=[target_model],
        max_rounds=5,
        min_rounds=2,
    )
    delegation = delegation_orchestrator.run(
        role=RoleName.IMPLEMENTER,
        controller=controller,
        target_model=target_model,
        objective="Produce implementation output using explicit handoff artifacts.",
        task_summary="Demonstrate workflow integration for delegated tasks.",
        constraints=["Do not rely on hidden context."],
        relevant_files=["docs/integration.md"],
        inputs={"phase": "project-next"},
        expected_output="Markdown result that can be consumed by project-* workflows.",
    )

    discussion_contract = build_discussion_contract(summary)
    handoff_package = load_handoff_package(tmp_path / delegation.handoff_path)
    delegation_contract = build_delegation_contract(
        handoff_package,
        handoff_path=delegation.handoff_path,
        result_path=delegation.result_path,
    )

    assert discussion_contract["artifact_kind"] == "discussion_summary"
    assert discussion_contract["summary_path"] == summary.summary_path
    assert discussion_contract["initial_position"] is not None
    assert discussion_contract["current_controller_position"] is not None
    assert discussion_contract["min_rounds"] == 2
    assert "Controller owns final synthesis" in summary.agreements
    assert delegation_contract["artifact_kind"] == "delegation_handoff"
    assert delegation_contract["status"] == "delegated"
    assert delegation_contract["delegation_status"] == "completed"
    assert delegation_contract["via_sidecar"] is True
    assert delegation_contract["handoff_path"] == delegation.handoff_path
    assert delegation_contract["result_path"] == delegation.result_path
    assert delegation_contract["handoff_schema"]["task_summary"].startswith("Demonstrate")
    assert summary.controller == controller


def test_discuss_cli_reads_project_default_models_for_workflow_integration(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        discuss_module, "get_participant", lambda _: IntegrationDiscussionParticipant()
    )
    config_path = tmp_path / ".council" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "\n".join(
            [
                "config_version: 1",
                "discussion:",
                "  default_models:",
                "    - gemini",
                "  max_rounds: 2",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "discuss",
            "How should project-next consume discuss output without explicit models?",
            "--project-root",
            str(tmp_path),
        ],
        env={"CODEX_SHELL": "1"},
    )

    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert payload["error"] is None
    assert payload["data"]["models_source"] == "project_default"
    assert payload["data"]["participants"] == ["codex", "gemini"]
    assert payload["data"]["effective_max_rounds"] == 2
    assert (tmp_path / payload["data"]["summary_path"]).is_file()
