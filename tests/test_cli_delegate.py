from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from councilflow.cli import delegate as delegate_module
from councilflow.cli.app import app
from councilflow.providers.base import ProviderError, ProviderRequest, ProviderResponse

runner = CliRunner()


def _write_claude_permission_settings(tmp_path: Path, *commands: str) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    allow_entries = [f"Bash({command}:*)" for command in commands]
    settings_path.write_text(
        json.dumps({"permissions": {"allow": allow_entries}}, ensure_ascii=False),
        encoding="utf-8",
    )


class FakeSuccessAdapter:
    model_name = "claude"

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(
            model="claude",
            content=f"Delegated successfully:\n\n{request.prompt}",
        )


class FakeFailureAdapter:
    model_name = "claude"

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        raise ProviderError("mock delegation failure")


@pytest.mark.parametrize(
    "role",
    ["implementer", "tester", "fixer", "reviewer", "architect", "advisor"],
)
def test_delegate_command_returns_structured_success_for_role(
    monkeypatch,
    tmp_path: Path,
    role: str,
) -> None:
    monkeypatch.setattr(
        delegate_module,
        "get_provider_adapter",
        lambda *args, **kwargs: FakeSuccessAdapter(),
    )

    result = runner.invoke(
        app,
        [
            "delegate",
            "--role",
            role,
            "--model",
            "claude",
            "--objective",
            f"Run the {role} stage.",
            "--task-summary",
            "Return a delegated artifact for workflow regression coverage.",
            "--project-root",
            str(tmp_path),
        ],
        env={"CODEX_SHELL": "1"},
    )

    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert payload["error"] is None
    assert payload["data"]["role"] == role
    assert payload["data"]["status"] == "delegated"
    assert payload["data"]["delegation_status"] == "completed"
    assert payload["data"]["via_sidecar"] is True
    assert (tmp_path / payload["data"]["handoff_path"]).is_file()
    assert (tmp_path / payload["data"]["result_path"]).is_file()


def test_delegate_command_returns_structured_success(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        delegate_module,
        "get_provider_adapter",
        lambda *args, **kwargs: FakeSuccessAdapter(),
    )
    _write_claude_permission_settings(tmp_path, "python -m pytest")

    result = runner.invoke(
        app,
        [
            "delegate",
            "--role",
            "tester",
            "--model",
            "claude",
            "--objective",
            "Validate delegation support.",
            "--task-summary",
            "Run tester stage verification through the delegated contract.",
            "--input",
            "verification_profile=workflow_meta",
            "--verification-command",
            "python -m pytest",
            "--required-artifact",
            "implementer_result=.council/delegations/del_prev/result.md",
            "--next-on-success",
            "Continue to tester synthesis.",
            "--next-on-failure",
            "Stop and report the failed tester stage.",
            "--project-root",
            str(tmp_path),
        ],
        env={"CODEX_SHELL": "1"},
    )

    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert payload["error"] is None
    assert payload["data"]["role"] == "tester"
    assert payload["data"]["status"] == "delegated"
    assert payload["data"]["delegation_status"] == "completed"
    assert payload["data"]["via_sidecar"] is True
    assert payload["data"]["required_artifacts"] == {
        "implementer_result": ".council/delegations/del_prev/result.md"
    }
    assert payload["data"]["verification_commands"] == [
        {"command": "python -m pytest", "purpose": None}
    ]
    assert payload["data"]["tester_preflight"]["status"] == "passed"
    assert payload["data"]["execution_guardrails"]["allow_commit"] is False
    assert payload["data"]["next_actions_on_success"] == ["Continue to tester synthesis."]
    assert payload["data"]["next_actions_on_failure"] == [
        "Stop and report the failed tester stage."
    ]
    assert (tmp_path / payload["data"]["handoff_path"]).is_file()
    assert (tmp_path / payload["data"]["result_path"]).is_file()


