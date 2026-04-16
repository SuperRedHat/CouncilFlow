"""Provider adapter for delegating work to a Claude Code CLI binary."""

from __future__ import annotations

from councilflow.providers.base import (
    CommandRunner,
    ProviderRequest,
    ProviderResponse,
    run_command,
)


class ClaudeCodeCliAdapter:
    """Adapter for a Claude Code CLI command."""

    model_name = "claude"

    def __init__(
        self,
        command: list[str] | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        self.command = command or ["claude", "-p"]
        self.runner = runner or run_command

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        content = self.runner(self.command, request.prompt)
        return ProviderResponse(model=self.model_name, content=content)

