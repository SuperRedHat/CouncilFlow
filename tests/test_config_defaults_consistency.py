"""TASK-046 — the template must remain the single source of role defaults."""

from __future__ import annotations

import yaml

from councilflow.config.loader import (
    build_default_config,
    default_role_mapping_payload,
    load_default_config_text,
)
from councilflow.models.config import RoleMapping
from councilflow.models.roles import DEFAULT_ROLE_MODELS, RoleName, normalize_model_name


def _template_roles() -> dict[str, str]:
    payload = yaml.safe_load(load_default_config_text()) or {}
    roles = payload.get("roles", {})
    return {str(role): normalize_model_name(str(model)) for role, model in roles.items()}


def test_role_mapping_defaults_match_template_roles_section() -> None:
    template_roles = _template_roles()
    mapping = RoleMapping.model_validate({})

    for role_name in RoleName:
        assert mapping.for_role(role_name) == template_roles[role_name.value], (
            f"RoleMapping.{role_name.value} drifted from default-config.yaml"
        )


def test_default_role_mapping_payload_matches_template() -> None:
    assert {
        role: normalize_model_name(model) for role, model in default_role_mapping_payload().items()
    } == _template_roles()


def test_deprecated_default_role_models_mirrors_template() -> None:
    template_roles = _template_roles()

    for role_name in RoleName:
        assert DEFAULT_ROLE_MODELS[role_name] == template_roles[role_name.value]


def test_build_default_config_uses_template_roles() -> None:
    config = build_default_config()
    template_roles = _template_roles()

    for role_name in RoleName:
        assert config.roles.for_role(role_name) == template_roles[role_name.value]


def test_partial_role_mapping_merges_template_defaults() -> None:
    template_roles = _template_roles()
    mapping = RoleMapping.model_validate({"planner": "codex"})

    assert mapping.for_role(RoleName.PLANNER) == "codex"
    for role_name in RoleName:
        if role_name is RoleName.PLANNER:
            continue
        assert mapping.for_role(role_name) == template_roles[role_name.value]
