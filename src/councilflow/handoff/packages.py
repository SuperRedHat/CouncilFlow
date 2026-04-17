"""Helpers for building and persisting delegation handoff packages."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from councilflow.models.delegation import HandoffPackage
from councilflow.models.roles import RoleName


def create_handoff_package(
    *,
    delegation_id: str,
    role: RoleName,
    objective: str,
    task_summary: str,
    constraints: list[str],
    relevant_files: list[str],
    inputs: dict[str, str],
    expected_output: str,
) -> HandoffPackage:
    """Create a structured handoff package for delegated execution."""

    return HandoffPackage(
        id=delegation_id,
        role=role.value,
        objective=objective,
        task_summary=task_summary,
        constraints=constraints,
        relevant_files=relevant_files,
        inputs=inputs,
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
            "expected_output": package.expected_output,
        },
        "consumption_rules": [
            "The workflow must read the handoff package explicitly from disk.",
            "The delegated model must not rely on hidden shared chat context.",
            "The result artifact should be treated as the authoritative delegated output.",
            "Only local_execution allows the host workflow to continue locally.",
            (
                "If council delegate returns an error or missing artifacts, the host "
                "workflow must stop instead of silently falling back to local execution."
            ),
        ],
    }
