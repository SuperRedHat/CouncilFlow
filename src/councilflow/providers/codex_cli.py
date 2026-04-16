"""Provider adapter for delegating work to a Codex CLI binary."""

from __future__ import annotations

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
        self.command = command or ["codex", "exec"]
        self.runner = runner or run_command

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        content = self.runner(self.command, request.prompt)
        return ProviderResponse(model=self.model_name, content=content)

