"""Prior-turn fidelity for discussion prompts.

History: TASK-123 (0.2.1 dev) truncated earlier-round messages to a 240-char
head. A real A/B (docs/token-report-2026-06-10.md) measured that this dropped
early-round operational detail living only in prose and degraded round-3 answer
grounding, so the compaction was REVERTED before the 0.2.1 release. These tests
lock the full-fidelity contract so a lossy compaction cannot silently return.
"""

from __future__ import annotations

import json

from councilflow.handoff.prompts import render_discussion_prompt
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


def _prior_turns_payload(prompt: str) -> list[dict]:
    start = prompt.index("Prior Turns JSON:\n") + len("Prior Turns JSON:\n")
    # json.dumps(indent=2) never emits a blank line, so the first blank line
    # after the marker terminates the JSON block.
    end = prompt.index("\n\n", start)
    return json.loads(prompt[start:end])


def test_earlier_round_prose_is_sent_in_full() -> None:
    # The A/B's failure mode: operational nuance past char 240 of an earlier
    # round's message. Post-revert it must reach the participant verbatim.
    early_nuance = "RQ has no native dead-letter queue so we need a DLQ shim."
    long_old = ("headline position. " * 20) + early_nuance  # nuance past char 240
    assert long_old.index(early_nuance) > 240
    turns = [
        _turn(1, "codex", long_old, disagreements=["X"], open_questions=["Q1"]),
        _turn(2, "codex", "latest round message", agreements=["A"]),
    ]
    prompt = render_discussion_prompt(_request(turns))

    assert early_nuance in prompt
    assert "message_summary" not in prompt
    assert "…[truncated]" not in prompt
    # Structured fields still present alongside the full prose.
    assert '"disagreements"' in prompt
    assert '"open_questions"' in prompt
    assert "latest round message" in prompt


def test_prior_turns_json_parseable_with_message_field_per_turn() -> None:
    turns = [
        _turn(1, "codex", "m1"),
        _turn(2, "gemini", "m2"),
    ]
    payload = _prior_turns_payload(render_discussion_prompt(_request(turns)))
    assert isinstance(payload, list) and len(payload) == 2
    # Every turn carries its full message under the SAME key — no per-round
    # message/message_summary split.
    assert [t["message"] for t in payload] == ["m1", "m2"]
    assert all("message_summary" not in t for t in payload)
