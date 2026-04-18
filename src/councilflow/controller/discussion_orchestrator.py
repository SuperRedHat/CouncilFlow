"""Discussion orchestration for controller-led multi-model collaboration."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
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
from councilflow.utils.logging import get_logger

_logger = get_logger(__name__)


class DiscussionParticipant(Protocol):
    """Minimal interface a discussion participant must implement."""

    def respond(self, request: DiscussionRequest) -> ParticipantResponse:
        """Generate the participant response for a discussion round."""


class UnavailableParticipantError(RuntimeError):
    """Raised when a requested discussion participant is not available."""

    def __init__(
        self,
        message: str,
        *,
        kind: str | None = None,
        error_kind: str | None = None,
    ) -> None:
        super().__init__(message)
        # Canonical field is `kind`, aligned with ProviderError.kind. The
        # legacy `error_kind` parameter is accepted to avoid breaking existing
        # callers (it is forwarded to `kind`) and a deprecation property keeps
        # read access working for at least one release cycle.
        self.kind: str | None = kind if kind is not None else error_kind

    @property
    def error_kind(self) -> str | None:
        import warnings

        warnings.warn(
            "UnavailableParticipantError.error_kind is deprecated; use .kind",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.kind


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
        min_rounds: int,
        controller_initial_position: str | None = None,
    ) -> DiscussionSummary:
        """Run the discussion loop, persist artifacts, and return the summary."""

        self.store.initialize()
        discussion_id = datetime.now(tz=UTC).strftime("disc_%Y%m%dT%H%M%S%fZ")
        discussion_dir = self.store.paths.discuss / discussion_id
        discussion_dir.mkdir(parents=True, exist_ok=True)
        record_path = discussion_dir / "record.json"
        import time as _time

        start_monotonic = _time.monotonic()
        _logger.info(
            "discussion.start id=%s controller=%s external_models=%s min_rounds=%d max_rounds=%d",
            discussion_id,
            controller,
            ",".join(external_models) or "<none>",
            min_rounds,
            max_rounds,
        )
        allowed_rounds = min(max_rounds, 5) if len(external_models) == 1 else max_rounds
        required_rounds = min(min_rounds, allowed_rounds)
        participants = [controller, *external_models]
        turns: list[DiscussionTurn] = []
        initial_position: str | None = None
        current_controller_position: str | None = None
        key_options: list[str] = []
        agreements: list[str] = []
        disagreements: list[str] = []
        open_questions: list[str] = []
        recommended_decisions: list[str] = []
        next_steps: list[str] = []
        ended_reason = "max_rounds_reached"
        controller_managed_locally = controller_initial_position is not None

        self.store.write_state(
            {
                "current_phase": "discussion",
                "current_controller": controller,
                "last_discussion_id": discussion_id,
            }
        )
        self._persist_record(
            record_path=record_path,
            discussion_id=discussion_id,
            controller=controller,
            question=question,
            participants=participants,
            status="running",
            initial_position=initial_position,
            current_controller_position=current_controller_position,
            required_rounds=required_rounds,
            allowed_rounds=allowed_rounds,
            ended_reason="in_progress",
            turns=turns,
        )

        try:
            controller_participant: DiscussionParticipant | None = None
            if controller_managed_locally:
                initial_position = controller_initial_position.strip()
                if not initial_position:
                    raise ValueError("controller_initial_position cannot be empty.")
                current_controller_position = initial_position
            else:
                controller_participant = self.participant_factory(controller)
                initial_response = self._respond(
                    participant=controller_participant,
                    request=DiscussionRequest(
                        discussion_id=discussion_id,
                        question=question,
                        controller=controller,
                        participant=controller,
                        round_number=0,
                        output_language=self.config.output_language,
                    ),
                    phase_label="controller_initial_position",
                )
                initial_position = initial_response.message
                current_controller_position = initial_position
                _extend_unique(key_options, initial_response.key_options)
                _extend_unique(agreements, initial_response.agreements)
                _extend_unique(disagreements, initial_response.disagreements)
                _extend_unique(open_questions, initial_response.open_questions)
                _append_if_present(recommended_decisions, initial_response.recommended_decision)
                _append_if_present(next_steps, initial_response.next_step)
            self._persist_record(
                record_path=record_path,
                discussion_id=discussion_id,
                controller=controller,
                question=question,
                participants=participants,
                status="running",
                initial_position=initial_position,
                current_controller_position=current_controller_position,
                required_rounds=required_rounds,
                allowed_rounds=allowed_rounds,
                ended_reason="in_progress",
                turns=turns,
            )

            for round_number in range(1, allowed_rounds + 1):
                round_responses: list[ParticipantResponse] = []
                for model in external_models:
                    participant = self.participant_factory(model)
                    response = self._respond(
                        participant=participant,
                        request=DiscussionRequest(
                            discussion_id=discussion_id,
                            question=question,
                            controller=controller,
                            participant=model,
                            round_number=round_number,
                            output_language=self.config.output_language,
                            initial_position=initial_position,
                            current_controller_position=current_controller_position,
                            prior_turns=turns,
                        ),
                        phase_label=f"participant_round_{round_number}",
                    )
                    round_responses.append(response)
                    turns.append(
                        DiscussionTurn(
                            round_number=round_number,
                            speaker_model=response.model,
                            speaker_role="participant",
                            message=response.message,
                            key_options=response.key_options,
                            agreements=response.agreements,
                            disagreements=response.disagreements,
                            open_questions=response.open_questions,
                            responds_to_models=[controller],
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

                if not controller_managed_locally and controller_participant is not None:
                    controller_response = self._respond(
                        participant=controller_participant,
                        request=DiscussionRequest(
                            discussion_id=discussion_id,
                            question=question,
                            controller=controller,
                            participant=controller,
                            round_number=round_number,
                            output_language=self.config.output_language,
                            initial_position=initial_position,
                            current_controller_position=current_controller_position,
                            prior_turns=turns,
                        ),
                        phase_label=f"controller_round_{round_number}",
                    )
                    round_responses.append(controller_response)
                    turns.append(
                        DiscussionTurn(
                            round_number=round_number,
                            speaker_model=controller,
                            speaker_role="controller",
                            message=controller_response.message,
                            key_options=controller_response.key_options,
                            agreements=controller_response.agreements,
                            disagreements=controller_response.disagreements,
                            open_questions=controller_response.open_questions,
                            responds_to_models=external_models,
                            introduced_new_info=controller_response.has_new_information,
                            supports_current_direction=controller_response.supports_current_direction,
                        )
                    )
                    current_controller_position = controller_response.message
                    _extend_unique(key_options, controller_response.key_options)
                    _extend_unique(agreements, controller_response.agreements)
                    _extend_unique(disagreements, controller_response.disagreements)
                    _extend_unique(open_questions, controller_response.open_questions)
                    _append_if_present(
                        recommended_decisions,
                        controller_response.recommended_decision,
                    )
                    _append_if_present(next_steps, controller_response.next_step)
                self._persist_record(
                    record_path=record_path,
                    discussion_id=discussion_id,
                    controller=controller,
                    question=question,
                    participants=participants,
                    status="running",
                    initial_position=initial_position,
                    current_controller_position=current_controller_position,
                    required_rounds=required_rounds,
                    allowed_rounds=allowed_rounds,
                    ended_reason="in_progress",
                    turns=turns,
                )

                if round_number >= required_rounds and round_responses and _round_has_converged(
                    round_responses
                ):
                    ended_reason = "converged"
                    break
        except Exception as exc:
            self._persist_record(
                record_path=record_path,
                discussion_id=discussion_id,
                controller=controller,
                question=question,
                participants=participants,
                status="failed",
                initial_position=initial_position,
                current_controller_position=current_controller_position,
                required_rounds=required_rounds,
                allowed_rounds=allowed_rounds,
                ended_reason="failed",
                turns=turns,
                error_message=str(exc),
                error_kind=getattr(exc, "kind", None),
            )
            self.store.append_run_record(
                "discussion",
                {
                    "discussion_id": discussion_id,
                    "status": "failed",
                    "error": str(exc),
                    "error_kind": getattr(exc, "kind", None),
                },
            )
            self.store.write_state(
                {
                    "current_phase": "idle",
                    "current_controller": controller,
                    "last_discussion_id": discussion_id,
                    "last_error": str(exc),
                }
            )
            raise

        rounds_completed = max((turn.round_number for turn in turns), default=0)
        summary = DiscussionSummary(
            discussion_id=discussion_id,
            question=question,
            controller=controller,
            participants=participants,
            initial_position=initial_position,
            current_controller_position=current_controller_position,
            min_rounds=required_rounds,
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
            required_rounds=required_rounds,
            participants=participants,
            turns=turns,
            record_path=record_path,
        )
        self.store.append_run_record(
            "discussion",
            {
                "discussion_id": persisted_summary.discussion_id,
                "summary_path": persisted_summary.summary_path,
                "ended_reason": persisted_summary.ended_reason,
                "status": "completed",
            },
        )
        _logger.info(
            "discussion.completed id=%s rounds=%d ended_reason=%s elapsed=%.3fs",
            discussion_id,
            rounds_completed,
            ended_reason,
            _time.monotonic() - start_monotonic,
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

    @staticmethod
    def _respond(
        *,
        participant: DiscussionParticipant,
        request: DiscussionRequest,
        phase_label: str,
    ) -> ParticipantResponse:
        try:
            return participant.respond(request)
        except UnavailableParticipantError as exc:
            raise UnavailableParticipantError(
                "Discussion participant "
                f"'{request.participant}' failed during {phase_label}: {exc}",
                kind=exc.kind,
            ) from exc

    def _persist_summary(
        self,
        *,
        summary: DiscussionSummary,
        controller: str,
        allowed_rounds: int,
        required_rounds: int,
        participants: list[str],
        turns: list[DiscussionTurn],
        record_path: Path,
    ) -> DiscussionSummary:
        discussion_dir = record_path.parent
        summary_path = discussion_dir / "summary.md"
        relative_summary_path = str(summary_path.relative_to(self.store.paths.project_root))
        persisted_summary = summary.model_copy(update={"summary_path": relative_summary_path})
        record = DiscussionRecord(
            id=summary.discussion_id,
            controller=controller,
            question=summary.question,
            participants=participants,
            status="completed",
            initial_position=summary.initial_position,
            current_controller_position=summary.current_controller_position,
            min_rounds=required_rounds,
            max_rounds=allowed_rounds,
            completed_rounds=summary.rounds_completed,
            ended_reason=summary.ended_reason,
            turns=turns,
            summary_path=relative_summary_path,
        )
        self.store.save_json(record_path, record.model_dump(mode="json"))
        self.store.write_text(summary_path, render_discussion_summary(persisted_summary))
        return persisted_summary

    def _persist_record(
        self,
        *,
        record_path: Path,
        discussion_id: str,
        controller: str,
        question: str,
        participants: list[str],
        status: str,
        initial_position: str | None,
        current_controller_position: str | None,
        required_rounds: int,
        allowed_rounds: int,
        ended_reason: str,
        turns: list[DiscussionTurn],
        error_message: str | None = None,
        error_kind: str | None = None,
    ) -> None:
        completed_rounds = max((turn.round_number for turn in turns), default=0)
        record = DiscussionRecord(
            id=discussion_id,
            controller=controller,
            question=question,
            participants=participants,
            status=status,
            initial_position=initial_position,
            current_controller_position=current_controller_position,
            min_rounds=required_rounds,
            max_rounds=allowed_rounds,
            completed_rounds=completed_rounds,
            ended_reason=ended_reason,
            turns=turns,
            error_message=error_message,
            error_kind=error_kind,
        )
        self.store.save_json(record_path, record.model_dump(mode="json"))


def _append_if_present(target: list[str], value: str | None) -> None:
    if value:
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
