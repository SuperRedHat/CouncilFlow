from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from councilflow.controller.delegation_orchestrator import (
    DelegationExecutionError,
    DelegationOrchestrator,
)
from councilflow.models.delegation import ReviewFinding, VerificationCommand
from councilflow.models.roles import RoleName
from councilflow.providers.base import ProviderError, ProviderRequest, ProviderResponse
from councilflow.state.store import CouncilStateStore


def _write_claude_permission_settings(tmp_path: Path, *commands: str) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    allow_entries = [f"Bash({command}:*)" for command in commands]
    settings_path.write_text(
        json.dumps({"permissions": {"allow": allow_entries}}, ensure_ascii=False),
        encoding="utf-8",
    )


class SuccessfulProvider:
    model_name = "claude"

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(model="claude", content=f"Handled:\n\n{request.prompt}")


class FailingProvider:
    model_name = "claude"

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        raise ProviderError("claude CLI is unavailable", kind="idle_timeout")


class ProtectedStateMutatingProvider:
    def __init__(self, project_root: Path) -> None:
        self.model_name = "claude"
        self.project_root = project_root

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        (self.project_root / ".council" / "state.json").write_text(
            '{"current_phase":"malicious"}',
            encoding="utf-8",
        )
        return ProviderResponse(model="claude", content="Touched protected state.")


class CommittingProvider:
    def __init__(self, project_root: Path) -> None:
        self.model_name = "claude"
        self.project_root = project_root

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        subprocess.run(
            ["git", "-C", str(self.project_root), "commit", "--allow-empty", "-m", "sidecar"],
            check=True,
            capture_output=True,
            text=True,
        )
        return ProviderResponse(model="claude", content="Created a commit.")


def test_delegation_orchestrator_persists_handoff_and_result(tmp_path: Path) -> None:
    _write_claude_permission_settings(tmp_path, "python -m pytest")
    store = CouncilStateStore(tmp_path)
    orchestrator = DelegationOrchestrator(
        store=store,
        participant_factory=lambda _: SuccessfulProvider(),
    )

    result = orchestrator.run(
        role=RoleName.TESTER,
        controller="codex",
        target_model="claude",
        objective="Validate provider adapters.",
        task_summary="Run tester-stage provider verification.",
        constraints=["Do not modify unrelated files."],
        relevant_files=["src/councilflow/providers/base.py"],
        inputs={"ticket": "TASK-005"},
        verification_commands=[
            VerificationCommand(command="python -m pytest", purpose="regression")
        ],
        expected_output="Markdown summary with actionable results.",
    )

    handoff_path = tmp_path / result.handoff_path
    result_path = tmp_path / result.result_path

    assert result.status == "delegated"
    assert result.delegation_status == "completed"
    assert result.via_sidecar is True
    assert result.tester_preflight.status == "passed"
    assert result.execution_guardrails.allow_commit is False
    assert handoff_path.is_file()
    assert result_path.is_file()
    handoff_payload = yaml.safe_load(handoff_path.read_text(encoding="utf-8"))
    assert handoff_payload["role"] == "tester"
    assert "tester-stage" in handoff_payload["task_summary"]
    assert handoff_payload["verification_commands"] == [
        {"command": "python -m pytest", "purpose": "regression"}
    ]
    assert "Handled:" in result_path.read_text(encoding="utf-8")


def test_delegation_orchestrator_persists_review_findings_and_fixer_sources(tmp_path: Path) -> None:
    store = CouncilStateStore(tmp_path)
    orchestrator = DelegationOrchestrator(
        store=store,
        participant_factory=lambda _: SuccessfulProvider(),
    )

    result = orchestrator.run(
        role=RoleName.FIXER,
        controller="codex",
        target_model="claude",
        objective="Repair issues raised after review.",
        task_summary="Apply targeted fixes without touching workflow state.",
        constraints=["Do not modify workflow state files."],
        relevant_files=["src/domain/game/game.ts"],
        inputs={"ticket": "TASK-005A"},
        required_artifacts={
            "tester_result": ".council/delegations/del_test/result.md",
            "reviewer_findings": ".council/delegations/del_review/findings.json",
        },
        review_findings=[
            ReviewFinding(
                finding_id="RV-002",
                severity="medium",
                title="Undo removes the wrong snapshot",
                body="undoLastMove() mismatches status and consecutive passes.",
                affected_files=["src/domain/game/game.ts"],
                required_fix="Restore state invariants when undo exits finished mode.",
            )
        ],
        expected_output="Markdown summary with actionable results.",
    )

    handoff_path = tmp_path / result.handoff_path
    handoff_payload = yaml.safe_load(handoff_path.read_text(encoding="utf-8"))

    assert result.review_findings[0].finding_id == "RV-002"
    assert result.fixer_input_sources[0].source_stage == "tester"
    assert result.fixer_input_sources[1].source_stage == "reviewer"
    assert handoff_payload["execution_guardrails"]["allow_commit"] is False
    assert handoff_payload["review_findings"][0]["title"] == "Undo removes the wrong snapshot"


