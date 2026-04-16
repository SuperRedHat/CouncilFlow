"""Provider adapter for delegating work to a Gemini CLI binary."""

from __future__ import annotations

import shutil
from pathlib import Path

from councilflow.providers.base import (
    CommandRunner,
    ProviderRequest,
    ProviderResponse,
    run_command,
)


class GeminiCliAdapter:
    """Adapter for a Gemini CLI command."""

    model_name = "gemini"

    def __init__(
        self,
        command: list[str] | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        self.command = command or _default_gemini_command()
        self.runner = runner or run_command

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        content = self.runner(self.command, request.prompt)
        return ProviderResponse(
            model=self.model_name,
            content=_strip_runtime_notices(content),
        )


def _default_gemini_command() -> list[str]:
    """Build a Windows-safe command for invoking the Gemini CLI."""

    resolved = shutil.which("gemini")
    if resolved is None:
        return ["gemini", "--approval-mode", "yolo", "--output-format", "text", "-p"]

    suffix = Path(resolved).suffix.lower()
    if suffix == ".ps1":
        return [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            resolved,
            "--approval-mode",
            "yolo",
            "--output-format",
            "text",
            "-p",
        ]
    if suffix in {".cmd", ".bat"}:
        return [
            "cmd",
            "/c",
            resolved,
            "--approval-mode",
            "yolo",
            "--output-format",
            "text",
            "-p",
        ]
    return [resolved, "--approval-mode", "yolo", "--output-format", "text", "-p"]


def _strip_runtime_notices(content: str) -> str:
    """Remove Gemini CLI runtime notices from the captured model output."""

    ignored_prefixes = (
        "YOLO mode is enabled.",
        "Attempt ",
    )
    cleaned_lines = [
        line for line in content.splitlines() if not line.startswith(ignored_prefixes)
    ]
    return "\n".join(cleaned_lines).strip()
