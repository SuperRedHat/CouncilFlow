"""Pydantic schema for persisted CouncilFlow configuration."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from councilflow.models.config import DiscussionSettings, ProviderSettings, RoleMapping
from councilflow.models.roles import ControllerName
from councilflow.utils.lang import SUPPORTED_OUTPUT_LANGUAGES


class CouncilConfig(BaseModel):
    """Top-level project configuration loaded from .council/config.yaml."""

    model_config = ConfigDict(extra="forbid")

    config_version: int = 1
    output_language: str = "zh-CN"
    controller_override: ControllerName | None = None
    roles: RoleMapping = Field(default_factory=RoleMapping)
    discussion: DiscussionSettings = Field(default_factory=DiscussionSettings)
    providers: ProviderSettings = Field(default_factory=ProviderSettings)

    @field_validator("output_language")
    @classmethod
    def validate_output_language(cls, value: str) -> str:
        """TASK-122: an unsupported language is a config error, not a silent
        zh-CN fallback discovered only in the CLI output."""

        if value not in SUPPORTED_OUTPUT_LANGUAGES:
            raise ValueError(
                f"output_language '{value}' is not supported; choose one of "
                f"{sorted(SUPPORTED_OUTPUT_LANGUAGES)}."
            )
        return value
