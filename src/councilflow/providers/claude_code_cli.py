"""Provider adapter for delegating work to a Claude Code CLI binary."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from councilflow.models.config import ProviderRuntimeSettings
from councilflow.providers.base import (
    CommandRunner,
    MonitoredProcessResult,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    ProviderRunResult,
    coerce_run_result,
    default_runtime_settings,
    run_monitored_process,
)

CLAUDE_STREAM_FLAGS = [
    "-p",
    "--verbose",
    "--output-format",
    "stream-json",
    "--include-partial-messages",
]


class ClaudeCodeCliAdapter:
    """Adapter for a Claude Code CLI command."""

    model_name = "claude"

    def __init__(
        self,
        command: list[str] | None = None,
        runner: CommandRunner | None = None,
        runtime: ProviderRuntimeSettings | None = None,
    ) -> None:
        self.command = command or _default_claude_command()
        self.runtime = runtime or default_runtime_settings()
        self.runner = runner or (
            lambda command, prompt, cwd=None: _run_claude_streaming_command(
                command,
                prompt,
                runtime=self.runtime,
                cwd=cwd,
            )
        )

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        result = coerce_run_result(self.runner(self.command, request.prompt, cwd=request.cwd))
        return ProviderResponse(
            model=self.model_name,
            content=result.content,
            metadata=result.metadata,
        )


def _default_claude_command() -> list[str]:
    """Build a Windows-safe command for invoking Claude in stream-json mode."""

    resolved = shutil.which("claude")
    if resolved is None:
        return ["claude", *CLAUDE_STREAM_FLAGS]

    suffix = Path(resolved).suffix.lower()
    if suffix == ".ps1":
        return ["powershell", "-ExecutionPolicy", "Bypass", "-File", resolved, *CLAUDE_STREAM_FLAGS]
    if suffix in {".cmd", ".bat"}:
        return ["cmd", "/c", resolved, *CLAUDE_STREAM_FLAGS]
    return [resolved, *CLAUDE_STREAM_FLAGS]


def _run_claude_streaming_command(
    command: list[str],
    prompt: str,
    runtime: ProviderRuntimeSettings | None = None,
    cwd: str | None = None,
) -> ProviderRunResult:
    """Execute Claude in stream-json mode and keep the subprocess alive while events arrive."""

    monitored = run_monitored_process(
        command,
        runtime=runtime,
        prompt_argument=prompt,
        cwd=cwd,
    )
    content, metadata = _parse_stream_json_output(monitored)
    return ProviderRunResult(content=content, metadata=metadata)


def _parse_stream_json_output(
    monitored: MonitoredProcessResult,
) -> tuple[str, dict[str, Any]]:
    """Extract the final answer and useful runtime metadata from Claude's JSONL stream."""

    event_count = 0
    partial_message_events = 0
    final_result: str | None = None
    fallback_text: str | None = None
    stream_models: list[str] = []
    terminal_reason: str | None = None

    for raw_line in monitored.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_count += 1
        payload_type = str(payload.get("type", ""))
        if payload_type == "result":
            if payload.get("is_error"):
                raise ProviderError(
                    str(payload.get("result") or "unknown Claude provider error"),
                    kind="process_exit",
                    metadata={
                        **monitored.metadata,
                        "stderr": monitored.stderr,
                        "terminal_reason": payload.get("terminal_reason"),
                        "api_error_status": payload.get("api_error_status"),
                    },
                )
            final_result = _normalize_text(payload.get("result"))
            terminal_reason = _normalize_text(payload.get("terminal_reason"))
            continue

        if payload_type == "assistant":
            message = payload.get("message", {})
            if isinstance(message, dict):
                model = _normalize_text(message.get("model"))
                if model and model not in stream_models:
                    stream_models.append(model)
                extracted_text = _extract_text_content(message.get("content"))
                if extracted_text:
                    fallback_text = extracted_text
            continue

        if payload_type == "stream_event":
            event = payload.get("event", {})
            delta = event.get("delta", {}) if isinstance(event, dict) else {}
            delta_type = _normalize_text(delta.get("type"))
            if delta_type in {"text_delta", "thinking_delta"}:
                partial_message_events += 1

    content = final_result or fallback_text or monitored.stdout.strip()
    metadata = {
        **monitored.metadata,
        "output_format": "stream-json",
        "event_count": event_count,
        "partial_message_events": partial_message_events,
        "terminal_reason": terminal_reason,
        "stream_models": stream_models,
    }
    return content, metadata


def _extract_text_content(content: object) -> str | None:
    """Extract the last visible text block from Claude assistant events."""

    if not isinstance(content, list):
        return None
    extracted: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "text":
            continue
        text = _normalize_text(block.get("text"))
        if text:
            extracted.append(text)
    if not extracted:
        return None
    return "\n".join(extracted).strip()


def _normalize_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
