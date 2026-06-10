"""Delegation orchestration for non-controller model execution."""

from __future__ import annotations

import hashlib
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from councilflow.handoff.packages import create_handoff_package, save_handoff_package
from councilflow.handoff.prompts import render_delegation_prompt
from councilflow.models.delegation import (
    DelegationRecord,
    DelegationResult,
    ExecutionGuardrails,
    FixerInputSource,
    ReviewFinding,
    TesterPreflight,
    VerificationCommand,
    WorkspaceFileChange,
)
from councilflow.models.roles import RoleName
from councilflow.providers.base import (
    ProviderAdapter,
    ProviderError,
    ProviderRequest,
    build_sandboxed_env,
)
from councilflow.providers.mcp_policy import (
    build_mcp_denied_env,
    plan_mcp_policy,
    role_allows_mcp,
    write_empty_mcp_configs,
)
from councilflow.state.store import CouncilStateStore
from councilflow.utils.io import (
    apply_import_changes,
    classify_import_changes,
    cleanup_workspace,
    detect_workspace_changes,
    materialize_workspace,
    snapshot_workspace_baseline,
    summarize_import_outcome,
)
from councilflow.utils.logging import get_logger
from councilflow.utils.permissions import command_is_available

_logger = get_logger(__name__)

PROTECTED_WORKFLOW_PATHS = (".claude/state", ".council/state.json")


class DelegationExecutionError(RuntimeError):
    """Structured error raised when delegation execution fails."""

    def __init__(
        self,
        message: str,
        *,
        delegation_id: str,
        handoff_path: str,
        record_path: str,
        error_kind: str | None = None,
        tester_preflight: TesterPreflight | None = None,
    ) -> None:
        super().__init__(message)
        self.delegation_id = delegation_id
        self.handoff_path = handoff_path
        self.record_path = record_path
        self.error_kind = error_kind
        self.tester_preflight = tester_preflight


def _run_tester_preflight(
    project_root: Path,
    *,
    target_model: str,
    verification_commands: list[VerificationCommand],
) -> TesterPreflight:
    """Probe the local environment before delegating a tester stage.

    Since 0.1.1 all three adapters run delegated subprocesses with auto-
    approval (Claude via ``--dangerously-skip-permissions``, Gemini via
    ``--approval-mode yolo``, Codex via user-configured policy), so the only
    check left is whether the verification commands' executables actually
    resolve on PATH. If any are missing, ``environment_not_ready`` fires so
    the controller fails fast instead of letting the sidecar hit a missing
    binary after it has started.
    """

    if not verification_commands:
        return TesterPreflight()

    availability = {
        item.command: ("available" if command_is_available(item.command) else "missing")
        for item in verification_commands
    }
    workspace_ready = project_root.exists()
    provider_ready = True

    if not workspace_ready or any(status != "available" for status in availability.values()):
        return TesterPreflight(
            status="environment_not_ready",
            provider_ready=provider_ready,
            workspace_ready=workspace_ready,
            command_availability=availability,
            permission_requirements=[],
            permission_status="not_checked",
        )

    return TesterPreflight(
        status="passed",
        provider_ready=provider_ready,
        workspace_ready=workspace_ready,
        command_availability=availability,
        permission_requirements=[],
        permission_status="not_required",
    )


def _hash_bytes(content: bytes) -> str:
    """Return a deterministic digest for a file snapshot."""

    return hashlib.sha256(content).hexdigest()


def _collect_guarded_file_paths(project_root: Path, protected_paths: list[str]) -> set[Path]:
    """Resolve every protected file currently covered by the guardrail scope."""

    guarded_files: set[Path] = set()
    for raw_path in protected_paths:
        resolved = project_root / raw_path
        if resolved.is_file():
            guarded_files.add(resolved)
            continue
        if resolved.is_dir():
            guarded_files.update(path for path in resolved.rglob("*") if path.is_file())
    return guarded_files


def _snapshot_protected_paths(
    project_root: Path,
    protected_paths: list[str],
) -> dict[str, bytes]:
    """Capture file contents for protected workflow paths before a delegated stage runs."""

    snapshot: dict[str, bytes] = {}
    for path in _collect_guarded_file_paths(project_root, protected_paths):
        snapshot[str(path.relative_to(project_root))] = path.read_bytes()
    return snapshot


