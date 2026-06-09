"""Shared enums and helpers for controllers, roles, and model names."""

from __future__ import annotations

from enum import StrEnum


class ControllerName(StrEnum):
    """Supported controller environments."""

    CODEX = "codex"
    CLAUDE = "claude"
    GEMINI = "gemini"


class RoleName(StrEnum):
    """Supported execution roles in CouncilFlow."""

    PLANNER = "planner"
    ARCHITECT = "architect"
    IMPLEMENTER = "implementer"
    TESTER = "tester"
    REVIEWER = "reviewer"
    FIXER = "fixer"
    ADVISOR = "advisor"
    SYNTHESIZER = "synthesizer"


def _default_role_models() -> dict[RoleName, str]:
    """Return the default role->model mapping derived from the packaged template."""

    # Imported lazily to avoid a circular import between models.roles and
    # config.loader (loader imports CouncilConfig which imports models.config,
    # which imports RoleName from this module).
    from councilflow.config.loader import default_role_mapping_payload

    payload = default_role_mapping_payload()
    return {RoleName(role): model for role, model in payload.items()}


# Legacy export retained as a deprecated alias — prefer _default_role_models()
# or RoleMapping.model_validate({}) so the template stays the single source of
# truth. See PRD §29.1.
class _DeprecatedDefaultRoleModels(dict[RoleName, str]):
    """Dict proxy that lazily reflects the packaged template defaults."""

    def __init__(self) -> None:
        super().__init__()

    def _refresh(self) -> None:
        super().clear()
        super().update(_default_role_models())

    def __getitem__(self, key: RoleName) -> str:  # type: ignore[override]
        self._refresh()
        return super().__getitem__(key)

    def __iter__(self):  # type: ignore[override]
        self._refresh()
        return super().__iter__()

    def items(self):  # type: ignore[override]
        self._refresh()
        return super().items()

    def keys(self):  # type: ignore[override]
        self._refresh()
        return super().keys()

    def values(self):  # type: ignore[override]
        self._refresh()
        return super().values()


DEFAULT_ROLE_MODELS: dict[RoleName, str] = _DeprecatedDefaultRoleModels()

MODEL_ALIASES: dict[str, str] = {
    # Controller CLI aliases → family name (the CLI itself, no variant info).
    # These are for dedup semantics in discuss / delegate when the user writes
    # the CLI's marketing name instead of the bare family name.
    "claude-code": ControllerName.CLAUDE.value,
    "claudecode": ControllerName.CLAUDE.value,
    "claude code": ControllerName.CLAUDE.value,
    "gemini-cli": ControllerName.GEMINI.value,
    "gemini cli": ControllerName.GEMINI.value,
    "google-gemini": ControllerName.GEMINI.value,
    "google gemini": ControllerName.GEMINI.value,
    "google": ControllerName.GEMINI.value,
    # Short variant names → family-variant form (preserve the variant).
    # A user writing `tester: haiku` gets routed to `claude-haiku` which in
    # turn flows through the adapter's `--model haiku` flag. Mapping these
    # to bare `claude` would lose the variant — which is exactly the 0.1.3
    # gap TASK-094 closes.
    "haiku": "claude-haiku",
    "sonnet": "claude-sonnet",
    "opus": "claude-opus",
}


def normalize_model_name(value: str) -> str:
    """Normalize model names for routing and discuss comparisons.

    Aliases that preserve variant info (like ``haiku → claude-haiku``) map to
    the canonical ``family-variant`` form so downstream layers
    (``resolve_adapter_model``, ``ClaudeCodeCliAdapter``, etc.) see a
    consistent name. Aliases that are just "this CLI marketing name equals
    this family" (like ``claude-code → claude``) collapse to the bare
    family name.
    """

    normalized = value.strip().lower()
    return MODEL_ALIASES.get(normalized, normalized)


_REGISTERED_ADAPTER_MODELS: frozenset[str] = frozenset(
    {
        ControllerName.CODEX.value,
        ControllerName.CLAUDE.value,
        ControllerName.GEMINI.value,
        "gpt",
    }
)


def resolve_adapter_model(value: str) -> str | None:
    """Return the adapter-ready model name, or None when no adapter is known.

    Family-variant names (``family-<variant>``) are accepted generically via
    a prefix rule so that new provider variants released by upstream CLIs
    (e.g. a hypothetical ``claude-sonnet-5``) work without a CouncilFlow
    patch. The adapter layer decides how to pass ``<variant>`` through to
    the target CLI (typically a ``--model <variant>`` flag).
    """

    normalized = normalize_model_name(value)
    if normalized in _REGISTERED_ADAPTER_MODELS:
        return normalized
    # Accept specific Claude variants (claude-haiku, claude-sonnet, claude-opus,
    # claude-3-5-sonnet, claude-sonnet-4-6, etc.). The Claude adapter passes
    # the variant through as `--model <variant>` to Claude Code CLI, which
    # resolves the exact model internally. We do not gate on specific known
    # Anthropic model versions because those change outside CouncilFlow's
    # release cadence.
    if normalized.startswith("claude-") and normalized != "claude-":
        return normalized
    # Accept specific Gemini variants (gemini-1.5-flash, gemini-2.5-pro, ...).
    if normalized.startswith("gemini-") and normalized != "gemini-":
        return normalized
    # Accept specific OpenAI variants (gpt-4o, gpt-4o-mini, o1-preview, ...).
    if normalized.startswith("gpt-") or normalized.startswith("o1-"):
        return normalized
    return None


def validate_model_name(value: str) -> str:
    """Normalize a configured model name and reject any unregistered target.

    Raises ValueError with an actionable message when no adapter can serve the
    model. This pushes the failure to config-load time instead of later at
    `council delegate` execution.
    """

    resolved = resolve_adapter_model(value)
    if resolved is None:
        raise ValueError(
            f"Unknown model '{value}'. No provider adapter is registered for it. "
            "Supported: codex, claude, gemini (plus gemini-<variant> aliases)."
        )
    return resolved


# ---------------------------------------------------------------------------
# Controller sentinel. A role mapped to the literal `controller` follows
# whoever is driving CouncilFlow (the active controller). Because the role and
# the controller are then the same model, execution stays LOCAL — the
# controller runs it directly and no sidecar is started. The sentinel is
# resolved to the concrete controller model at routing time
# (`build_route_decision`), not at config-load time (the controller is a
# runtime signal). It is a roles-only concept: discuss models, fallbacks, and
# provider settings keep using `validate_model_name` (concrete models only).
# ---------------------------------------------------------------------------
CONTROLLER_SENTINEL = "controller"


def is_controller_sentinel(value: str) -> bool:
    """Return True when `value` is the `controller` sentinel (case-insensitive)."""

    return normalize_model_name(value) == CONTROLLER_SENTINEL


def validate_role_model_name(value: str) -> str:
    """Validate a *role* model name, additionally accepting the `controller`
    sentinel (role follows the active controller). For role primary models only;
    fallbacks / discuss models keep requiring a concrete registered model.
    """

    if is_controller_sentinel(value):
        return CONTROLLER_SENTINEL
    return validate_model_name(value)
