from __future__ import annotations

from types import SimpleNamespace

import pytest
import typer

from councilflow.utils.lang import (
    DEFAULT_OUTPUT_LANGUAGE,
    emit_console_text,
    resolve_output_language,
)


def test_output_language_defaults_to_zh_cn_and_supports_en() -> None:
    assert DEFAULT_OUTPUT_LANGUAGE == "zh-CN"
    assert resolve_output_language(None) == "zh-CN"
    assert resolve_output_language("en") == "en"
    assert resolve_output_language("fr-FR") == "zh-CN"


def test_emit_console_text_falls_back_when_stdout_encoding_rejects_emoji(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_echo(message: str) -> None:
        calls.append(message)
        if len(calls) == 1:
            raise UnicodeEncodeError("gbk", "🎯", 0, 1, "illegal multibyte sequence")

    monkeypatch.setattr(typer, "echo", fake_echo)
    monkeypatch.setattr("councilflow.utils.lang.sys.stdout", SimpleNamespace(encoding="gbk"))

    emit_console_text("中文 + emoji 🎯")

    assert len(calls) == 2
    assert "\\U0001f3af" in calls[1] or "\\ud83c\\udfaf" in calls[1]


def test_emit_console_text_fallback_keeps_json_parseable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TASK-121: the encoding fallback must emit VALID JSON — the old
    backslashreplace fallback produced \\xNN / \\UXXXXXXXX escapes that broke
    the machine-readable stdout contract exactly on non-GBK output."""

    import json

    from councilflow.utils.lang import emit_response

    payload = emit_response(data={"answer": "中文🎯结论", "ok": True})
    calls: list[str] = []

    def fake_echo(message: str) -> None:
        calls.append(message)
        if len(calls) == 1:
            # Simulate a GBK console that cannot encode the emoji.
            message.encode("gbk")

    monkeypatch.setattr(typer, "echo", fake_echo)
    monkeypatch.setattr(
        "councilflow.utils.lang.sys.stdout", SimpleNamespace(encoding="gbk")
    )

    emit_console_text(payload)

    assert len(calls) == 2
    parsed = json.loads(calls[1])  # must be valid JSON after escaping
    assert parsed["data"]["ok"] is True
    assert parsed["data"]["answer"] == "中文🎯结论"  # \\uXXXX round-trips
