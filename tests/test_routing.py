from __future__ import annotations

from pathlib import Path

import yaml

from councilflow.config.loader import build_default_config, load_config
from councilflow.controller.routing import (
    resolve_discuss_models,
    route_role,
    select_discuss_models,
)
from councilflow.models.roles import ControllerName, RoleName


def test_load_config_returns_defaults_when_file_is_missing(tmp_path: Path) -> None:
    config = load_config(tmp_path / "missing-config.yaml")

    assert config == build_default_config()
    assert config.roles.implementer == "claude"


def test_load_config_validates_custom_role_mapping(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "output_language": "en",
                "roles": {
                    "planner": "codex",
                    "architect": "codex",
                    "implementer": "gpt",
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
    assert config.roles.implementer == "gpt"
    assert config.roles.advisor == "gemini"


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
    assert decision.via_sidecar is False


def test_route_role_delegates_when_target_differs_from_controller() -> None:
    decision = route_role(
        role=RoleName.IMPLEMENTER,
        config=build_default_config(),
        controller=ControllerName.CODEX,
    )

    assert decision.target_model == "claude"
    assert decision.via_sidecar is True


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
