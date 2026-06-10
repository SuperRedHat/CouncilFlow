"""Multi-mode convergence evaluator for multi-model discussions.

Given the current state of a discussion (question + completed turns +
round counters), decides whether the orchestrator should run another
round or converge. Supports three policies from
:class:`councilflow.models.config.DiscussionSettings`:

``strict_count`` (pre-0.1.3 behavior)
    Converge after ``completed_rounds >= min_rounds`` AND the most
    recent external turn signals no new info + supports the current
    direction. Escape valve: ``completed_rounds >= max_rounds``.

``semantic``
    Converge as soon as the most recent round introduces no new info
    AND no new disagreements, but only after the hard ``min_rounds``
    floor is met. ``max_rounds`` still caps.

``hybrid``
    Infer a coarse topic from the question text (architecture / review
    / clarification / other), look up ``min_rounds_by_topic`` for a
    per-topic hard floor, then fall back to ``semantic`` semantics.

Never calls an LLM. Reads only structured fields already present on
:class:`DiscussionTurn` (``introduced_new_info``,
``supports_current_direction``, ``disagreements``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from councilflow.models.config import DiscussionSettings
from councilflow.models.discussion import DiscussionTurn


@dataclass(frozen=True)
class ConvergenceDecision:
    """Result of one :func:`evaluate` call.

    Attributes
    ----------
    converged:
        ``True`` if the orchestrator should stop.
    reason:
        Short machine-readable reason (``"no_new_info"``,
        ``"max_rounds"``, ``"min_rounds_not_met"``, ``"no_external_participants"``,
        ``"external_agreed"``, etc.).
    next_action:
        ``"continue"`` / ``"converge"`` / ``"max_rounds_reached"``.
    """

    converged: bool
    reason: str
    next_action: Literal["continue", "converge", "max_rounds_reached"]


@dataclass(frozen=True)
class DiscussionState:
    """Minimal view of a discussion required to decide convergence."""

    question: str
    completed_rounds: int
    turns: list[DiscussionTurn]
    external_participant_count: int


# Topic inference: cheap keyword match, not an LLM call. Deliberately
# coarse; users who want finer control can extend via RFC.
_TOPIC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("architecture", ("architect", "design", "structure", "schema", "topology")),
    ("review", ("review", "critique", "feedback", "audit")),
    (
        "clarification",
        ("what is", "how does", "how do", "clarif", "explain", "definition", "meaning"),
    ),
)


def _infer_topic(question: str) -> str:
    """Return one of ``architecture`` / ``review`` / ``clarification`` / ``other``."""

    lower = question.lower()
    for topic, keywords in _TOPIC_RULES:
        if any(kw in lower for kw in keywords):
            return topic
    return "other"


def _last_external_turn(turns: list[DiscussionTurn]) -> DiscussionTurn | None:
    """Return the most recent turn from a non-controller participant."""

    for turn in reversed(turns):
        if turn.speaker_role == "participant":
            return turn
    return None


def _previous_disagreements_count(turns: list[DiscussionTurn]) -> int:
    """Sum of disagreements across all but the final external turn.

    Used to detect whether the latest round introduced new disagreements
    beyond what was already on the table.
    """

    externals = [t for t in turns if t.speaker_role == "participant"]
    if len(externals) < 2:
        return 0
    return sum(len(t.disagreements) for t in externals[:-1])


def _previous_rounds_disagreements_count(turns: list[DiscussionTurn]) -> int:
    """Sum of external disagreements in all rounds BEFORE the latest round.

    TASK-120 multi-participant baseline: with one external turn per round this
    matches the legacy all-but-last-turn count; with several participants per
    round it compares round-against-round instead of turn-against-turn.
    """

    if not turns:
        return 0
    max_round = max(t.round_number for t in turns)
    return sum(
        len(t.disagreements)
        for t in turns
        if t.speaker_role == "participant" and t.round_number < max_round
    )


def _latest_round_externals(turns: list[DiscussionTurn]) -> list[DiscussionTurn]:
    """Return external (non-controller) turns belonging to the highest round."""

    if not turns:
        return []
    max_round = max(t.round_number for t in turns)
    return [
        t for t in turns
        if t.round_number == max_round and t.speaker_role == "participant"
    ]


def _evaluate_strict_count(
    state: DiscussionState, config: DiscussionSettings
) -> ConvergenceDecision:
    """Pre-0.1.3 behavior: all external turns in latest round must agree.

    Matches the legacy ``_round_has_converged`` check in
    ``discussion_orchestrator``: every external participant's response
    must support the current direction, add no new information, and
    carry no disagreements or open questions.
    """

    if state.completed_rounds >= config.max_rounds:
        return ConvergenceDecision(
            converged=True,
            reason="max_rounds",
            next_action="max_rounds_reached",
        )
    if state.completed_rounds < config.min_rounds:
        return ConvergenceDecision(
            converged=False,
            reason="min_rounds_not_met",
            next_action="continue",
        )

    latest_externals = _latest_round_externals(state.turns)
    if not latest_externals:
        # Min rounds met but no external turn recorded yet; keep going.
        return ConvergenceDecision(
            converged=False,
            reason="awaiting_external_turn",
            next_action="continue",
        )

    all_agreed = all(
        t.supports_current_direction
        and not t.introduced_new_info
        and not t.disagreements
        and not t.open_questions
        for t in latest_externals
    )
    if all_agreed:
        return ConvergenceDecision(
            converged=True,
            reason="external_agreed",
            next_action="converge",
        )
    return ConvergenceDecision(
        converged=False,
        reason="external_not_yet_converged",
        next_action="continue",
    )


def _evaluate_semantic(
    state: DiscussionState, config: DiscussionSettings
) -> ConvergenceDecision:
    """Converge when the latest round adds no new info / disagreements."""

    if state.completed_rounds >= config.max_rounds:
        return ConvergenceDecision(
            converged=True,
            reason="max_rounds",
            next_action="max_rounds_reached",
        )
    # Hard floor: semantic never short-circuits before min_rounds.
    if state.completed_rounds < config.min_rounds:
        return ConvergenceDecision(
            converged=False,
            reason="min_rounds_not_met",
            next_action="continue",
        )

    # TASK-120: evaluate ALL external turns of the latest round, not just the
    # most recent speaker — with 2+ models, an earlier participant's new info
    # or disagreements in the same round must block convergence too.
    latest_externals = _latest_round_externals(state.turns)
    if not latest_externals:
        return ConvergenceDecision(
            converged=False,
            reason="awaiting_external_turn",
            next_action="continue",
        )

    # Semantic signal: no new info + no new disagreements beyond the baseline
    # accumulated in earlier rounds.
    prior_count = _previous_rounds_disagreements_count(state.turns)
    current_count = sum(len(t.disagreements) for t in latest_externals)
    no_new_disagreements = current_count <= prior_count
    introduced_new_info = any(t.introduced_new_info for t in latest_externals)
    if not introduced_new_info and no_new_disagreements:
        return ConvergenceDecision(
            converged=True,
            reason="no_new_info",
            next_action="converge",
        )
    return ConvergenceDecision(
        converged=False,
        reason="new_info_or_disagreements_present",
        next_action="continue",
    )


def _evaluate_hybrid(
    state: DiscussionState, config: DiscussionSettings
) -> ConvergenceDecision:
    """Per-topic min_rounds floor, then semantic check."""

    if state.completed_rounds >= config.max_rounds:
        return ConvergenceDecision(
            converged=True,
            reason="max_rounds",
            next_action="max_rounds_reached",
        )
    topic = _infer_topic(state.question)
    topic_floor = config.min_rounds  # default
    if config.min_rounds_by_topic:
        topic_floor = max(topic_floor, config.min_rounds_by_topic.get(topic, config.min_rounds))

    if state.completed_rounds < topic_floor:
        return ConvergenceDecision(
            converged=False,
            reason=f"topic_min_rounds_not_met:{topic}:{topic_floor}",
            next_action="continue",
        )
    # After topic-specific floor, semantic rules apply.
    return _evaluate_semantic(state, config)


def _normalize_state(
    state_or_args: (
        DiscussionState
        | tuple[str, int, list[DiscussionTurn], int]
    ),
) -> DiscussionState:
    if isinstance(state_or_args, DiscussionState):
        return state_or_args
    question, completed_rounds, turns, external_participant_count = state_or_args
    return DiscussionState(
        question=question,
        completed_rounds=completed_rounds,
        turns=list(turns),
        external_participant_count=external_participant_count,
    )


def evaluate(
    state: DiscussionState,
    config: DiscussionSettings,
) -> ConvergenceDecision:
    """Decide whether ``state`` is converged under the given ``config``.

    ``config.convergence_policy`` chooses the mode:

    - ``strict_count`` → :func:`_evaluate_strict_count`
    - ``semantic`` → :func:`_evaluate_semantic`
    - ``hybrid`` → :func:`_evaluate_hybrid`

    Short-circuit: when no external (non-controller) participants are
    present, converge immediately with reason
    ``"no_external_participants"``. This preserves the pre-0.1.3 behavior
    where dedup-empty discussions short-circuit; it applies regardless
    of policy.
    """

    state = _normalize_state(state)

    if state.external_participant_count == 0:
        return ConvergenceDecision(
            converged=True,
            reason="no_external_participants",
            next_action="converge",
        )

    policy = config.convergence_policy
    if policy == "strict_count":
        return _evaluate_strict_count(state, config)
    if policy == "semantic":
        return _evaluate_semantic(state, config)
    if policy == "hybrid":
        return _evaluate_hybrid(state, config)
    # Defensive: Pydantic Literal validation makes this unreachable.
    raise ValueError(f"Unsupported convergence_policy: {policy!r}")


# `_` shim only needed to silence unused-import when re is referenced in
# _infer_topic indirectly; keeping the module-level import fresh for
# future regex-based inference without dead-code tickets.
_ = re.compile


__all__ = [
    "ConvergenceDecision",
    "DiscussionState",
    "evaluate",
]
