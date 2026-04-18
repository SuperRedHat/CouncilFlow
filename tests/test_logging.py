"""TASK-051 — structured logging configuration contract."""

from __future__ import annotations

import logging

import pytest

from councilflow.utils.logging import (
    DEBUG_ENV_FLAG,
    configure_logging,
    get_logger,
)


def test_configure_logging_defaults_to_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DEBUG_ENV_FLAG, raising=False)

    root = configure_logging()

    assert root.level == logging.WARNING
    for handler in root.handlers:
        assert handler.level == logging.WARNING


def test_configure_logging_enables_debug_with_env_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DEBUG_ENV_FLAG, "1")

    root = configure_logging()

    assert root.level == logging.DEBUG
    for handler in root.handlers:
        assert handler.level == logging.DEBUG


def test_get_logger_places_loggers_under_councilflow_namespace() -> None:
    logger = get_logger("councilflow.providers.base")
    assert logger.name == "councilflow.providers.base"

    shortened = get_logger("utils.logging")
    assert shortened.name == "councilflow.utils.logging"


def test_configure_logging_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DEBUG_ENV_FLAG, raising=False)

    first = configure_logging()
    second = configure_logging()

    assert first is second
    # Each call resets the handler list; it must stay at exactly one entry.
    assert len(first.handlers) == 1


def test_logger_calls_never_interpolate_prompt_or_handoff_body() -> None:
    """Scan only logger invocation lines to make sure no prompt/handoff text
    slips through in structured log format strings."""

    import re
    from pathlib import Path

    src_root = Path(__file__).resolve().parents[1] / "src" / "councilflow"
    logger_call_pattern = re.compile(r"_logger\.(debug|info|warning|error|critical)\(")
    forbidden_inside_log = ("request.prompt", "package.objective", "handoff_text", "prompt_body")

    offending: list[str] = []
    for py_file in src_root.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        lines = text.splitlines()
        for idx, line in enumerate(lines):
            if not logger_call_pattern.search(line):
                continue
            # Walk forward until the closing paren of this call.
            call_block = line
            depth = line.count("(") - line.count(")")
            cursor = idx + 1
            while depth > 0 and cursor < len(lines):
                call_block += "\n" + lines[cursor]
                depth += lines[cursor].count("(") - lines[cursor].count(")")
                cursor += 1
            for needle in forbidden_inside_log:
                if needle in call_block:
                    offending.append(f"{py_file.name}:{idx + 1}: {needle}")
    assert offending == []