def _restore_protected_paths(
    project_root: Path,
    protected_paths: list[str],
    snapshot: dict[str, bytes],
) -> None:
    """Restore protected workflow files to their pre-delegation contents."""

    current_paths = {
        str(path.relative_to(project_root)): path
        for path in _collect_guarded_file_paths(project_root, protected_paths)
    }
    for relative_path, path in current_paths.items():
        if relative_path not in snapshot:
            path.unlink(missing_ok=True)
    for relative_path, content in snapshot.items():
        destination = project_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)


def _detect_protected_path_changes(
    project_root: Path,
    protected_paths: list[str],
    snapshot: dict[str, bytes],
) -> list[str]:
    """Return the protected paths that changed during delegated execution."""

    changed: list[str] = []
    current_paths = {
        str(path.relative_to(project_root)): path
        for path in _collect_guarded_file_paths(project_root, protected_paths)
    }
    for relative_path, content in snapshot.items():
        current_path = current_paths.get(relative_path)
        if current_path is None:
            changed.append(relative_path)
            continue
        if _hash_bytes(current_path.read_bytes()) != _hash_bytes(content):
            changed.append(relative_path)
    for relative_path in current_paths:
        if relative_path not in snapshot:
            changed.append(relative_path)
    return sorted(set(changed))


def _read_git_head(project_root: Path) -> str | None:
    """Return the current git HEAD sha for the project, if available."""

    try:
        completed = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    head = completed.stdout.strip()
    return head or None


