"""Discussion orchestration for controller-led multi-model collaboration."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Protocol

from councilflow.config.schema import CouncilConfig
from councilflow.handoff.summaries import render_discussion_summary
from councilflow.models.discussion import (
    DiscussionRecord,
    DiscussionRequest,
    DiscussionSummary,
    DiscussionTurn,
    ParticipantResponse,
)
from councilflow.state.store import CouncilStateStore


class DiscussionParticipant(Protocol):
    """Minimal interface a discussion participant must implement."""

    def respond(self, request: DiscussionRequest) -> ParticipantResponse:
        """Generate the participant response for a discussion round."""


class UnavailableParticipantError(RuntimeError):
    """Raised when a requested discussion participant is not available."""


class DiscussionOrchestrator:
    """Coordinate controller-led discussion rounds and persist the outcome."""

    def __init__(
        self,
        store: CouncilStateStore,
        config: CouncilConfig,
        participant_factory: Callable[[str], DiscussionParticipant],
    ) -> None:
        self.store = store
        self.config = config
        self.participant_factory = participant_factory

    def run(
        self,
        *,
        question: str,
        controller: str,
        external_models: list[str],
        max_rounds: int,
    ) -> DiscussionSummary:
        """Run the discussion loop, persist artifacts, and return the summary."""

        self.store.initialize()
        discussion_id = datetime.now(tz=UTC).strftime("disc_%Y%m%dT%H%M%S%fZ")
        allowed_rounds = min(max_rounds, 5) if len(external_models) == 1 else max_rounds
        participants = [controller, *external_models]
        turns: list[DiscussionTurn] = []
        key_options: list[str] = []
        agreements: list[str] = []
        disagreements: list[str] = []
        open_questions: list[str] = []
        recommended_decisions: list[str] = []
        next_steps: list[str] = []
        ended_reason = "max_rounds_reached"

        self.store.write_state(
            {
                "current_phase": "discussion",
                "current_controller": controller,
                "last_discussion_id": discussion_id,
            }
        )

        for round_number in range(1, allowed_rounds + 1):
            round_responses: list[ParticipantResponse] = []
            for model in external_models:
                participant = self.participant_factory(model)
                response = participant.respond(
                    DiscussionRequest(
                        discussion_id=discussion_id,
                        question=question,
                        controller=controller,
                        participant=model,
                        round_number=round_number,
                        output_language=self.config.output_language,
                        prior_turns=turns,
                    )
                )
                round_responses.append(response)
                turns.append(
                    DiscussionTurn(
                        round_number=round_number,
                        speaker_model=response.model,
                        message=response.message,
                        key_options=response.key_options,
                        agreements=response.agreements,
                        disagreements=response.disagreements,
                        open_questions=response.open_questions,
                        introduced_new_info=response.has_new_information,
                        supports_current_direction=response.supports_current_direction,
                    )
                )
                _extend_unique(key_options, response.key_options)
                _extend_unique(agreements, response.agreements)
                _extend_unique(disagreements, response.disagreements)
                _extend_unique(open_questions, response.open_questions)
                _append_if_present(recommended_decisions, response.recommended_decision)
                _append_if_present(next_steps, response.next_step)

            if round_responses and _round_has_converged(round_responses):
                ended_reason = "converged"
                break

        rounds_completed = max((turn.round_number for turn in turns), default=0)
        summary = DiscussionSummary(
            discussion_id=discussion_id,
            question=question,
            controller=controller,
            participants=participants,
            rounds_completed=rounds_completed,
            ended_reason=ended_reason,
            key_options=key_options,
            agreements=agreements,
            disagreements=disagreements,
            recommended_decision=_final_value(
                recommended_decisions,
                "Controller should continue with the strongest supported direction.",
            ),
            open_questions=open_questions,
            next_step=_final_value(
                next_steps,
                "Controller should continue the workflow using this discussion summary.",
            ),
        )
        persisted_summary = self._persist_summary(
            summary=summary,
            controller=controller,
            allowed_rounds=allowed_rounds,
            participants=participants,
            turns=turns,
        )
        self.store.append_run_record(
            "discussion",
            {
                "discussion_id": persisted_summary.discussion_id,
                "summary_path": persisted_summary.summary_path,
                "ended_reason": persisted_summary.ended_reason,
            },
        )
        self.store.write_state(
            {
                "current_phase": "idle",
                "current_controller": controller,
                "last_discussion_id": discussion_id,
                "last_summary_path": persisted_summary.summary_path,
            }
        )
        return persisted_summary

    def _persist_summary(
        self,
        *,
        summary: DiscussionSummary,
        controller: str,
        allowed_rounds: int,
        participants: list[str],
        turns: list[DiscussionTurn],
    ) -> DiscussionSummary:
        discussion_dir = self.store.paths.discuss / summary.discussion_id
        discussion_dir.mkdir(parents=True, exist_ok=True)
        summary_path = discussion_dir / "summary.md"
        record_path = discussion_dir / "record.json"
        relative_summary_path = str(summary_path.relative_to(self.store.paths.project_root))
        persisted_summary = summary.model_copy(update={"summary_path": relative_summary_path})
        record = DiscussionRecord(
            id=summary.discussion_id,
            controller=controller,
            question=summary.question,
            participants=participants,
            status="completed",
            max_rounds=allowed_rounds,
            completed_rounds=summary.rounds_completed,
            ended_reason=summary.ended_reason,
            turns=turns,
            summary_path=relative_summary_path,
        )
        self.store.save_json(record_path, record.model_dump(mode="json"))
        self.store.write_text(summary_path, render_discussion_summary(persisted_summary))
        return persisted_summary


def _append_if_present(target: list[str], value: str | None) -> None:
    if value and value not in target:
        target.append(value)


def _extend_unique(target: list[str], values: Iterable[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _final_value(values: list[str], fallback: str) -> str:
    return values[-1] if values else fallback


def _round_has_converged(responses: list[ParticipantResponse]) -> bool:
    return all(
        response.supports_current_direction
        and not response.has_new_information
        and not response.disagreements
        and not response.open_questions
        for response in responses
    )
