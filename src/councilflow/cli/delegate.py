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
from councilflow.models.delegation import ExecutionGuardrails, ImportManifest
from councilflow.models.roles import RoleName, normalize_model_name
from councilflow.providers.base import ProviderAdapter
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
INPUT_OPTION = typer.Option(
    None,
    "--input",
    help="Repeat KEY=VALUE to attach structured stage inputs.",
)
VERIFICATION_COMMAND_OPTION = typer.Option(
    None,
    "--verification-command",
    help=(
        "Repeat to attach structured tester verification commands without relying "
        "on a joined shell string."
    ),
)
REQUIRED_ARTIFACT_OPTION = typer.Option(
    None,
    "--required-artifact",
    help="Repeat LABEL=PATH to declare required upstream artifacts for this stage.",
)
NEXT_ON_SUCCESS_OPTION = typer.Option(
    None,
    "--next-on-success",
    help="Repeat to describe the workflow action that should happen when this stage succeeds.",
)
NEXT_ON_FAILURE_OPTION = typer.Option(
    None,
    "--next-on-failure",
    help="Repeat to describe the workflow action that should happen when this stage fails.",
)
WRITABLE_GLOB_OPTION = typer.Option(
    None,
    "--writable-glob",
    help=(
        "Repeat to allow-list a path glob that the sidecar may write back to "
        "the host project (maps to ExecutionGuardrails.import_manifest.writable_globs). "
        "Without this flag, empty writable_globs deny-by-default rejects every "
        "sidecar-driven import; implementer / fixer stages must set at least one "
        "glob or their output will be discarded."
    ),
)
READONLY_ARTIFACT_OPTION = typer.Option(
    None,
    "--readonly-artifact",
    help=(
        "Repeat a relative path that the sidecar may read but never modify "
        "(ExecutionGuardrails.import_manifest.readonly_artifact_paths)."
    ),
)
ALLOW_COMMIT_OPTION = typer.Option(
    False,
    "--allow-commit",
    help=(
        "Opt the delegated stage into creating git commits. Default is "
        "deny; most tasks keep commit decisions at the controller."
    ),
)
ALLOW_WORKFLOW_STATE_WRITE_OPTION = typer.Option(
    False,
    "--allow-workflow-state-write",
    help=(
        "Opt the delegated stage into modifying workflow state files (.claude/state, "
        ".council/state.json). Only enable for workflow-maintenance tasks."
    ),
)
PROJECT_ROOT_OPTION = typer.Option(
    DEFAULT_PROJECT_ROOT,
    "--project-root",
    resolve_path=True,
    file_okay=False,
    dir_okay=True,
    help="Project root used to resolve .council state and artifacts.",
)


def _parse_key_value_items(items: list[str] | None, *, option_name: str) -> dict[str, str]:
    """Parse repeated KEY=VALUE items into a mapping."""

    parsed: dict[str, str] = {}
    for item in items or []:
        key, separator, value = item.partition("=")
        if not separator or not key.strip() or not value.strip():
            raise typer.BadParameter(
                f"{option_name} expects KEY=VALUE items, got '{item}'."
            )
        parsed[key.strip()] = value.strip()
    return parsed


def get_provider_adapter(
    model: str,
    runtime: ProviderRuntimeSettings | None = None,
) -> ProviderAdapter:
    """Resolve a provider adapter for the requested model via the registry."""

    from councilflow.providers.registry import resolve_adapter

    # Preserve the legacy gemini-<variant> routing: the registry's gemini
    # factory reads the raw model name, but for historical reasons the CLI
    # path always resolved specific variants through the default factory.
    if normalize_model_name(model).startswith("gemini-") and model != "gemini-cli":
        return GeminiCliAdapter(model=model, runtime=runtime)
    return resolve_adapter(model, runtime=runtime)


def delegate(
    role: RoleName = ROLE_OPTION,
    model: str | None = MODEL_OPTION,
    objective: str = OBJECTIVE_OPTION,
    task_summary: str = TASK_SUMMARY_OPTION,
    constraint: list[str] | None = CONSTRAINT_OPTION,
    relevant_file: list[str] | None = RELEVANT_FILE_OPTION,
    expected_output: str = EXPECTED_OUTPUT_OPTION,
    stage_input: list[str] | None = INPUT_OPTION,
    verification_command: list[str] | None = VERIFICATION_COMMAND_OPTION,
    required_artifact: list[str] | None = REQUIRED_ARTIFACT_OPTION,
    next_on_success: list[str] | None = NEXT_ON_SUCCESS_OPTION,
    next_on_failure: list[str] | None = NEXT_ON_FAILURE_OPTION,
    writable_glob: list[str] | None = WRITABLE_GLOB_OPTION,
    readonly_artifact: list[str] | None = READONLY_ARTIFACT_OPTION,
    allow_commit: bool = ALLOW_COMMIT_OPTION,
    allow_workflow_state_write: bool = ALLOW_WORKFLOW_STATE_WRITE_OPTION,
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
    structured_inputs = _parse_key_value_items(stage_input, option_name="--input")
    required_artifacts = _parse_key_value_items(
        required_artifact,
        option_name="--required-artifact",
    )
    guardrails_kwargs: dict[str, object] = {}
    if allow_commit:
        guardrails_kwargs["allow_commit"] = True
    if allow_workflow_state_write:
        guardrails_kwargs["allow_workflow_state_write"] = True
    if writable_glob or readonly_artifact:
        guardrails_kwargs["import_manifest"] = ImportManifest(
            writable_globs=list(writable_glob or []),
            readonly_artifact_paths=list(readonly_artifact or []),
        )
    execution_guardrails = ExecutionGuardrails(**guardrails_kwargs) if guardrails_kwargs else None
    try:
        result = orchestrator.run(
            role=role,
            controller=controller,
            target_model=decision.target_model,
            objective=objective,
            task_summary=task_summary,
            constraints=list(constraint or []),
            relevant_files=list(relevant_file or []),
            inputs={
                "controller": controller,
                "configured_language": config.output_language,
                **structured_inputs,
            },
            required_artifacts=required_artifacts,
            verification_commands=list(verification_command or []),
            execution_guardrails=execution_guardrails,
            next_actions_on_success=list(next_on_success or []),
            next_actions_on_failure=list(next_on_failure or []),
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
                    "tester_preflight": (
                        exc.tester_preflight.model_dump(mode="json")
                        if exc.tester_preflight is not None
                        else None
                    ),
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
