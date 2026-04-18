"""Structured delegation models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class VerificationCommand(BaseModel):
    """Structured tester command metadata."""

    command: str
    purpose: str | None = None


class TesterPreflight(BaseModel):
    """Preflight contract for tester stages."""

    status: Literal[
        "not_requested",
        "pending",
        "passed",
        "permission_blocked",
        "environment_not_ready",
    ] = "not_requested"
    provider_ready: bool | None = None
    workspace_ready: bool | None = None
    command_availability: dict[str, str] = Field(default_factory=dict)
    permission_requirements: list[str] = Field(default_factory=list)
    permission_status: str | None = None


class ReviewFinding(BaseModel):
    """Structured reviewer finding that a fixer stage can consume."""

    finding_id: str
    severity: Literal["low", "medium", "high", "critical"]
    title: str
    body: str
    affected_files: list[str] = Field(default_factory=list)
    source_stage: str = "reviewer"
    required_fix: str


class FixerInputSource(BaseModel):
    """Artifact source that a fixer stage is expected to read."""

    label: str
    source_stage: str
    artifact_path: str


DEFAULT_PROTECTED_PATHS: tuple[str, ...] = (
    ".claude/state",
    ".council/state.json",
    ".workflow-core",
    ".claude/skills",
    ".codex/skills",
    ".gemini/skills",
)


DEFAULT_ISOLATION_EXCLUDE_PATTERNS: tuple[str, ...] = (
    "node_modules/**",
    "__pycache__/**",
    ".venv/**",
    ".council/**",
    ".claude/**",
    ".codex/**",
    ".gemini/**",
    ".workflow-core/**",
    ".git",
    ".git/**",
)


class IsolatedWorkspace(BaseModel):
    """Sidecar workspace isolation contract for a delegated stage."""

    strategy: Literal["copy", "git_worktree", "none"] = "git_worktree"
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(
        default_factory=lambda: list(DEFAULT_ISOLATION_EXCLUDE_PATTERNS)
    )
    workspace_path: str | None = None


class ImportManifest(BaseModel):
    """Controlled import-back policy for sidecar workspace outputs."""

    writable_globs: list[str] = Field(default_factory=list)
    readonly_artifact_paths: list[str] = Field(default_factory=list)
    max_file_count: int = Field(default=200, ge=1)
    max_total_bytes: int = Field(default=10 * 1024 * 1024, ge=1)


class WorkspaceFileChange(BaseModel):
    """Per-file entry of the sidecar workspace manifest."""

    path: str
    change_type: Literal["added", "modified", "deleted"]
    byte_size: int = Field(default=0, ge=0)
    imported: bool = False
    rejection_reason: str | None = None


class ExecutionGuardrails(BaseModel):
    """Write-scope and git-state controls for delegated stages."""

    writable_paths: list[str] = Field(default_factory=list)
    protected_paths: list[str] = Field(
        default_factory=lambda: list(DEFAULT_PROTECTED_PATHS)
    )
    allow_commit: bool = False
    allow_workflow_state_write: bool = False
    isolated_workspace: IsolatedWorkspace = Field(default_factory=IsolatedWorkspace)
    import_manifest: ImportManifest = Field(default_factory=ImportManifest)


class HandoffPackage(BaseModel):
    """Structured handoff payload for delegated work."""

    id: str
    role: str
    objective: str
    task_summary: str
    constraints: list[str] = Field(default_factory=list)
    relevant_files: list[str] = Field(default_factory=list)
    inputs: dict[str, str] = Field(default_factory=dict)
    required_artifacts: dict[str, str] = Field(default_factory=dict)
    verification_commands: list[VerificationCommand] = Field(default_factory=list)
    tester_preflight: TesterPreflight = Field(default_factory=TesterPreflight)
    review_findings: list[ReviewFinding] = Field(default_factory=list)
    fixer_input_sources: list[FixerInputSource] = Field(default_factory=list)
    execution_guardrails: ExecutionGuardrails = Field(default_factory=ExecutionGuardrails)
    next_actions_on_success: list[str] = Field(default_factory=list)
    next_actions_on_failure: list[str] = Field(default_factory=list)
    expected_output: str


class DelegationResult(BaseModel):
    """Successful delegation output metadata."""

    delegation_id: str
    role: str
    model: str
    handoff_path: str
    result_path: str
    content: str
    status: str
    delegation_status: str
    via_sidecar: bool
    required_artifacts: dict[str, str] = Field(default_factory=dict)
    verification_commands: list[VerificationCommand] = Field(default_factory=list)
    tester_preflight: TesterPreflight = Field(default_factory=TesterPreflight)
    review_findings: list[ReviewFinding] = Field(default_factory=list)
    fixer_input_sources: list[FixerInputSource] = Field(default_factory=list)
    execution_guardrails: ExecutionGuardrails = Field(default_factory=ExecutionGuardrails)
    next_actions_on_success: list[str] = Field(default_factory=list)
    next_actions_on_failure: list[str] = Field(default_factory=list)
    workspace_manifest: list[WorkspaceFileChange] = Field(default_factory=list)
    import_outcome: Literal["none", "applied", "partial", "rejected"] = "none"
    import_rejected_reason: str | None = None


class DelegationRecord(BaseModel):
    """Persisted delegation state for recovery and auditing."""

    id: str
    role: str
    target_model: str
    status: str
    handoff_path: str
    result_path: str | None = None
    error: str | None = None
    error_kind: str | None = None
    tester_preflight: dict[str, object] | None = None