class DelegationOrchestrator:
    """Build handoff packages, invoke adapters, and persist delegation artifacts."""

    def __init__(
        self,
        store: CouncilStateStore,
        participant_factory: Callable[[str], ProviderAdapter],
    ) -> None:
        self.store = store
        self.participant_factory = participant_factory

    def _persist_failure(
        self,
        *,
        delegation_id: str,
        role: RoleName,
        target_model: str,
        controller: str,
        handoff_path: str,
        record_path: Path,
        error: ProviderError,
        tester_preflight: TesterPreflight | None = None,
    ) -> DelegationExecutionError:
        """Persist a structured failure record and return the raised exception."""

        relative_record_path = str(record_path.relative_to(self.store.paths.project_root))
        self.store.save_json(
            record_path,
            DelegationRecord(
                id=delegation_id,
                role=role.value,
                target_model=target_model,
                status="failed",
                handoff_path=handoff_path,
                error=str(error),
                error_kind=error.kind,
                tester_preflight=(
                    tester_preflight.model_dump(mode="json")
                    if tester_preflight is not None
                    else None
                ),
            ).model_dump(mode="json"),
        )
        self.store.write_state(
            {
                "current_phase": "idle",
                "current_controller": controller,
                "last_delegation_id": delegation_id,
                "last_delegation_status": "failed",
            }
        )
        self.store.append_run_record(
            "delegation",
            {
                "delegation_id": delegation_id,
                "role": role.value,
                "target_model": target_model,
                "status": "failed",
                "error": str(error),
                "error_kind": error.kind,
                "tester_preflight": (
                    tester_preflight.model_dump(mode="json")
                    if tester_preflight is not None
                    else None
                ),
            },
        )
        return DelegationExecutionError(
            str(error),
            delegation_id=delegation_id,
            handoff_path=handoff_path,
            record_path=relative_record_path,
            error_kind=error.kind,
            tester_preflight=tester_preflight,
        )

    def run(
        self,
        *,
        role: RoleName,
        controller: str,
        target_model: str,
        objective: str,
        task_summary: str,
        constraints: list[str],
        relevant_files: list[str],
        inputs: dict[str, str],
        required_artifacts: dict[str, str] | None = None,
        verification_commands: list[VerificationCommand] | list[str] | None = None,
        tester_preflight: TesterPreflight | None = None,
        review_findings: list[ReviewFinding] | None = None,
        fixer_input_sources: list[FixerInputSource] | None = None,
        execution_guardrails: ExecutionGuardrails | None = None,
        next_actions_on_success: list[str] | None = None,
        next_actions_on_failure: list[str] | None = None,
        expected_output: str,
    ) -> DelegationResult:
        """Persist a handoff package, invoke the adapter, and store the result."""

        self.store.initialize()
        delegation_id = datetime.now(tz=UTC).strftime("del_%Y%m%dT%H%M%S%fZ")
        delegation_dir = self.store.paths.delegations / delegation_id
        delegation_dir.mkdir(parents=True, exist_ok=True)
        start_monotonic = time.monotonic()
        _logger.info(
            "delegation.start id=%s role=%s target_model=%s controller=%s",
            delegation_id, role.value, target_model, controller,
        )
        package = create_handoff_package(
            delegation_id=delegation_id,
            role=role,
            objective=objective,
            task_summary=task_summary,
            constraints=constraints,
            relevant_files=relevant_files,
            inputs=inputs,
            required_artifacts=required_artifacts or {},
            verification_commands=verification_commands,
            tester_preflight=tester_preflight,
            review_findings=review_findings,
            fixer_input_sources=fixer_input_sources,
            execution_guardrails=execution_guardrails,
            next_actions_on_success=list(next_actions_on_success or []),
            next_actions_on_failure=list(next_actions_on_failure or []),
            expected_output=expected_output,
        )
        if role is RoleName.TESTER:
            package.tester_preflight = _run_tester_preflight(
                self.store.paths.project_root,
                target_model=target_model,
                verification_commands=package.verification_commands,
            )
        handoff_path = save_handoff_package(package, delegation_dir / "handoff.yaml")
        record_path = delegation_dir / "record.json"
        relative_handoff_path = str(handoff_path.relative_to(self.store.paths.project_root))

        self.store.write_state(
            {
                "current_phase": "delegation",
                "current_controller": controller,
                "last_delegation_id": delegation_id,
            }
        )

        if package.tester_preflight.status == "environment_not_ready":
            missing_commands = ", ".join(
                command
                for command, status in package.tester_preflight.command_availability.items()
                if status != "available"
            )
            error = ProviderError(
                "Tester preflight blocked delegated verification because the environment "
                f"is not ready for: {missing_commands}.",
                kind="environment_not_ready",
                metadata={
                    "tester_preflight": package.tester_preflight.model_dump(mode="json"),
                },
            )
            raise self._persist_failure(
                delegation_id=delegation_id,
                role=role,
                target_model=target_model,
                controller=controller,
                handoff_path=relative_handoff_path,
                record_path=record_path,
                error=error,
                tester_preflight=package.tester_preflight,
            )

        protected_snapshot = (
            _snapshot_protected_paths(
                self.store.paths.project_root,
                package.execution_guardrails.protected_paths,
            )
            if not package.execution_guardrails.allow_workflow_state_write
            else {}
        )
        initial_git_head = (
            _read_git_head(self.store.paths.project_root)
            if not package.execution_guardrails.allow_commit
            else None
        )

        # TASK-118: setup failures (workspace materialization, handoff persist,
        # MCP policy, baseline snapshot) previously escaped as raw exceptions —
        # no cleanup, no failure record; `delegation wait` then starved on a
        # record.json frozen at status=running. Contain them like provider
        # failures.
        materialization = None
        try:
            materialization = materialize_workspace(
                project_root=self.store.paths.project_root,
                council_root=self.store.paths.council_root,
                delegation_id=delegation_id,
                isolated=package.execution_guardrails.isolated_workspace,
            )
            package.execution_guardrails.isolated_workspace = (
                package.execution_guardrails.isolated_workspace.model_copy(
                    update={
                        "strategy": materialization.effective_strategy,
                        "workspace_path": str(
                            materialization.workspace_path.relative_to(
                                self.store.paths.project_root
                            )
                        )
                        if materialization.workspace_path != self.store.paths.project_root
                        else None,
                    }
                )
            )
            # Persist the resolved isolation choice back to handoff.yaml so downstream
            # consumers see the effective strategy instead of the requested default.
            save_handoff_package(package, delegation_dir / "handoff.yaml")

            # Apply the MCP access policy for this role. Delegated execution roles
            # (implementer/tester/reviewer/fixer/advisor) get an empty worktree-
            # local MCP config so they cannot attach the host's project-manager MCP
            # and silently write `.claude/state/logs.json`. Controller-facing roles
            # (architect/planner/synthesizer) keep their access because they are
            # expected to read PRD / task / architecture data.
            mcp_policy = plan_mcp_policy(
                role, self.store.paths.project_root, materialization.workspace_path
            )
            mcp_env_extra: dict[str, str] = {}
            if (
                not role_allows_mcp(role)
                and materialization.workspace_path != self.store.paths.project_root
            ):
                write_empty_mcp_configs(materialization.workspace_path)
                mcp_env_extra = build_mcp_denied_env(
                    self.store.paths.project_root, materialization.workspace_path
                )
                _logger.info(
                    "delegation.mcp_policy id=%s role=%s decision=deny",
                    delegation_id,
                    role.value,
                )
            else:
                _logger.info(
                    "delegation.mcp_policy id=%s role=%s decision=allow",
                    delegation_id,
                    role.value,
                )

            # Capture a file-level baseline of the freshly materialized workspace
            # BEFORE the provider runs so detect_workspace_changes can later report
            # only the sidecar's own edits. Comparing the post-run workspace to the
            # host source tree (the pre-TASK-058 behavior) incorrectly flagged
            # untracked source files as ``deleted`` and imported those deletions
            # back, destroying user work — see TASK-058 incident log.
            workspace_baseline = (
                snapshot_workspace_baseline(materialization.workspace_path)
                if materialization.workspace_path != self.store.paths.project_root
                else None
            )

        except Exception as exc:  # noqa: BLE001 — converted to canonical failure
            if materialization is not None:
                cleanup_workspace(
                    self.store.paths.project_root,
                    materialization.workspace_path,
                    materialization.effective_strategy,
                )
            setup_error = ProviderError(
                f"Delegation setup failed before provider start: {exc}",
                kind="delegation_setup_failed",
            )
            raise self._persist_failure(
                delegation_id=delegation_id,
                role=role,
                target_model=target_model,
                controller=controller,
                handoff_path=relative_handoff_path,
                record_path=record_path,
                error=setup_error,
                tester_preflight=(
                    package.tester_preflight if role is RoleName.TESTER else None
                ),
            ) from exc

        workspace_manifest: list[WorkspaceFileChange] = []
        import_outcome = "none"
        import_rejected_reason: str | None = None

        try:
            provider = self.participant_factory(target_model)
            sandboxed_env = build_sandboxed_env(delegation_id)
            if mcp_env_extra:
                sandboxed_env.update(mcp_env_extra)
            response = provider.ask(
                ProviderRequest(
                    prompt=render_delegation_prompt(package),
                    context={
                        "delegation_id": delegation_id,
                        "handoff_path": relative_handoff_path,
                        "workspace_path": str(materialization.workspace_path),
                        "mcp_policy": mcp_policy,
                    },
                    cwd=(
                        str(materialization.workspace_path)
                        if materialization.workspace_path
                        != self.store.paths.project_root
                        else None
                    ),
                    env_override=sandboxed_env,
                )
            )

            if (
                materialization.workspace_path != self.store.paths.project_root
                and workspace_baseline is not None
            ):
                detected = detect_workspace_changes(
                    baseline=workspace_baseline,
                    workspace_path=materialization.workspace_path,
                )
                workspace_manifest = classify_import_changes(
                    detected,
                    package.execution_guardrails,
                )
                apply_import_changes(
                    workspace_manifest,
                    source_root=self.store.paths.project_root,
                    workspace_path=materialization.workspace_path,
                )
                import_outcome, import_rejected_reason = summarize_import_outcome(
                    workspace_manifest
                )

            if not package.execution_guardrails.allow_workflow_state_write:
                changed_paths = _detect_protected_path_changes(
                    self.store.paths.project_root,
                    package.execution_guardrails.protected_paths,
                    protected_snapshot,
                )
                if changed_paths:
                    _logger.warning(
                        "delegation.guardrail_violation id=%s reason=%s count=%d",
                        delegation_id,
                        "protected_paths_modified",
                        len(changed_paths),
                    )
                    _restore_protected_paths(
                        self.store.paths.project_root,
                        package.execution_guardrails.protected_paths,
                        protected_snapshot,
                    )
                    raise ProviderError(
                        "Delegated stage modified protected workflow paths despite "
                        f"allow_workflow_state_write=false: {', '.join(changed_paths)}.",
                        kind="guardrail_violation",
                        metadata={"changed_paths": changed_paths},
                    )
            if not package.execution_guardrails.allow_commit:
                current_git_head = _read_git_head(self.store.paths.project_root)
                if initial_git_head is not None and current_git_head != initial_git_head:
                    _logger.warning(
                        "delegation.guardrail_violation id=%s reason=unexpected_commit",
                        delegation_id,
                    )
                    raise ProviderError(
                        "Delegated stage created a git commit despite allow_commit=false.",
                        kind="guardrail_violation",
                        metadata={
                            "initial_head": initial_git_head,
                            "current_head": current_git_head,
                        },
                    )
        except ProviderError as exc:
            # TASK-118: with isolation strategy "none" the sidecar runs directly
            # in the host tree — a provider that failed/timed out may already
            # have modified protected workflow files. The success path detects
            # and restores; the failure path must too.
            if not package.execution_guardrails.allow_workflow_state_write:
                changed_paths = _detect_protected_path_changes(
                    self.store.paths.project_root,
                    package.execution_guardrails.protected_paths,
                    protected_snapshot,
                )
                if changed_paths:
                    _logger.warning(
                        "delegation.guardrail_violation id=%s reason=%s count=%d "
                        "(restored on failure path)",
                        delegation_id,
                        "protected_paths_modified",
                        len(changed_paths),
                    )
                    _restore_protected_paths(
                        self.store.paths.project_root,
                        package.execution_guardrails.protected_paths,
                        protected_snapshot,
                    )
            cleanup_workspace(
                self.store.paths.project_root,
                materialization.workspace_path,
                materialization.effective_strategy,
            )
            raise self._persist_failure(
                delegation_id=delegation_id,
                role=role,
                target_model=target_model,
                controller=controller,
                handoff_path=relative_handoff_path,
                record_path=record_path,
                error=exc,
                tester_preflight=(
                    package.tester_preflight if role is RoleName.TESTER else None
                ),
            ) from exc

        cleanup_workspace(
            self.store.paths.project_root,
            materialization.workspace_path,
            materialization.effective_strategy,
        )

        elapsed = time.monotonic() - start_monotonic
        _logger.info(
            "delegation.completed id=%s role=%s import_outcome=%s manifest=%d elapsed=%.3fs",
            delegation_id, role.value, import_outcome, len(workspace_manifest), elapsed,
        )

        result_path = delegation_dir / "result.md"
        self.store.write_text(result_path, response.content)
        relative_result_path = str(result_path.relative_to(self.store.paths.project_root))
        self.store.save_json(
            record_path,
            DelegationRecord(
                id=delegation_id,
                role=role.value,
                target_model=target_model,
                status="completed",
                handoff_path=relative_handoff_path,
                result_path=relative_result_path,
            ).model_dump(mode="json"),
        )
        self.store.append_run_record(
            "delegation",
            {
                "delegation_id": delegation_id,
                "role": role.value,
                "target_model": target_model,
                "result_path": relative_result_path,
                "mcp_policy": mcp_policy,
            },
        )
        self.store.write_state(
            {
                "current_phase": "idle",
                "current_controller": controller,
                "last_delegation_id": delegation_id,
                "last_delegation_status": "completed",
                "last_result_path": relative_result_path,
            }
        )
        return DelegationResult(
            delegation_id=delegation_id,
            role=role.value,
            model=target_model,
            handoff_path=relative_handoff_path,
            result_path=relative_result_path,
            content=response.content,
            status="delegated",
            delegation_status="completed",
            via_sidecar=True,
            required_artifacts=package.required_artifacts,
            verification_commands=package.verification_commands,
            tester_preflight=package.tester_preflight,
            review_findings=package.review_findings,
            fixer_input_sources=package.fixer_input_sources,
            execution_guardrails=package.execution_guardrails,
            next_actions_on_success=package.next_actions_on_success,
            next_actions_on_failure=package.next_actions_on_failure,
            workspace_manifest=workspace_manifest,
            import_outcome=import_outcome,
            import_rejected_reason=import_rejected_reason,
        )
