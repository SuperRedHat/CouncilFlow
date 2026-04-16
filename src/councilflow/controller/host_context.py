"""Detect the current controller from explicit config or host environment."""

from __future__ import annotations

import os
from collections.abc import Mapping

from councilflow.config.schema import CouncilConfig
from councilflow.models.config import ControllerContext
from councilflow.models.roles import ControllerName


class HostContextError(RuntimeError):
    """Raised when the current controller cannot be identified."""


def detect_controller(
    environ: Mapping[str, str] | None = None,
    config: CouncilConfig | None = None,
) -> ControllerContext:
    """Detect the active controller using explicit overrides before env signals."""

    if config and config.controller_override is not None:
        return ControllerContext(
            controller=config.controller_override,
            source="config.controller_override",
        )

    env = os.environ if environ is None else environ

    codex_origin = env.get("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", "").lower()
    if env.get("CODEX_SHELL"):
        return ControllerContext(controller=ControllerName.CODEX, source="CODEX_SHELL")
    if env.get("CODEX_THREAD_ID"):
        return ControllerContext(controller=ControllerName.CODEX, source="CODEX_THREAD_ID")
    if "codex" in codex_origin:
        return ControllerContext(
            controller=ControllerName.CODEX,
            source="CODEX_INTERNAL_ORIGINATOR_OVERRIDE",
        )

    claude_keys = (
        "CLAUDECODE",
        "CLAUDE_CODE",
        "CLAUDE_CODE_SHELL",
        "CLAUDE_SHELL",
        "CLAUDECODE_SHELL",
    )
    for key in claude_keys:
        if env.get(key):
            return ControllerContext(controller=ControllerName.CLAUDE, source=key)

    gemini_keys = (
        "GEMINI_CLI",
        "GEMINI_CLI_SESSION",
        "GEMINI_CLI_IDE_PID",
    )
    for key in gemini_keys:
        if env.get(key):
            return ControllerContext(controller=ControllerName.GEMINI, source=key)

    raise HostContextError(
        "Unable to detect the current controller from the environment. "
        "Set controller_override in config or run inside Codex / Claude Code / Gemini CLI."
    )
