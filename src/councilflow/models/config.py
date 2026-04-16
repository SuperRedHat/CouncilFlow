"""Runtime models used by config loading, host detection, and routing."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from councilflow.models.roles import (
    DEFAULT_ROLE_MODELS,
    ControllerName,
    RoleName,
    normalize_model_name,
)


class RoleMapping(BaseModel):
    """Role-to-model mapping with default assignments for CouncilFlow v1."""

    model_config = ConfigDict(extra="forbid")

    planner: str = DEFAULT_ROLE_MODELS[RoleName.PLANNER]
    architect: str = DEFAULT_ROLE_MODELS[RoleName.ARCHITECT]
    implementer: str = DEFAULT_ROLE_MODELS[RoleName.IMPLEMENTER]
    tester: str = DEFAULT_ROLE_MODELS[RoleName.TESTER]
    reviewer: str = DEFAULT_ROLE_MODELS[RoleName.REVIEWER]
    fixer: str = DEFAULT_ROLE_MODELS[RoleName.FIXER]
    advisor: str = DEFAULT_ROLE_MODELS[RoleName.ADVISOR]
    synthesizer: str = DEFAULT_ROLE_MODELS[RoleName.SYNTHESIZER]

    @field_validator("*", mode="before")
    @classmethod
    def normalize_models(cls, value: str) -> str:
        """Normalize configured model names before validation."""

        if not isinstance(value, str):
            raise TypeError("Role mappings must be strings.")
        normalized = normalize_model_name(value)
        if not normalized:
            raise ValueError("Role mappings cannot be empty.")
        return normalized

    def for_role(self, role: RoleName) -> str:
        """Return the target model for a given role."""

        return getattr(self, role.value)


class ControllerContext(BaseModel):
    """Detected controller information for the current host environment."""

    controller: ControllerName
    source: str


class DiscussTargetResolution(BaseModel):
    """Normalized discuss participants after dedupe and controller filtering."""

    requested_models: list[str] = Field(default_factory=list)
    external_models: list[str] = Field(default_factory=list)
    ignored_models: list[str] = Field(default_factory=list)
    warning: str | None = None

    @property
    def requires_sidecar(self) -> bool:
        """Whether any non-controller participant remains after filtering."""

        return bool(self.external_models)


class RouteDecision(BaseModel):
    """Routing result for a role execution request."""

    role: RoleName
    controller: ControllerName
    target_model: str
    via_sidecar: bool
    reason: str
