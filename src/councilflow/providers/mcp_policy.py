"""Policy for deciding which delegated roles keep MCP access.

Background
----------
When a delegated CLI (Claude Code, Codex, Gemini) is launched from a sidecar
worktree, it inherits the host controller's global MCP registrations from
`~/.claude/settings.json` (and the equivalents). That registration includes
`project-manager`, which writes `.claude/state/logs.json` whenever any tool
logs — even during implementer / tester stages that should not be touching
workflow state.

The default guardrail in `delegation_orchestrator` snapshots the protected
paths, detects the write, restores the pre-delegation contents, and fails the
stage with `error_kind=guardrail_violation`. That *keeps the data safe* but
turns every long-running delegation into an unnecessary failure.

This module declares which roles SHOULD legitimately have MCP access and gives
the orchestrator a way to write a per-delegation, worktree-local empty MCP
config that the CLI can pick up instead of the global one.

Policy
------
* `architect`, `planner`, `synthesizer` — keep MCP. They need to read PRD,
  architecture, and task data while running, and they are expected to update
  workflow state as part of their normal work.
* `implementer`, `tester`, `reviewer`, `fixer`, `advisor` — MCP blocked. They
  operate on code / tests / reviews; writing workflow state is the controller's
  job, not theirs.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from councilflow.models.roles import RoleName

ROLES_WITH_MCP_ACCESS: frozenset[RoleName] = frozenset(
    {
        RoleName.ARCHITECT,
        RoleName.PLANNER,
        RoleName.SYNTHESIZER,
    }
)


def role_allows_mcp(role: RoleName) -> bool:
    """Return True when the role is allowed to call MCP tools during delegation."""

    return role in ROLES_WITH_MCP_ACCESS


def _write_settings(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_empty_mcp_configs(workspace_path: Path) -> list[Path]:
    """Write worktree-local empty MCP configs for Claude / Codex / Gemini.

    Each CLI's project-local settings file is created with an empty
    `mcpServers` map so the sidecar CLI cannot auto-attach the host's global
    MCP registrations. The function returns the list of written paths so the
    orchestrator can log the policy decision.

    This is a best-effort layer — if a CLI ignores its project-local override
    the final guardrail (`_detect_protected_path_changes`) still catches any
    protected-path write at import time.
    """

    written: list[Path] = []
    claude_settings = workspace_path / ".claude" / "settings.json"
    codex_settings = workspace_path / ".codex" / "settings.json"
    gemini_settings = workspace_path / ".gemini" / "settings.json"

    empty = json.dumps({"mcpServers": {}}, ensure_ascii=False, indent=2)
    for path in (claude_settings, codex_settings, gemini_settings):
        _write_settings(path, empty)
        written.append(path)
    return written


def build_mcp_denied_env(project_root: Path, workspace_path: Path) -> dict[str, str]:
    """Build extra env vars that hint each CLI toward the worktree MCP scope.

    Returned keys include:
    * `COUNCILFLOW_MCP_POLICY=deny` — informational, surfaced in logs
    * `CLAUDE_PROJECT_DIR` / `CODEX_PROJECT_DIR` / `GEMINI_PROJECT_DIR` —
      redundant with cwd but some CLIs read them directly for settings lookup
    """

    workspace = str(workspace_path)
    return {
        "COUNCILFLOW_MCP_POLICY": "deny",
        "COUNCILFLOW_MCP_SOURCE_PROJECT": str(project_root),
        "CLAUDE_PROJECT_DIR": workspace,
        "CODEX_PROJECT_DIR": workspace,
        "GEMINI_PROJECT_DIR": workspace,
    }


def plan_mcp_policy(
    role: RoleName, project_root: Path, workspace_path: Path
) -> dict[str, object]:
    """Return a summary of the MCP policy that will apply for this delegation.

    Used by the orchestrator to log the effective policy into the run record.
    """

    allows = role_allows_mcp(role)
    plan: dict[str, object] = {
        "role": role.value,
        "allows_mcp": allows,
        "denied_by_policy": not allows,
    }
    if not allows:
        plan["worktree_settings_written"] = True
        plan["env_hints"] = sorted(build_mcp_denied_env(project_root, workspace_path).keys())
    return plan


def collect_settings_paths(workspace_path: Path) -> Iterable[Path]:
    """Return the paths the policy writes, for tests and introspection."""

    return (
        workspace_path / ".claude" / "settings.json",
        workspace_path / ".codex" / "settings.json",
        workspace_path / ".gemini" / "settings.json",
    )
