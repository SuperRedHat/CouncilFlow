"""Helpers for building and persisting delegation handoff packages."""

from __future__ import annotations

from pathlib import Path

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

