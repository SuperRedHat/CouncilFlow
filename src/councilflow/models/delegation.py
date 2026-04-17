"""Structured delegation models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HandoffPackage(BaseModel):
    """Structured handoff payload for delegated work."""

    id: str
    role: str
    objective: str
    task_summary: str
    constraints: list[str] = Field(default_factory=list)
    relevant_files: list[str] = Field(default_factory=list)
    inputs: dict[str, str] = Field(default_factory=dict)
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


class DelegationRecord(BaseModel):
    """Persisted delegation state for recovery and auditing."""

    id: str
    role: str
    target_model: str
    status: str
    handoff_path: str
    result_path: str | None = None
    error: str | None = None
