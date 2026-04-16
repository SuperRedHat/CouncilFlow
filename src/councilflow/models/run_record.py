"""Structured model for persisted run records."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RunRecord(BaseModel):
    """A persisted runtime record written under .council/runs."""

    kind: str
    created_at: str
    payload: dict[str, Any] = Field(default_factory=dict)

