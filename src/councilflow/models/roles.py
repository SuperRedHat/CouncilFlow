"""Shared enums and helpers for controllers, roles, and model names."""

from __future__ import annotations

from enum import StrEnum


class ControllerName(StrEnum):
    """Supported controller environments."""

    CODEX = "codex"
    CLAUDE = "claude"


class RoleName(StrEnum):
    """Supported execution roles in CouncilFlow."""

    PLANNER = "planner"
    ARCHITECT = "architect"
    IMPLEMENTER = "implementer"
    TESTER = "tester"
    REVIEWER = "reviewer"
    FIXER = "fixer"
    ADVISOR = "advisor"
    SYNTHESIZER = "synthesizer"


DEFAULT_ROLE_MODELS: dict[RoleName, str] = {
    RoleName.PLANNER: ControllerName.CODEX.value,
    RoleName.ARCHITECT: ControllerName.CODEX.value,
    RoleName.IMPLEMENTER: ControllerName.CLAUDE.value,
    RoleName.TESTER: ControllerName.CLAUDE.value,
    RoleName.REVIEWER: ControllerName.CODEX.value,
    RoleName.FIXER: ControllerName.CODEX.value,
    RoleName.ADVISOR: "gpt",
    RoleName.SYNTHESIZER: ControllerName.CODEX.value,
}

MODEL_ALIASES: dict[str, str] = {
    "claude-code": ControllerName.CLAUDE.value,
    "claudecode": ControllerName.CLAUDE.value,
    "claude code": ControllerName.CLAUDE.value,
}


def normalize_model_name(value: str) -> str:
    """Normalize model names for routing and discuss comparisons."""

    normalized = value.strip().lower()
    return MODEL_ALIASES.get(normalized, normalized)
