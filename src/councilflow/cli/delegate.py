"""CLI entrypoint for delegating work to non-controller models."""

from __future__ import annotations

from pathlib import Path

import typer

from councilflow.controller.delegation_orchestrator import (
    DelegationExecutionError,
    DelegationOrchestrator,
)
from councilflow.controller.host_context import detect_controller
from councilflow.controller.routing import build_route_decision
from councilflow.models.config import ProviderRuntimeSettings
from councilflow.models.roles import RoleName, normalize_model_name
from councilflow.providers.base import ProviderAdapter, ProviderError
from councilflow.providers.claude_code_cli import ClaudeCodeCliAdapter
from councilflow.providers.codex_cli import CodexCliAdapter
from councilflow.providers.gemini_cli import GeminiCliAdapter
from councilflow.state.store import CouncilStateStore
from councilflow.utils.lang import emit_console_text, emit_response, resolve_output_language

DEFAULT_PROJECT_ROOT = Path(".")
ROLE_OPTION = typer.Option(..., "--role", help="Role to delegate.")
MODEL_OPTION = typer.Option(
    None,
    "--model",
    help="Override the target model. Falls back to the configured role mapping when omitted.",
)
OBJECTIVE_OPTION = typer.Option(..., "--objective", help="Delegation objective.")
TASK_SUMMARY_OPTION = typer.Option(
    ...,
    "--task-summary",
    help="Short summary of the delegated work.",
)
CONSTRAINT_OPTION = typer.Option(
    None,
    "--constraint",
    help="Repeat to provide multiple delegation constraints.",
)
RELEVANT_FILE_OPTION = typer.Option(
    None,
    "--relevant-file",
    help="Repeat to provide relevant files for the handoff package.",
)
EXPECTED_OUTPUT_OPTION = typer.Option(
    "Markdown summary with actionable results.",
    "--expected-output",
    help="Describe the output format expected from the delegated model.",
)
PROJECT_ROOT_OPTION = typer.Option(
    DEFAULT_PROJECT_ROOT,
    "--project-root",
    resolve_path=True,
    file_okay=False,
    dir_okay=True,
    help="Project root used to resolve .council state and artifacts.",
)


def get_provider_adapter(
    model: str,
    runtime: ProviderRuntimeSettings | None = None,
) -> ProviderAdapter:
    """Resolve a provider adapter for the requested model."""

    normalized = normalize_model_name(model)
    if normalized == "codex":
        return CodexCliAdapter(runtime=runtime)
    if normalized == "claude":
        return ClaudeCodeCliAdapter(runtime=runtime)
    if normalized == "gemini":
        # Use original model name if it's a specific version (e.g., gemini-1.5-flash)
        specific_model = model if model.startswith("gemini-") and model != "gemini-cli" else None
        return GeminiCliAdapter(model=specific_model, runtime=runtime)
    raise ProviderError(f"No provider adapter is registered for model '{model}'.")


def delegate(
    role: RoleName = ROLE_OPTION,
    model: str | None = MODEL_OPTION,
    objective: str = OBJECTIVE_OPTION,
    task_summary: str = TASK_SUMMARY_OPTION,
    constraint: list[str] | None = CONSTRAINT_OPTION,
    relevant_file: list[str] | None = RELEVANT_FILE_OPTION,
    expected_output: str = EXPECTED_OUTPUT_OPTION,
    project_root: Path = PROJECT_ROOT_OPTION,
) -> None:
    """Generate a handoff package and delegate the work to a provider adapter."""

    store = CouncilStateStore(project_root)
    store.initialize()
    config = store.load_config()
    controller_context = detect_controller(config=config)
    controller = controller_context.controller.value
    decision = build_route_decision(
        role=role,
        controller=controller_context.controller,
        target_model=model or config.roles.for_role(role),
    )
    output_language = resolve_output_language(config.output_language)
    if decision.status == "local_execution":
        emit_console_text(
            emit_response(
                data={
                    "role": role.value,
                    "model": decision.target_model,
                    "status": decision.status,
                    "via_sidecar": decision.via_sidecar,
                    "reason": (
                        "Target model resolves to the active controller, so execution "
                        "stays local and no sidecar is started."
                    ),
                },
                meta={
                    "command": "delegate",
                    "output_language": output_language,
                },
            )
        )
        return

    orchestrator = DelegationOrchestrator(
        store=store,
        participant_factory=lambda requested_model: get_provider_adapter(
            requested_model,
            config.providers.for_model(requested_model),
        ),
    )
    try:
        result = orchestrator.run(
            role=role,
            controller=controller,
            target_model=decision.target_model,
            objective=objective,
            task_summary=task_summary,
            constraints=list(constraint or []),
            relevant_files=list(relevant_file or []),
            inputs={"controller": controller, "configured_language": config.output_language},
            expected_output=expected_output,
        )
    except DelegationExecutionError as exc:
        emit_console_text(
            emit_response(
                data=None,
                meta={
                    "command": "delegate",
                    "output_language": output_language,
                },
                error={
                    "status": "error",
                    "via_sidecar": True,
                    "role": role.value,
                    "model": decision.target_model,
                    "message": str(exc),
                    "error_kind": exc.error_kind,
                    "delegation_id": exc.delegation_id,
                    "handoff_path": exc.handoff_path,
                    "record_path": exc.record_path,
                },
            )
        )
        raise typer.Exit(code=1) from exc

    emit_console_text(
        emit_response(
            data=result.model_dump(mode="json"),
            meta={
                "command": "delegate",
                "output_language": output_language,
            },
        )
    )
