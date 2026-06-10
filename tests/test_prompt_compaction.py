"""TASK-123: discussion prompt compaction — size discipline without losing
the signals convergence and participants actually use."""

from __future__ import annotations

import json

from councilflow.handoff.prompts import (
    _EARLIER_ROUND_SUMMARY_CAP,
    _LATEST_ROUND_MESSAGE_CAP,
    render_discussion_prompt,
)
from councilflow.models.discussion import DiscussionRequest, DiscussionTurn


def _turn(round_num: int, speaker: str, message: str, **over) -> DiscussionTurn:
    return DiscussionTurn(
        round_number=round_num,
        speaker_model=speaker,
        speaker_role="participant",
        message=message,
        **over,
    )


def _request(turns: list[DiscussionTurn]) -> DiscussionRequest:
    return DiscussionRequest(
        discussion_id="disc_x",
        question="How should we proceed?",
        controller="claude",
        participant="codex",
        round_number=3,
        output_language="en",
        initial_position="ship it",
        current_controller_position="still ship it",
        prior_turns=turns,
    )


def test_earlier_rounds_keep_structured_positions_not_full_messages() -> None:
    long_old = "OLD-ROUND-PROSE " * 300  # ~4.8KB
    turns = [
        _turn(1, "codex", long_old, disagreements=["X"], open_questions=["Q1"]),
        _turn(2, "codex", "latest round message", agreements=["A"]),
    ]
    prompt = render_discussion_prompt(_request(turns))

    # Earlier round: full prose gone, structured positions preserved.
    assert long_old not in prompt
    assert '"disagreements": ["X"]' in prompt
    assert '"open_questions": ["Q1"]' in prompt
    assert "message_summary" in prompt
    # Latest round: full message present.
    assert "latest round message" in prompt
    assert '"agreements": ["A"]' in prompt


def test_latest_round_message_is_capped_but_marked() -> None:
    huge = "L" * (_LATEST_ROUND_MESSAGE_CAP + 5000)
    turns = [_turn(1, "codex", huge)]
    prompt = render_discussion_prompt(_request(turns))
    assert "…[truncated]" in prompt
    assert "L" * (_LATEST_ROUND_MESSAGE_CAP + 1) not in prompt


def test_prior_turns_json_is_compact_and_parseable() -> None:
    turns = [
        _turn(1, "codex", "m1"),
        _turn(2, "gemini", "m2"),
    ]
    prompt = render_discussion_prompt(_request(turns))
    start = prompt.index("Prior Turns JSON:\n") + len("Prior Turns JSON:\n")
    end = prompt.index("\n\n", start)
    payload = json.loads(prompt[start:end])
    assert isinstance(payload, list) and len(payload) == 2
    # no indent: the serialized block is a single line
    assert "\n" not in prompt[start:end]


def test_multi_round_growth_is_bounded() -> None:
    """The N-th round prompt must not re-carry every earlier round's prose."""

    prose = "ROUND-PROSE " * 200  # ~2.4KB per turn
    many = [
        _turn(r, speaker, prose)
        for r in range(1, 6)
        for speaker in ("codex", "gemini")
    ]
    prompt = render_discussion_prompt(_request(many))
    # 10 turns x 2.4KB = ~24KB of raw prose; compacted prompt carries the two
    # latest-round messages plus ~240B summaries for the rest.
    assert len(prompt) < 12_000
    assert prompt.count(_EARLIER_ROUND_SUMMARY_CAP * "X") == 0  # sanity: no filler
