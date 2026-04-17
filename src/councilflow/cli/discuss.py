"""CLI entrypoint for multi-model discussion orchestration."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from councilflow.controller.discussion_orchestrator import (
    DiscussionOrchestrator,
    DiscussionParticipant,
    UnavailableParticipantError,
)
from councilflow.controller.host_context import detect_controller
from councilflow.controller.routing import resolve_discuss_models, select_discuss_models
from councilflow.handoff.prompts import render_discussion_prompt
from councilflow.models.discussion import DiscussionRequest, ParticipantResponse
from councilflow.models.roles import normalize_model_name
from councilflow.providers.base import ProviderAdapter, ProviderError, ProviderRequest
from councilflow.providers.claude_code_cli import ClaudeCodeCliAdapter
from councilflow.providers.codex_cli import CodexCliAdapter
from councilflow.providers.gemini_cli import GeminiCliAdapter
from councilflow.state.store import CouncilStateStore
from councilflow.utils.lang import emit_console_text, emit_response, resolve_output_language

DEFAULT_PROJECT_ROOT = Path(".")
QUESTION_ARGUMENT = typer.Argument(..., help="Question to discuss across models.")
MODELS_OPTION = typer.Option(
    None,
    "--models",
    help=(
        "Comma-separated non-controller models to invite into the discussion. "
        "When omitted, CouncilFlow uses discussion.default_models from the "
        "project-local .council/config.yaml."
    ),
)
MAX_ROUNDS_OPTION = typer.Option(
    None,
    "--max-rounds",
    min=1,
    help=(
        "Maximum discussion rounds before the controller forces convergence. "
        "When omitted, CouncilFlow uses discussion.max_rounds from the "
        "project-local .council/config.yaml."
    ),
)
PROJECT_ROOT_OPTION = typer.Option(
    DEFAULT_PROJECT_ROOT,
    "--project-root",
    resolve_path=True,
    file_okay=False,
    dir_okay=True,
    help="Project root used to resolve the .council local state directory.",
)


class ProviderDiscussionParticipant:
    """Adapter that turns provider output into a structured discussion response."""

    def __init__(self, model: str, adapter: ProviderAdapter) -> None:
        self.model = model
        self.adapter = adapter

    def respond(self, request: DiscussionRequest) -> ParticipantResponse:
        prompt = render_discussion_prompt(request)
        try:
            response = self.adapter.ask(ProviderRequest(prompt=prompt))
        except ProviderError as exc:
            raise UnavailableParticipantError(str(exc)) from exc

        parsed = _parse_participant_payload(response.content)
        return ParticipantResponse(
            model=self.model,
            message=parsed["message"],
            key_options=parsed["key_options"],
            agreements=parsed["agreements"],
            disagreements=parsed["disagreements"],
            open_questions=parsed["open_questions"],
            recommended_decision=parsed["recommended_decision"],
            next_step=parsed["next_step"],
            supports_current_direction=parsed["supports_current_direction"],
            has_new_information=parsed["has_new_information"],
        )


def get_participant(model: str) -> DiscussionParticipant:
    """Resolve a participant implementation for a model name."""

    normalized = normalize_model_name(model)
    if normalized == "codex":
        return ProviderDiscussionParticipant(normalized, CodexCliAdapter())
    if normalized == "claude":
        return ProviderDiscussionParticipant("claude", ClaudeCodeCliAdapter())
    if normalized == "gemini":
        # Use original model name if it's a specific version (e.g., gemini-1.5-flash)
        specific_model = model if model.startswith("gemini-") and model != "gemini-cli" else None
        return ProviderDiscussionParticipant("gemini", GeminiCliAdapter(model=specific_model))
    raise UnavailableParticipantError(
        f"No discussion participant is registered for model '{model}'."
    )


def discuss(
    question: str = QUESTION_ARGUMENT,
    models: str | None = MODELS_OPTION,
    max_rounds: int | None = MAX_ROUNDS_OPTION,
    project_root: Path = PROJECT_ROOT_OPTION,
) -> None:
    """Run a structured multi-model discussion and persist its artifacts locally."""

    store = CouncilStateStore(project_root)
    store.initialize()
    config = store.load_config()
    output_language = resolve_output_language(config.output_language)
    controller = detect_controller(config=config).controller
    explicit_models = None
    if models is not None:
        explicit_models = [item for item in models.split(",") if item.strip()]
    requested_models, models_source = select_discuss_models(explicit_models, config)
    resolution = resolve_discuss_models(requested_models, controller)
    effective_max_rounds = max_rounds or config.discussion.max_rounds

    if not resolution.requires_sidecar:
        payload = {
            "question": question,
            "participants": [controller.value],
            "requested_models": resolution.requested_models,
            "external_models": resolution.external_models,
            "ignored_models": resolution.ignored_models,
            "warning": resolution.warning,
            "models_source": models_source,
            "configured_default_models": config.discussion.default_models,
            "effective_max_rounds": effective_max_rounds,
            "rounds_completed": 0,
        }
        emit_console_text(
            emit_response(
                data=payload,
                meta={
                    "command": "discuss",
                    "output_language": output_language,
                },
            )
        )
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
            max_rounds=effective_max_rounds,
        )
    except UnavailableParticipantError as exc:
        emit_console_text(
            emit_response(
                data=None,
                meta={
                    "command": "discuss",
                    "output_language": output_language,
                },
                error={
                    "message": str(exc),
                },
            )
        )
        raise typer.Exit(code=1) from exc

    emit_console_text(
        emit_response(
            data={
                **summary.model_dump(mode="json"),
                "models_source": models_source,
                "configured_default_models": config.discussion.default_models,
                "effective_max_rounds": effective_max_rounds,
            },
            meta={
                "command": "discuss",
                "output_language": output_language,
            },
        )
    )


def _parse_participant_payload(content: str) -> dict[str, object]:
    """Parse provider output into the structured discussion response schema."""

    parsed = _extract_json_object(content)
    if parsed is None:
        return {
            "message": content.strip(),
            "key_options": [],
            "agreements": [],
            "disagreements": [],
            "open_questions": [],
            "recommended_decision": content.strip().splitlines()[0] if content.strip() else None,
            "next_step": "Controller should review the participant response and continue.",
            "supports_current_direction": False,
            "has_new_information": True,
        }

    return {
        "message": str(parsed.get("message", "")).strip(),
        "key_options": _normalize_string_list(parsed.get("key_options")),
        "agreements": _normalize_string_list(parsed.get("agreements")),
        "disagreements": _normalize_string_list(parsed.get("disagreements")),
        "open_questions": _normalize_string_list(parsed.get("open_questions")),
        "recommended_decision": _normalize_optional_string(parsed.get("recommended_decision")),
        "next_step": _normalize_optional_string(parsed.get("next_step"))
        or "Controller should review the participant response and continue.",
        "supports_current_direction": bool(parsed.get("supports_current_direction", True)),
        "has_new_information": bool(parsed.get("has_new_information", False)),
    }


def _extract_json_object(content: str) -> dict[str, object] | None:
    stripped = content.strip()
    candidates = [stripped]
    if "```" in stripped:
        for chunk in stripped.split("```"):
            chunk = chunk.strip()
            if chunk.startswith("json"):
                candidates.append(chunk[4:].strip())
            elif chunk.startswith("{"):
                candidates.append(chunk)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and start < end:
        candidates.append(stripped[start : end + 1])

    for candidate in candidates:
        try:
            raw = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            return raw
    return None


def _normalize_optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            result.append(text)
    return result
