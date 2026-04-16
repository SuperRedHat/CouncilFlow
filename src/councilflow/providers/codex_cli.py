"""Provider adapter for delegating work to a Codex CLI binary."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from councilflow.providers.base import (
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    CommandRunner,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
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
        self.runner = runner or _run_codex_command

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


def _run_codex_command(
    command: list[str],
    prompt: str,
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS,
) -> str:
    """Execute Codex with the prompt provided on stdin for Windows compatibility."""

    try:
        completed = subprocess.run(
            command,
            input=prompt.encode("utf-8"),
            capture_output=True,
            check=False,
            text=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProviderError(
            f"Provider command timed out after {timeout_seconds:g}s."
        ) from exc
    except OSError as exc:
        raise ProviderError(str(exc)) from exc

    stdout = completed.stdout.decode("utf-8", errors="replace").strip()
    stderr = completed.stderr.decode("utf-8", errors="replace").strip()
    if completed.returncode != 0:
        raise ProviderError(stderr or "unknown provider error")
    return stdout
