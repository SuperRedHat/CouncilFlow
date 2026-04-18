"""Provider adapter for delegating work to a Codex CLI binary."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from councilflow.models.config import ProviderRuntimeSettings
from councilflow.providers.base import (
    CommandRunner,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    ProviderRunResult,
    coerce_run_result,
    default_runtime_settings,
)


class CodexCliAdapter:
    """Adapter for a Codex CLI command."""

    model_name = "codex"

    def __init__(
        self,
        command: list[str] | None = None,
        runner: CommandRunner | None = None,
        runtime: ProviderRuntimeSettings | None = None,
    ) -> None:
        self.command = command or _default_codex_command()
        self.runtime = runtime or default_runtime_settings()
        self.runner = runner or (
            lambda command, prompt, cwd=None: _run_codex_command(
                command, prompt, runtime=self.runtime, cwd=cwd,
            )
        )

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        result = coerce_run_result(self.runner(self.command, request.prompt, cwd=request.cwd))
        return ProviderResponse(
            model=self.model_name,
            content=result.content,
            metadata=result.metadata,
        )


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
    runtime: ProviderRuntimeSettings | None = None,
    cwd: str | None = None,
) -> ProviderRunResult:
    """Execute Codex with the prompt provided on stdin for Windows compatibility."""

    runtime_settings = runtime or default_runtime_settings()
    try:
        completed = subprocess.run(
            command,
            input=prompt.encode("utf-8"),
            capture_output=True,
            check=False,
            text=False,
            timeout=runtime_settings.total_timeout_seconds,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProviderError(
            f"Provider command timed out after {runtime_settings.total_timeout_seconds:g}s.",
            kind="total_timeout",
            metadata={
                "command": command,
                "total_timeout_seconds": runtime_settings.total_timeout_seconds,
                "idle_timeout_seconds": runtime_settings.idle_timeout_seconds,
            },
        ) from exc
    except OSError as exc:
        raise ProviderError(str(exc), kind="os_error", metadata={"command": command}) from exc

    stdout = completed.stdout.decode("utf-8", errors="replace").strip()
    stderr = completed.stderr.decode("utf-8", errors="replace").strip()
    if completed.returncode != 0:
        raise ProviderError(
            stderr or "unknown provider error",
            kind="process_exit",
            metadata={
                "command": command,
                "returncode": completed.returncode,
                "stderr": stderr,
            },
        )
    return ProviderRunResult(
        content=stdout,
        metadata={
            "execution_mode": "blocking",
            "timeout_strategy": "total_only",
            "total_timeout_seconds": runtime_settings.total_timeout_seconds,
            "idle_timeout_seconds": runtime_settings.idle_timeout_seconds,
            "returncode": completed.returncode,
            "stderr": stderr,
        },
    )
