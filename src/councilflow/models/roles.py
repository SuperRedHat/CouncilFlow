"""Shared enums and helpers for controllers, roles, and model names."""

from __future__ import annotations

from enum import StrEnum


class ControllerName(StrEnum):
    """Supported controller environments."""

    CODEX = "codex"
    CLAUDE = "claude"
    GEMINI = "gemini"


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


def _default_role_models() -> dict[RoleName, str]:
    """Return the default role->model mapping derived from the packaged template."""

    # Imported lazily to avoid a circular import between models.roles and
    # config.loader (loader imports CouncilConfig which imports models.config,
    # which imports RoleName from this module).
    from councilflow.config.loader import default_role_mapping_payload

    payload = default_role_mapping_payload()
    return {RoleName(role): model for role, model in payload.items()}


# Legacy export retained as a deprecated alias — prefer _default_role_models()
# or RoleMapping.model_validate({}) so the template stays the single source of
# truth. See PRD §29.1.
class _DeprecatedDefaultRoleModels(dict[RoleName, str]):
    """Dict proxy that lazily reflects the packaged template defaults."""

    def __init__(self) -> None:
        super().__init__()

    def _refresh(self) -> None:
        super().clear()
        super().update(_default_role_models())

    def __getitem__(self, key: RoleName) -> str:  # type: ignore[override]
        self._refresh()
        return super().__getitem__(key)

    def __iter__(self):  # type: ignore[override]
        self._refresh()
        return super().__iter__()

    def items(self):  # type: ignore[override]
        self._refresh()
        return super().items()

    def keys(self):  # type: ignore[override]
        self._refresh()
        return super().keys()

    def values(self):  # type: ignore[override]
        self._refresh()
        return super().values()


DEFAULT_ROLE_MODELS: dict[RoleName, str] = _DeprecatedDefaultRoleModels()

MODEL_ALIASES: dict[str, str] = {
    "claude-code": ControllerName.CLAUDE.value,
    "claudecode": ControllerName.CLAUDE.value,
    "claude code": ControllerName.CLAUDE.value,
    "claude-3-5-sonnet": ControllerName.CLAUDE.value,
    "gemini-cli": ControllerName.GEMINI.value,
    "gemini cli": ControllerName.GEMINI.value,
    "gemini-pro": ControllerName.GEMINI.value,
    "gemini-flash": ControllerName.GEMINI.value,
    "gemini-1.5": ControllerName.GEMINI.value,
    "gemini-2.0": ControllerName.GEMINI.value,
    "gemini-1.5-pro": ControllerName.GEMINI.value,
    "gemini-1.5-flash": ControllerName.GEMINI.value,
    "gemini-2.0-flash": ControllerName.GEMINI.value,
    "google-gemini": ControllerName.GEMINI.value,
    "google gemini": ControllerName.GEMINI.value,
    "google": ControllerName.GEMINI.value,
}


def normalize_model_name(value: str) -> str:
    """Normalize model names for routing and discuss comparisons."""

    normalized = value.strip().lower()
    return MODEL_ALIASES.get(normalized, normalized)
