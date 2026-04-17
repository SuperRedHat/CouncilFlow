from __future__ import annotations

import json
from pathlib import Path

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


def test_delegate_command_returns_structured_success(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(delegate_module, "get_provider_adapter", lambda _: FakeSuccessAdapter())

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
    assert (tmp_path / payload["data"]["handoff_path"]).is_file()
    assert (tmp_path / payload["data"]["result_path"]).is_file()


def test_delegate_command_returns_structured_error(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(delegate_module, "get_provider_adapter", lambda _: FakeFailureAdapter())

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
    assert payload["error"]["role"] == "implementer"
    assert payload["error"]["model"] == "claude"
    assert payload["error"]["message"] == "mock delegation failure"
    assert payload["error"]["handoff_path"].endswith("handoff.yaml")


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
