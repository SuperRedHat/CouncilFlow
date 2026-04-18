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


class WorkspaceWritingProvider:
    """Fake provider that writes files into request.cwd (the sidecar workspace)."""

    model_name = "claude"

    def __init__(self, files_to_write: dict[str, str]) -> None:
        self.files_to_write = files_to_write
        self.observed_cwd: Path | None = None

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        assert request.cwd is not None, "isolated workspace must set cwd"
        workspace = Path(request.cwd)
        self.observed_cwd = workspace
        for relative, content in self.files_to_write.items():
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return ProviderResponse(model="claude", content="Workspace edits applied.")


def _seed_project(tmp_path: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def test_delegation_orchestrator_materializes_workspace_and_imports_allowed(
    tmp_path: Path,
) -> None:
    _write_claude_permission_settings(tmp_path, "python -m pytest")
    _seed_project(tmp_path, {"src/app.py": "print('hello')\n"})
    store = CouncilStateStore(tmp_path)
    provider = WorkspaceWritingProvider({"src/app.py": "print('hello world')\n"})
    orchestrator = DelegationOrchestrator(
        store=store,
        participant_factory=lambda _: provider,
    )

    from councilflow.models.delegation import ExecutionGuardrails, ImportManifest

    result = orchestrator.run(
        role=RoleName.IMPLEMENTER,
        controller="codex",
        target_model="claude",
        objective="Materialize and import",
        task_summary="Modify src/app.py inside sidecar workspace.",
        constraints=[],
        relevant_files=["src/app.py"],
        inputs={},
        execution_guardrails=ExecutionGuardrails(
            import_manifest=ImportManifest(writable_globs=["src/**"]),
        ),
        expected_output="Import-back result.",
    )

    assert provider.observed_cwd is not None
    assert provider.observed_cwd != tmp_path
    assert result.import_outcome == "applied"
    assert len(result.workspace_manifest) == 1
    manifest_entry = result.workspace_manifest[0]
    assert manifest_entry.path == "src/app.py"
    assert manifest_entry.change_type == "modified"
    assert manifest_entry.imported is True
    # Sidecar change actually landed in the host project root.
    assert (tmp_path / "src/app.py").read_text(encoding="utf-8") == "print('hello world')\n"


def test_delegation_orchestrator_rejects_protected_path_imports(tmp_path: Path) -> None:
    _write_claude_permission_settings(tmp_path, "python -m pytest")
    _seed_project(tmp_path, {"src/app.py": "print('ok')\n"})
    store = CouncilStateStore(tmp_path)
    # The sidecar writes a .workflow-core file; the default protected paths must
    # reject that even if the provider happens to materialize the change.
    provider = WorkspaceWritingProvider(
        {".workflow-core/skills/project-next/SKILL.md": "tampered\n"}
    )
    orchestrator = DelegationOrchestrator(
        store=store,
        participant_factory=lambda _: provider,
    )

    from councilflow.models.delegation import ExecutionGuardrails, ImportManifest

    result = orchestrator.run(
        role=RoleName.IMPLEMENTER,
        controller="codex",
        target_model="claude",
        objective="Try to poison workflow state",
        task_summary="Attempt to import into .workflow-core",
        constraints=[],
        relevant_files=[],
        inputs={},
        execution_guardrails=ExecutionGuardrails(
            import_manifest=ImportManifest(
                writable_globs=[".workflow-core/**"],  # permissive import globs
            ),
        ),
        expected_output="Should not land in host.",
    )

    assert result.import_outcome == "rejected"
    rejected_paths = [change.path for change in result.workspace_manifest]
    assert any(path.startswith(".workflow-core/") for path in rejected_paths)
    # Host project must not contain the rejected file.
    assert not (tmp_path / ".workflow-core/skills/project-next/SKILL.md").exists()


def test_delegation_orchestrator_does_not_import_source_untracked_files_as_deleted(
    tmp_path: Path,
) -> None:
    """TASK-058 regression: previous implementer added src/feature/new.ts to
    source but never committed. Tester is a later delegation that ran in its
    own git_worktree (no knowledge of the untracked file). The detector must
    NOT flag the source file as ``deleted`` — if it did, apply_import_changes
    would unlink user work. Here we simulate the scenario without a real git
    repo; the copy fallback reproduces the same detect path that bit the
    real chess project."""

    _write_claude_permission_settings(tmp_path, "python -m pytest")
    _seed_project(tmp_path, {"src/app.py": "print('ok')\n"})
    # Simulate a previous implementer's untracked file already landed in source.
    untracked = tmp_path / "src" / "features" / "game_session" / "reducer.ts"
    untracked.parent.mkdir(parents=True, exist_ok=True)
    untracked.write_text("export const reducer = () => {};\n", encoding="utf-8")

    store = CouncilStateStore(tmp_path)
    # Sidecar does NOT touch any file.
    quiet_provider = WorkspaceWritingProvider({})
    orchestrator = DelegationOrchestrator(
        store=store,
        participant_factory=lambda _: quiet_provider,
    )

    from councilflow.models.delegation import ExecutionGuardrails, ImportManifest

    result = orchestrator.run(
        role=RoleName.TESTER,
        controller="codex",
        target_model="claude",
        objective="TASK-058 regression",
        task_summary="Sidecar touches nothing; source has untracked file.",
        constraints=[],
        relevant_files=[],
        inputs={},
        execution_guardrails=ExecutionGuardrails(
            # Even with an overly permissive manifest, manifest must stay
            # empty because the sidecar did not actually modify anything.
            import_manifest=ImportManifest(writable_globs=["**"]),
        ),
        expected_output="",
    )

    assert result.workspace_manifest == []
    assert result.import_outcome == "none"
    # The key assertion: the untracked file must STILL exist after the
    # delegation completes. Pre-TASK-058 this was unlinked.
    assert untracked.exists(), "sidecar-untouched source file must not be removed"
    assert untracked.read_text(encoding="utf-8") == "export const reducer = () => {};\n"


def test_delegation_orchestrator_empty_writable_globs_rejects_all_imports(
    tmp_path: Path,
) -> None:
    """TASK-058 regression: the default ImportManifest has writable_globs=[].
    Previously this meant ``allow everything`` (bug). After the fix, empty
    globs mean ``reject everything`` so a tester-style delegation cannot
    accidentally write back to source."""

    _write_claude_permission_settings(tmp_path, "python -m pytest")
    _seed_project(tmp_path, {})

    provider = WorkspaceWritingProvider(
        {"src/cheeky.ts": "// should never reach source\n"}
    )
    store = CouncilStateStore(tmp_path)
    orchestrator = DelegationOrchestrator(
        store=store,
        participant_factory=lambda _: provider,
    )

    # Default ExecutionGuardrails() with default ImportManifest() has writable_globs=[]
    result = orchestrator.run(
        role=RoleName.TESTER,
        controller="codex",
        target_model="claude",
        objective="TASK-058 default-safe regression",
        task_summary="Default guardrails must reject workspace writes.",
        constraints=[],
        relevant_files=[],
        inputs={},
        expected_output="",
    )

    assert result.import_outcome == "rejected"
    assert any(
        c.path == "src/cheeky.ts" and c.imported is False for c in result.workspace_manifest
    )
    assert not (tmp_path / "src" / "cheeky.ts").exists()


def test_delegation_orchestrator_rejects_path_outside_writable_globs(tmp_path: Path) -> None:
    _write_claude_permission_settings(tmp_path, "python -m pytest")
    _seed_project(tmp_path, {"src/app.py": "ok\n", "docs/README.md": "old\n"})
    store = CouncilStateStore(tmp_path)
    # Writable globs only cover src/**, but sidecar edits docs/README.md.
    provider = WorkspaceWritingProvider({"docs/README.md": "new\n"})
    orchestrator = DelegationOrchestrator(
        store=store,
        participant_factory=lambda _: provider,
    )

    from councilflow.models.delegation import ExecutionGuardrails, ImportManifest

    result = orchestrator.run(
        role=RoleName.IMPLEMENTER,
        controller="codex",
        target_model="claude",
        objective="Attempt to edit docs",
        task_summary="docs/ edit should be rejected without writable_globs.",
        constraints=[],
        relevant_files=[],
        inputs={},
        execution_guardrails=ExecutionGuardrails(
            import_manifest=ImportManifest(writable_globs=["src/**"]),
        ),
        expected_output="Rejected import.",
    )

    assert result.import_outcome == "rejected"
    assert result.workspace_manifest[0].path == "docs/README.md"
    assert result.workspace_manifest[0].imported is False
    assert result.workspace_manifest[0].rejection_reason is not None
    # Original docs/README.md in host untouched.
    assert (tmp_path / "docs/README.md").read_text(encoding="utf-8") == "old\n"
