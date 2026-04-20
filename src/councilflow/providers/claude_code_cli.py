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

# ``--dangerously-skip-permissions`` is intentional and matches the risk posture
# taken by the Gemini adapter's ``--approval-mode yolo``: delegated subprocesses
# run inside a materialized worktree with ``build_sandboxed_env`` markers,
# ``DEFAULT_PROTECTED_PATHS`` snapshot/restore, deny-by-default
# ``writable_globs``, and the role-scoped MCP policy, so the upstream CLI
# permission gate would only add friction on top of those four layers while
# offering no additional safety for an already-contained stage. Surfacing the
# ``dangerously`` name is a deliberate cost — if you can read this line you
# already opted in by invoking ``council delegate``.
CLAUDE_STREAM_FLAGS = [
    "-p",
    "--verbose",
    "--output-format",
    "stream-json",
    "--include-partial-messages",
    "--dangerously-skip-permissions",
]


# Short aliases that the Claude Code CLI accepts natively on its ``--model``
# flag (per Anthropic's CLI docs). When the caller configures a variant like
# ``claude-haiku``, we strip the ``claude-`` prefix before passing the name to
# the CLI so the CLI sees a form it recognizes. Longer / versioned names
# (``claude-sonnet-4-6``, ``claude-3-5-sonnet-20241022``) are passed through
# unchanged — they are CLI-native full IDs.
_CLAUDE_CLI_SHORT_ALIASES: frozenset[str] = frozenset({"haiku", "sonnet", "opus"})


def _variant_to_cli_model_arg(variant: str) -> str:
    """Map an internal ``claude-<variant>`` string to the CLI ``--model`` arg."""

    if variant.startswith("claude-"):
        remainder = variant[len("claude-") :]
        if remainder in _CLAUDE_CLI_SHORT_ALIASES:
            return remainder
    return variant


class ClaudeCodeCliAdapter:
    """Adapter for a Claude Code CLI command.

    Mirrors the :class:`GeminiCliAdapter` variant pattern: the public
    ``model_name`` stays the canonical family name (``"claude"``) so
    ``ProviderResponse.model`` and downstream dedup/speaker_model comparisons
    see a stable identifier, while the specific variant (``claude-haiku``,
    ``claude-sonnet-4-6``, etc.) is carried on the instance as
    ``claude_variant`` and surfaced via ``ProviderResponse.metadata``.

    When a variant is supplied, the adapter injects ``--model <name>`` into
    the constructed CLI command (before ``-p``) so the Claude Code CLI
    selects the requested model rather than whatever its own default is.
    """

    model_name = "claude"

    def __init__(
        self,
        model: str | None = None,
        command: list[str] | None = None,
        runner: CommandRunner | None = None,
        runtime: ProviderRuntimeSettings | None = None,
    ) -> None:
        # Only store a variant when the caller actually passed one that is
        # distinct from the bare family name. ``model="claude"`` and
        # ``model=None`` are equivalent — the 0.1.3 no-variant behavior.
        self.claude_variant: str | None = (
            model if model and model.strip() and model != "claude" else None
        )
        base_command = command or _default_claude_command()

        if self.claude_variant:
            cli_model_arg = _variant_to_cli_model_arg(self.claude_variant)
            # Insert --model before -p so the flag is parsed with the stream
            # setup, matching the Gemini adapter's insertion point.
            if "-p" in base_command:
                idx = base_command.index("-p")
                self.command = (
                    base_command[:idx]
                    + ["--model", cli_model_arg]
                    + base_command[idx:]
                )
            else:
                self.command = base_command + ["--model", cli_model_arg]
        else:
            self.command = base_command

        self.runtime = runtime or default_runtime_settings()
        self.runner = runner or (
            lambda command, prompt, cwd=None, env=None: _run_claude_streaming_command(
                command,
                prompt,
                runtime=self.runtime,
                cwd=cwd,
                env=env,
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
        metadata = dict(result.metadata)
        if self.claude_variant:
            metadata["claude_variant"] = self.claude_variant
        return ProviderResponse(
            model=self.model_name,
            content=result.content,
            metadata=metadata,
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
    env: dict[str, str] | None = None,
) -> ProviderRunResult:
    """Execute Claude in stream-json mode and keep the subprocess alive while events arrive."""

    monitored = run_monitored_process(
        command,
        runtime=runtime,
        prompt_argument=prompt,
        cwd=cwd,
        env=env,
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
