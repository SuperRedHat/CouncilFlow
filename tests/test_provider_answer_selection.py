"""Direct unit tests for TASK-119 streaming-answer extraction (finding 3) and
gemini runtime-notice stripping (finding 4).

These close the gap flagged in the 2026-06-10 audit: the codex/gemini event-based
answer-selection path (the actual fix for finding 3) shipped with no independent
test coverage, so a trailing plain-text CLI notice corrupting "the answer" could
regress silently.

Findings 1 (runtime_probe utf-8 decode) and 2 (process-tree termination) remain
exercised at integration level only: finding 1 needs a real CLI emitting
locale-invalid `--help` bytes, and finding 2's `_terminate_process` uses
`os.killpg` on POSIX (a raw in-process child without `start_new_session` would
target the test runner's own group) — neither is safely/deterministically
reproducible as a unit test.
"""

from __future__ import annotations

import json

from councilflow.providers.codex_cli import _select_codex_answer
from councilflow.providers.gemini_cli import (
    _ATTEMPT_NOTICE_RE,
    _select_gemini_answer,
    _strip_runtime_notices,
)


def _jsonl(*events: dict) -> list[str]:
    return [json.dumps(e) for e in events]


# --- codex --json answer selection (finding 3) ---


def test_codex_trailing_plaintext_notice_does_not_corrupt_answer() -> None:
    # The pre-fix "last line" heuristic would have returned the update banner.
    lines = _jsonl(
        {"msg": {"type": "agent_message", "message": "the real answer"}},
    ) + ["⚠ codex update available: run `npm i -g @openai/codex`"]
    assert _select_codex_answer(lines) == "the real answer"


def test_codex_last_agent_message_wins_over_earlier() -> None:
    lines = _jsonl(
        {"msg": {"type": "agent_message", "message": "draft"}},
        {"msg": {"type": "agent_message", "message": "final"}},
    )
    assert _select_codex_answer(lines) == "final"


def test_codex_item_assistant_message_shape() -> None:
    lines = _jsonl({"item": {"type": "assistant_message", "text": "via item"}})
    assert _select_codex_answer(lines) == "via item"


def test_codex_task_complete_last_agent_message() -> None:
    lines = _jsonl(
        {"msg": {"type": "task_complete", "last_agent_message": "done text"}}
    )
    assert _select_codex_answer(lines) == "done text"


def test_codex_falls_back_to_last_json_line_when_no_known_shape() -> None:
    lines = _jsonl({"msg": {"type": "token_count", "n": 5}}, {"unknown": "x"})
    assert _select_codex_answer(lines) == json.dumps({"unknown": "x"})


def test_codex_no_json_returns_last_nonempty_line() -> None:
    assert _select_codex_answer(["plain one", "plain two"]) == "plain two"
    assert _select_codex_answer([]) is None


# --- gemini stream-json answer selection (finding 3) ---


def test_gemini_trailing_notice_does_not_corrupt_response() -> None:
    lines = _jsonl({"response": "gemini answer"}) + ["Attempt 1 failed: rate limit"]
    assert _select_gemini_answer(lines) == "gemini answer"


def test_gemini_stream_content_events_last_text_wins() -> None:
    lines = _jsonl(
        {"type": "content", "text": "part 1"},
        {"type": "message", "text": "part 2 final"},
    )
    assert _select_gemini_answer(lines) == "part 2 final"


def test_gemini_falls_back_to_last_json_then_last_line() -> None:
    assert _select_gemini_answer(_jsonl({"foo": 1})) == json.dumps({"foo": 1})
    assert _select_gemini_answer(["raw text"]) == "raw text"
    assert _select_gemini_answer([]) is None


# --- gemini Attempt-notice anchoring (finding 4) ---


def test_attempt_notice_regex_matches_real_retry_lines() -> None:
    assert _ATTEMPT_NOTICE_RE.match("Attempt 1 failed: timeout")
    assert _ATTEMPT_NOTICE_RE.match("Attempt 2 of 3")


def test_attempt_notice_regex_preserves_legit_answer_lines() -> None:
    # The pre-fix bare startswith("Attempt ") deleted these legitimate lines.
    assert not _ATTEMPT_NOTICE_RE.match("Attempting a new database design")
    assert not _ATTEMPT_NOTICE_RE.match("Attempts should be idempotent")


def test_strip_runtime_notices_keeps_answer_drops_notices() -> None:
    raw = "\n".join(
        [
            "YOLO mode is enabled.",
            "Attempt 1 failed: rate limit",
            "Attempting a fresh approach to the schema",
            "Final recommendation: SQLite",
        ]
    )
    cleaned = _strip_runtime_notices(raw)
    assert "YOLO mode is enabled." not in cleaned
    assert "Attempt 1 failed" not in cleaned
    assert "Attempting a fresh approach to the schema" in cleaned
    assert "Final recommendation: SQLite" in cleaned
