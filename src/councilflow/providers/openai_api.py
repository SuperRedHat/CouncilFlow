"""Optional OpenAI Chat adapter used for `advisor` style roles.

The adapter is opt-in: the `openai` SDK is listed as an extra (``pip install
councilflow[openai]``) so projects that never route any role to ``gpt`` never
pay the dependency cost. When the SDK is not installed the adapter raises a
structured ``ProviderError(kind="environment_not_ready")`` on the first
``ask`` call so the downstream delegation failure is classified the same way
as a missing CLI.

The adapter does not run a subprocess; it talks to the OpenAI API directly.
That means TASK-043's sidecar workspace and TASK-044's env scrubbing are
informational only here — there is no child process to receive ``cwd`` or a
scrubbed environment. The adapter still accepts those request fields so the
call site can stay uniform.
"""

from __future__ import annotations

import os
from typing import Any

from councilflow.models.config import ProviderRuntimeSettings
from councilflow.providers.base import (
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    default_runtime_settings,
)


class OpenAIChatAdapter:
    """Opt-in OpenAI Chat Completions adapter for non-controller advisor roles."""

    model_name = "gpt"

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        runtime: ProviderRuntimeSettings | None = None,
        api_key_env: str = "OPENAI_API_KEY",
        client: Any | None = None,
    ) -> None:
        self.openai_model = model
        self.runtime = runtime or default_runtime_settings()
        self.api_key_env = api_key_env
        self._injected_client = client

    def _resolve_client(self) -> Any:
        if self._injected_client is not None:
            return self._injected_client

        try:
            from openai import OpenAI  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ProviderError(
                "openai SDK is not installed. Install with: "
                "pip install 'councilflow[openai]'",
                kind="environment_not_ready",
                metadata={"sdk": "openai"},
            ) from exc

        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise ProviderError(
                f"{self.api_key_env} environment variable is not set.",
                kind="environment_not_ready",
                metadata={"env_key": self.api_key_env},
            )

        return OpenAI(
            api_key=api_key,
            timeout=self.runtime.total_timeout_seconds,
        )

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        client = self._resolve_client()
        try:
            response = client.chat.completions.create(
                model=self.openai_model,
                messages=[{"role": "user", "content": request.prompt}],
            )
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - forward structured
            raise ProviderError(
                str(exc),
                kind="process_exit",
                metadata={"openai_model": self.openai_model},
            ) from exc

        content = ""
        if getattr(response, "choices", None):
            choice = response.choices[0]
            message = getattr(choice, "message", None)
            if message is not None:
                content = getattr(message, "content", "") or ""

        usage = getattr(response, "usage", None)
        usage_dict: dict[str, Any] | None
        if usage is None:
            usage_dict = None
        elif hasattr(usage, "model_dump"):
            usage_dict = usage.model_dump()
        elif hasattr(usage, "__dict__"):
            usage_dict = dict(usage.__dict__)
        else:
            usage_dict = None

        metadata: dict[str, Any] = {
            "openai_model": self.openai_model,
            "execution_mode": "api",
            "total_timeout_seconds": self.runtime.total_timeout_seconds,
        }
        if usage_dict is not None:
            metadata["usage"] = usage_dict

        return ProviderResponse(
            model=self.model_name,
            content=content.strip(),
            metadata=metadata,
        )
