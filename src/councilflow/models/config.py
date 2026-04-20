"""Runtime models used by config loading, host detection, and routing."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from councilflow.models.roles import (
    ControllerName,
    RoleName,
    normalize_model_name,
    validate_model_name,
)


class RoleRoute(BaseModel):
    """One candidate route entry inside a role's dynamic routing list.

    A role can be configured as either a plain model name (shorthand,
    equivalent to a single-entry list) or as an ordered list of routes
    where the first whose ``when`` expression matches (``None`` always
    matches) is selected. ``fallback`` specifies additional models to
    attempt if the primary adapter call fails with a structured error.
    """

    model_config = ConfigDict(extra="forbid")

    model: str
    when: str | None = None
    fallback: list[str] | None = None

    @field_validator("model", mode="before")
    @classmethod
    def _normalize_primary_model(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise TypeError("RoleRoute.model must be a string.")
        if not value.strip():
            raise ValueError("RoleRoute.model cannot be empty.")
        return validate_model_name(value)

    @field_validator("when", mode="before")
    @classmethod
    def _normalize_when(cls, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError("RoleRoute.when must be a string expression or None.")
        stripped = value.strip()
        return stripped or None

    @field_validator("fallback", mode="before")
    @classmethod
    def _normalize_fallback(cls, value: Any) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            candidates = [value]
        elif isinstance(value, list):
            candidates = value
        else:
            raise TypeError("RoleRoute.fallback must be a string or list of strings.")
        out: list[str] = []
        for item in candidates:
            if not isinstance(item, str):
                raise TypeError("RoleRoute.fallback entries must be strings.")
            if not item.strip():
                raise ValueError("RoleRoute.fallback entries cannot be empty.")
            out.append(validate_model_name(item))
        return out or None


class RoleMapping(BaseModel):
    """Role-to-model mapping backed by the packaged template as single source.

    Each role accepts either the shorthand string (single model) or an
    ordered list of :class:`RoleRoute` entries for dynamic routing. The
    shorthand is normalized to a single-entry list on load, so the
    internal representation is always ``list[RoleRoute]``.
    """

    model_config = ConfigDict(extra="forbid")

    planner: list[RoleRoute]
    architect: list[RoleRoute]
    implementer: list[RoleRoute]
    tester: list[RoleRoute]
    reviewer: list[RoleRoute]
    fixer: list[RoleRoute]
    advisor: list[RoleRoute]
    synthesizer: list[RoleRoute]

    @model_validator(mode="before")
    @classmethod
    def apply_template_defaults(cls, value: Any) -> Any:
        """Merge packaged template defaults into any partial roles input."""

        from councilflow.config.loader import default_role_mapping_payload

        if value is None:
            return default_role_mapping_payload()
        if isinstance(value, dict):
            template = default_role_mapping_payload()
            return {**template, **value}
        return value

    @field_validator(
        "planner",
        "architect",
        "implementer",
        "tester",
        "reviewer",
        "fixer",
        "advisor",
        "synthesizer",
        mode="before",
    )
    @classmethod
    def normalize_routes(cls, value: Any) -> list[dict[str, Any]]:
        """Accept shorthand string or list of strings/dicts, normalize to dicts.

        Pydantic will then finalize each dict into a :class:`RoleRoute`
        and run its field validators (including model-name normalization).
        """

        if value is None:
            raise ValueError("Role mappings cannot be null.")
        if isinstance(value, str):
            if not value.strip():
                raise ValueError("Role mappings cannot be empty.")
            return [{"model": value}]
        if isinstance(value, list):
            if not value:
                raise ValueError("Role mapping list cannot be empty.")
            normalized: list[dict[str, Any]] = []
            for item in value:
                if isinstance(item, str):
                    if not item.strip():
                        raise ValueError("Role mapping list entries cannot be empty strings.")
                    normalized.append({"model": item})
                elif isinstance(item, dict):
                    normalized.append(item)
                elif isinstance(item, RoleRoute):
                    normalized.append(item.model_dump())
                else:
                    raise TypeError(
                        "Role mapping list entries must be str, dict, or RoleRoute."
                    )
            return normalized
        raise TypeError("Role mappings must be a string or a list of routes.")

    def for_role(self, role: RoleName) -> str:
        """Return the primary model for a role (first route's ``model``).

        Backward-compatible shortcut for callers that do not evaluate
        dynamic routing. The role router uses :meth:`routes_for_role`
        instead to access the full route list and ``when`` conditions.
        """

        routes = getattr(self, role.value)
        if not routes:
            raise ValueError(f"No routes configured for role {role.value}.")
        return routes[0].model

    def routes_for_role(self, role: RoleName) -> list[RoleRoute]:
        """Return the full ordered list of routes for a role."""

        return list(getattr(self, role.value))


class DiscussionSettings(BaseModel):
    """Project-level defaults for structured multi-model discussions.

    0.1.3 adds two new fields for semantic convergence:

    ``convergence_policy``
        Strategy for deciding when a discussion has converged:
        ``strict_count`` (default, pre-0.1.3 behavior: honor
        ``min_rounds`` hard count), ``semantic`` (stop as soon as a
        round adds no new information and no new disagreements, but
        still respect ``min_rounds`` as a hard floor), or ``hybrid``
        (per-topic ``min_rounds_by_topic`` floor plus semantic check
        after the floor is reached).

    ``min_rounds_by_topic``
        Optional mapping like ``{"architecture": 2, "clarification": 1}``
        consulted by the ``hybrid`` policy. Keys are matched against
        the discussion question's inferred topic. ``None`` disables
        per-topic overrides entirely.

    In ``semantic`` mode, ``min_rounds`` continues to act as a hard
    minimum — a discussion never converges before completing that many
    rounds, even if the very first round produces no new info.
    """

    model_config = ConfigDict(extra="forbid")

    default_models: list[str] = Field(default_factory=list)
    min_rounds: int = Field(default=1, ge=1)
    max_rounds: int = Field(default=5, ge=1)
    convergence_policy: Literal["strict_count", "semantic", "hybrid"] = Field(
        default="strict_count",
        description="When to consider a multi-model discussion converged.",
    )
    min_rounds_by_topic: dict[str, int] | None = Field(
        default=None,
        description=(
            "Optional per-topic minimum rounds override used by hybrid "
            "convergence policy."
        ),
    )

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


class ProviderRuntimeSettings(BaseModel):
    """Runtime execution window for provider subprocesses."""

    model_config = ConfigDict(extra="forbid")

    total_timeout_seconds: float = Field(default=900.0, gt=0)
    idle_timeout_seconds: float | None = Field(default=None, gt=0)


class ProviderRuntimeOverrides(BaseModel):
    """Optional per-provider runtime overrides merged onto the default settings."""

    model_config = ConfigDict(extra="forbid")

    total_timeout_seconds: float | None = Field(default=None, gt=0)
    idle_timeout_seconds: float | None = Field(default=None, gt=0)


class ProviderSettings(BaseModel):
    """Project-level runtime settings for non-controller provider calls."""

    model_config = ConfigDict(extra="forbid")

    default: ProviderRuntimeSettings = Field(
        default_factory=lambda: ProviderRuntimeSettings(
            total_timeout_seconds=900.0,
            idle_timeout_seconds=None,
        )
    )
    codex: ProviderRuntimeOverrides | None = None
    claude: ProviderRuntimeOverrides = Field(
        default_factory=lambda: ProviderRuntimeOverrides(idle_timeout_seconds=180.0)
    )
    gemini: ProviderRuntimeOverrides | None = None

    def for_model(self, model: str) -> ProviderRuntimeSettings:
        """Return merged runtime settings for the requested model."""

        runtime = self.default.model_copy(deep=True)
        normalized = normalize_model_name(model)
        override = (
            getattr(self, normalized, None)
            if normalized in {"codex", "claude", "gemini"}
            else None
        )
        if override is None:
            return runtime
        if override.total_timeout_seconds is not None:
            runtime.total_timeout_seconds = override.total_timeout_seconds
        if override.idle_timeout_seconds is not None:
            runtime.idle_timeout_seconds = override.idle_timeout_seconds
        return runtime


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
    status: str
    via_sidecar: bool
    reason: str
