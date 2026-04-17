from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from councilflow.cli import delegate as delegate_module
from councilflow.cli.app import app
from councilflow.providers.base import ProviderError, ProviderRequest, ProviderResponse

runner = CliRunner()


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

    result = runner.invoke(
        app,
        [
            "delegate",
            "--role",
            "implementer",
            "--model",
            "claude",
            "--objective",
            "Implement delegation support.",
            "--task-summary",
            "Add delegation CLI plumbing.",
            "--input",
            "verification_profile=workflow_meta",
            "--input",
            "verification_commands=python -m pytest",
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
    assert payload["data"]["role"] == "implementer"
    assert payload["data"]["status"] == "delegated"
    assert payload["data"]["delegation_status"] == "completed"
    assert payload["data"]["via_sidecar"] is True
    assert payload["data"]["required_artifacts"] == {
        "implementer_result": ".council/delegations/del_prev/result.md"
    }
    assert payload["data"]["next_actions_on_success"] == ["Continue to tester synthesis."]
    assert payload["data"]["next_actions_on_failure"] == [
        "Stop and report the failed tester stage."
    ]
    assert (tmp_path / payload["data"]["handoff_path"]).is_file()
    assert (tmp_path / payload["data"]["result_path"]).is_file()


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
