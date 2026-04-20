"""Tests for the multi-mode convergence evaluator (TASK-080)."""

from __future__ import annotations

import pytest

from councilflow.controller.convergence_evaluator import (
    ConvergenceDecision,
    DiscussionState,
    evaluate,
)
from councilflow.models.config import DiscussionSettings
from councilflow.models.discussion import DiscussionTurn


def _ctrl_turn(round_num: int) -> DiscussionTurn:
    return DiscussionTurn(
        round_number=round_num,
        speaker_model="claude",
        speaker_role="controller",
        message="controller framing",
    )


def _ext_turn(
    round_num: int,
    *,
    speaker: str = "codex",
    introduced_new_info: bool = True,
    supports: bool = False,
    disagreements: list[str] | None = None,
) -> DiscussionTurn:
    return DiscussionTurn(
        round_number=round_num,
        speaker_model=speaker,
        speaker_role="participant",
        message="external",
        introduced_new_info=introduced_new_info,
        supports_current_direction=supports,
        disagreements=disagreements or [],
    )


def _settings(**overrides) -> DiscussionSettings:
    base = {"min_rounds": 1, "max_rounds": 5, "convergence_policy": "strict_count"}
    base.update(overrides)
    return DiscussionSettings.model_validate(base)


def test_short_circuit_when_no_external_participants() -> None:
    state = DiscussionState(
        question="any",
        completed_rounds=0,
        turns=[],
        external_participant_count=0,
    )
    d = evaluate(state, _settings())
    assert d.converged is True
    assert d.reason == "no_external_participants"
    assert d.next_action == "converge"


def test_short_circuit_overrides_policy() -> None:
    for policy in ("strict_count", "semantic", "hybrid"):
        state = DiscussionState("q", 0, [], 0)
        d = evaluate(state, _settings(convergence_policy=policy))
        assert d.converged and d.reason == "no_external_participants"


def test_strict_count_below_min_rounds_continues() -> None:
    state = DiscussionState("q", 0, [_ctrl_turn(1)], 1)
    d = evaluate(state, _settings(min_rounds=2))
    assert d.converged is False
    assert d.reason == "min_rounds_not_met"
    assert d.next_action == "continue"


def test_strict_count_max_rounds_reached() -> None:
    state = DiscussionState("q", 5, [_ctrl_turn(1), _ext_turn(1)], 1)
    d = evaluate(state, _settings(min_rounds=1, max_rounds=5))
    assert d.converged is True
    assert d.reason == "max_rounds"
    assert d.next_action == "max_rounds_reached"


def test_strict_count_converges_when_external_agrees() -> None:
    turns = [
        _ctrl_turn(1),
        _ext_turn(1, supports=True, introduced_new_info=False),
    ]
    state = DiscussionState("q", 1, turns, 1)
    d = evaluate(state, _settings(min_rounds=1))
    assert d.converged is True
    assert d.reason == "external_agreed"


def test_strict_count_continues_when_external_disagrees() -> None:
    turns = [_ctrl_turn(1), _ext_turn(1, supports=False, introduced_new_info=True)]
    state = DiscussionState("q", 1, turns, 1)
    d = evaluate(state, _settings(min_rounds=1))
    assert d.converged is False


def test_semantic_respects_min_rounds_floor() -> None:
    turns = [
        _ctrl_turn(1),
        _ext_turn(1, introduced_new_info=False, disagreements=[]),
    ]
    state = DiscussionState("q", 1, turns, 1)
    d = evaluate(state, _settings(min_rounds=2, convergence_policy="semantic"))
    assert d.converged is False
    assert d.reason == "min_rounds_not_met"


def test_semantic_converges_when_no_new_info() -> None:
    turns = [
        _ctrl_turn(1),
        _ext_turn(1, introduced_new_info=True, disagreements=["X"]),
        _ctrl_turn(2),
        _ext_turn(2, introduced_new_info=False, disagreements=["X"]),
    ]
    state = DiscussionState("q", 2, turns, 1)
    d = evaluate(state, _settings(min_rounds=1, convergence_policy="semantic"))
    assert d.converged is True
    assert d.reason == "no_new_info"


