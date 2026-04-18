from __future__ import annotations

import shutil
import subprocess
import sys

import pytest

from councilflow.models.config import ProviderRuntimeSettings
from councilflow.providers.base import (
    CONTROLLER_ENV_KEYS,
    DELEGATED_STAGE_ENV_FLAG,
    DELEGATION_ID_ENV_KEY,
    MonitoredProcessResult,
    ProviderError,
    build_sandboxed_env,
    run_command,
    run_monitored_process,
)
from councilflow.providers.claude_code_cli import (
    _default_claude_command,
    _parse_stream_json_output,
)
from councilflow.providers.codex_cli import _default_codex_command, _run_codex_command
from councilflow.providers.gemini_cli import (
    STDIN_PROMPT_INSTRUCTION,
    GeminiCliAdapter,
    _default_gemini_command,
    _run_gemini_command,
    _strip_runtime_notices,
)


def test_codex_command_wraps_powershell_script(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: "C:/tools/codex.ps1")

    command = _default_codex_command()

    assert command[:4] == ["powershell", "-ExecutionPolicy", "Bypass", "-File"]
    assert command[-1] == "exec"


def test_gemini_command_wraps_powershell_script(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: "C:/tools/gemini.ps1")

    command = _default_gemini_command()

    assert command[:4] == ["powershell", "-ExecutionPolicy", "Bypass", "-File"]
    assert "--approval-mode" in command
    assert "yolo" in command
    assert command[-1] == "-p"


def test_claude_command_wraps_powershell_script(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: "C:/tools/claude.ps1")

    command = _default_claude_command()

    assert command[:4] == ["powershell", "-ExecutionPolicy", "Bypass", "-File"]
    assert "--output-format" in command
    assert "stream-json" in command
    assert "--include-partial-messages" in command


def test_run_command_wraps_os_errors() -> None:
    with pytest.raises(ProviderError) as exc_info:
        run_command(["this-command-should-not-exist"], "prompt")

    assert exc_info.value.kind == "os_error"


def test_run_command_wraps_total_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ProviderError, match="timed out") as exc_info:
        run_command(
            ["codex", "exec"],
            "prompt",
            runtime=ProviderRuntimeSettings(total_timeout_seconds=0.1, idle_timeout_seconds=None),
        )

    assert exc_info.value.kind == "total_timeout"


def test_run_monitored_process_resets_idle_timeout_on_new_output() -> None:
    script = (
        "import sys,time; "
        "print('tick-1'); sys.stdout.flush(); "
        "time.sleep(0.2); "
        "print('tick-2'); sys.stdout.flush()"
    )

    result = run_monitored_process(
        [sys.executable, "-c", script],
        runtime=ProviderRuntimeSettings(total_timeout_seconds=3, idle_timeout_seconds=0.5),
    )

    assert result.stdout == "tick-1\ntick-2"
    assert result.metadata["execution_mode"] == "stream_monitored"
    assert result.metadata["timeout_strategy"] == "total_plus_idle"


def test_run_monitored_process_raises_idle_timeout_after_silence() -> None:
    script = (
        "import sys,time; "
        "print('start'); sys.stdout.flush(); "
        "time.sleep(0.4); "
        "print('end'); sys.stdout.flush()"
    )

    with pytest.raises(ProviderError, match="idle timeout") as exc_info:
        run_monitored_process(
            [sys.executable, "-c", script],
            runtime=ProviderRuntimeSettings(total_timeout_seconds=3, idle_timeout_seconds=0.1),
        )

    assert exc_info.value.kind == "idle_timeout"


def test_run_codex_command_sends_prompt_via_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> object:
        captured["args"] = args[0]
        captured["input"] = kwargs["input"]

        class Result:
            returncode = 0
            stdout = b"ok"
            stderr = b""

        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = _run_codex_command(["codex", "exec"], "line 1\nline 2")

    assert result.content == "ok"
    assert result.metadata["execution_mode"] == "blocking"
    assert captured["args"] == ["codex", "exec"]
    assert captured["input"] == b"line 1\nline 2"


def test_gemini_adapter_supports_specific_model() -> None:
    adapter = GeminiCliAdapter(model="gemini-1.5-flash")
    # Family name stays stable; specific variant lives in gemini_variant.
    assert adapter.model_name == "gemini"
    assert adapter.gemini_variant == "gemini-1.5-flash"
    assert "--model" in adapter.command
    assert "gemini-1.5-flash" in adapter.command
    p_idx = adapter.command.index("-p")
    m_idx = adapter.command.index("--model")
    assert m_idx < p_idx


