from __future__ import annotations

from pathlib import Path

from councilflow.config.loader import build_default_config
from councilflow.controller.discussion_orchestrator import DiscussionOrchestrator
from councilflow.models.discussion import DiscussionRequest, ParticipantResponse
from councilflow.state.store import CouncilStateStore


class ScriptedParticipant:
    def __init__(self, responses: list[ParticipantResponse]) -> None:
        self._responses = responses
        self._index = 0

    def respond(self, request: DiscussionRequest) -> ParticipantResponse:
        response = self._responses[min(self._index, len(self._responses) - 1)]
        self._index += 1
        return response.model_copy(update={"model": request.participant})


def test_single_external_model_discussion_caps_rounds_at_five(tmp_path: Path) -> None:
    store = CouncilStateStore(tmp_path)
    orchestrator = DiscussionOrchestrator(
        store=store,
        config=build_default_config(),
        participant_factory=lambda _: ScriptedParticipant(
            [
                ParticipantResponse(
                    model="claude",
                    message=f"Round {index}",
                    key_options=[f"Option {index}"],
                    supports_current_direction=False,
                    has_new_information=True,
                )
                for index in range(1, 7)
            ]
        ),
    )

    summary = orchestrator.run(
        question="How should we split the architecture?",
        controller="codex",
        external_models=["claude"],
        max_rounds=9,
    )

    assert summary.rounds_completed == 5
    assert summary.ended_reason == "max_rounds_reached"
    assert summary.summary_path is not None
    assert (tmp_path / summary.summary_path).is_file()


def test_discussion_converges_early_and_persists_summary(tmp_path: Path) -> None:
    store = CouncilStateStore(tmp_path)
    participant = ScriptedParticipant(
        [
            ParticipantResponse(
                model="claude",
                message="The current direction is sound.",
                key_options=["Keep controller-first orchestration"],
                agreements=["Use controller-led synthesis"],
                recommended_decision="Proceed with the controller-first design.",
                next_step="Move into implementation planning.",
                supports_current_direction=True,
                has_new_information=False,
            )
        ]
    )
    orchestrator = DiscussionOrchestrator(
        store=store,
        config=build_default_config(),
        participant_factory=lambda _: participant,
    )

    summary = orchestrator.run(
        question="Should we keep the controller-first design?",
        controller="codex",
        external_models=["claude"],
        max_rounds=5,
    )

    assert summary.rounds_completed == 1
    assert summary.ended_reason == "converged"
    assert summary.agreements == ["Use controller-led synthesis"]
    assert summary.recommended_decision == "Proceed with the controller-first design."
    assert summary.next_step == "Move into implementation planning."
    assert summary.summary_path is not None
    summary_file = tmp_path / summary.summary_path
    assert summary_file.is_file()
    assert "Recommended Decision" in summary_file.read_text(encoding="utf-8")

