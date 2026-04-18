"""Provider adapter registry.

A single registry keeps the mapping from provider family name to adapter
factory so `cli/delegate.py` and `cli/discuss.py` no longer carry parallel
if-elif branches. Future adapters (OpenAIChatAdapter, local HTTP, etc.) only
need to register here.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from councilflow.models.config import ProviderRuntimeSettings
from councilflow.models.roles import normalize_model_name
from councilflow.providers.base import ProviderAdapter, ProviderError
from councilflow.providers.claude_code_cli import ClaudeCodeCliAdapter
from councilflow.providers.codex_cli import CodexCliAdapter
from councilflow.providers.gemini_cli import GeminiCliAdapter
from councilflow.providers.openai_api import OpenAIChatAdapter

AdapterFactory = Callable[[str, ProviderRuntimeSettings | None], ProviderAdapter]


def _make_codex(model: str, runtime: ProviderRuntimeSettings | None) -> ProviderAdapter:
    return CodexCliAdapter(runtime=runtime)


def _make_claude(model: str, runtime: ProviderRuntimeSettings | None) -> ProviderAdapter:
    return ClaudeCodeCliAdapter(runtime=runtime)


def _make_gemini(model: str, runtime: ProviderRuntimeSettings | None) -> ProviderAdapter:
    # Preserve the original variant (e.g. gemini-1.5-flash) so the Gemini CLI
    # can be invoked with --model <variant>. The adapter itself normalizes
    # ProviderResponse.model back to "gemini".
    variant = (
        model
        if model.startswith("gemini-") and model != "gemini-cli"
        else None
    )
    return GeminiCliAdapter(model=variant, runtime=runtime)


def _make_openai(model: str, runtime: ProviderRuntimeSettings | None) -> ProviderAdapter:
    # The normalized family name is "gpt"; the concrete OpenAI model is only
    # taken from an explicit "gpt-<...>" alias. Anything else defaults to the
    # cheapest reasonable fallback so the user does not pay for gpt-4 by
    # accident. Set OPENAI_MODEL to override from the environment.
    if model != "gpt" and model.startswith("gpt-"):
        openai_model = model
    else:
        openai_model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    return OpenAIChatAdapter(model=openai_model, runtime=runtime)


REGISTRY: dict[str, AdapterFactory] = {
    "codex": _make_codex,
    "claude": _make_claude,
    "gemini": _make_gemini,
    "gpt": _make_openai,
}


def register_adapter_factory(family: str, factory: AdapterFactory) -> None:
    """Register a new adapter factory. Intended for out-of-tree extensions."""

    REGISTRY[family] = factory


def _family_for_normalized(normalized: str) -> str | None:
    """Collapse a normalized model name to its adapter family."""

    if normalized in REGISTRY:
        return normalized
    if normalized.startswith("gemini-"):
        return "gemini"
    if normalized.startswith("gpt-") or normalized.startswith("o1-"):
        return "gpt"
    return None


def resolve_adapter(
    model: str,
    runtime: ProviderRuntimeSettings | None = None,
) -> ProviderAdapter:
    """Resolve a provider adapter for the given model name.

    Raises a ProviderError(kind="adapter_missing") when no registered family
    can serve the request. The model string can be any alias accepted by
    normalize_model_name; specific variants (e.g. gemini-1.5-flash, gpt-4o)
    resolve to the gemini / gpt family but are passed through to the factory
    so it can pick the concrete backend.
    """

    normalized = normalize_model_name(model)
    family = _family_for_normalized(normalized)
    # Guard: roles.resolve_adapter_model already vets unknown names, but keep
    # a defensive None-check so that adapters not actually registered (for
    # example if an out-of-tree build deletes 'gpt' from REGISTRY) still
    # produce the canonical adapter_missing error.
    if family is None or family not in REGISTRY:
        raise ProviderError(
            f"No provider adapter is registered for model '{model}' "
            f"(normalized='{normalized}').",
            kind="adapter_missing",
        )
    return REGISTRY[family](normalized, runtime)
