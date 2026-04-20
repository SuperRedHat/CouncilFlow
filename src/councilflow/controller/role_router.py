"""Role router: pick a target model for a role based on RoleMapping.

The router evaluates the ordered list of :class:`RoleRoute` entries for
the requested role against a task context dict, using the restricted
:func:`councilflow.config.when_eval.evaluate` to match ``when``
conditions. The first route whose ``when`` is ``None`` or evaluates to
True wins; its ``fallback`` list becomes the secondary attempt chain
for the downstream adapter caller.

Routing decisions are append-only audit records written to
``<project_root>/.council/runs/<run_id>/routing.json`` when a path is
supplied; the file is plain JSON (array of decision records) so that
``council status`` and external tooling can read it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from councilflow.config.when_eval import WhenExpressionError, evaluate
from councilflow.models.config import RoleMapping, RoleRoute
from councilflow.models.roles import RoleName


class RoutingNoMatchError(Exception):
    """Raised when no RoleRoute matches the current task context.

    The `kind` attribute is ``"routing_no_match"`` by contract (see
    ``docs/integration.md``). Callers should surface it as a structured
    error with this kind to downstream workflows.
    """

    kind: str = "routing_no_match"

    def __init__(
        self,
        role: str,
        tried: list[dict[str, Any]],
        task_context: dict[str, Any] | None = None,
    ) -> None:
        self.role = role
        self.tried = tried
        self.task_context = task_context or {}
        super().__init__(
            f"No RoleRoute matched for role `{role}` "
            f"({len(tried)} route(s) evaluated)."
        )


@dataclass
class RouteAttempt:
    """One entry in the `tried_routes` audit log for a single resolve() call."""

    index: int
    model: str
    when: str | None
    matched: bool
    reason: str  # "default_match" / "when_true" / "when_false" / "when_error"
    error: str | None = None


@dataclass
class RoutingDecision:
    """Result of :func:`resolve` for one role resolution request.

    Attributes
    ----------
    role:
        The role name (enum value, e.g. ``"implementer"``).
    primary_model:
        Target model chosen by the first matching route. Never ``None``
        on success — a no-match case raises :class:`RoutingNoMatchError`.
    fallback_chain:
        Additional models to try if the primary adapter call fails.
        Ordered from most preferred to least.
    matched_route_index:
        The 0-based index of the matching entry inside the role's
        ``routes_for_role()`` list.
    matched_when_expr:
        The matching route's ``when`` source (or ``None`` for a default
        match).
    tried_routes:
        Full audit trail of every route evaluated before the match was
        found, in order.
    task_context_summary:
        Shallow copy of the task context keys used for routing. Kept
        small to avoid bloating audit artifacts; attribute values are
        stringified.
    """

    role: str
    primary_model: str
    fallback_chain: list[str]
    matched_route_index: int
    matched_when_expr: str | None
    tried_routes: list[RouteAttempt] = field(default_factory=list)
    task_context_summary: dict[str, Any] = field(default_factory=dict)

    def to_log_record(self) -> dict[str, Any]:
        """Serialize this decision as a JSON-safe audit record."""

        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "role": self.role,
            "primary_model": self.primary_model,
            "fallback_chain": list(self.fallback_chain),
            "matched_route_index": self.matched_route_index,
            "matched_when_expr": self.matched_when_expr,
            "tried_routes": [asdict(a) for a in self.tried_routes],
            "task_context_summary": self.task_context_summary,
        }


def _summarize_task_context(task_context: dict[str, Any] | None) -> dict[str, Any]:
    """Produce a small, JSON-safe summary of task_context for audit logs."""

    if not task_context:
        return {}
    summary: dict[str, Any] = {}
    for key, value in task_context.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            summary[key] = value
        elif isinstance(value, dict):
            inner: dict[str, Any] = {}
            for k, v in value.items():
                if isinstance(v, (str, int, float, bool)) or v is None:
                    inner[k] = v
                else:
                    inner[k] = type(v).__name__
            summary[key] = inner
        else:
            summary[key] = type(value).__name__
    return summary


def _evaluate_route(
    route: RoleRoute, context: dict[str, Any]
) -> tuple[bool, str, str | None]:
    """Evaluate a single route's ``when`` condition.

    Returns a tuple ``(matched, reason, error)``:
    - ``matched``: True if the route should be selected.
    - ``reason``: ``"default_match"`` (when is None), ``"when_true"``,
      ``"when_false"``, or ``"when_error"``.
    - ``error``: ``None`` unless the ``when`` expression raised
      :class:`WhenExpressionError`, in which case the message is stored.
    """

    if route.when is None:
        return True, "default_match", None
    try:
        result = evaluate(route.when, context)
    except WhenExpressionError as err:
        return False, "when_error", str(err)
    return (True, "when_true", None) if result else (False, "when_false", None)


def resolve(
    role: RoleName | str,
    role_mapping: RoleMapping,
    task_context: dict[str, Any] | None = None,
    *,
    log_path: Path | None = None,
) -> RoutingDecision:
    """Pick the first matching route for ``role`` and return a decision.

    Parameters
    ----------
    role:
        Role to resolve. Accepts either a :class:`RoleName` enum value
        or its string value.
    role_mapping:
        The project's ``RoleMapping`` instance (typically
        ``CouncilConfig.roles``).
    task_context:
        Dict passed to the ``when`` evaluator. By convention should
        include a ``"task"`` key whose value is a dict with task fields
        like ``complexity`` / ``module`` / ``id``. May be ``None`` or
        empty, in which case only routes with ``when=None`` will match.
    log_path:
        If provided, append this decision's JSON record to the given
        file (creating parents if needed). Typical value:
        ``<repo_root>/.council/runs/<run_id>/routing.json``.

    Returns
    -------
    RoutingDecision
        Holds primary_model, fallback_chain, matched_route_index,
        matched_when_expr, full tried_routes audit, and a shallow
        task_context_summary.

    Raises
    ------
    RoutingNoMatchError
        If no route matches or the role has no configured routes.
    """

    role_str = role.value if isinstance(role, RoleName) else str(role)
    # Fetch routes via the mapping's public API so shorthand configs
    # work transparently (returned as a single-entry list).
    try:
        if isinstance(role, RoleName):
            routes = role_mapping.routes_for_role(role)
        else:
            # Map string to RoleName if possible.
            routes = role_mapping.routes_for_role(RoleName(role_str))
    except (AttributeError, ValueError) as err:
        raise RoutingNoMatchError(
            role=role_str,
            tried=[],
            task_context=_summarize_task_context(task_context),
        ) from err

    context = task_context or {}
    ctx_summary = _summarize_task_context(context)
    tried: list[RouteAttempt] = []

    for idx, route in enumerate(routes):
        matched, reason, error = _evaluate_route(route, context)
        tried.append(
            RouteAttempt(
                index=idx,
                model=route.model,
                when=route.when,
                matched=matched,
                reason=reason,
                error=error,
            )
        )
        if matched:
            decision = RoutingDecision(
                role=role_str,
                primary_model=route.model,
                fallback_chain=list(route.fallback or []),
                matched_route_index=idx,
                matched_when_expr=route.when,
                tried_routes=tried,
                task_context_summary=ctx_summary,
            )
            if log_path is not None:
                _append_routing_log(log_path, decision)
            return decision

    # All routes evaluated, none matched.
    if log_path is not None:
        _append_no_match_log(log_path, role_str, tried, ctx_summary)
    raise RoutingNoMatchError(
        role=role_str,
        tried=[asdict(a) for a in tried],
        task_context=ctx_summary,
    )


def _append_routing_log(log_path: Path, decision: RoutingDecision) -> None:
    """Append a successful routing decision to the audit JSON array file."""

    _append_record(log_path, decision.to_log_record())


def _append_no_match_log(
    log_path: Path,
    role: str,
    tried: list[RouteAttempt],
    ctx_summary: dict[str, Any],
) -> None:
    """Append a no-match record so failures are also audited."""

    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "role": role,
        "primary_model": None,
        "fallback_chain": [],
        "matched_route_index": None,
        "matched_when_expr": None,
        "tried_routes": [asdict(a) for a in tried],
        "task_context_summary": ctx_summary,
        "error_kind": "routing_no_match",
    }
    _append_record(log_path, record)


def _append_record(log_path: Path, record: dict[str, Any]) -> None:
    """Append `record` to a JSON file holding a top-level array."""

    log_path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[Any] = []
    if log_path.is_file():
        try:
            text = log_path.read_text(encoding="utf-8")
            if text.strip():
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    existing = parsed
        except (OSError, json.JSONDecodeError):
            existing = []
    existing.append(record)
    log_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


__all__ = [
    "RouteAttempt",
    "RoutingDecision",
    "RoutingNoMatchError",
    "resolve",
]
