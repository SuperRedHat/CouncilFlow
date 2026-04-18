"""Helpers for building and persisting delegation handoff packages."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from councilflow.models.delegation import (
    ExecutionGuardrails,
    FixerInputSource,
    HandoffPackage,
    ReviewFinding,
    TesterPreflight,
    VerificationCommand,
)
from councilflow.models.roles import RoleName


def _coerce_verification_commands(
    verification_commands: list[VerificationCommand] | list[str] | None,
    inputs: dict[str, str],
) -> list[VerificationCommand]:
    """Normalize verification commands into structured command entries."""

    if verification_commands:
        normalized: list[VerificationCommand] = []
        for item in verification_commands:
            if isinstance(item, VerificationCommand):
                normalized.append(item)
            else:
                normalized.append(VerificationCommand(command=item))
        return normalized

    raw = inputs.get("verification_commands", "").strip()
    if not raw:
        return []

    if "&&" in raw:
        parts = [part.strip() for part in raw.split("&&") if part.strip()]
    else:
        parts = [part.strip() for part in raw.splitlines() if part.strip()]
    return [VerificationCommand(command=part) for part in parts]


def _infer_fixer_input_sources(required_artifacts: dict[str, str]) -> list[FixerInputSource]:
    """Derive fixer input sources from existing required-artifact labels."""

    sources: list[FixerInputSource] = []
    for label, artifact_path in required_artifacts.items():
        source_stage = label.split("_", 1)[0] if "_" in label else "upstream"
        sources.append(
            FixerInputSource(
                label=label,
                source_stage=source_stage,
                artifact_path=artifact_path,
            )
        )
    return sources


def _default_tester_preflight(
    role: RoleName,
    verification_commands: list[VerificationCommand],
    tester_preflight: TesterPreflight | None,
) -> TesterPreflight:
    """Provide a predictable tester preflight contract."""

    if tester_preflight is not None:
        return tester_preflight
    if role is not RoleName.TESTER or not verification_commands:
        return TesterPreflight()
    return TesterPreflight(
        status="pending",
        command_availability={item.command: "required" for item in verification_commands},
    )


def create_handoff_package(
    *,
    delegation_id: str,
    role: RoleName,
    objective: str,
    task_summary: str,
    constraints: list[str],
    relevant_files: list[str],
    inputs: dict[str, str],
    required_artifacts: dict[str, str],
    verification_commands: list[VerificationCommand] | list[str] | None = None,
    tester_preflight: TesterPreflight | None = None,
    review_findings: list[ReviewFinding] | None = None,
    fixer_input_sources: list[FixerInputSource] | None = None,
    execution_guardrails: ExecutionGuardrails | None = None,
    next_actions_on_success: list[str],
    next_actions_on_failure: list[str],
    expected_output: str,
) -> HandoffPackage:
    """Create a structured handoff package for delegated execution."""

    structured_commands = _coerce_verification_commands(verification_commands, inputs)
    return HandoffPackage(
        id=delegation_id,
        role=role.value,
        objective=objective,
        task_summary=task_summary,
        constraints=constraints,
        relevant_files=relevant_files,
        inputs=inputs,
        required_artifacts=required_artifacts,
        verification_commands=structured_commands,
        tester_preflight=_default_tester_preflight(role, structured_commands, tester_preflight),
        review_findings=list(review_findings or []),
        fixer_input_sources=list(
            fixer_input_sources or _infer_fixer_input_sources(required_artifacts)
        ),
        execution_guardrails=execution_guardrails or ExecutionGuardrails(),
        next_actions_on_success=next_actions_on_success,
        next_actions_on_failure=next_actions_on_failure,
        expected_output=expected_output,
    )


def save_handoff_package(package: HandoffPackage, path: Path) -> Path:
    """Persist a handoff package as YAML."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = package.model_dump(mode="json")
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def load_handoff_package(path: Path) -> HandoffPackage:
    """Load a persisted handoff package from YAML."""

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("Handoff package must deserialize to a mapping.")
    return HandoffPackage.model_validate(raw)


def build_delegation_contract(
    package: HandoffPackage,
    *,
    handoff_path: str,
    result_path: str | None = None,
) -> dict[str, Any]:
    """Build a machine-readable contract for project-* workflow integration."""

    return {
        "artifact_kind": "delegation_handoff",
        "command": "council delegate",
        "status": "delegated",
        "delegation_status": "completed",
        "via_sidecar": True,
        "handoff_path": handoff_path,
        "result_path": result_path,
        "handoff_schema": {
            "id": package.id,
            "role": package.role,
            "objective": package.objective,
            "task_summary": package.task_summary,
            "constraints": package.constraints,
            "relevant_files": package.relevant_files,
            "inputs": package.inputs,
            "required_artifacts": package.required_artifacts,
            "verification_commands": [
                item.model_dump(mode="json") for item in package.verification_commands
            ],
            "tester_preflight": package.tester_preflight.model_dump(mode="json"),
            "review_findings": [item.model_dump(mode="json") for item in package.review_findings],
            "fixer_input_sources": [
                item.model_dump(mode="json") for item in package.fixer_input_sources
            ],
            "execution_guardrails": package.execution_guardrails.model_dump(mode="json"),
            "next_actions_on_success": package.next_actions_on_success,
            "next_actions_on_failure": package.next_actions_on_failure,
            "expected_output": package.expected_output,
        },
        "stage_guidance": {
            "required_artifacts": package.required_artifacts,
            "verification_commands": [
                item.model_dump(mode="json") for item in package.verification_commands
            ],
            "tester_preflight": package.tester_preflight.model_dump(mode="json"),
            "review_findings": [item.model_dump(mode="json") for item in package.review_findings],
            "fixer_input_sources": [
                item.model_dump(mode="json") for item in package.fixer_input_sources
            ],
            "execution_guardrails": package.execution_guardrails.model_dump(mode="json"),
            "next_actions_on_success": package.next_actions_on_success,
            "next_actions_on_failure": package.next_actions_on_failure,
        },
        "consumption_rules": [
            "The workflow must read the handoff package explicitly from disk.",
            "The delegated model must not rely on hidden shared chat context.",
            "The result artifact should be treated as the authoritative delegated output.",
            "Required upstream artifacts must be read before the host enters the next stage.",
            (
                "The host should use the declared next-actions guidance instead of "
                "inventing its own stage transitions."
            ),
            (
                "Structured verification commands, tester preflight requirements, and "
                "review findings should be consumed from the contract instead of being "
                "reconstructed from free-form prose."
            ),
            (
                "Delegated stages must not create git commits or modify workflow state "
                "files unless the execution guardrails explicitly allow those actions."
            ),
            "Only local_execution allows the host workflow to continue locally.",
            (
                "If council delegate returns an error or missing artifacts, the host "
                "workflow must stop instead of silently falling back to local execution."
            ),
            (
                "Delegated stages must honor execution_guardrails.isolated_workspace: "
                "ordinary code tasks should execute inside the sidecar workspace instead "
                "of the host project root."
            ),
            (
                "Result changes must be declared through DelegationResult.workspace_manifest "
                "and only files matching execution_guardrails.import_manifest.writable_globs "
                "may be imported back into the host project."
            ),
        ],
    }
