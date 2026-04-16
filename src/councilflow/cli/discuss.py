"""CLI entrypoint for multi-model discussion orchestration."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from councilflow.controller.discussion_orchestrator import (
    DiscussionOrchestrator,
    UnavailableParticipantError,
)
from councilflow.controller.host_context import detect_controller
from councilflow.controller.routing import resolve_discuss_models
from councilflow.models.discussion import DiscussionRequest, ParticipantResponse
from councilflow.state.store import CouncilStateStore

DEFAULT_PROJECT_ROOT = Path(".")
QUESTION_ARGUMENT = typer.Argument(..., help="Question to discuss across models.")
MODELS_OPTION = typer.Option(
    ...,
    "--models",
    help="Comma-separated non-controller models to invite into the discussion.",
)
MAX_ROUNDS_OPTION = typer.Option(
    5,
    "--max-rounds",
    min=1,
    help="Maximum discussion rounds before the controller forces convergence.",
)
PROJECT_ROOT_OPTION = typer.Option(
    DEFAULT_PROJECT_ROOT,
    "--project-root",
    resolve_path=True,
    file_okay=False,
    dir_okay=True,
    help="Project root used to resolve the .council local state directory.",
)


class UnavailableParticipant:
    """Placeholder participant used until provider adapters are wired in."""

    def __init__(self, model: str) -> None:
        self.model = model

    def respond(self, request: DiscussionRequest) -> ParticipantResponse:
        raise UnavailableParticipantError(
            f"No discussion participant is registered for model '{self.model}'. "
            "Wire a provider adapter before running real cross-model discussions."
        )


def get_participant(model: str) -> UnavailableParticipant:
    """Resolve a participant implementation for a model name."""

    return UnavailableParticipant(model)


def discuss(
    question: str = QUESTION_ARGUMENT,
    models: str = MODELS_OPTION,
    max_rounds: int = MAX_ROUNDS_OPTION,
    project_root: Path = PROJECT_ROOT_OPTION,
) -> None:
    """Run a structured multi-model discussion and persist its artifacts locally."""

    store = CouncilStateStore(project_root)
    store.initialize()
    config = store.load_config()
    controller = detect_controller(config=config).controller
    requested_models = [item for item in models.split(",") if item.strip()]
    resolution = resolve_discuss_models(requested_models, controller)

    if not resolution.requires_sidecar:
        payload = {
            "data": {
                "question": question,
                "participants": [controller.value],
                "requested_models": resolution.requested_models,
                "external_models": resolution.external_models,
                "ignored_models": resolution.ignored_models,
                "warning": resolution.warning,
                "rounds_completed": 0,
            },
            "error": None,
        }
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    orchestrator = DiscussionOrchestrator(
        store=store,
        config=config,
        participant_factory=get_participant,
    )
    try:
        summary = orchestrator.run(
            question=question,
            controller=controller.value,
            external_models=resolution.external_models,
            max_rounds=max_rounds,
        )
    except UnavailableParticipantError as exc:
        typer.echo(
            json.dumps(
                {
                    "data": None,
                    "error": {
                        "message": str(exc),
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
                "data": summary.model_dump(mode="json"),
                "error": None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
