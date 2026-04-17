"""Runtime models used by config loading, host detection, and routing."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class DiscussionSettings(BaseModel):
    """Project-level defaults for structured multi-model discussions."""

    model_config = ConfigDict(extra="forbid")

    default_models: list[str] = Field(default_factory=list)
    min_rounds: int = Field(default=1, ge=1)
    max_rounds: int = Field(default=5, ge=1)

    @field_validator("default_models", mode="before")
    @classmethod
    def normalize_default_models(cls, value: object) -> list[str]:
        """Normalize and de-duplicate configured default discussion models."""

        if value is None:
            return []
        if isinstance(value, str):
            raw_items = value.split(",")
        elif isinstance(value, list):
            raw_items = value
        else:
            raise TypeError("discussion.default_models must be a string or list of strings.")

        normalized_models: list[str] = []
        seen_models: set[str] = set()
        for item in raw_items:
            if not isinstance(item, str):
                raise TypeError("discussion.default_models must contain only strings.")
            normalized = normalize_model_name(item)
            if not normalized:
                raise ValueError("discussion.default_models cannot contain empty entries.")
            if normalized in seen_models:
                continue
            seen_models.add(normalized)
            normalized_models.append(normalized)
        return normalized_models

    @model_validator(mode="after")
    def validate_round_bounds(self) -> DiscussionSettings:
        """Ensure minimum discussion rounds do not exceed the configured maximum."""

        if self.min_rounds > self.max_rounds:
            raise ValueError("discussion.min_rounds cannot exceed discussion.max_rounds.")
        return self


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
