"""Prompt rendering helpers for delegated execution."""

from __future__ import annotations

from councilflow.models.delegation import HandoffPackage


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

