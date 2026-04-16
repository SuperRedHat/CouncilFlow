"""Provider adapter for delegating work to a Codex CLI binary."""

from __future__ import annotations

import shutil
from pathlib import Path

from councilflow.providers.base import (
    CommandRunner,
    ProviderRequest,
    ProviderResponse,
    run_command,
)


class CodexCliAdapter:
    """Adapter for a Codex CLI command."""

    model_name = "codex"

    def __init__(
        self,
        command: list[str] | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        self.command = command or _default_codex_command()
        self.runner = runner or run_command

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        content = self.runner(self.command, request.prompt)
        return ProviderResponse(model=self.model_name, content=content)


def _default_codex_command() -> list[str]:
    """Build a Windows-safe command for invoking the Codex CLI."""

    resolved = shutil.which("codex")
    if resolved is None:
        return ["codex", "exec"]

    suffix = Path(resolved).suffix.lower()
    if suffix == ".ps1":
        return ["powershell", "-ExecutionPolicy", "Bypass", "-File", resolved, "exec"]
    if suffix in {".cmd", ".bat"}:
        return ["cmd", "/c", resolved, "exec"]
    return [resolved, "exec"]