def test_delegate_command_skips_claude_permission_preflight(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Since 0.1.1 the Claude adapter runs with --dangerously-skip-permissions,
    so tester preflight no longer probes .claude/settings.json. A tester stage
    whose verification command would previously have tripped
    ``permission_blocked`` must now pass the preflight — the worktree +
    guardrails stack is the enforcing layer."""

    monkeypatch.setattr(
        delegate_module,
        "get_provider_adapter",
        lambda *args, **kwargs: FakeSuccessAdapter(),
    )

    result = runner.invoke(
        app,
        [
            "delegate",
            "--role",
            "tester",
            "--model",
            "claude",
            "--objective",
            "Validate tester preflight.",
            "--task-summary",
            "Run without pre-seeded claude allow-list.",
            "--verification-command",
            "python -m pytest",
            "--project-root",
            str(tmp_path),
        ],
        env={"CODEX_SHELL": "1"},
    )

    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert payload["error"] is None
    data = payload["data"]
    assert data is not None
    assert data["status"] == "delegated"
    assert data["tester_preflight"]["status"] == "passed"
    assert data["tester_preflight"]["permission_status"] == "not_required"


def test_delegate_command_reports_environment_not_ready_for_missing_command(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        delegate_module,
        "get_provider_adapter",
        lambda *args, **kwargs: FakeSuccessAdapter(),
    )
    _write_claude_permission_settings(tmp_path, "missing-tool")

    result = runner.invoke(
        app,
        [
            "delegate",
            "--role",
            "tester",
            "--model",
            "claude",
            "--objective",
            "Validate tester preflight.",
            "--task-summary",
            "Detect missing tooling before delegated verification starts.",
            "--verification-command",
            "missing-tool run",
            "--project-root",
            str(tmp_path),
        ],
        env={"CODEX_SHELL": "1"},
    )

    payload = json.loads(result.output)

    assert result.exit_code == 1
    assert payload["data"] is None
    assert payload["error"]["error_kind"] == "environment_not_ready"
    assert payload["error"]["tester_preflight"]["status"] == "environment_not_ready"
    assert payload["error"]["tester_preflight"]["command_availability"] == {
        "missing-tool run": "missing"
    }


@pytest.mark.parametrize(
    "role",
    ["implementer", "tester", "fixer", "reviewer", "architect", "advisor"],
)
def test_delegate_command_returns_structured_error_for_role(
    monkeypatch,
    tmp_path: Path,
    role: str,
) -> None:
    monkeypatch.setattr(
        delegate_module,
        "get_provider_adapter",
        lambda *args, **kwargs: FakeFailureAdapter(),
    )

    result = runner.invoke(
        app,
        [
            "delegate",
            "--role",
            role,
            "--model",
            "claude",
            "--objective",
            "Implement delegation support.",
            "--task-summary",
            "Add delegation CLI plumbing.",
            "--project-root",
            str(tmp_path),
        ],
        env={"CODEX_SHELL": "1"},
    )

    payload = json.loads(result.output)

    assert result.exit_code == 1
    assert payload["data"] is None
    assert payload["error"]["status"] == "error"
    assert payload["error"]["via_sidecar"] is True
    assert payload["error"]["role"] == role
    assert payload["error"]["model"] == "claude"
    assert payload["error"]["message"] == "mock delegation failure"
    assert payload["error"]["error_kind"] == "process_exit"
    assert payload["error"]["handoff_path"].endswith("handoff.yaml")


def test_delegate_command_rejects_invalid_input_shape(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "delegate",
            "--role",
            "tester",
            "--objective",
            "Validate the stage contract.",
            "--task-summary",
            "Reject malformed input metadata.",
            "--input",
            "not-a-pair",
            "--project-root",
            str(tmp_path),
        ],
        env={"CODEX_SHELL": "1"},
    )

    assert result.exit_code != 0
    assert "--input expects KEY=VALUE" in result.output


@pytest.mark.parametrize(
    "role",
    ["implementer", "tester", "fixer", "reviewer", "architect", "advisor"],
)
def test_delegate_command_allows_same_controller_local_execution_for_role(
    tmp_path: Path,
    role: str,
) -> None:
    result = runner.invoke(
        app,
        [
            "delegate",
            "--role",
            role,
            "--model",
            "codex",
            "--objective",
            f"Run the {role} stage locally.",
            "--task-summary",
            "This should remain on the active controller.",
            "--project-root",
            str(tmp_path),
        ],
        env={"CODEX_SHELL": "1"},
    )

    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert payload["error"] is None
    assert payload["data"]["role"] == role
    assert payload["data"]["model"] == "codex"
    assert payload["data"]["status"] == "local_execution"
    assert payload["data"]["via_sidecar"] is False


def test_delegate_command_stays_local_when_role_maps_to_controller(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "delegate",
            "--role",
            "reviewer",
            "--objective",
            "Review local output.",
            "--task-summary",
            "This should stay on the controller.",
            "--project-root",
            str(tmp_path),
        ],
        env={"CODEX_SHELL": "1"},
    )

    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert payload["error"] is None
    assert payload["data"]["status"] == "local_execution"
    assert payload["data"]["via_sidecar"] is False
    assert "stays local" in payload["data"]["reason"]


def test_delegate_command_normalizes_aliases_for_local_execution(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "delegate",
            "--role",
            "tester",
            "--model",
            "claude-code",
            "--objective",
            "Run locally with alias normalization.",
            "--task-summary",
            "Alias should resolve to active Claude controller.",
            "--project-root",
            str(tmp_path),
        ],
        env={
            "CLAUDE_CODE_SHELL": "1",
            "CODEX_SHELL": None,
            "CODEX_THREAD_ID": None,
            "CODEX_INTERNAL_ORIGINATOR_OVERRIDE": None,
        },
    )

    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert payload["error"] is None
    assert payload["data"]["model"] == "claude"
    assert payload["data"]["status"] == "local_execution"


def test_delegate_command_stays_local_for_gemini_controller(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "delegate",
            "--role",
            "reviewer",
            "--model",
            "gemini-cli",
            "--objective",
            "Run locally for Gemini.",
            "--task-summary",
            "Alias should resolve to the Gemini controller.",
            "--project-root",
            str(tmp_path),
        ],
        env={
            "GEMINI_CLI": "1",
            "CODEX_SHELL": None,
            "CODEX_THREAD_ID": None,
            "CODEX_INTERNAL_ORIGINATOR_OVERRIDE": None,
            "CLAUDE_CODE_SHELL": None,
        },
    )

    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert payload["error"] is None
    assert payload["data"]["model"] == "gemini"
    assert payload["data"]["status"] == "local_execution"


def test_delegate_with_gemini_controller_alias_normalization(tmp_path: Path) -> None:
    """Test that alias normalization resolves gemini alias to active gemini controller."""
    result = runner.invoke(
        app,
        [
            "delegate",
            "--role",
            "tester",
            "--model",
            "gemini",
            "--objective",
            "Run locally with alias normalization.",
            "--task-summary",
            "Alias should resolve to active Gemini controller.",
            "--project-root",
            str(tmp_path),
        ],
        env={
            "GEMINI_CLI": "1",
            "CODEX_SHELL": None,
            "CODEX_THREAD_ID": None,
            "CODEX_INTERNAL_ORIGINATOR_OVERRIDE": None,
            "CLAUDE_CODE_SHELL": None,
        },
    )

    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert payload["error"] is None
    assert payload["data"]["model"] == "gemini"
    assert payload["data"]["status"] == "local_execution"
    assert payload["data"]["via_sidecar"] is False


def test_delegate_command_refuses_recursive_invocation_inside_delegated_stage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        delegate_module,
        "get_provider_adapter",
        lambda *args, **kwargs: FakeSuccessAdapter(),
    )

    result = runner.invoke(
        app,
        [
            "delegate",
            "--role",
            "implementer",
            "--objective",
            "Try to recurse from sidecar.",
            "--task-summary",
            "Must be rejected by the recursion guard.",
            "--project-root",
            str(tmp_path),
        ],
        env={
            "COUNCILFLOW_DELEGATED_STAGE": "1",
            "COUNCILFLOW_DELEGATION_ID": "del_parent",
            "CODEX_SHELL": None,
            "CODEX_THREAD_ID": None,
            "CODEX_INTERNAL_ORIGINATOR_OVERRIDE": None,
            "CLAUDECODE": None,
            "CLAUDE_CODE": None,
            "CLAUDE_SHELL": None,
            "CLAUDE_CODE_SHELL": None,
            "CLAUDECODE_SHELL": None,
            "GEMINI_CLI": None,
        },
    )

    payload = json.loads(result.output)

    assert result.exit_code == 2
    assert payload["error"]["error_kind"] == "recursive_workflow_violation"
    assert payload["error"]["delegation_id"] == "del_parent"
    assert payload["data"] is None


def test_delegate_command_threads_writable_globs_and_allow_commit_into_guardrails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """TASK-058 follow-up: --writable-glob / --readonly-artifact / --allow-commit
    must reach ExecutionGuardrails so implementer / fixer stages can opt back
    into sidecar imports under the new deny-by-default semantic."""

    monkeypatch.setattr(
        delegate_module,
        "get_provider_adapter",
        lambda *args, **kwargs: FakeSuccessAdapter(),
    )
    _write_claude_permission_settings(tmp_path, "python -m pytest")

    result = runner.invoke(
        app,
        [
            "delegate",
            "--role",
            "implementer",
            "--model",
            "claude",
            "--objective",
            "Wire writable_globs through CLI",
            "--task-summary",
            "Expect guardrails to carry writable_globs + allow_commit",
            "--writable-glob",
            "src/features/game-session/**",
            "--writable-glob",
            "tests/unit/features/game-session/**",
            "--readonly-artifact",
            "docs/prd.md",
            "--allow-commit",
            "--project-root",
            str(tmp_path),
        ],
        env={"CODEX_SHELL": "1"},
    )

    payload = json.loads(result.output)
    guardrails = payload["data"]["execution_guardrails"]

    assert result.exit_code == 0
    assert guardrails["allow_commit"] is True
    assert guardrails["import_manifest"]["writable_globs"] == [
        "src/features/game-session/**",
        "tests/unit/features/game-session/**",
    ]
    assert guardrails["import_manifest"]["readonly_artifact_paths"] == ["docs/prd.md"]
    # allow_workflow_state_write stays false unless --allow-workflow-state-write is set.
    assert guardrails["allow_workflow_state_write"] is False


def test_status_command_is_allowed_inside_delegated_stage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result = runner.invoke(
        app,
        [
            "status",
            "--project-root",
            str(tmp_path),
        ],
        env={
            "COUNCILFLOW_DELEGATED_STAGE": "1",
            "COUNCILFLOW_DELEGATION_ID": "del_parent",
            "CODEX_SHELL": "1",  # host context still needs a controller signal
        },
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["data"]["current_controller"] == "codex"


# ---------------------------------------------------------------------------
# TASK-077: dynamic routing integration
# ---------------------------------------------------------------------------


def test_delegate_uses_router_when_no_model_override(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Without --model, delegate should consult role_router to pick the model."""
    monkeypatch.setattr(
        delegate_module,
        "get_provider_adapter",
        lambda *args, **kwargs: FakeSuccessAdapter(),
    )

    # Write a config that routes implementer by complexity.
    (tmp_path / ".council").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".council" / "config.yaml").write_text(
        "\n".join(
            [
                "config_version: 1",
                "output_language: en",
                "roles:",
                "  implementer:",
                "    - model: gemini",
                "      when: \"task.complexity == 'S'\"",
                "    - model: claude",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "delegate",
            "--role",
            "implementer",
            "--objective",
            "Ship the S-complexity thing.",
            "--task-summary",
            "tiny task",
            "--input",
            "complexity=S",
            "--project-root",
            str(tmp_path),
        ],
        env={"CODEX_SHELL": "1"},
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    # Router picked gemini (first route matched on complexity == 'S')
    data = payload["data"]
    assert data.get("target_model") == "gemini" or data.get("model") == "gemini"

    # Audit log written
    routing_log = tmp_path / ".council" / "runs" / "routing" / "routing.json"
    assert routing_log.is_file()
    records = json.loads(routing_log.read_text(encoding="utf-8"))
    assert any(
        r.get("primary_model") == "gemini" and r.get("role") == "implementer"
        for r in records
    )


def test_delegate_routing_no_match_returns_structured_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """When no route matches and no --model is given, emit routing_no_match."""
    monkeypatch.setattr(
        delegate_module,
        "get_provider_adapter",
        lambda *args, **kwargs: FakeSuccessAdapter(),
    )

    (tmp_path / ".council").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".council" / "config.yaml").write_text(
        "\n".join(
            [
                "config_version: 1",
                "output_language: en",
                "roles:",
                "  implementer:",
                "    - model: gemini",
                "      when: \"task.complexity == 'XL'\"",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "delegate",
            "--role",
            "implementer",
            "--objective",
            "Ship the M-complexity thing.",
            "--task-summary",
            "mid task",
            "--input",
            "complexity=M",
            "--project-root",
            str(tmp_path),
        ],
        env={"CODEX_SHELL": "1"},
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"]["error_kind"] == "routing_no_match"
    assert payload["error"]["role"] == "implementer"
    assert "tried_routes" in payload["error"]


def test_delegate_model_flag_bypasses_router(monkeypatch, tmp_path: Path) -> None:
    """--model has highest priority and skips route resolution entirely."""
    monkeypatch.setattr(
        delegate_module,
        "get_provider_adapter",
        lambda *args, **kwargs: FakeSuccessAdapter(),
    )

    # Config that would route implementer to gemini if routing ran.
    (tmp_path / ".council").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".council" / "config.yaml").write_text(
        "\n".join(
            [
                "config_version: 1",
                "output_language: en",
                "roles:",
                "  implementer: gemini",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "delegate",
            "--role",
            "implementer",
            "--model",
            "claude",  # explicit override should win
            "--objective",
            "Explicit model wins.",
            "--task-summary",
            "explicit model task",
            "--project-root",
            str(tmp_path),
        ],
        env={"CODEX_SHELL": "1"},
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    data = payload["data"]
    assert data.get("target_model") == "claude" or data.get("model") == "claude"

    # Router should NOT have written a log entry since we skipped it
    routing_log = tmp_path / ".council" / "runs" / "routing" / "routing.json"
    assert not routing_log.exists()
