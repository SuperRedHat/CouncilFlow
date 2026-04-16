from __future__ import annotations

import pytest

from councilflow.config.schema import CouncilConfig
from councilflow.controller.host_context import HostContextError, detect_controller
from councilflow.models.roles import ControllerName


def test_detects_codex_from_environment() -> None:
    context = detect_controller(
        environ={
            "CODEX_SHELL": "1",
            "CODEX_INTERNAL_ORIGINATOR_OVERRIDE": "Codex Desktop",
        }
    )

    assert context.controller == ControllerName.CODEX
    assert context.source == "CODEX_SHELL"


def test_config_override_wins_over_environment() -> None:
    config = CouncilConfig(controller_override=ControllerName.CLAUDE)
    context = detect_controller(environ={"CODEX_SHELL": "1"}, config=config)

    assert context.controller == ControllerName.CLAUDE
    assert context.source == "config.controller_override"


def test_raises_when_controller_cannot_be_detected() -> None:
    with pytest.raises(HostContextError):
        detect_controller(environ={})