def test_semantic_does_not_converge_when_new_disagreements_added() -> None:
    turns = [
        _ctrl_turn(1),
        _ext_turn(1, introduced_new_info=True, disagreements=["X"]),
        _ctrl_turn(2),
        _ext_turn(2, introduced_new_info=False, disagreements=["X", "Y"]),
    ]
    state = DiscussionState("q", 2, turns, 1)
    d = evaluate(state, _settings(min_rounds=1, convergence_policy="semantic"))
    assert d.converged is False
    assert d.reason == "new_info_or_disagreements_present"


def test_semantic_max_rounds_still_caps() -> None:
    turns = [_ctrl_turn(1), _ext_turn(1, introduced_new_info=True)]
    state = DiscussionState("q", 5, turns, 1)
    d = evaluate(state, _settings(min_rounds=1, max_rounds=5, convergence_policy="semantic"))
    assert d.converged is True
    assert d.reason == "max_rounds"


def test_hybrid_architecture_topic_uses_specific_floor() -> None:
    turns = [
        _ctrl_turn(1),
        _ext_turn(1, introduced_new_info=False, disagreements=[]),
    ]
    state = DiscussionState("What architecture should we pick?", 1, turns, 1)
    d = evaluate(
        state,
        _settings(
            min_rounds=1,
            convergence_policy="hybrid",
            min_rounds_by_topic={"architecture": 2, "clarification": 1},
        ),
    )
    assert d.converged is False
    assert "architecture" in d.reason


def test_hybrid_clarification_topic_uses_lower_floor() -> None:
    turns = [
        _ctrl_turn(1),
        _ext_turn(1, introduced_new_info=False, disagreements=[]),
    ]
    state = DiscussionState("What is the delegation contract?", 1, turns, 1)
    d = evaluate(
        state,
        _settings(
            min_rounds=1,
            convergence_policy="hybrid",
            min_rounds_by_topic={"architecture": 2, "clarification": 1},
        ),
    )
    assert d.converged is True
    assert d.reason == "no_new_info"


def test_hybrid_other_topic_falls_back_to_default_min_rounds() -> None:
    turns = [_ctrl_turn(1), _ext_turn(1, introduced_new_info=False)]
    state = DiscussionState("random topic", 1, turns, 1)
    d = evaluate(
        state,
        _settings(
            min_rounds=1,
            convergence_policy="hybrid",
            min_rounds_by_topic={"architecture": 2},
        ),
    )
    assert d.converged is True


def test_hybrid_without_topic_map_behaves_like_semantic() -> None:
    turns = [_ctrl_turn(1), _ext_turn(1, introduced_new_info=False)]
    state = DiscussionState("q", 1, turns, 1)
    d = evaluate(
        state,
        _settings(
            min_rounds=1,
            convergence_policy="hybrid",
            min_rounds_by_topic=None,
        ),
    )
    assert d.converged is True
    assert d.reason == "no_new_info"


def test_evaluate_rejects_unknown_policy() -> None:
    settings = DiscussionSettings.model_validate({"convergence_policy": "strict_count"})
    object.__setattr__(settings, "convergence_policy", "unknown")
    state = DiscussionState("q", 1, [_ctrl_turn(1), _ext_turn(1)], 1)
    with pytest.raises(ValueError):
        evaluate(state, settings)


def test_decision_is_frozen() -> None:
    state = DiscussionState("q", 0, [], 0)
    d = evaluate(state, _settings())
    assert isinstance(d, ConvergenceDecision)
    with pytest.raises(Exception):  # noqa: B017  # frozen dataclass raises FrozenInstanceError
        d.converged = False  # type: ignore[misc]
