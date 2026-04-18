"""Provider adapter registry.

A single registry keeps the mapping from provider family name to adapter
factory so `cli/delegate.py` and `cli/discuss.py` no longer carry parallel
if-elif branches. Future adapters (OpenAIChatAdapter, local HTTP, etc.) only
need to register here.
"""

from __future__ import annotations

from collections.abc import Callable

from councilflow.models.config import ProviderRuntimeSettings
from councilflow.models.roles import normalize_model_name, resolve_adapter_model
from councilflow.providers.base import ProviderAdapter, ProviderError
from councilflow.providers.claude_code_cli import ClaudeCodeCliAdapter
from councilflow.providers.codex_cli import CodexCliAdapter
from councilflow.providers.gemini_cli import GeminiCliAdapter

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


REGISTRY: dict[str, AdapterFactory] = {
    "codex": _make_codex,
    "claude": _make_claude,
    "gemini": _make_gemini,
}


def register_adapter_factory(family: str, factory: AdapterFactory) -> None:
    """Register a new adapter factory. Intended for out-of-tree extensions."""

    REGISTRY[family] = factory


def resolve_adapter(
    model: str,
    runtime: ProviderRuntimeSettings | None = None,
) -> ProviderAdapter:
    """Resolve a provider adapter for the given model name.

    Raises a ProviderError(kind="adapter_missing") when no registered family
    can serve the request. The model string can be any alias accepted by
    normalize_model_name; specific variants (e.g. gemini-1.5-flash) resolve to
    the gemini family but are passed through to the adapter so it can pick the
    correct concrete backend.
    """

    normalized = normalize_model_name(model)
    family = resolve_adapter_model(model)
    factory = REGISTRY.get(family) if family else None
    if factory is None:
        raise ProviderError(
            f"No provider adapter is registered for model '{model}' "
            f"(normalized='{normalized}').",
            kind="adapter_missing",
        )
    # Pass the normalized name so the factory can use variant-style dispatch
    # without us having to special-case it here.
    return factory(normalized, runtime)
