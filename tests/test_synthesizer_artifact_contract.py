"""Regression tests for the 0.1.5 synthesizer artifact-first contract.

From 0.1.5 onward the three workflow skills (project-design, project-plan,
project-change) explicitly route synthesizer sidecar output to
``.council/delegations/<id>/result.md`` rather than host-state writes.
These tests pin the happy path: a synthesizer delegation whose fake
provider returns markdown produces a ``result.md`` artifact, no
``.claude/state/*`` mutation, and ``status != "guardrail_violation"``.

See PRD §33 / architecture §29 for the contract, and TASK-101 for the
registration history.
"""

from __future__ import annotations

from pathlib import Path

from councilflow.controller.delegation_orchestrator import DelegationOrchestrator
from councilflow.models.roles import RoleName
from councilflow.providers.base import ProviderRequest, ProviderResponse
from councilflow.state.store import CouncilStateStore


class _SynthesizerProvider:
    """Produces markdown-shaped synthesis without touching host state."""

    model_name = "claude"

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(
            model="claude",
            content=(
                "# Synthesis\n\n"
                "## Combined outcome\n\n"
                "- Integrates architect + planner inputs.\n"
                "- Ready for host controller to consume and persist "
                "via MCP `save_architecture` / `save_prd` / `create_tasks`.\n"
            ),
        )


def _read_mcp_state_snapshot(project_root: Path) -> dict[str, bytes]:
    """Capture the on-disk contents of every file under .claude/state/*.

    Only .claude/state/* is surveyed; .council/state.json is excluded
    because the orchestrator itself legitimately updates it to track
    last_delegation_id / last_delegation_result_path after each run.
    The contract this test pins is specifically that the sidecar does
    not reach into MCP-managed host state (PRD / tasks / logs /
    architecture) from a synthesizer stage.
    """

    snapshot: dict[str, bytes] = {}
    state_dir = project_root / ".claude" / "state"
    if state_dir.is_dir():
        for child in state_dir.rglob("*"):
            if child.is_file():
                snapshot[str(child.relative_to(project_root))] = child.read_bytes()
    return snapshot


def test_synthesizer_sidecar_writes_result_md_without_touching_mcp_state(
    tmp_path: Path,
) -> None:
    """Happy path: synthesizer delegation writes result.md, leaves
    MCP-managed host state (.claude/state/*) untouched, and returns
    status=delegated."""

    store = CouncilStateStore(tmp_path)
    store.initialize()
    # Seed .claude/state/ with a baseline file so post-run snapshot
    # diff is meaningful (otherwise both snapshots would be empty and
    # the equality would be trivially true).
    mcp_state_dir = tmp_path / ".claude" / "state"
    mcp_state_dir.mkdir(parents=True, exist_ok=True)
    baseline = mcp_state_dir / "architecture.md"
    baseline.write_text("# baseline architecture\n", encoding="utf-8")
    pre_snapshot = _read_mcp_state_snapshot(tmp_path)
    assert pre_snapshot, "MCP state baseline must exist before the run"

    orchestrator = DelegationOrchestrator(
        store=store,
        participant_factory=lambda _: _SynthesizerProvider(),
    )

    result = orchestrator.run(
        role=RoleName.SYNTHESIZER,
        controller="codex",
        target_model="claude",
        objective="Combine architect + planner artifacts into a final plan.",
        task_summary="Synthesizer artifact-first contract regression.",
        constraints=[],
        relevant_files=[],
        inputs={},
        verification_commands=[],
        expected_output="Markdown synthesis for the host controller to persist.",
    )

    # Core contract assertions.
    assert result.status == "delegated"
    assert result.delegation_status == "completed"
    assert result.via_sidecar is True

    # result.md exists at the sidecar artifact path and carries the
    # provider's markdown (the host controller reads this next).
    result_path = tmp_path / result.result_path
    assert result_path.is_file()
    body = result_path.read_text(encoding="utf-8")
    assert "# Synthesis" in body
    assert "Combined outcome" in body

    # MCP-managed host state untouched — this is the contract the
    # 0.1.5 skill-protocol change is about.
    post_snapshot = _read_mcp_state_snapshot(tmp_path)
    assert post_snapshot == pre_snapshot, (
        ".claude/state/* must not be modified by a synthesizer delegation "
        "that only writes its result.md artifact."
    )


def test_synthesizer_role_keeps_mcp_access_but_does_not_need_it(
    tmp_path: Path,
) -> None:
    """Synthesizer keeps MCP (per PRD §33 / integration.md MCP policy
    table), but a well-behaved sidecar never needs to use it — the
    artifact-first path is the expected one. This asserts that the
    happy path does not log a ``decision=deny`` for synthesizer."""

    import logging

    store = CouncilStateStore(tmp_path)
    orchestrator = DelegationOrchestrator(
        store=store,
        participant_factory=lambda _: _SynthesizerProvider(),
    )

    logger = logging.getLogger("councilflow.controller.delegation_orchestrator")
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture(level=logging.INFO)
    logger.addHandler(handler)
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        orchestrator.run(
            role=RoleName.SYNTHESIZER,
            controller="codex",
            target_model="claude",
            objective="No-op synthesis.",
            task_summary="Synthesizer MCP policy decision log.",
            constraints=[],
            relevant_files=[],
            inputs={},
            verification_commands=[],
            expected_output="Markdown.",
        )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    mcp_decisions = [
        record.getMessage()
        for record in records
        if "delegation.mcp_policy" in record.getMessage()
    ]
    # synthesizer is controller-facing → decision should be allow
    assert any(
        "role=synthesizer" in message and "decision=allow" in message
        for message in mcp_decisions
    ), f"unexpected MCP policy trace: {mcp_decisions!r}"
