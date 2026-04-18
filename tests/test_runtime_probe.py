"""TASK-052 — streaming-capability probe for Codex and Gemini."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from councilflow.providers import runtime_probe
from councilflow.providers.runtime_probe import (
    ProviderCapabilities,
    _cache_path,
    detect_provider_capabilities,
    get_or_detect_capabilities,
    load_cached_capabilities,
    probe_codex_streaming,
    probe_gemini_streaming,
    save_capabilities,
)


def _stub_run(output: str, returncode: int = 0) -> callable:
    def fake_run(*args, **kwargs):  # noqa: ANN001 - matches subprocess.run signature
        class Result:
            stdout = output
            stderr = ""

        return Result()

    return fake_run


def test_probe_codex_streaming_detects_json_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/codex")
    monkeypatch.setattr(
        subprocess,
        "run",
        _stub_run("Usage: codex exec [--json] [--help]"),
    )

    assert probe_codex_streaming() is True


def test_probe_codex_streaming_returns_false_when_cli_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda _: None)

    assert probe_codex_streaming() is False


def test_probe_gemini_streaming_detects_stream_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/gemini")
    monkeypatch.setattr(
        subprocess,
        "run",
        _stub_run("Output formats: text, json, stream-json"),
    )

    assert probe_gemini_streaming() is True


def test_detect_provider_capabilities_aggregates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_probe, "probe_codex_streaming", lambda: True)
    monkeypatch.setattr(runtime_probe, "probe_gemini_streaming", lambda: False)

    capabilities = detect_provider_capabilities()
    assert capabilities.codex_streaming is True
    assert capabilities.gemini_streaming is False


def test_save_and_load_cached_capabilities_roundtrip(tmp_path: Path) -> None:
    council_root = tmp_path / ".council"
    original = ProviderCapabilities(codex_streaming=True, gemini_streaming=False)

    path = save_capabilities(council_root, original)
    assert path == _cache_path(council_root)

    recovered = load_cached_capabilities(council_root)
    assert recovered == original


def test_get_or_detect_capabilities_uses_cache_when_present(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    council_root = tmp_path / ".council"
    save_capabilities(
        council_root,
        ProviderCapabilities(codex_streaming=True, gemini_streaming=True),
    )

    # Cache is hit without running the probes.
    def _boom() -> bool:
        raise AssertionError("probe should not run when cache exists")

    monkeypatch.setattr(runtime_probe, "probe_codex_streaming", _boom)
    monkeypatch.setattr(runtime_probe, "probe_gemini_streaming", _boom)

    capabilities = get_or_detect_capabilities(council_root)
    assert capabilities.codex_streaming is True
    assert capabilities.gemini_streaming is True


def test_get_or_detect_capabilities_refresh_runs_probes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    council_root = tmp_path / ".council"
    save_capabilities(
        council_root,
        ProviderCapabilities(codex_streaming=False, gemini_streaming=False),
    )

    monkeypatch.setattr(runtime_probe, "probe_codex_streaming", lambda: True)
    monkeypatch.setattr(runtime_probe, "probe_gemini_streaming", lambda: True)

    refreshed = get_or_detect_capabilities(council_root, refresh=True)
    assert refreshed.codex_streaming is True
    assert refreshed.gemini_streaming is True

    cached = load_cached_capabilities(council_root)
    assert cached == refreshed
