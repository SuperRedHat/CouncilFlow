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
from councilflow.controller.routing import build_route_decision
from councilflow.handoff.packages import build_delegation_contract, load_handoff_package
from councilflow.handoff.summaries import build_discussion_contract
from councilflow.models.delegation import ReviewFinding, VerificationCommand
from councilflow.models.discussion import DiscussionRequest, ParticipantResponse
from councilflow.models.roles import ControllerName, RoleName
from councilflow.providers.base import ProviderRequest, ProviderResponse
from councilflow.state.store import CouncilStateStore

runner = CliRunner()
WORKFLOW_CORE_ROOT = Path.home() / ".workflow-core"


def _write_claude_permission_settings(tmp_path: Path, *commands: str) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    allow_entries = [f"Bash({command}:*)" for command in commands]
    settings_path.write_text(
        json.dumps({"permissions": {"allow": allow_entries}}, ensure_ascii=False),
        encoding="utf-8",
    )


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
        required_artifacts={},
        next_actions_on_success=["Enter tester using the emitted implementation result artifact."],
        next_actions_on_failure=["Stop and report the failed implementer stage."],
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
    assert delegation_contract["handoff_schema"]["next_actions_on_success"] == [
        "Enter tester using the emitted implementation result artifact."
    ]
    assert delegation_contract["handoff_schema"]["next_actions_on_failure"] == [
        "Stop and report the failed implementer stage."
    ]
    assert (
        any(
            "next-actions guidance" in rule
            and "stage transitions" in rule
            for rule in delegation_contract["consumption_rules"]
        )
    )
    assert delegation_contract["handoff_schema"]["execution_guardrails"]["allow_commit"] is False
    assert discussion_contract["consumption_rules"][-1] == (
        "If summary_path is missing, the workflow must treat the discussion as incomplete."
    )
    assert summary.controller == controller


