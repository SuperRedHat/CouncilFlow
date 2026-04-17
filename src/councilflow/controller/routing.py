"""Routing helpers for discuss participants and role execution."""

from __future__ import annotations

from collections.abc import Sequence

from councilflow.config.schema import CouncilConfig
from councilflow.models.config import DiscussTargetResolution, RouteDecision
from councilflow.models.roles import ControllerName, RoleName, normalize_model_name


def select_discuss_models(
    explicit_models: Sequence[str] | None,
    config: CouncilConfig,
) -> tuple[list[str], str]:
    """Choose discuss participants from explicit args or project defaults."""

    if explicit_models is not None:
        return list(explicit_models), "explicit"
    return list(config.discussion.default_models), "project_default"


def resolve_discuss_models(
    requested_models: Sequence[str],
    controller: ControllerName,
) -> DiscussTargetResolution:
    """Normalize discuss targets, removing duplicates and the current controller."""

    normalized_models: list[str] = []
    ignored_models: list[str] = []
    seen_models: set[str] = set()
    controller_name = controller.value

    for model in requested_models:
        normalized = normalize_model_name(model)
        if not normalized:
            continue
        if normalized in seen_models:
            ignored_models.append(normalized)
            continue
        seen_models.add(normalized)
        normalized_models.append(normalized)

    external_models: list[str] = []
    controller_ignored = False
    for model in normalized_models:
        if model == controller_name:
            ignored_models.append(model)
            controller_ignored = True
            continue
        external_models.append(model)

    warning: str | None = None
    if not normalized_models:
        warning = (
            "No additional discuss models were provided or configured. "
            "Pass --models or set discussion.default_models in .council/config.yaml "
            "to start cross-model discussion."
        )
    elif controller_ignored and not external_models:
        warning = (
            "Requested discuss models matched the current controller. "
            "Specify a different model to start cross-model discussion."
        )

    return DiscussTargetResolution(
        requested_models=normalized_models,
        external_models=external_models,
        ignored_models=ignored_models,
        warning=warning,
    )


def route_role(
    role: RoleName,
    config: CouncilConfig,
    controller: ControllerName,
) -> RouteDecision:
    """Route a role either to the current controller or to the sidecar."""

    target_model = config.roles.for_role(role)
    if target_model == controller.value:
        return RouteDecision(
            role=role,
            controller=controller,
            target_model=target_model,
            via_sidecar=False,
            reason="Role is mapped to the active controller.",
        )

    return RouteDecision(
        role=role,
        controller=controller,
        target_model=target_model,
        via_sidecar=True,
        reason="Role is mapped to a non-controller model and must be delegated.",
    )
