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


def test_provider_and_discussion_defaults_match_template() -> None:
    """TASK-122: bare-schema defaults stay in lockstep with the template, so a
    config that omits a section behaves like a freshly templated project
    (the 100x provider-timeout drift was a real shipped bug)."""

    from councilflow.config.schema import CouncilConfig

    payload = yaml.safe_load(load_default_config_text()) or {}
    cfg = CouncilConfig.model_validate({})

    tpl_providers = payload["providers"]
    assert (
        cfg.providers.default.total_timeout_seconds
        == tpl_providers["default"]["total_timeout_seconds"]
    )
    assert (
        cfg.providers.claude.idle_timeout_seconds
        == tpl_providers["claude"]["idle_timeout_seconds"]
    )

    tpl_disc = payload["discussion"]
    assert cfg.discussion.min_rounds == tpl_disc["min_rounds"]
    assert cfg.discussion.max_rounds == tpl_disc["max_rounds"]
    assert cfg.discussion.default_models == [
        normalize_model_name(m) for m in tpl_disc["default_models"]
    ]


def test_output_language_rejected_at_load_time() -> None:
    import pytest as _pytest
    from pydantic import ValidationError

    from councilflow.config.schema import CouncilConfig

    with _pytest.raises(ValidationError, match="output_language"):
        CouncilConfig.model_validate({"output_language": "fr-FR"})


def test_default_models_must_resolve_to_registered_adapters() -> None:
    import pytest as _pytest
    from pydantic import ValidationError

    from councilflow.models.config import DiscussionSettings

    with _pytest.raises(ValidationError, match="does not resolve"):
        DiscussionSettings.model_validate({"default_models": ["llama-3"]})
    # claude variants resolve since TASK-117
    ok = DiscussionSettings.model_validate({"default_models": ["claude-sonnet", "codex"]})
    assert ok.default_models == ["claude-sonnet", "codex"]


def test_command_is_available_handles_quoted_absolute_paths(tmp_path) -> None:
    from councilflow.utils.permissions import command_is_available

    exe = tmp_path / "my tool.exe"
    exe.write_text("", encoding="utf-8")
    assert command_is_available(f'"{exe}" --version') is True
    assert command_is_available('"C:/definitely/missing/tool.exe" run') is False
