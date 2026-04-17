from __future__ import annotations

from pathlib import Path

from councilflow.config.loader import build_default_config
from councilflow.controller.discussion_orchestrator import DiscussionOrchestrator
from councilflow.models.discussion import (
    DiscussionRecord,
    DiscussionRequest,
    DiscussionTurn,
    ParticipantResponse,
)
from councilflow.state.store import CouncilStateStore


class ScriptedParticipant:
    def __init__(self, responses: list[ParticipantResponse]) -> None:
        self._responses = responses
        self._index = 0

    def respond(self, request: DiscussionRequest) -> ParticipantResponse:
        response = self._responses[min(self._index, len(self._responses) - 1)]
        self._index += 1
        return response.model_copy(update={"model": request.participant})


class ScriptedFactory:
    def __init__(self, scripted_responses: dict[str, list[ParticipantResponse]]) -> None:
        self._participants = {
            model: ScriptedParticipant(responses)
            for model, responses in scripted_responses.items()
        }

    def __call__(self, model: str) -> ScriptedParticipant:
        return self._participants[model]


def test_single_external_model_discussion_caps_rounds_at_five(tmp_path: Path) -> None:
    store = CouncilStateStore(tmp_path)
    factory = ScriptedFactory(
        {
            "codex": [
                ParticipantResponse(
                    model="codex",
                    message="Initial controller position",
                    supports_current_direction=False,
                    has_new_information=True,
                )
            ]
            + [
                ParticipantResponse(
                    model="codex",
                    message=f"Controller round {index}",
                    supports_current_direction=False,
                    has_new_information=True,
                )
                for index in range(1, 7)
            ],
            "claude": [
                ParticipantResponse(
                    model="claude",
                    message=f"Round {index}",
                    key_options=[f"Option {index}"],
                    supports_current_direction=False,
                    has_new_information=True,
                )
                for index in range(1, 7)
            ],
        }
    )
    orchestrator = DiscussionOrchestrator(
        store=store,
        config=build_default_config(),
        participant_factory=factory,
    )

    summary = orchestrator.run(
        question="How should we split the architecture?",
        controller="codex",
        external_models=["claude"],
        max_rounds=9,
        min_rounds=2,
    )

    assert summary.rounds_completed == 5
    assert summary.ended_reason == "max_rounds_reached"
    assert summary.min_rounds == 2
    assert summary.initial_position == "Initial controller position"
    assert summary.current_controller_position == "Controller round 5"
    assert summary.summary_path is not None
    assert (tmp_path / summary.summary_path).is_file()


def test_discussion_waits_for_min_rounds_before_converging(tmp_path: Path) -> None:
    store = CouncilStateStore(tmp_path)
    factory = ScriptedFactory(
        {
            "codex": [
                ParticipantResponse(
                    model="codex",
                    message="Start with the controller-first design and validate it.",
                    key_options=["Keep controller-led synthesis"],
                    recommended_decision="Start from the controller-first proposal.",
                    next_step="Collect external critique before finalizing.",
                    supports_current_direction=False,
                    has_new_information=True,
                ),
                ParticipantResponse(
                    model="codex",
                    message="Refined the proposal after the first critique.",
                    key_options=["Keep controller-led synthesis"],
                    agreements=["Use controller-led synthesis"],
                    recommended_decision="Continue refining after external feedback.",
                    next_step="Run one more round to confirm convergence.",
                    supports_current_direction=False,
                    has_new_information=True,
                ),
                ParticipantResponse(
                    model="codex",
                    message="The refined direction is now stable.",
                    key_options=["Keep controller-led synthesis"],
                    agreements=["Use controller-led synthesis"],
                    recommended_decision="Proceed with the controller-first design.",
                    next_step="Move into implementation planning.",
                    supports_current_direction=True,
                    has_new_information=False,
                ),
            ],
            "claude": [
                ParticipantResponse(
                    model="claude",
                    message="The current direction is sound.",
                    key_options=["Keep controller-first orchestration"],
                    agreements=["Use controller-led synthesis"],
                    recommended_decision="Proceed with the controller-first design.",
                    next_step="Move into implementation planning.",
                    supports_current_direction=True,
                    has_new_information=False,
                ),
                ParticipantResponse(
                    model="claude",
                    message="The refined direction still looks good.",
                    key_options=["Keep controller-first orchestration"],
                    agreements=["Use controller-led synthesis"],
                    recommended_decision="Proceed with the controller-first design.",
                    next_step="Move into implementation planning.",
                    supports_current_direction=True,
                    has_new_information=False,
                ),
            ],
        }
    )
    orchestrator = DiscussionOrchestrator(
        store=store,
        config=build_default_config(),
        participant_factory=factory,
    )

    summary = orchestrator.run(
        question="Should we keep the controller-first design?",
        controller="codex",
        external_models=["claude"],
        max_rounds=5,
        min_rounds=2,
    )

    assert summary.rounds_completed == 2
    assert summary.ended_reason == "converged"
    assert summary.min_rounds == 2
    assert summary.initial_position == "Start with the controller-first design and validate it."
    assert summary.current_controller_position == "The refined direction is now stable."
    assert summary.agreements == ["Use controller-led synthesis"]
    assert summary.recommended_decision == "Proceed with the controller-first design."
    assert summary.next_step == "Move into implementation planning."
    assert summary.summary_path is not None
    summary_file = tmp_path / summary.summary_path
    assert summary_file.is_file()
    summary_text = summary_file.read_text(encoding="utf-8")
    assert "Initial Position" in summary_text
    assert "Current Controller Position" in summary_text
    assert "Recommended Decision" in summary_file.read_text(encoding="utf-8")


def test_discussion_models_support_controller_positions_and_round_trip_turns() -> None:
    record = DiscussionRecord(
        id="disc_test",
        controller="codex",
        question="Should the controller expose an initial position?",
        participants=["codex", "claude"],
        status="completed",
        initial_position="Start from a controller-led proposal before asking for critique.",
        current_controller_position="The controller updated the proposal after external feedback.",
        min_rounds=2,
        max_rounds=5,
        completed_rounds=2,
        ended_reason="converged",
        turns=[
            DiscussionTurn(
                round_number=1,
                speaker_model="claude",
                speaker_role="participant",
                message="The initial position is good but needs clearer risks.",
                responds_to_models=["codex"],
                introduced_new_info=True,
                supports_current_direction=False,
            ),
            DiscussionTurn(
                round_number=2,
                speaker_model="codex",
                speaker_role="controller",
                message="Updated the position to include the missing risks.",
                responds_to_models=["claude"],
                introduced_new_info=True,
                supports_current_direction=True,
            ),
        ],
    )

    payload = record.model_dump(mode="json")

    assert payload["initial_position"].startswith("Start from a controller-led proposal")
    assert payload["current_controller_position"].startswith("The controller updated")
    assert payload["min_rounds"] == 2
    assert payload["turns"][1]["speaker_role"] == "controller"
    assert payload["turns"][1]["responds_to_models"] == ["claude"]
