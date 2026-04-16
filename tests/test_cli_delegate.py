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
    assert payload["error"]["message"] == "mock delegation failure"
    assert payload["error"]["handoff_path"].endswith("handoff.yaml")
