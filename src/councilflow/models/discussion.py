"""Structured discussion protocol models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DiscussionTurn(BaseModel):
    """A single model response within a discussion round."""

    round_number: int
    speaker_model: str
    speaker_role: Literal["controller", "participant"] = "participant"
    message: str
    key_options: list[str] = Field(default_factory=list)
    agreements: list[str] = Field(default_factory=list)
    disagreements: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    responds_to_models: list[str] = Field(default_factory=list)
    introduced_new_info: bool = True
    supports_current_direction: bool = False


class DiscussionRequest(BaseModel):
    """Structured payload passed into a discussion participant."""

    discussion_id: str
    question: str
    controller: str
    participant: str
    round_number: int
    output_language: str
    initial_position: str | None = None
    current_controller_position: str | None = None
    prior_turns: list[DiscussionTurn] = Field(default_factory=list)


class ParticipantResponse(BaseModel):
    """Structured response returned by a discussion participant."""

    model: str
    message: str
    key_options: list[str] = Field(default_factory=list)
    agreements: list[str] = Field(default_factory=list)
    disagreements: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    recommended_decision: str | None = None
    next_step: str | None = None
    supports_current_direction: bool = False
    has_new_information: bool = True


class DiscussionSummary(BaseModel):
    """Final structured summary returned by the controller."""

    discussion_id: str
    question: str
    controller: str
    participants: list[str]
    initial_position: str | None = None
    current_controller_position: str | None = None
    min_rounds: int = 1
    rounds_completed: int
    ended_reason: str
    key_options: list[str] = Field(default_factory=list)
    agreements: list[str] = Field(default_factory=list)
    disagreements: list[str] = Field(default_factory=list)
    recommended_decision: str
    open_questions: list[str] = Field(default_factory=list)
    next_step: str
    summary_path: str | None = None


class DiscussionRecord(BaseModel):
    """Persisted discussion record containing turns and artifact paths."""

    id: str
    controller: str
    question: str
    participants: list[str]
    status: str
    initial_position: str | None = None
    current_controller_position: str | None = None
    min_rounds: int = 1
    max_rounds: int
    completed_rounds: int
    ended_reason: str
    turns: list[DiscussionTurn] = Field(default_factory=list)
    summary_path: str | None = None
    error_message: str | None = None
