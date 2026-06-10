"""Provider adapter for delegating work to a Codex CLI binary."""

from __future__ import annotations

import json
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
    run_monitored_process,
)


class CodexCliAdapter:
    """Adapter for a Codex CLI command."""

    model_name = "codex"

    def __init__(
        self,
        command: list[str] | None = None,
        runner: CommandRunner | None = None,
        runtime: ProviderRuntimeSettings | None = None,
        stream_mode: bool = False,
    ) -> None:
        self.stream_mode = stream_mode
        self.command = command or _default_codex_command(stream=stream_mode)
        self.runtime = runtime or default_runtime_settings()
        if runner is not None:
            self.runner = runner
        elif stream_mode:
            self.runner = (
                lambda command, prompt, cwd=None, env=None: _run_codex_streaming_command(
                    command, prompt, runtime=self.runtime, cwd=cwd, env=env,
                )
            )
        else:
            self.runner = (
                lambda command, prompt, cwd=None, env=None: _run_codex_command(
                    command, prompt, runtime=self.runtime, cwd=cwd, env=env,
                )
            )

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        result = coerce_run_result(
            self.runner(
                self.command,
                request.prompt,
                cwd=request.cwd,
                env=request.env_override,
            )
        )
        return ProviderResponse(
            model=self.model_name,
            content=result.content,
            metadata=result.metadata,
        )


def _default_codex_command(stream: bool = False) -> list[str]:
    """Build a Windows-safe command for invoking the Codex CLI."""

    args = ["exec"]
    if stream:
        args.append("--json")

    resolved = shutil.which("codex")
    if resolved is None:
        return ["codex", *args]

    suffix = Path(resolved).suffix.lower()
    if suffix == ".ps1":
        return ["powershell", "-ExecutionPolicy", "Bypass", "-File", resolved, *args]
    if suffix in {".cmd", ".bat"}:
        return ["cmd", "/c", resolved, *args]
    return [resolved, *args]


def _run_codex_command(
    command: list[str],
    prompt: str,
    runtime: ProviderRuntimeSettings | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
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
            env=env,
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


def _run_codex_streaming_command(
    command: list[str],
    prompt: str,
    runtime: ProviderRuntimeSettings | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> ProviderRunResult:
    """Run Codex with stdin prompt under run_monitored_process for idle timeouts."""

    monitored = run_monitored_process(
        command,
        runtime=runtime,
        stdin_payload=prompt.encode("utf-8"),
        cwd=cwd,
        env=env,
    )
    # TASK-119: codex emits one JSON event per line under --json. Select the
    # final agent-message event when the shape is recognizable; otherwise fall
    # back to the last JSON-parseable line so a trailing plain-text CLI notice
    # (update banner, telemetry warning) can no longer corrupt the answer.
    lines = [line for line in monitored.stdout.splitlines() if line.strip()]
    final = _select_codex_answer(lines)
    if final is None:
        final = monitored.stdout
    metadata = {
        **monitored.metadata,
        "output_format": "codex-json",
        "event_count": len(lines),
    }
    return ProviderRunResult(content=final, metadata=metadata)


def _select_codex_answer(lines: list[str]) -> str | None:
    """Pick the authoritative answer from codex --json JSONL output.

    Preference order:
    1. text of the LAST event with a known agent-answer shape
       (``{"msg": {"type": "agent_message", "message": ...}}`` or
       ``{"item": {"type": "agent_message"|"assistant_message", "text": ...}}``)
    2. the last line that parses as JSON, verbatim (pre-TASK-119 behavior,
       minus trailing non-JSON notices)
    3. the last non-empty line (no JSON in the output at all)
    """

    best_text: str | None = None
    last_json_line: str | None = None
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        last_json_line = line
        if not isinstance(event, dict):
            continue
        msg = event.get("msg")
        if isinstance(msg, dict) and msg.get("type") in {"agent_message", "task_complete"}:
            value = msg.get("message") or msg.get("last_agent_message")
            if isinstance(value, str) and value.strip():
                best_text = value
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") in {"agent_message", "assistant_message"}:
            value = item.get("text")
            if isinstance(value, str) and value.strip():
                best_text = value
    if best_text is not None:
        return best_text
    if last_json_line is not None:
        return last_json_line
    return lines[-1] if lines else None
