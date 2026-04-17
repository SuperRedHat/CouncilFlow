"""Pydantic schema for persisted CouncilFlow configuration."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from councilflow.models.config import DiscussionSettings, ProviderSettings, RoleMapping
from councilflow.models.roles import ControllerName


class CouncilConfig(BaseModel):
    """Top-level project configuration loaded from .council/config.yaml."""

    model_config = ConfigDict(extra="forbid")

    config_version: int = 1
    output_language: str = "zh-CN"
    controller_override: ControllerName | None = None
    roles: RoleMapping = Field(default_factory=RoleMapping)
    discussion: DiscussionSettings = Field(default_factory=DiscussionSettings)
    providers: ProviderSettings = Field(default_factory=ProviderSettings)
