"""Tests for RoleMapping / RoleRoute / Discussion schema extensions (TASK-074)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from councilflow.models.config import DiscussionSettings, RoleMapping, RoleRoute
from councilflow.models.roles import RoleName

# ---------------------------------------------------------------------------
# RoleRoute
# ---------------------------------------------------------------------------


def test_role_route_from_plain_dict() -> None:
    route = RoleRoute.model_validate({"model": "claude"})
    assert route.model == "claude"
    assert route.when is None
    assert route.fallback is None


def test_role_route_with_when_and_fallback() -> None:
    route = RoleRoute.model_validate(
        {"model": "claude", "when": "task.complexity == 'L'", "fallback": ["gemini"]}
    )
    assert route.model == "claude"
    assert route.when == "task.complexity == 'L'"
    assert route.fallback == ["gemini"]


def test_role_route_fallback_single_string_is_wrapped_to_list() -> None:
    route = RoleRoute.model_validate({"model": "claude", "fallback": "gemini"})
    assert route.fallback == ["gemini"]


def test_role_route_when_whitespace_becomes_none() -> None:
    route = RoleRoute.model_validate({"model": "claude", "when": "   "})
    assert route.when is None


def test_role_route_rejects_unknown_model() -> None:
    with pytest.raises(ValidationError):
        RoleRoute.model_validate({"model": "not-a-real-model-xxx"})


def test_role_route_rejects_empty_model() -> None:
    with pytest.raises(ValidationError):
        RoleRoute.model_validate({"model": ""})


def test_role_route_rejects_empty_fallback_entry() -> None:
    with pytest.raises(ValidationError):
        RoleRoute.model_validate({"model": "claude", "fallback": [""]})


def test_role_route_normalizes_model_case() -> None:
    route = RoleRoute.model_validate({"model": "Claude"})
    # validate_model_name lowercases known model names
    assert route.model == "claude"


# ---------------------------------------------------------------------------
# RoleMapping — shorthand (str) vs list form
# ---------------------------------------------------------------------------


def test_rolemapping_shorthand_string_normalizes_to_single_route() -> None:
    mapping = RoleMapping.model_validate({"implementer": "gemini"})
    routes = mapping.routes_for_role(RoleName.IMPLEMENTER)
    assert len(routes) == 1
    assert routes[0].model == "gemini"
    assert routes[0].when is None
    assert routes[0].fallback is None


def test_rolemapping_list_form_preserves_order_and_fields() -> None:
    mapping = RoleMapping.model_validate(
        {
            "implementer": [
                {"model": "claude", "when": "task.complexity == 'L'"},
                {"model": "gemini", "fallback": ["claude"]},
            ]
        }
    )
    routes = mapping.routes_for_role(RoleName.IMPLEMENTER)
    assert len(routes) == 2
    assert routes[0].model == "claude"
    assert routes[0].when == "task.complexity == 'L'"
    assert routes[1].model == "gemini"
    assert routes[1].fallback == ["claude"]


def test_rolemapping_list_with_shorthand_string_entries() -> None:
    mapping = RoleMapping.model_validate({"implementer": ["claude", "gemini"]})
    routes = mapping.routes_for_role(RoleName.IMPLEMENTER)
    assert [r.model for r in routes] == ["claude", "gemini"]
    assert all(r.when is None for r in routes)


def test_rolemapping_rejects_empty_list() -> None:
    with pytest.raises(ValidationError):
        RoleMapping.model_validate({"implementer": []})


def test_rolemapping_rejects_null() -> None:
    with pytest.raises(ValidationError):
        RoleMapping.model_validate({"implementer": None})


def test_rolemapping_rejects_unknown_model_in_shorthand() -> None:
    with pytest.raises(ValidationError):
        RoleMapping.model_validate({"implementer": "not-a-real-model-xxx"})


def test_rolemapping_rejects_unknown_model_in_list() -> None:
    with pytest.raises(ValidationError):
        RoleMapping.model_validate(
            {"implementer": [{"model": "not-a-real-model-xxx"}]}
        )


# ---------------------------------------------------------------------------
# RoleMapping — public API
# ---------------------------------------------------------------------------


def test_for_role_returns_primary_model_of_first_route() -> None:
    mapping = RoleMapping.model_validate(
        {
            "implementer": [
                {"model": "claude", "when": "task.complexity == 'L'"},
                {"model": "gemini"},
            ]
        }
    )
    assert mapping.for_role(RoleName.IMPLEMENTER) == "claude"


def test_routes_for_role_returns_independent_copy() -> None:
    mapping = RoleMapping.model_validate({"implementer": "claude"})
    first = mapping.routes_for_role(RoleName.IMPLEMENTER)
    second = mapping.routes_for_role(RoleName.IMPLEMENTER)
    # different list objects, same contents
    assert first is not second
    assert [r.model for r in first] == [r.model for r in second]


# ---------------------------------------------------------------------------
# Backward compatibility — existing shorthand-only configs load unchanged
# ---------------------------------------------------------------------------


def test_backward_compat_full_shorthand_config_loads() -> None:
    """Equivalent to current .council/config.yaml shape before 0.1.3."""
    mapping = RoleMapping.model_validate(
        {
            "planner": "codex",
            "architect": "codex",
            "implementer": "claude",
            "tester": "claude",
            "reviewer": "codex",
            "fixer": "codex",
            "advisor": "claude",
            "synthesizer": "codex",
        }
    )
    for role, expected in [
        (RoleName.PLANNER, "codex"),
        (RoleName.ARCHITECT, "codex"),
        (RoleName.IMPLEMENTER, "claude"),
        (RoleName.TESTER, "claude"),
        (RoleName.REVIEWER, "codex"),
        (RoleName.FIXER, "codex"),
        (RoleName.ADVISOR, "claude"),
        (RoleName.SYNTHESIZER, "codex"),
    ]:
        assert mapping.for_role(role) == expected
        # internal representation is list[RoleRoute] with single entry
        routes = mapping.routes_for_role(role)
        assert len(routes) == 1
        assert routes[0].when is None
        assert routes[0].fallback is None


def test_backward_compat_partial_shorthand_uses_template_defaults() -> None:
    """Partial input is filled in from the packaged template default."""
    mapping = RoleMapping.model_validate({"planner": "gemini"})
    assert mapping.for_role(RoleName.PLANNER) == "gemini"
    # Others fall back to the template
    assert mapping.for_role(RoleName.IMPLEMENTER)  # at least loads


# ---------------------------------------------------------------------------
# DiscussionSettings — existing behavior stays
# ---------------------------------------------------------------------------


def test_discussion_settings_backward_compat_defaults() -> None:
    settings = DiscussionSettings.model_validate({})
    assert settings.default_models == []
    assert settings.min_rounds == 1
    assert settings.max_rounds == 5
