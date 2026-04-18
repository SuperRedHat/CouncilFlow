"""Base provider interfaces and runtime helpers for delegated execution."""

from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Callable
from queue import Empty, Queue
from typing import Any, Protocol

from pydantic import BaseModel, Field

from councilflow.models.config import ProviderRuntimeSettings

CommandRunner = Callable[..., "ProviderRunResult | str"]
DEFAULT_PROVIDER_TOTAL_TIMEOUT_SECONDS = 900.0
DEFAULT_PROVIDER_IDLE_TIMEOUT_SECONDS = 180.0


class ProviderRequest(BaseModel):
    """Request payload sent to a provider adapter."""

    prompt: str
    context: dict[str, Any] = Field(default_factory=dict)
    cwd: str | None = None


class ProviderResponse(BaseModel):
    """Response payload returned by a provider adapter."""

    model: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderRunResult(BaseModel):
    """Raw provider subprocess result before adapter-level model attribution."""

    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MonitoredProcessResult(BaseModel):
    """Captured stdout/stderr and metadata for a monitored subprocess."""

    stdout: str
    stderr: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderError(RuntimeError):
    """Raised when a provider invocation fails."""

    def __init__(
        self,
        message: str,
        *,
        kind: str = "process_exit",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        # Common kinds include process_exit, total_timeout, idle_timeout, os_error,
        # permission_blocked, environment_not_ready, and guardrail_violation.
        self.kind = kind
        self.metadata = metadata or {}


class ProviderAdapter(Protocol):
    """Minimal interface that provider adapters must implement."""

    model_name: str

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        """Send a prompt to the provider and return its response."""


def default_runtime_settings() -> ProviderRuntimeSettings:
    """Return the runtime defaults used when config does not provide overrides."""

    return ProviderRuntimeSettings(
        total_timeout_seconds=DEFAULT_PROVIDER_TOTAL_TIMEOUT_SECONDS,
        idle_timeout_seconds=None,
    )


def coerce_run_result(result: ProviderRunResult | str) -> ProviderRunResult:
    """Normalize custom runner outputs so legacy string-returning fakes still work."""

    if isinstance(result, ProviderRunResult):
        return result
    return ProviderRunResult(content=str(result))


def run_command(
    command: list[str],
    prompt: str,
    runtime: ProviderRuntimeSettings | None = None,
    cwd: str | None = None,
) -> ProviderRunResult:
    """Execute a CLI command with the prompt appended as the final argument."""

    runtime_settings = runtime or default_runtime_settings()
    try:
        completed = subprocess.run(
            [*command, prompt],
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


def run_monitored_process(
    command: list[str],
    *,
    runtime: ProviderRuntimeSettings | None = None,
    prompt_argument: str | None = None,
    stdin_payload: bytes | None = None,
    cwd: str | None = None,
) -> MonitoredProcessResult:
    """Execute a subprocess while tracking both total duration and output activity."""

    runtime_settings = runtime or default_runtime_settings()
    full_command = [*command, prompt_argument] if prompt_argument is not None else list(command)
    start = time.monotonic()
    last_activity = start
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    queue: Queue[tuple[str, str | None]] = Queue()
    process: subprocess.Popen[str] | None = None
    reader_threads: list[threading.Thread] = []
    open_streams = {"stdout", "stderr"}

    try:
        process = subprocess.Popen(
            full_command,
            stdin=subprocess.PIPE if stdin_payload is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=cwd,
        )
    except OSError as exc:
        raise ProviderError(
            str(exc),
            kind="os_error",
            metadata={"command": full_command},
        ) from exc

    if stdin_payload is not None and process.stdin is not None:
        process.stdin.write(stdin_payload.decode("utf-8", errors="replace"))
        process.stdin.close()

    def reader(stream_name: str, stream: Any) -> None:
        try:
            for raw_line in iter(stream.readline, ""):
                queue.put((stream_name, raw_line))
        finally:
            stream.close()
            queue.put((f"{stream_name}_closed", None))

    assert process.stdout is not None
    assert process.stderr is not None
    for stream_name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
        thread = threading.Thread(target=reader, args=(stream_name, stream), daemon=True)
        thread.start()
        reader_threads.append(thread)

    try:
        while True:
            now = time.monotonic()
            total_elapsed = now - start
            idle_elapsed = now - last_activity
            if total_elapsed > runtime_settings.total_timeout_seconds:
                _terminate_process(process)
                raise ProviderError(
                    "Provider command exceeded the total timeout of "
                    f"{runtime_settings.total_timeout_seconds:g}s.",
                    kind="total_timeout",
                    metadata={
                        "command": full_command,
                        "total_timeout_seconds": runtime_settings.total_timeout_seconds,
                        "idle_timeout_seconds": runtime_settings.idle_timeout_seconds,
                        "duration_seconds": round(total_elapsed, 3),
                    },
                )
            if (
                runtime_settings.idle_timeout_seconds is not None
                and idle_elapsed > runtime_settings.idle_timeout_seconds
            ):
                _terminate_process(process)
                raise ProviderError(
                    "Provider command exceeded the idle timeout of "
                    f"{runtime_settings.idle_timeout_seconds:g}s without new output.",
                    kind="idle_timeout",
                    metadata={
                        "command": full_command,
                        "total_timeout_seconds": runtime_settings.total_timeout_seconds,
                        "idle_timeout_seconds": runtime_settings.idle_timeout_seconds,
                        "duration_seconds": round(total_elapsed, 3),
                        "idle_duration_seconds": round(idle_elapsed, 3),
                    },
                )

            if process.poll() is not None and not open_streams and queue.empty():
                break

            try:
                stream_name, payload = queue.get(timeout=0.1)
            except Empty:
                continue

            if stream_name.endswith("_closed"):
                open_streams.discard(stream_name.removesuffix("_closed"))
                continue

            if payload is None:
                continue
            last_activity = time.monotonic()
            line = payload.rstrip("\r\n")
            if stream_name == "stdout":
                stdout_lines.append(line)
            else:
                stderr_lines.append(line)

        returncode = process.wait(timeout=1)
    finally:
        for thread in reader_threads:
            thread.join(timeout=0.2)

    stdout = "\n".join(stdout_lines).strip()
    stderr = "\n".join(stderr_lines).strip()
    duration_seconds = round(time.monotonic() - start, 3)
    metadata = {
        "execution_mode": "stream_monitored",
        "timeout_strategy": "total_plus_idle"
        if runtime_settings.idle_timeout_seconds is not None
        else "total_only",
        "total_timeout_seconds": runtime_settings.total_timeout_seconds,
        "idle_timeout_seconds": runtime_settings.idle_timeout_seconds,
        "stdout_line_count": len(stdout_lines),
        "stderr_line_count": len(stderr_lines),
        "duration_seconds": duration_seconds,
        "returncode": returncode,
    }
    if returncode != 0:
        raise ProviderError(
            stderr or stdout or "unknown provider error",
            kind="process_exit",
            metadata={**metadata, "command": full_command, "stderr": stderr},
        )
    return MonitoredProcessResult(stdout=stdout, stderr=stderr, metadata=metadata)


def _terminate_process(process: subprocess.Popen[str]) -> None:
    """Best-effort shutdown for a monitored provider subprocess."""

    if process.poll() is not None:
        return
    try:
        process.kill()
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        pass