def test_delegation_orchestrator_records_failures(tmp_path: Path) -> None:
    store = CouncilStateStore(tmp_path)
    orchestrator = DelegationOrchestrator(
        store=store,
        participant_factory=lambda _: FailingProvider(),
    )

    with pytest.raises(DelegationExecutionError) as exc_info:
        orchestrator.run(
            role=RoleName.IMPLEMENTER,
            controller="codex",
            target_model="claude",
            objective="Implement provider adapters.",
            task_summary="Add the delegation provider layer.",
            constraints=[],
            relevant_files=[],
            inputs={},
            expected_output="Markdown summary with actionable results.",
        )

    error = exc_info.value
    record = json.loads((tmp_path / error.record_path).read_text(encoding="utf-8"))

    assert error.delegation_id.startswith("del_")
    assert error.error_kind == "idle_timeout"
    assert record["status"] == "failed"
    assert record["error"] == "claude CLI is unavailable"
    assert record["error_kind"] == "idle_timeout"
    assert error.handoff_path.endswith("handoff.yaml")


def test_delegation_orchestrator_blocks_tester_on_missing_permissions(tmp_path: Path) -> None:
    store = CouncilStateStore(tmp_path)
    orchestrator = DelegationOrchestrator(
        store=store,
        participant_factory=lambda _: SuccessfulProvider(),
    )

    with pytest.raises(DelegationExecutionError) as exc_info:
        orchestrator.run(
            role=RoleName.TESTER,
            controller="codex",
            target_model="claude",
            objective="Run tester verification.",
            task_summary="Block when Claude permissions are missing.",
            constraints=[],
            relevant_files=[],
            inputs={},
            verification_commands=[VerificationCommand(command="python -m pytest")],
            expected_output="Markdown summary with actionable results.",
        )

    error = exc_info.value
    record = json.loads((tmp_path / error.record_path).read_text(encoding="utf-8"))

    assert error.error_kind == "permission_blocked"
    assert error.tester_preflight is not None
    assert error.tester_preflight.status == "permission_blocked"
    assert record["tester_preflight"]["permission_status"] == "blocked"


def test_delegation_orchestrator_blocks_guardrail_state_writes(tmp_path: Path) -> None:
    _write_claude_permission_settings(tmp_path, "python -m pytest")
    store = CouncilStateStore(tmp_path)
    orchestrator = DelegationOrchestrator(
        store=store,
        participant_factory=lambda _: ProtectedStateMutatingProvider(tmp_path),
    )

    with pytest.raises(DelegationExecutionError) as exc_info:
        orchestrator.run(
            role=RoleName.TESTER,
            controller="codex",
            target_model="claude",
            objective="Run tester verification.",
            task_summary="Block protected workflow state mutations.",
            constraints=[],
            relevant_files=[],
            inputs={},
            verification_commands=[VerificationCommand(command="python -m pytest")],
            expected_output="Markdown summary with actionable results.",
        )

    error = exc_info.value
    state_payload = json.loads((tmp_path / ".council" / "state.json").read_text(encoding="utf-8"))

    assert error.error_kind == "guardrail_violation"
    assert state_payload["current_phase"] == "idle"


def test_delegation_orchestrator_blocks_guardrail_commits(tmp_path: Path) -> None:
    _write_claude_permission_settings(tmp_path, "python -m pytest")
    subprocess.run(["git", "-C", str(tmp_path), "init"], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "CouncilFlow Test"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "councilflow@example.com"],
        check=True,
        capture_output=True,
        text=True,
    )
    (tmp_path / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "README.md"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "seed"],
        check=True,
        capture_output=True,
        text=True,
    )

    store = CouncilStateStore(tmp_path)
    orchestrator = DelegationOrchestrator(
        store=store,
        participant_factory=lambda _: CommittingProvider(tmp_path),
    )

    with pytest.raises(DelegationExecutionError) as exc_info:
        orchestrator.run(
            role=RoleName.TESTER,
            controller="codex",
            target_model="claude",
            objective="Run tester verification.",
            task_summary="Block unexpected git commits from sidecar execution.",
            constraints=[],
            relevant_files=[],
            inputs={},
            verification_commands=[VerificationCommand(command="python -m pytest")],
            expected_output="Markdown summary with actionable results.",
        )

    assert exc_info.value.error_kind == "guardrail_violation"
