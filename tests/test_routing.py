from __future__ import annotations

from pathlib import Path

import yaml

from councilflow.config.loader import build_default_config, load_config
from councilflow.config.schema import CouncilConfig
from councilflow.controller.routing import (
    build_route_decision,
    resolve_discuss_models,
    route_role,
    select_discuss_models,
)
from councilflow.models.roles import ControllerName, RoleName


def test_load_config_returns_defaults_when_file_is_missing(tmp_path: Path) -> None:
    config = load_config(tmp_path / "missing-config.yaml")

    assert config == build_default_config()
    assert config.roles.for_role(RoleName.IMPLEMENTER) == "controller"


def test_load_config_validates_custom_role_mapping(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "output_language": "en",
                "roles": {
                    "planner": "codex",
                    "architect": "codex",
                    "implementer": "claude",
                    "tester": "claude",
                    "reviewer": "codex",
                    "fixer": "codex",
                    "advisor": "gemini",
                    "synthesizer": "codex",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.output_language == "en"
    assert config.roles.for_role(RoleName.IMPLEMENTER) == "claude"
    assert config.roles.for_role(RoleName.ADVISOR) == "gemini"


def test_resolve_discuss_models_ignores_controller_and_duplicates() -> None:
    resolution = resolve_discuss_models(
        requested_models=["codex", "Claude", "claude", "gpt"],
        controller=ControllerName.CODEX,
    )

    assert resolution.requested_models == ["codex", "claude", "gpt"]
    assert resolution.external_models == ["claude", "gpt"]
    assert resolution.ignored_models == ["claude", "codex"]
    assert resolution.warning is None
    assert resolution.requires_sidecar is True


def test_resolve_discuss_models_warns_when_only_controller_is_requested() -> None:
    resolution = resolve_discuss_models(
        requested_models=["codex", "Codex"],
        controller=ControllerName.CODEX,
    )

    assert resolution.external_models == []
    assert resolution.warning is not None
    assert "current controller" in resolution.warning
    assert resolution.requires_sidecar is False


def test_resolve_discuss_models_warns_when_no_models_are_available() -> None:
    resolution = resolve_discuss_models(
        requested_models=[],
        controller=ControllerName.CODEX,
    )

    assert resolution.external_models == []
    assert resolution.warning is not None
    assert "No additional discuss models" in resolution.warning
    assert resolution.requires_sidecar is False


def test_resolve_discuss_models_normalizes_controller_aliases() -> None:
    resolution = resolve_discuss_models(
        requested_models=["claude-code", "gpt"],
        controller=ControllerName.CLAUDE,
    )

    assert resolution.external_models == ["gpt"]
    assert resolution.ignored_models == ["claude"]


def test_resolve_discuss_models_normalizes_gemini_aliases() -> None:
    resolution = resolve_discuss_models(
        requested_models=["gemini-cli", "codex"],
        controller=ControllerName.GEMINI,
    )

    assert resolution.external_models == ["codex"]
    assert resolution.ignored_models == ["gemini"]


def test_route_role_runs_locally_when_target_matches_controller() -> None:
    decision = route_role(
        role=RoleName.PLANNER,
        config=build_default_config(),
        controller=ControllerName.CODEX,
    )

    assert decision.target_model == "codex"
    assert decision.status == "local_execution"
    assert decision.via_sidecar is False


def test_route_role_delegates_when_target_differs_from_controller() -> None:
    # A role pinned to a concrete model that differs from the controller still
    # delegates (the shipped `controller` default would instead stay local).
    config = CouncilConfig.model_validate({"roles": {"implementer": "codex"}})
    decision = route_role(
        role=RoleName.IMPLEMENTER,
        config=config,
        controller=ControllerName.CLAUDE,
    )

    assert decision.target_model == "codex"
    assert decision.status == "delegated"
    assert decision.via_sidecar is True


def test_build_route_decision_normalizes_aliases_and_exposes_status() -> None:
    decision = build_route_decision(
        role=RoleName.TESTER,
        controller=ControllerName.CLAUDE,
        target_model="claude-code",
    )

    assert decision.target_model == "claude"
    assert decision.status == "local_execution"
    assert decision.via_sidecar is False


def test_select_discuss_models_uses_project_defaults_when_explicit_is_missing() -> None:
    config = build_default_config()
    config.discussion.default_models = ["gemini", "claude"]

    selected, source = select_discuss_models(None, config)

    assert selected == ["gemini", "claude"]
    assert source == "project_default"


def test_select_discuss_models_prefers_explicit_over_project_defaults() -> None:
    config = build_default_config()
    config.discussion.default_models = ["gemini"]

    selected, source = select_discuss_models(["claude"], config)

    assert selected == ["claude"]
    assert source == "explicit"


def test_build_route_decision_controller_sentinel_stays_local_for_any_controller() -> None:
    # The `controller` sentinel follows whoever is driving: role and controller
    # are the same model, so execution stays local for every controller.
    for controller in (ControllerName.CODEX, ControllerName.CLAUDE, ControllerName.GEMINI):
        decision = build_route_decision(
            role=RoleName.IMPLEMENTER,
            controller=controller,
            target_model="controller",
        )
        assert decision.status == "local_execution"
        assert decision.via_sidecar is False
        # sentinel resolves to the concrete controller model for downstream/emit
        assert decision.target_model == controller.value


def test_default_config_roles_follow_controller_locally() -> None:
    # The shipped default maps every role to `controller`, so a fresh project
    # runs every role on the active controller — no sidecar — whoever drives.
    config = build_default_config()
    for controller in (ControllerName.CODEX, ControllerName.CLAUDE, ControllerName.GEMINI):
        decision = route_role(
            role=RoleName.IMPLEMENTER, config=config, controller=controller
        )
        assert decision.status == "local_execution"
        assert decision.via_sidecar is False
        assert decision.target_model == controller.value


def test_role_accepts_controller_sentinel_but_fallback_rejects_it() -> None:
    import pytest
    from pydantic import ValidationError

    # A role's primary model may be the `controller` sentinel ...
    config = CouncilConfig.model_validate({"roles": {"planner": "controller"}})
    assert config.roles.for_role(RoleName.PLANNER) == "controller"
    # ... but a fallback must still be a concrete, registered model.
    with pytest.raises(ValidationError):
        CouncilConfig.model_validate(
            {"roles": {"planner": [{"model": "codex", "fallback": ["controller"]}]}}
        )


def test_discussion_default_models_reject_controller_sentinel() -> None:
    import pytest
    from pydantic import ValidationError

    # `controller` is a roles-only sentinel; it must not leak into discuss models
    # (it would otherwise fail late with adapter_missing at discuss time).
    with pytest.raises(ValidationError):
        CouncilConfig.model_validate(
            {"discussion": {"default_models": ["controller", "codex"]}}
        )
