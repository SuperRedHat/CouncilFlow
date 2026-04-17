"""Delegation orchestration for non-controller model execution."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from councilflow.handoff.packages import create_handoff_package, save_handoff_package
from councilflow.handoff.prompts import render_delegation_prompt
from councilflow.models.delegation import DelegationRecord, DelegationResult
from councilflow.models.roles import RoleName
from councilflow.providers.base import ProviderAdapter, ProviderError, ProviderRequest
from councilflow.state.store import CouncilStateStore


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
    ) -> None:
        super().__init__(message)
        self.delegation_id = delegation_id
        self.handoff_path = handoff_path
        self.record_path = record_path
        self.error_kind = error_kind


class DelegationOrchestrator:
    """Build handoff packages, invoke adapters, and persist delegation artifacts."""

    def __init__(
        self,
        store: CouncilStateStore,
        participant_factory: Callable[[str], ProviderAdapter],
    ) -> None:
        self.store = store
        self.participant_factory = participant_factory

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
        next_actions_on_success: list[str] | None = None,
        next_actions_on_failure: list[str] | None = None,
        expected_output: str,
    ) -> DelegationResult:
        """Persist a handoff package, invoke the adapter, and store the result."""

        self.store.initialize()
        delegation_id = datetime.now(tz=UTC).strftime("del_%Y%m%dT%H%M%S%fZ")
        delegation_dir = self.store.paths.delegations / delegation_id
        delegation_dir.mkdir(parents=True, exist_ok=True)
        package = create_handoff_package(
            delegation_id=delegation_id,
            role=role,
            objective=objective,
            task_summary=task_summary,
            constraints=constraints,
            relevant_files=relevant_files,
            inputs=inputs,
            required_artifacts=required_artifacts or {},
            next_actions_on_success=list(next_actions_on_success or []),
            next_actions_on_failure=list(next_actions_on_failure or []),
            expected_output=expected_output,
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

        try:
            provider = self.participant_factory(target_model)
            response = provider.ask(
                ProviderRequest(
                    prompt=render_delegation_prompt(package),
                    context={
                        "delegation_id": delegation_id,
                        "handoff_path": relative_handoff_path,
                    },
                )
            )
        except ProviderError as exc:
            relative_record_path = str(record_path.relative_to(self.store.paths.project_root))
            self.store.save_json(
                record_path,
                DelegationRecord(
                    id=delegation_id,
                    role=role.value,
                    target_model=target_model,
                    status="failed",
                    handoff_path=relative_handoff_path,
                    error=str(exc),
                    error_kind=exc.kind,
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
                    "error": str(exc),
                    "error_kind": exc.kind,
                },
            )
            raise DelegationExecutionError(
                str(exc),
                delegation_id=delegation_id,
                handoff_path=relative_handoff_path,
                record_path=relative_record_path,
                error_kind=exc.kind,
            ) from exc

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
            next_actions_on_success=package.next_actions_on_success,
            next_actions_on_failure=package.next_actions_on_failure,
        )