def test_discuss_cli_reads_project_default_models_for_workflow_integration(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        discuss_module,
        "get_participant",
        lambda *args, **kwargs: IntegrationDiscussionParticipant(),
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


@pytest.mark.parametrize(
    ("role", "required_artifacts", "next_success", "next_failure"),
    [
        (
            RoleName.IMPLEMENTER,
            {},
            ["Enter tester using the implementation result artifact."],
            ["Stop and report the failed implementer stage."],
        ),
        (
            RoleName.TESTER,
            {"implementer_result": ".council/delegations/del_impl/result.md"},
            ["If verification passes, enter reviewer before any synthesis/status flow."],
            ["Enter fixer, then rerun tester."],
        ),
        (
            RoleName.REVIEWER,
            {
                "implementer_result": ".council/delegations/del_impl/result.md",
                "tester_result": ".council/delegations/del_test/result.md",
            },
            ["If reviewer passes, continue to synthesis/status flow."],
            ["Enter fixer, then rerun tester and reviewer."],
        ),
        (
            RoleName.FIXER,
            {
                "tester_result": ".council/delegations/del_test/result.md",
                "reviewer_findings": ".council/delegations/del_review/findings.json",
            },
            ["Re-enter tester, then reviewer, using the new fixer result artifact."],
            ["Stop and report the failed fixer stage."],
        ),
    ],
)
def test_project_next_stage_contracts_are_explicit(
    tmp_path: Path,
    role: RoleName,
    required_artifacts: dict[str, str],
    next_success: list[str],
    next_failure: list[str],
) -> None:
    if role is RoleName.TESTER:
        _write_claude_permission_settings(tmp_path, "python -m pytest")
    store = CouncilStateStore(tmp_path)
    orchestrator = DelegationOrchestrator(
        store=store,
        participant_factory=lambda _: IntegrationDelegationProvider(),
    )

    result = orchestrator.run(
        role=role,
        controller="codex",
        target_model="claude",
        objective=f"Run the {role.value} stage for project-next.",
        task_summary=f"Structured {role.value} phase execution.",
        constraints=["Do not rely on hidden shared chat context."],
        relevant_files=["docs/integration.md"],
        inputs={"workflow": "project-next"},
        required_artifacts=required_artifacts,
        next_actions_on_success=next_success,
        next_actions_on_failure=next_failure,
        expected_output="Markdown result that the host workflow can consume explicitly.",
    )

    handoff_package = load_handoff_package(tmp_path / result.handoff_path)
    contract = build_delegation_contract(
        handoff_package,
        handoff_path=result.handoff_path,
        result_path=result.result_path,
    )

    assert contract["handoff_schema"]["role"] == role.value
    assert contract["handoff_schema"]["required_artifacts"] == required_artifacts
    assert contract["stage_guidance"]["next_actions_on_success"] == next_success
    assert contract["stage_guidance"]["next_actions_on_failure"] == next_failure
    assert "Required upstream artifacts must be read" in contract["consumption_rules"][3]


def test_tester_and_fixer_contracts_expose_preflight_findings_and_guardrails(
    tmp_path: Path,
) -> None:
    _write_claude_permission_settings(tmp_path, "pnpm exec eslint", "pnpm exec vitest")
    store = CouncilStateStore(tmp_path)
    orchestrator = DelegationOrchestrator(
        store=store,
        participant_factory=lambda _: IntegrationDelegationProvider(),
    )

    tester_result = orchestrator.run(
        role=RoleName.TESTER,
        controller="codex",
        target_model="claude",
        objective="Run structured tester verification.",
        task_summary="Execute verification commands through the tester stage.",
        constraints=["Do not rely on hidden shared chat context."],
        relevant_files=["docs/integration.md"],
        inputs={"workflow": "project-next"},
        verification_commands=[
            VerificationCommand(command="pnpm exec eslint .", purpose="lint"),
            VerificationCommand(command="pnpm exec vitest run", purpose="unit"),
        ],
        required_artifacts={"implementer_result": ".council/delegations/del_impl/result.md"},
        expected_output="Structured tester artifact.",
    )
    tester_package = load_handoff_package(tmp_path / tester_result.handoff_path)
    tester_contract = build_delegation_contract(
        tester_package,
        handoff_path=tester_result.handoff_path,
        result_path=tester_result.result_path,
    )

    assert tester_contract["handoff_schema"]["tester_preflight"]["status"] == "passed"
    assert tester_contract["handoff_schema"]["verification_commands"] == [
        {"command": "pnpm exec eslint .", "purpose": "lint"},
        {"command": "pnpm exec vitest run", "purpose": "unit"},
    ]
    assert tester_contract["handoff_schema"]["execution_guardrails"]["allow_commit"] is False
    assert any(
        "Structured verification commands, tester preflight requirements, and review findings"
        in rule
        for rule in tester_contract["consumption_rules"]
    )

    fixer_result = orchestrator.run(
        role=RoleName.FIXER,
        controller="codex",
        target_model="claude",
        objective="Fix reviewer findings without touching workflow state.",
        task_summary="Repair semantic issues found after tester passed.",
        constraints=["Keep workflow state files untouched."],
        relevant_files=["src/councilflow/handoff/packages.py"],
        inputs={"workflow": "project-next"},
        required_artifacts={
            "tester_result": ".council/delegations/del_test/result.md",
            "reviewer_findings": ".council/delegations/del_review/findings.json",
        },
        review_findings=[
            ReviewFinding(
                finding_id="RV-001",
                severity="high",
                title="Undo leaves stale finished result",
                body="undoLastMove() leaves a finished-state result attached after re-entry.",
                affected_files=["src/domain/game/game.ts"],
                required_fix="Clear stale result and realign snapshot/state invariants.",
            )
        ],
        expected_output="Structured fixer artifact.",
    )
    fixer_package = load_handoff_package(tmp_path / fixer_result.handoff_path)
    fixer_contract = build_delegation_contract(
        fixer_package,
        handoff_path=fixer_result.handoff_path,
        result_path=fixer_result.result_path,
    )

    assert fixer_contract["handoff_schema"]["review_findings"][0]["finding_id"] == "RV-001"
    assert fixer_contract["handoff_schema"]["fixer_input_sources"] == [
        {
            "label": "tester_result",
            "source_stage": "tester",
            "artifact_path": ".council/delegations/del_test/result.md",
        },
        {
            "label": "reviewer_findings",
            "source_stage": "reviewer",
            "artifact_path": ".council/delegations/del_review/findings.json",
        },
    ]
    assert (
        fixer_contract["stage_guidance"]["execution_guardrails"]["allow_workflow_state_write"]
        is False
    )


@pytest.mark.parametrize(
    ("role", "controller", "target_model", "expected_status"),
    [
        (RoleName.IMPLEMENTER, ControllerName.CODEX, "claude", "delegated"),
        (RoleName.TESTER, ControllerName.CODEX, "claude", "delegated"),
        (RoleName.FIXER, ControllerName.CODEX, "claude", "delegated"),
        (RoleName.REVIEWER, ControllerName.CODEX, "claude", "delegated"),
        (RoleName.ARCHITECT, ControllerName.CODEX, "claude", "delegated"),
        (RoleName.ADVISOR, ControllerName.CODEX, "claude", "delegated"),
        (RoleName.IMPLEMENTER, ControllerName.CODEX, "codex", "local_execution"),
        (RoleName.TESTER, ControllerName.CODEX, "codex", "local_execution"),
        (RoleName.FIXER, ControllerName.CODEX, "codex", "local_execution"),
        (RoleName.REVIEWER, ControllerName.CODEX, "codex", "local_execution"),
        (RoleName.ARCHITECT, ControllerName.CODEX, "codex", "local_execution"),
        (RoleName.ADVISOR, ControllerName.CODEX, "codex", "local_execution"),
    ],
)
def test_route_decision_covers_key_role_outcomes(
    role: RoleName,
    controller: ControllerName,
    target_model: str,
    expected_status: str,
) -> None:
    decision = build_route_decision(
        role=role,
        controller=controller,
        target_model=target_model,
    )

    assert decision.role == role
    assert decision.status == expected_status
    assert decision.via_sidecar is (expected_status == "delegated")


@pytest.mark.parametrize(
    ("skill", "required_phrases"),
    [
        (
            "project-next",
            [
                "status = local_execution",
                "status = delegated",
                "停止当前 workflow 并如实报告失败",
                "council` 明确缺失或不可调用",
                "缺少 handoff/result artifact",
                "缺少 summary artifact",
                "tester 通过后不要直接收口",
                "只有当 tester 与 reviewer 都明确通过后",
            ],
        ),
        (
            "project-review",
            [
                "status = local_execution",
                "status = delegated",
                "停止当前 workflow 并报告失败",
                "council` 明确缺失或不可调用",
                "缺少 handoff/result artifact",
                "缺少 summary artifact",
            ],
        ),
        (
            "project-change",
            [
                "status = local_execution",
                "status = delegated",
                "停止当前 workflow 并报告失败",
                "council` 明确缺失或不可调用",
                "缺少 handoff/result artifact",
                "缺少 summary artifact",
            ],
        ),
        (
            "project-design",
            [
                "status = local_execution",
                "status = delegated",
                "停止当前 workflow 并报告失败",
                "council` 明确缺失或不可调用",
                "缺少 handoff/result artifact",
                "缺少 summary artifact",
            ],
        ),
    ],
)
def test_shared_skills_document_hard_stop_and_explicit_fallback(
    skill: str,
    required_phrases: list[str],
) -> None:
    text = (WORKFLOW_CORE_ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")

    for phrase in required_phrases:
        assert phrase in text


def test_release_checklist_covers_failure_stop_and_council_missing_fallback() -> None:
    checklist = (Path(__file__).resolve().parents[1] / "docs" / "release-checklist.md").read_text(
        encoding="utf-8"
    )

    assert (
        "implementer -> tester -> reviewer -> [fixer -> tester -> reviewer]*" in checklist
    )
    assert (
        "Verify route/discuss failures stop the workflow instead of silently switching to local "
        "execution."
        in checklist
    )
    assert (
        "Verify temporarily hiding or breaking the `council` command produces an explicit local "
        "fallback"
        in checklist
    )


def test_sidecar_isolation_contract_defaults_and_contract_surface(tmp_path: Path) -> None:
    """TASK-042: default isolation/import contract is modeled and flows into the handoff."""

    from councilflow.handoff.packages import create_handoff_package
    from councilflow.handoff.prompts import render_delegation_prompt
    from councilflow.models.delegation import (
        DEFAULT_ISOLATION_EXCLUDE_PATTERNS,
        DEFAULT_PROTECTED_PATHS,
        DelegationResult,
        ExecutionGuardrails,
        ImportManifest,
        IsolatedWorkspace,
        WorkspaceFileChange,
    )

    guardrails = ExecutionGuardrails()
    assert guardrails.protected_paths == list(DEFAULT_PROTECTED_PATHS)
    assert ".workflow-core" in guardrails.protected_paths
    assert ".claude/skills" in guardrails.protected_paths
    assert ".codex/skills" in guardrails.protected_paths
    assert ".gemini/skills" in guardrails.protected_paths
    assert guardrails.isolated_workspace.strategy == "git_worktree"
    assert guardrails.isolated_workspace.exclude_patterns == list(
        DEFAULT_ISOLATION_EXCLUDE_PATTERNS
    )
    assert guardrails.isolated_workspace.workspace_path is None
    assert guardrails.import_manifest.max_file_count == 200
    assert guardrails.import_manifest.max_total_bytes == 10 * 1024 * 1024

    # Custom isolation overrides survive round-trip serialization.
    custom = ExecutionGuardrails(
        isolated_workspace=IsolatedWorkspace(
            strategy="copy",
            include_patterns=["src/**"],
            exclude_patterns=["node_modules/**"],
            workspace_path=".council/workspaces/del_test",
        ),
        import_manifest=ImportManifest(
            writable_globs=["src/**", "tests/**"],
            readonly_artifact_paths=["docs/integration.md"],
            max_file_count=50,
            max_total_bytes=1024,
        ),
    )
    round_trip = ExecutionGuardrails.model_validate(custom.model_dump(mode="json"))
    assert round_trip.isolated_workspace.strategy == "copy"
    assert round_trip.import_manifest.writable_globs == ["src/**", "tests/**"]
    assert round_trip.import_manifest.max_total_bytes == 1024

    # WorkspaceFileChange validates known change types and defaults.
    change = WorkspaceFileChange(path="src/foo.py", change_type="modified", byte_size=512)
    assert change.imported is False
    assert change.rejection_reason is None
    with pytest.raises(ValueError):
        WorkspaceFileChange(path="src/foo.py", change_type="renamed", byte_size=1)

    # DelegationResult exposes workspace_manifest + import_outcome defaults.
    result = DelegationResult(
        delegation_id="del_x",
        role="implementer",
        model="claude",
        handoff_path=".council/delegations/del_x/handoff.yaml",
        result_path=".council/delegations/del_x/result.md",
        content="noop",
        status="delegated",
        delegation_status="completed",
        via_sidecar=True,
    )
    assert result.workspace_manifest == []
    assert result.import_outcome == "none"
    assert result.import_rejected_reason is None

    # Contract and prompt expose the new fields end-to-end.
    package = create_handoff_package(
        delegation_id="del_contract",
        role=RoleName.IMPLEMENTER,
        objective="Contract test",
        task_summary="Contract test",
        constraints=[],
        relevant_files=[],
        inputs={},
        required_artifacts={},
        expected_output="n/a",
        next_actions_on_success=[],
        next_actions_on_failure=[],
    )
    contract = build_delegation_contract(
        package,
        handoff_path=".council/delegations/del_contract/handoff.yaml",
    )
    contract_guardrails = contract["handoff_schema"]["execution_guardrails"]
    assert contract_guardrails["isolated_workspace"]["strategy"] == "git_worktree"
    assert contract_guardrails["import_manifest"]["max_file_count"] == 200
    assert any(
        "isolated_workspace" in rule and "sidecar workspace" in rule
        for rule in contract["consumption_rules"]
    )
    assert any(
        "workspace_manifest" in rule and "writable_globs" in rule
        for rule in contract["consumption_rules"]
    )

    prompt = render_delegation_prompt(package)
    assert "isolated_workspace.strategy: git_worktree" in prompt
    assert "import_manifest.max_file_count: 200" in prompt


def test_integration_doc_documents_sidecar_isolation_contract() -> None:
    integration_path = (
        Path(__file__).resolve().parents[1] / "docs" / "integration.md"
    )
    text = integration_path.read_text(encoding="utf-8")

    assert "## Sidecar Isolation Contract" in text
    assert "execution_guardrails.isolated_workspace" in text
    assert "execution_guardrails.import_manifest" in text
    assert "workspace_manifest" in text
    assert ".workflow-core" in text
    assert "git_worktree" in text
