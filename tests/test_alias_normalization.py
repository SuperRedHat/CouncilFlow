"""Alias normalization + unknown-model rejection (TASK-047)."""

from __future__ import annotations

import pytest

from councilflow.config.schema import CouncilConfig
from councilflow.controller.host_context import detect_controller
from councilflow.controller.routing import resolve_discuss_models
from councilflow.models.config import RoleMapping
from councilflow.models.roles import (
    ControllerName,
    normalize_model_name,
    resolve_adapter_model,
    validate_model_name,
)


def test_normalize_model_name_gemini_direct() -> None:
    assert normalize_model_name("gemini") == ControllerName.GEMINI.value


def test_resolve_discuss_models_dedupes_gemini_cli_alias() -> None:
    resolution = resolve_discuss_models(
        requested_models=["gemini-cli", "codex"],
        controller=ControllerName.GEMINI,
    )
    assert resolution.external_models == ["codex"]
    assert resolution.ignored_models == ["gemini"]


def test_resolve_discuss_models_dedupes_raw_gemini() -> None:
    resolution = resolve_discuss_models(
        requested_models=["gemini", "codex"],
        controller=ControllerName.GEMINI,
    )
    assert resolution.external_models == ["codex"]
    assert resolution.ignored_models == ["gemini"]


def test_detect_controller_uses_config_override_to_select_gemini() -> None:
    config = CouncilConfig(controller_override=ControllerName.GEMINI)
    context = detect_controller(config=config)
    assert context.controller == ControllerName.GEMINI
    assert context.source == "config.controller_override"


def test_resolve_adapter_model_accepts_registered_families() -> None:
    assert resolve_adapter_model("codex") == "codex"
    assert resolve_adapter_model("claude") == "claude"
    assert resolve_adapter_model("gemini") == "gemini"
    assert resolve_adapter_model("gemini-1.5-flash") == "gemini"
    assert resolve_adapter_model("gemini-2.5-pro") == "gemini-2.5-pro"


def test_resolve_adapter_model_accepts_gpt_family_after_openai_adapter() -> None:
    assert resolve_adapter_model("gpt") == "gpt"
    assert resolve_adapter_model("gpt-4o-mini") == "gpt-4o-mini"
    assert resolve_adapter_model("o1-preview") == "o1-preview"


def test_resolve_adapter_model_rejects_unknown_names() -> None:
    assert resolve_adapter_model("clood") is None
    assert resolve_adapter_model("mistral") is None
    assert resolve_adapter_model("llama-3") is None


def test_validate_model_name_raises_actionable_value_error() -> None:
    with pytest.raises(ValueError, match="No provider adapter"):
        validate_model_name("clood")
    with pytest.raises(ValueError, match="No provider adapter"):
        validate_model_name("llama-3")


def test_role_mapping_rejects_unknown_adapter_at_load_time() -> None:
    with pytest.raises(ValueError, match="No provider adapter"):
        RoleMapping.model_validate({"planner": "clood"})
