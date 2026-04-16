"""Provider adapter for delegating work to a Gemini CLI binary."""

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

STDIN_PROMPT_INSTRUCTION = (
    "Treat the UTF-8 stdin content as the full task to complete and return only "
    "the answer requested by that task."
)


class GeminiCliAdapter:
    """Adapter for a Gemini CLI command."""

    def __init__(
        self,
        model: str | None = None,
        command: list[str] | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        self.model_name = model or "gemini"
        base_command = command or _default_gemini_command()

        if model and model != "gemini":
            # Insert --model flag before -p if present, otherwise append
            if "-p" in base_command:
                idx = base_command.index("-p")
                self.command = base_command[:idx] + ["--model", model] + base_command[idx:]
            else:
                self.command = base_command + ["--model", model]
        else:
            self.command = base_command

        self.runner = runner or _run_gemini_command

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


def _run_gemini_command(
    command: list[str],
    prompt: str,
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS,
) -> str:
    """Execute Gemini with the real multi-line prompt provided on stdin."""

    try:
        completed = subprocess.run(
            [*command, STDIN_PROMPT_INSTRUCTION],
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
