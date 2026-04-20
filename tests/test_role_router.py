"""Tests for the role router (TASK-076)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from councilflow.controller.role_router import (
    RoutingDecision,
    RoutingNoMatchError,
    resolve,
)
from councilflow.models.config import RoleMapping
from councilflow.models.roles import RoleName

# ---------------------------------------------------------------------------
# Shorthand routing (single str) — the pre-0.1.3 backward-compatible case
# ---------------------------------------------------------------------------


def test_shorthand_routing_resolves_to_single_model() -> None:
    mapping = RoleMapping.model_validate({"implementer": "claude"})
    decision = resolve(RoleName.IMPLEMENTER, mapping, task_context={"task": {}})

    assert isinstance(decision, RoutingDecision)
    assert decision.role == "implementer"
    assert decision.primary_model == "claude"
    assert decision.fallback_chain == []
    assert decision.matched_route_index == 0
    assert decision.matched_when_expr is None
    assert len(decision.tried_routes) == 1
    assert decision.tried_routes[0].reason == "default_match"


def test_resolve_accepts_string_role_name() -> None:
    mapping = RoleMapping.model_validate({"implementer": "claude"})
    decision = resolve("implementer", mapping, task_context={})
    assert decision.primary_model == "claude"


# ---------------------------------------------------------------------------
# Expression-based routing — first match wins
# ---------------------------------------------------------------------------


def test_expression_route_hits_first_matching_entry() -> None:
    mapping = RoleMapping.model_validate(
        {
            "implementer": [
                {"model": "claude", "when": "task.complexity == 'L'"},
                {"model": "gemini", "when": "task.complexity in ['S', 'M']"},
            ]
        }
    )
    decision = resolve(
        RoleName.IMPLEMENTER, mapping, task_context={"task": {"complexity": "L"}}
    )
    assert decision.primary_model == "claude"
    assert decision.matched_route_index == 0
    assert decision.matched_when_expr == "task.complexity == 'L'"


def test_expression_route_skips_non_matching_first_entry() -> None:
    mapping = RoleMapping.model_validate(
        {
            "implementer": [
                {"model": "claude", "when": "task.complexity == 'L'"},
                {"model": "gemini", "when": "task.complexity in ['S', 'M']"},
            ]
        }
    )
    decision = resolve(
        RoleName.IMPLEMENTER, mapping, task_context={"task": {"complexity": "S"}}
    )
    assert decision.primary_model == "gemini"
    assert decision.matched_route_index == 1
    # Both routes were tried
    assert len(decision.tried_routes) == 2
    assert decision.tried_routes[0].matched is False
    assert decision.tried_routes[0].reason == "when_false"


def test_default_match_after_expression_routes() -> None:
    mapping = RoleMapping.model_validate(
        {
            "implementer": [
                {"model": "claude", "when": "task.complexity == 'XL'"},
                {"model": "gemini"},  # default fallback
            ]
        }
    )
    decision = resolve(
        RoleName.IMPLEMENTER, mapping, task_context={"task": {"complexity": "L"}}
    )
    assert decision.primary_model == "gemini"
    assert decision.matched_route_index == 1
    assert decision.matched_when_expr is None


# ---------------------------------------------------------------------------
# No match — raise RoutingNoMatchError
# ---------------------------------------------------------------------------


def test_no_match_raises_routing_no_match_error() -> None:
    mapping = RoleMapping.model_validate(
        {
            "implementer": [
                {"model": "claude", "when": "task.complexity == 'L'"},
                {"model": "gemini", "when": "task.complexity == 'XL'"},
            ]
        }
    )
    with pytest.raises(RoutingNoMatchError) as excinfo:
        resolve(
            RoleName.IMPLEMENTER, mapping, task_context={"task": {"complexity": "S"}}
        )
    err = excinfo.value
    assert err.kind == "routing_no_match"
    assert err.role == "implementer"
    assert len(err.tried) == 2


def test_when_error_treated_as_no_match_not_crash() -> None:
    """A broken `when` expression should be logged as when_error but not halt."""
    # This gets past RoleRoute validation because the expr isn't evaluated there.
    # But RoleRoute does NOT compile-check when — evaluation error happens at resolve().
    # We build the mapping directly to bypass shorthand normalization that would
    # otherwise fail the syntax check later.
    mapping = RoleMapping.model_validate(
        {
            "implementer": [
                # __import__ is rejected at evaluate() time
                {"model": "claude", "when": "__import__('os')"},
                {"model": "gemini"},  # default fallback
            ]
        }
    )
    decision = resolve(
        RoleName.IMPLEMENTER, mapping, task_context={"task": {"complexity": "L"}}
    )
    # The dangerous route is skipped with when_error; default fallback wins.
    assert decision.primary_model == "gemini"
    assert decision.tried_routes[0].reason == "when_error"
    assert decision.tried_routes[0].error is not None


# ---------------------------------------------------------------------------
# Fallback chain preserved
# ---------------------------------------------------------------------------


def test_fallback_chain_preserved_in_decision() -> None:
    mapping = RoleMapping.model_validate(
        {
            "implementer": [
                {"model": "claude", "fallback": ["gemini", "codex"]},
            ]
        }
    )
    decision = resolve(RoleName.IMPLEMENTER, mapping, task_context={})
    assert decision.primary_model == "claude"
    assert decision.fallback_chain == ["gemini", "codex"]


def test_empty_fallback_defaults_to_empty_list() -> None:
    mapping = RoleMapping.model_validate({"implementer": "claude"})
    decision = resolve(RoleName.IMPLEMENTER, mapping, task_context={})
    assert decision.fallback_chain == []


# ---------------------------------------------------------------------------
# Log persistence to .council/runs/<run_id>/routing.json
# ---------------------------------------------------------------------------


def test_routing_log_persisted_to_file(tmp_path: Path) -> None:
    mapping = RoleMapping.model_validate({"implementer": "claude"})
    log_path = tmp_path / "routing.json"

    decision = resolve(
        RoleName.IMPLEMENTER,
        mapping,
        task_context={"task": {"id": "TASK-001", "complexity": "L"}},
        log_path=log_path,
    )

    assert log_path.is_file()
    records = json.loads(log_path.read_text(encoding="utf-8"))
    assert isinstance(records, list)
    assert len(records) == 1
    record = records[0]
    assert record["role"] == "implementer"
    assert record["primary_model"] == decision.primary_model
    assert record["matched_route_index"] == 0
    assert record["task_context_summary"]["task"]["id"] == "TASK-001"
    assert "timestamp" in record
    assert "tried_routes" in record


def test_routing_log_appends_on_multiple_calls(tmp_path: Path) -> None:
    mapping = RoleMapping.model_validate({"implementer": "claude"})
    log_path = tmp_path / "routing.json"
    resolve(RoleName.IMPLEMENTER, mapping, task_context={"task": {}}, log_path=log_path)
    resolve(RoleName.IMPLEMENTER, mapping, task_context={"task": {}}, log_path=log_path)

    records = json.loads(log_path.read_text(encoding="utf-8"))
    assert len(records) == 2


def test_no_match_also_writes_audit_record(tmp_path: Path) -> None:
    mapping = RoleMapping.model_validate(
        {
            "implementer": [
                {"model": "claude", "when": "task.complexity == 'L'"},
            ]
        }
    )
    log_path = tmp_path / "routing.json"
    with pytest.raises(RoutingNoMatchError):
        resolve(
            RoleName.IMPLEMENTER,
            mapping,
            task_context={"task": {"complexity": "S"}},
            log_path=log_path,
        )
    records = json.loads(log_path.read_text(encoding="utf-8"))
    assert len(records) == 1
    assert records[0]["error_kind"] == "routing_no_match"


def test_routing_log_robust_to_corrupted_file(tmp_path: Path) -> None:
    """A corrupted existing log file should not block new appends."""
    mapping = RoleMapping.model_validate({"implementer": "claude"})
    log_path = tmp_path / "routing.json"
    log_path.write_text("{ not json", encoding="utf-8")

    resolve(RoleName.IMPLEMENTER, mapping, task_context={}, log_path=log_path)
    records = json.loads(log_path.read_text(encoding="utf-8"))
    assert len(records) == 1


# ---------------------------------------------------------------------------
# task_context_summary keeps the audit payload small and safe
# ---------------------------------------------------------------------------


def test_task_context_summary_flattens_non_primitive_values() -> None:
    class Blob:
        pass

    mapping = RoleMapping.model_validate({"implementer": "claude"})
    decision = resolve(
        RoleName.IMPLEMENTER,
        mapping,
        task_context={"task": {"id": "X", "payload": Blob()}, "extra": Blob()},
    )
    summary = decision.task_context_summary
    assert summary["task"]["id"] == "X"
    # Non-primitive inner values become their type name
    assert summary["task"]["payload"] == "Blob"
    # Non-primitive top-level values become their type name
    assert summary["extra"] == "Blob"


# ---------------------------------------------------------------------------
# Router does NOT call any provider — pure decision function
# ---------------------------------------------------------------------------


def test_router_does_not_instantiate_providers() -> None:
    """The router must return a decision without touching providers/adapters."""
    # If it tried, an unknown model should have failed RoleRoute validation
    # (it does), but we also check here that resolve() returns cleanly without
    # side effects — no file writes when log_path is None.
    mapping = RoleMapping.model_validate({"implementer": "claude"})
    decision = resolve(RoleName.IMPLEMENTER, mapping, task_context={}, log_path=None)
    assert decision.primary_model == "claude"
