"""Prompt rendering helpers for delegated execution."""

from __future__ import annotations

import json

from councilflow.models.delegation import HandoffPackage
from councilflow.models.discussion import DiscussionRequest


def render_delegation_prompt(package: HandoffPackage) -> str:
    """Render a deterministic prompt from a handoff package."""

    constraints = "\n".join(f"- {item}" for item in package.constraints) or "- None"
    relevant_files = "\n".join(f"- {item}" for item in package.relevant_files) or "- None"
    inputs = "\n".join(f"- {key}: {value}" for key, value in package.inputs.items()) or "- None"
    return (
        f"You are the delegated {package.role}.\n\n"
        f"Objective:\n{package.objective}\n\n"
        f"Task Summary:\n{package.task_summary}\n\n"
        f"Constraints:\n{constraints}\n\n"
        f"Relevant Files:\n{relevant_files}\n\n"
        f"Inputs:\n{inputs}\n\n"
        f"Expected Output:\n{package.expected_output}\n"
    )


def render_discussion_prompt(request: DiscussionRequest) -> str:
    """Render a structured prompt for external discussion participants."""

    prior_turns = [
        {
            "round_number": turn.round_number,
            "speaker_model": turn.speaker_model,
            "message": turn.message,
            "agreements": turn.agreements,
            "disagreements": turn.disagreements,
            "open_questions": turn.open_questions,
        }
        for turn in request.prior_turns
    ]
    return (
        "You are participating in a controller-led discussion.\n\n"
        f"Controller: {request.controller}\n"
        f"Participant: {request.participant}\n"
        f"Round: {request.round_number}\n"
        f"Output Language: {request.output_language}\n\n"
        f"Question:\n{request.question}\n\n"
        "Prior Turns JSON:\n"
        f"{json.dumps(prior_turns, ensure_ascii=False, indent=2)}\n\n"
        "Return raw JSON only with this schema:\n"
        "{\n"
        '  "message": "string",\n'
        '  "key_options": ["string"],\n'
        '  "agreements": ["string"],\n'
        '  "disagreements": ["string"],\n'
        '  "open_questions": ["string"],\n'
        '  "recommended_decision": "string",\n'
        '  "next_step": "string",\n'
        '  "supports_current_direction": true,\n'
        '  "has_new_information": false\n'
        "}\n"
    )
