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
    verification_commands = (
        "\n".join(
            f"- {item.command}" + (f" ({item.purpose})" if item.purpose else "")
            for item in package.verification_commands
        )
        or "- None"
    )
    tester_preflight = (
        "\n".join(
            [
                f"- status: {package.tester_preflight.status}",
                (
                    f"- command_availability: "
                    f"{json.dumps(
                        package.tester_preflight.command_availability,
                        ensure_ascii=False,
                    )}"
                ),
                (
                    f"- permission_requirements: "
                    f"{json.dumps(
                        package.tester_preflight.permission_requirements,
                        ensure_ascii=False,
                    )}"
                ),
                f"- permission_status: {package.tester_preflight.permission_status or 'unknown'}",
            ]
        )
        if package.tester_preflight.status != "not_requested"
        else "- None"
    )
    review_findings = (
        "\n".join(
            f"- [{item.severity}] {item.finding_id}: {item.title} | "
            f"files={', '.join(item.affected_files) or 'n/a'} | fix={item.required_fix}"
            for item in package.review_findings
        )
        or "- None"
    )
    fixer_input_sources = (
        "\n".join(
            f"- {item.label} ({item.source_stage}): {item.artifact_path}"
            for item in package.fixer_input_sources
        )
        or "- None"
    )
    isolation = package.execution_guardrails.isolated_workspace
    manifest = package.execution_guardrails.import_manifest
    execution_guardrails = "\n".join(
        [
            f"- allow_commit: {str(package.execution_guardrails.allow_commit).lower()}",
            (
                "- allow_workflow_state_write: "
                f"{str(package.execution_guardrails.allow_workflow_state_write).lower()}"
            ),
            (
                f"- writable_paths: "
                f"{json.dumps(package.execution_guardrails.writable_paths, ensure_ascii=False)}"
            ),
            (
                f"- protected_paths: "
                f"{json.dumps(package.execution_guardrails.protected_paths, ensure_ascii=False)}"
            ),
            f"- isolated_workspace.strategy: {isolation.strategy}",
            (
                f"- isolated_workspace.include_patterns: "
                f"{json.dumps(isolation.include_patterns, ensure_ascii=False)}"
            ),
            (
                f"- isolated_workspace.exclude_patterns: "
                f"{json.dumps(isolation.exclude_patterns, ensure_ascii=False)}"
            ),
            f"- isolated_workspace.workspace_path: {isolation.workspace_path or 'auto'}",
            (
                f"- import_manifest.writable_globs: "
                f"{json.dumps(manifest.writable_globs, ensure_ascii=False)}"
            ),
            (
                f"- import_manifest.readonly_artifact_paths: "
                f"{json.dumps(manifest.readonly_artifact_paths, ensure_ascii=False)}"
            ),
            f"- import_manifest.max_file_count: {manifest.max_file_count}",
            f"- import_manifest.max_total_bytes: {manifest.max_total_bytes}",
        ]
    )
    required_artifacts = (
        "\n".join(f"- {key}: {value}" for key, value in package.required_artifacts.items())
        or "- None"
    )
    next_actions_on_success = (
        "\n".join(f"- {item}" for item in package.next_actions_on_success) or "- None"
    )
    next_actions_on_failure = (
        "\n".join(f"- {item}" for item in package.next_actions_on_failure) or "- None"
    )
    return (
        f"You are the delegated {package.role}.\n\n"
        f"Objective:\n{package.objective}\n\n"
        f"Task Summary:\n{package.task_summary}\n\n"
        f"Constraints:\n{constraints}\n\n"
        f"Relevant Files:\n{relevant_files}\n\n"
        f"Inputs:\n{inputs}\n\n"
        f"Verification Commands:\n{verification_commands}\n\n"
        f"Tester Preflight Contract:\n{tester_preflight}\n\n"
        "If the tester preflight status is not passed, do not attempt verification commands. "
        "Report the blocked state instead.\n\n"
        f"Review Findings:\n{review_findings}\n\n"
        f"Fixer Input Sources:\n{fixer_input_sources}\n\n"
        f"Execution Guardrails:\n{execution_guardrails}\n\n"
        f"Required Upstream Artifacts:\n{required_artifacts}\n\n"
        f"Next Actions On Success:\n{next_actions_on_success}\n\n"
        f"Next Actions On Failure:\n{next_actions_on_failure}\n\n"
        f"Expected Output:\n{package.expected_output}\n"
    )


def render_discussion_prompt(request: DiscussionRequest) -> str:
    """Render a structured prompt for external discussion participants.

    Prior turns are sent in full to every participant each round. An earlier
    TASK-123 "compaction" that truncated earlier-round messages to 240 chars was
    reverted in v0.2.1: a real A/B (docs/token-report-2026-06-10.md) showed it
    measurably degraded answer quality when early-round operational detail lived
    only in prose, and the token savings did not justify that loss.
    """

    prior_turns = [
        {
            "round_number": turn.round_number,
            "speaker_model": turn.speaker_model,
            "speaker_role": turn.speaker_role,
            "message": turn.message,
            "agreements": turn.agreements,
            "disagreements": turn.disagreements,
            "open_questions": turn.open_questions,
            "responds_to_models": turn.responds_to_models,
        }
        for turn in request.prior_turns
    ]
    if request.participant == request.controller and request.round_number == 0:
        return (
            "You are the controller in a structured multi-model discussion.\n\n"
            f"Controller: {request.controller}\n"
            f"Output Language: {request.output_language}\n\n"
            f"Question:\n{request.question}\n\n"
            "Produce the controller's initial position before any external critique.\n"
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
            '  "has_new_information": true\n'
            "}\n"
        )
    if request.participant == request.controller:
        return (
            "You are the controller in a structured multi-model discussion.\n\n"
            f"Controller: {request.controller}\n"
            f"Round: {request.round_number}\n"
            f"Output Language: {request.output_language}\n\n"
            f"Question:\n{request.question}\n\n"
            f"Initial Position:\n{request.initial_position or '-'}\n\n"
            f"Current Controller Position:\n{request.current_controller_position or '-'}\n\n"
            "Prior Turns JSON:\n"
            f"{json.dumps(prior_turns, ensure_ascii=False, indent=2)}\n\n"
            "Review the external critique, then respond as the controller. Update or defend the "
            "controller position and return raw JSON only with this schema:\n"
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
    return (
        "You are participating in a controller-led discussion.\n\n"
        f"Controller: {request.controller}\n"
        f"Participant: {request.participant}\n"
        f"Round: {request.round_number}\n"
        f"Output Language: {request.output_language}\n\n"
        f"Question:\n{request.question}\n\n"
        f"Initial Controller Position:\n{request.initial_position or '-'}\n\n"
        f"Current Controller Position:\n{request.current_controller_position or '-'}\n\n"
        "Prior Turns JSON:\n"
        f"{json.dumps(prior_turns, ensure_ascii=False, indent=2)}\n\n"
        "Comment on the controller position rather than starting from zero. Support, critique, "
        "refine, or challenge it as needed.\n\n"
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