def test_codex_adapter_stream_mode_adds_json_flag_and_uses_monitored_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from councilflow.providers.base import MonitoredProcessResult
    from councilflow.providers.codex_cli import CodexCliAdapter

    captured: dict[str, object] = {}

    def fake_monitored(command, **kwargs):  # noqa: ANN001
        captured["command"] = command
        captured["stdin"] = kwargs.get("stdin_payload")
        return MonitoredProcessResult(
            stdout='{"event":"final","text":"ok"}',
            stderr="",
            metadata={"execution_mode": "stream_monitored"},
        )

    monkeypatch.setattr(
        "councilflow.providers.codex_cli.run_monitored_process",
        fake_monitored,
    )

    adapter = CodexCliAdapter(stream_mode=True)
    assert "--json" in adapter.command

    from councilflow.providers.base import ProviderRequest

    response = adapter.ask(ProviderRequest(prompt="hello codex"))
    assert response.model == "codex"
    assert response.content == '{"event":"final","text":"ok"}'
    assert response.metadata["execution_mode"] == "stream_monitored"
    assert response.metadata["output_format"] == "codex-json"
    assert captured["stdin"] == b"hello codex"


def test_gemini_adapter_stream_mode_uses_stream_json_output_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from councilflow.providers.base import MonitoredProcessResult

    captured: dict[str, object] = {}

    def fake_monitored(command, **kwargs):  # noqa: ANN001
        captured["command"] = command
        captured["prompt_arg"] = kwargs.get("prompt_argument")
        captured["stdin"] = kwargs.get("stdin_payload")
        return MonitoredProcessResult(
            stdout='{"type":"result","text":"ok"}',
            stderr="",
            metadata={"execution_mode": "stream_monitored"},
        )

    monkeypatch.setattr(
        "councilflow.providers.gemini_cli.run_monitored_process",
        fake_monitored,
    )

    adapter = GeminiCliAdapter(stream_mode=True)
    assert "stream-json" in adapter.command

    from councilflow.providers.base import ProviderRequest

    response = adapter.ask(ProviderRequest(prompt="question"))
    assert response.model == "gemini"
    assert response.metadata["output_format"] == "gemini-stream-json"
    assert captured["prompt_arg"] == STDIN_PROMPT_INSTRUCTION
    assert captured["stdin"] == b"question"


def test_gemini_adapter_surfaces_variant_through_response_metadata() -> None:
    class FakeRunner:
        def __call__(self, command, prompt, cwd=None, env=None):
            from councilflow.providers.base import ProviderRunResult

            return ProviderRunResult(content="hello", metadata={"execution_mode": "blocking"})

    adapter = GeminiCliAdapter(model="gemini-1.5-flash", runner=FakeRunner())
    from councilflow.providers.base import ProviderRequest

    response = adapter.ask(ProviderRequest(prompt="ping"))
    assert response.model == "gemini"
    assert response.metadata["gemini_variant"] == "gemini-1.5-flash"


def test_run_gemini_command_sends_prompt_via_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> object:
        captured["args"] = args[0]
        captured["input"] = kwargs["input"]

        class Result:
            returncode = 0
            stdout = b"ok"
            stderr = b""

        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = _run_gemini_command(["gemini", "-p"], "line 1\nline 2")

    assert result.content == "ok"
    assert result.metadata["execution_mode"] == "blocking"
    assert captured["args"] == ["gemini", "-p", STDIN_PROMPT_INSTRUCTION]
    assert captured["input"] == b"line 1\nline 2"


def test_strip_runtime_notices_removes_gemini_cli_noise() -> None:
    cleaned = _strip_runtime_notices(
        "hello\nYOLO mode is enabled. All tool calls will be automatically approved.\n"
        "Attempt 1 failed: retrying\n"
    )

    assert cleaned == "hello"


def test_build_sandboxed_env_strips_controller_signals_and_injects_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in CONTROLLER_ENV_KEYS:
        monkeypatch.setenv(key, "leak")
    monkeypatch.setenv("PATH", "/usr/bin")  # benign key is preserved

    env = build_sandboxed_env("del_testenv")

    for key in CONTROLLER_ENV_KEYS:
        assert key not in env, f"{key} leaked into sandboxed env"
    assert env[DELEGATED_STAGE_ENV_FLAG] == "1"
    assert env[DELEGATION_ID_ENV_KEY] == "del_testenv"
    assert env["PATH"] == "/usr/bin"


def test_run_command_threads_cwd_and_env_into_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> object:
        captured["cwd"] = kwargs.get("cwd")
        captured["env"] = kwargs.get("env")

        class Result:
            returncode = 0
            stdout = b"ok"
            stderr = b""

        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    run_command(
        ["codex", "exec"],
        "prompt",
        cwd="/tmp/workspace",
        env={"HELLO": "world"},
    )

    assert captured["cwd"] == "/tmp/workspace"
    assert captured["env"] == {"HELLO": "world"}


def test_parse_claude_stream_json_prefers_final_result() -> None:
    monitored = MonitoredProcessResult(
        stdout="\n".join(
            [
                '{"type":"assistant","message":{"model":"claude-haiku","content":[{"type":"text","text":"draft"}]}}',
                (
                    '{"type":"result","subtype":"success","is_error":false,'
                    '"result":"final answer","terminal_reason":"completed"}'
                ),
            ]
        ),
        stderr="",
        metadata={"execution_mode": "stream_monitored"},
    )

    content, metadata = _parse_stream_json_output(monitored)

    assert content == "final answer"
    assert metadata["output_format"] == "stream-json"
    assert metadata["event_count"] == 2
    assert metadata["terminal_reason"] == "completed"
