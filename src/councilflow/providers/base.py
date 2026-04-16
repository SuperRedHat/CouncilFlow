"""Base provider interfaces for delegated execution."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel, Field

CommandRunner = Callable[[list[str], str], str]


class ProviderRequest(BaseModel):
    """Request payload sent to a provider adapter."""

    prompt: str
    context: dict[str, Any] = Field(default_factory=dict)


class ProviderResponse(BaseModel):
    """Response payload returned by a provider adapter."""

    model: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderError(RuntimeError):
    """Raised when a provider invocation fails."""


class ProviderAdapter(Protocol):
    """Minimal interface that provider adapters must implement."""

    model_name: str

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        """Send a prompt to the provider and return its response."""


def run_command(command: list[str], prompt: str) -> str:
    """Execute a CLI command with the prompt appended as the final argument."""

    completed = subprocess.run(
        [*command, prompt],
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or "unknown provider error"
        raise ProviderError(stderr)
    return completed.stdout.strip()

