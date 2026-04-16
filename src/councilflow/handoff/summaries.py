"""Render discussion summaries into Markdown artifacts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from councilflow.models.discussion import DiscussionSummary


def render_discussion_summary(summary: DiscussionSummary) -> str:
    """Render a structured discussion summary as Markdown."""

    sections = [
        f"# Discussion {summary.discussion_id}",
        "",
        f"- Question: {summary.question}",
        f"- Controller: {summary.controller}",
        f"- Participants: {', '.join(summary.participants)}",
        f"- Rounds Completed: {summary.rounds_completed}",
        f"- Ended Reason: {summary.ended_reason}",
        "",
        "## Key Options",
        _render_list(summary.key_options),
        "",
        "## Agreements",
        _render_list(summary.agreements),
        "",
        "## Disagreements",
        _render_list(summary.disagreements),
        "",
        "## Recommended Decision",
        summary.recommended_decision,
        "",
        "## Open Questions",
        _render_list(summary.open_questions),
        "",
        "## Next Step",
        summary.next_step,
        "",
    ]
    return "\n".join(sections)


def build_discussion_contract(summary: DiscussionSummary) -> dict[str, Any]:
    """Build a machine-readable discussion contract for project-* workflows."""

    return {
        "artifact_kind": "discussion_summary",
        "command": "council discuss",
        "summary_path": summary.summary_path,
        "question": summary.question,
        "participants": summary.participants,
        "recommended_decision": summary.recommended_decision,
        "open_questions": summary.open_questions,
        "next_step": summary.next_step,
        "consumption_rules": [
            (
                "Embedded discuss flows must read the summary artifact instead of "
                "hidden conversation state."
            ),
            "The controller remains responsible for final synthesis and workflow continuation.",
            "If summary_path is missing, the workflow must treat the discussion as incomplete.",
        ],
    }


def _render_list(items: Sequence[str]) -> str:
    if not items:
        return "- None"
    return "\n".join(f"- {item}" for item in items)
