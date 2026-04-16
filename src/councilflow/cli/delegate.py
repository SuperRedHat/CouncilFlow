"""CLI entrypoint for delegating work to non-controller models."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from councilflow.controller.delegation_orchestrator import (
    DelegationExecutionError,
    DelegationOrchestrator,
)
from councilflow.controller.host_context import detect_controller
from councilflow.models.roles import RoleName
from councilflow.providers.base import ProviderAdapter, ProviderError
from councilflow.providers.claude_code_cli import ClaudeCodeCliAdapter
from councilflow.providers.codex_cli import CodexCliAdapter
from councilflow.state.store import CouncilStateStore

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


def get_provider_adapter(model: str) -> ProviderAdapter:
    """Resolve a provider adapter for the requested model."""

    normalized = model.strip().lower()
    if normalized == "codex":
        return CodexCliAdapter()
    if normalized in {"claude", "claude-code"}:
        return ClaudeCodeCliAdapter()
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
    controller = detect_controller(config=config).controller.value
    target_model = (model or config.roles.for_role(role)).strip().lower()

    orchestrator = DelegationOrchestrator(
        store=store,
        participant_factory=get_provider_adapter,
    )
    try:
        result = orchestrator.run(
            role=role,
            controller=controller,
            target_model=target_model,
            objective=objective,
            task_summary=task_summary,
            constraints=list(constraint or []),
            relevant_files=list(relevant_file or []),
            inputs={"controller": controller, "configured_language": config.output_language},
            expected_output=expected_output,
        )
    except DelegationExecutionError as exc:
        typer.echo(
            json.dumps(
                {
                    "data": None,
                    "error": {
                        "message": str(exc),
                        "delegation_id": exc.delegation_id,
                        "handoff_path": exc.handoff_path,
                        "record_path": exc.record_path,
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise typer.Exit(code=1) from exc

    typer.echo(
        json.dumps(
            {
                "data": result.model_dump(mode="json"),
                "error": None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
