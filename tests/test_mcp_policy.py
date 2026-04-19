"""Tests for the delegated-role MCP access policy."""

from __future__ import annotations

import json
from pathlib import Path

from councilflow.models.roles import RoleName
from councilflow.providers.mcp_policy import (
    ROLES_WITH_MCP_ACCESS,
    build_mcp_denied_env,
    plan_mcp_policy,
    role_allows_mcp,
    write_empty_mcp_configs,
)


def test_execution_roles_denied_by_default() -> None:
    for role in (
        RoleName.IMPLEMENTER,
        RoleName.TESTER,
        RoleName.REVIEWER,
        RoleName.FIXER,
        RoleName.ADVISOR,
    ):
        assert role_allows_mcp(role) is False, f"{role} should be denied"


def test_controller_facing_roles_allowed() -> None:
    for role in (RoleName.ARCHITECT, RoleName.PLANNER, RoleName.SYNTHESIZER):
        assert role_allows_mcp(role) is True, f"{role} should be allowed"


def test_allowed_roles_frozenset_exposes_policy() -> None:
    assert RoleName.SYNTHESIZER in ROLES_WITH_MCP_ACCESS
    assert RoleName.IMPLEMENTER not in ROLES_WITH_MCP_ACCESS


def test_write_empty_mcp_configs_creates_three_cli_settings(tmp_path: Path) -> None:
    written = write_empty_mcp_configs(tmp_path)
    paths = [p for p in written]

    assert tmp_path / ".claude" / "settings.json" in paths
    assert tmp_path / ".codex" / "settings.json" in paths
    assert tmp_path / ".gemini" / "settings.json" in paths

    for path in paths:
        content = json.loads(path.read_text(encoding="utf-8"))
        assert content == {"mcpServers": {}}


def test_build_mcp_denied_env_returns_expected_hints(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    workspace = tmp_path / "workspace"
    project_root.mkdir()
    workspace.mkdir()

    env = build_mcp_denied_env(project_root, workspace)

    assert env["COUNCILFLOW_MCP_POLICY"] == "deny"
    assert env["COUNCILFLOW_MCP_SOURCE_PROJECT"] == str(project_root)
    assert env["CLAUDE_PROJECT_DIR"] == str(workspace)
    assert env["CODEX_PROJECT_DIR"] == str(workspace)
    assert env["GEMINI_PROJECT_DIR"] == str(workspace)


def test_plan_mcp_policy_for_denied_role(tmp_path: Path) -> None:
    plan = plan_mcp_policy(RoleName.IMPLEMENTER, tmp_path, tmp_path / "wt")

    assert plan["role"] == "implementer"
    assert plan["allows_mcp"] is False
    assert plan["denied_by_policy"] is True
    assert plan["worktree_settings_written"] is True
    assert "COUNCILFLOW_MCP_POLICY" in plan["env_hints"]


def test_plan_mcp_policy_for_allowed_role(tmp_path: Path) -> None:
    plan = plan_mcp_policy(RoleName.SYNTHESIZER, tmp_path, tmp_path / "wt")

    assert plan["role"] == "synthesizer"
    assert plan["allows_mcp"] is True
    assert plan["denied_by_policy"] is False
    assert "worktree_settings_written" not in plan
