"""Provider adapter for delegating work to a Gemini CLI binary."""

from __future__ import annotations

import json
import re
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
        runtime: ProviderRuntimeSettings | None = None,
        stream_mode: bool = False,
    ) -> None:
        # Adapter exposes the stable family name regardless of the specific
        # variant. The variant (e.g. gemini-1.5-flash) is surfaced via
        # ProviderResponse.metadata.gemini_variant instead of leaking into
        # downstream speaker_model / participants comparisons.
        self.model_name = "gemini"
        self.gemini_variant: str | None = model if model and model != "gemini" else None
        self.stream_mode = stream_mode
        base_command = command or _default_gemini_command(stream=stream_mode)

        if self.gemini_variant:
            # Insert --model flag before -p if present, otherwise append
            if "-p" in base_command:
                idx = base_command.index("-p")
                self.command = (
                    base_command[:idx]
                    + ["--model", self.gemini_variant]
                    + base_command[idx:]
                )
            else:
                self.command = base_command + ["--model", self.gemini_variant]
        else:
            self.command = base_command

        self.runtime = runtime or default_runtime_settings()
        if runner is not None:
            self.runner = runner
        elif stream_mode:
            self.runner = (
                lambda command, prompt, cwd=None, env=None: _run_gemini_streaming_command(
                    command, prompt, runtime=self.runtime, cwd=cwd, env=env,
                )
            )
        else:
            self.runner = (
                lambda command, prompt, cwd=None, env=None: _run_gemini_command(
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
        metadata = dict(result.metadata)
        if self.gemini_variant:
            metadata["gemini_variant"] = self.gemini_variant
        return ProviderResponse(
            model=self.model_name,
            content=_strip_runtime_notices(result.content),
            metadata=metadata,
        )


def _default_gemini_command(stream: bool = False) -> list[str]:
    """Build a Windows-safe command for invoking the Gemini CLI."""

    output_format = "stream-json" if stream else "text"
    args = ["--approval-mode", "yolo", "--output-format", output_format, "-p"]

    resolved = shutil.which("gemini")
    if resolved is None:
        return ["gemini", *args]

    suffix = Path(resolved).suffix.lower()
    if suffix == ".ps1":
        return ["powershell", "-ExecutionPolicy", "Bypass", "-File", resolved, *args]
    if suffix in {".cmd", ".bat"}:
        return ["cmd", "/c", resolved, *args]
    return [resolved, *args]


def _run_gemini_command(
    command: list[str],
    prompt: str,
    runtime: ProviderRuntimeSettings | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> ProviderRunResult:
    """Execute Gemini with the real multi-line prompt provided on stdin."""

    runtime_settings = runtime or default_runtime_settings()
    try:
        completed = subprocess.run(
            [*command, STDIN_PROMPT_INSTRUCTION],
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


def _run_gemini_streaming_command(
    command: list[str],
    prompt: str,
    runtime: ProviderRuntimeSettings | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> ProviderRunResult:
    """Execute Gemini under run_monitored_process with idle-timeout semantics."""

    monitored = run_monitored_process(
        command,
        runtime=runtime,
        prompt_argument=STDIN_PROMPT_INSTRUCTION,
        stdin_payload=prompt.encode("utf-8"),
        cwd=cwd,
        env=env,
    )
    # TASK-119: prefer the last JSON event carrying response text; fall back to
    # the last JSON-parseable line, then the raw last line — a trailing
    # plain-text CLI notice can no longer be returned as "the answer".
    lines = [line for line in monitored.stdout.splitlines() if line.strip()]
    final = _select_gemini_answer(lines)
    if final is None:
        final = monitored.stdout
    metadata = {
        **monitored.metadata,
        "output_format": "gemini-stream-json",
        "event_count": len(lines),
    }
    return ProviderRunResult(content=final, metadata=metadata)


def _select_gemini_answer(lines: list[str]) -> str | None:
    """Pick the authoritative answer from gemini stream-json output.

    Preference order: last event with a recognizable text payload
    ({"response": ...} aggregate or {"type": "content"/"message", "text": ...}
    stream events) → last JSON-parseable line verbatim → last non-empty line.
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
        value = event.get("response")
        if isinstance(value, str) and value.strip():
            best_text = value
            continue
        if event.get("type") in {"content", "message", "assistant"}:
            value = event.get("text") or event.get("content")
            if isinstance(value, str) and value.strip():
                best_text = value
    if best_text is not None:
        return best_text
    if last_json_line is not None:
        return last_json_line
    return lines[-1] if lines else None


# TASK-119: anchored to the CLI's actual retry-notice formats
# ("Attempt 1 failed: …", "Attempt 2 of 3 …"). A bare startswith("Attempt ")
# also deleted legitimate answer lines that happened to begin with the word.
_ATTEMPT_NOTICE_RE = re.compile(r"^Attempt \d+ (?:of \d+\b|failed\b)")


def _strip_runtime_notices(content: str) -> str:
    """Remove Gemini CLI runtime notices from the captured model output."""

    cleaned_lines = [
        line
        for line in content.splitlines()
        if not (line.startswith("YOLO mode is enabled.") or _ATTEMPT_NOTICE_RE.match(line))
    ]
    return "\n".join(cleaned_lines).strip()
