from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from councilflow.controller.delegation_orchestrator import (
    DelegationExecutionError,
    DelegationOrchestrator,
)
from councilflow.models.roles import RoleName
from councilflow.providers.base import ProviderError, ProviderRequest, ProviderResponse
from councilflow.state.store import CouncilStateStore


class SuccessfulProvider:
    model_name = "claude"

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(model="claude", content=f"Handled:\n\n{request.prompt}")


class FailingProvider:
    model_name = "claude"

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        raise ProviderError("claude CLI is unavailable", kind="idle_timeout")


def test_delegation_orchestrator_persists_handoff_and_result(tmp_path: Path) -> None:
    store = CouncilStateStore(tmp_path)
    orchestrator = DelegationOrchestrator(
        store=store,
        participant_factory=lambda _: SuccessfulProvider(),
    )

    result = orchestrator.run(
        role=RoleName.IMPLEMENTER,
        controller="codex",
        target_model="claude",
        objective="Implement provider adapters.",
        task_summary="Add the delegation provider layer.",
        constraints=["Do not modify unrelated files."],
        relevant_files=["src/councilflow/providers/base.py"],
        inputs={"ticket": "TASK-005"},
        expected_output="Markdown summary with actionable results.",
    )

    handoff_path = tmp_path / result.handoff_path
    result_path = tmp_path / result.result_path

    assert result.status == "delegated"
    assert result.delegation_status == "completed"
    assert result.via_sidecar is True
    assert handoff_path.is_file()
    assert result_path.is_file()
    handoff_payload = yaml.safe_load(handoff_path.read_text(encoding="utf-8"))
    assert handoff_payload["role"] == "implementer"
    assert "provider layer" in handoff_payload["task_summary"]
    assert "Handled:" in result_path.read_text(encoding="utf-8")


def test_delegation_orchestrator_records_failures(tmp_path: Path) -> None:
    store = CouncilStateStore(tmp_path)
    orchestrator = DelegationOrchestrator(
        store=store,
        participant_factory=lambda _: FailingProvider(),
    )

    with pytest.raises(DelegationExecutionError) as exc_info:
        orchestrator.run(
            role=RoleName.IMPLEMENTER,
            controller="codex",
            target_model="claude",
            objective="Implement provider adapters.",
            task_summary="Add the delegation provider layer.",
            constraints=[],
            relevant_files=[],
            inputs={},
            expected_output="Markdown summary with actionable results.",
        )

    error = exc_info.value
    record = json.loads((tmp_path / error.record_path).read_text(encoding="utf-8"))

    assert error.delegation_id.startswith("del_")
    assert error.error_kind == "idle_timeout"
    assert record["status"] == "failed"
    assert record["error"] == "claude CLI is unavailable"
    assert record["error_kind"] == "idle_timeout"
    assert error.handoff_path.endswith("handoff.yaml")
