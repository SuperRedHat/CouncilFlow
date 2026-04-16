from __future__ import annotations

import shutil
import subprocess

import pytest

from councilflow.providers.base import ProviderError, run_command
from councilflow.providers.codex_cli import _default_codex_command
from councilflow.providers.gemini_cli import _default_gemini_command, _strip_runtime_notices


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


def test_run_command_wraps_os_errors() -> None:
    with pytest.raises(ProviderError):
        run_command(["this-command-should-not-exist"], "prompt")


def test_run_command_wraps_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ProviderError, match="timed out"):
        run_command(["codex", "exec"], "prompt", timeout_seconds=0.1)


def test_strip_runtime_notices_removes_gemini_cli_noise() -> None:
    cleaned = _strip_runtime_notices(
        "hello\nYOLO mode is enabled. All tool calls will be automatically approved.\n"
        "Attempt 1 failed: retrying\n"
    )

    assert cleaned == "hello"
