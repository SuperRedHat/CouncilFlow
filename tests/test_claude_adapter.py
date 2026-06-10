"""Tests for ClaudeCodeCliAdapter variant support (TASK-095)."""

from __future__ import annotations

import pytest

from councilflow.providers.base import ProviderRequest, ProviderResponse
from councilflow.providers.claude_code_cli import (
    ClaudeCodeCliAdapter,
    _variant_to_cli_model_arg,
)


class _StubRunner:
    """Captures the command and returns a canned ProviderResponse-shaped dict."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    def __call__(self, command, prompt, cwd=None, env=None):
        self.calls.append((list(command), prompt))
        return {"content": "stubbed", "metadata": {}}


@pytest.mark.parametrize(
    ("variant", "expected_cli_arg"),
    [
        ("claude-haiku", "haiku"),
        ("claude-sonnet", "sonnet"),
        ("claude-opus", "opus"),
        ("claude-sonnet-4-6", "claude-sonnet-4-6"),
        ("claude-3-5-sonnet-20241022", "claude-3-5-sonnet-20241022"),
        ("claude-haiku-4-5", "claude-haiku-4-5"),
        ("haiku", "haiku"),
        ("some-other-id", "some-other-id"),
    ],
)
def test_variant_to_cli_model_arg(variant: str, expected_cli_arg: str) -> None:
    assert _variant_to_cli_model_arg(variant) == expected_cli_arg


def test_adapter_without_model_does_not_inject_model_flag() -> None:
    adapter = ClaudeCodeCliAdapter()
    assert "--model" not in adapter.command
    assert adapter.claude_variant is None
    assert adapter.model_name == "claude"


def test_adapter_with_empty_model_does_not_inject_flag() -> None:
    for empty in ("", "   ", "claude"):
        adapter = ClaudeCodeCliAdapter(model=empty)
        assert "--model" not in adapter.command, f"failed for model={empty!r}"
        assert adapter.claude_variant is None


def test_adapter_with_short_alias_model_inserts_cli_flag() -> None:
    adapter = ClaudeCodeCliAdapter(model="claude-haiku")
    assert "--model" in adapter.command
    assert "haiku" in adapter.command
    assert adapter.claude_variant == "claude-haiku"


def test_adapter_with_versioned_model_inserts_full_name() -> None:
    adapter = ClaudeCodeCliAdapter(model="claude-sonnet-4-6")
    assert "--model" in adapter.command
    assert "claude-sonnet-4-6" in adapter.command
    assert adapter.claude_variant == "claude-sonnet-4-6"


def test_adapter_model_flag_precedes_p_flag() -> None:
    adapter = ClaudeCodeCliAdapter(model="claude-haiku")
    cmd = adapter.command
    assert "-p" in cmd, "sanity: stream mode uses -p"
    model_idx = cmd.index("--model")
    p_idx = cmd.index("-p")
    assert model_idx < p_idx
    assert cmd[model_idx + 1] == "haiku"


def test_adapter_with_custom_command_still_supports_variant() -> None:
    custom = ["my-claude", "-p", "--verbose"]
    adapter = ClaudeCodeCliAdapter(model="claude-haiku", command=custom)
    assert adapter.command[:3] == ["my-claude", "--model", "haiku"]
    assert adapter.command[3:] == ["-p", "--verbose"]


def test_adapter_model_name_is_always_canonical() -> None:
    for variant in (None, "claude", "claude-haiku", "claude-sonnet-4-6"):
        adapter = ClaudeCodeCliAdapter(model=variant)
        assert adapter.model_name == "claude"


def test_ask_adds_claude_variant_to_metadata() -> None:
    runner = _StubRunner()
    adapter = ClaudeCodeCliAdapter(model="claude-haiku", runner=runner)
    response = adapter.ask(ProviderRequest(prompt="hello"))
    assert isinstance(response, ProviderResponse)
    assert response.model == "claude"
    assert response.metadata.get("claude_variant") == "claude-haiku"


def test_ask_without_variant_does_not_add_metadata_key() -> None:
    runner = _StubRunner()
    adapter = ClaudeCodeCliAdapter(runner=runner)
    response = adapter.ask(ProviderRequest(prompt="hello"))
    assert "claude_variant" not in response.metadata
    assert response.model == "claude"


def test_ask_preserves_runner_metadata_alongside_variant() -> None:
    from councilflow.providers.base import ProviderRunResult

    runner = lambda cmd, prompt, cwd=None, env=None: ProviderRunResult(  # noqa: E731
        content="ok",
        metadata={"upstream_key": "upstream_value"},
    )
    adapter = ClaudeCodeCliAdapter(model="claude-haiku", runner=runner)
    response = adapter.ask(ProviderRequest(prompt="hello"))
    assert response.metadata.get("upstream_key") == "upstream_value"
    assert response.metadata.get("claude_variant") == "claude-haiku"


# TASK-115: the prompt must travel via STDIN, never argv — on Windows the CLI
# resolves to claude.cmd behind `cmd /c`, where an argv prompt is a
# BatBadBut-class injection surface and is capped at 8191 chars.
def test_streaming_prompt_travels_via_stdin_not_argv(monkeypatch) -> None:
    from councilflow.providers import claude_code_cli
    from councilflow.providers.base import MonitoredProcessResult

    captured: dict = {}

    def fake_run(
        command, runtime=None, prompt_argument=None, stdin_payload=None, cwd=None, env=None
    ):
        captured["command"] = list(command)
        captured["prompt_argument"] = prompt_argument
        captured["stdin_payload"] = stdin_payload
        return MonitoredProcessResult(
            stdout='{"type":"result","result":"ok"}', stderr="", metadata={}
        )

    monkeypatch.setattr(claude_code_cli, "run_monitored_process", fake_run)

    # 50KB prompt with cmd metacharacters: way past the 8191-char cmd.exe limit
    # and hostile to cmd parsing if it ever leaked back into argv.
    hostile = ('payload "%PATH%" & calc.exe ^| ' * 2048)
    result = claude_code_cli._run_claude_streaming_command(["claude", "-p"], hostile)

    assert captured["prompt_argument"] is None
    assert captured["stdin_payload"] == hostile.encode("utf-8")
    assert captured["command"] == ["claude", "-p"]  # argv untouched by the prompt
    assert result.content == "ok"
