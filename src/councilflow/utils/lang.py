"""Output-language and response helpers for the CouncilFlow CLI surface."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from typing import Any

import typer

DEFAULT_OUTPUT_LANGUAGE = "zh-CN"
SUPPORTED_OUTPUT_LANGUAGES = {"zh-CN", "en"}


def resolve_output_language(configured: str | None, override: str | None = None) -> str:
    """Resolve the output language, falling back to zh-CN when unsupported."""

    candidate = override or configured or DEFAULT_OUTPUT_LANGUAGE
    if candidate in SUPPORTED_OUTPUT_LANGUAGES:
        return candidate
    return DEFAULT_OUTPUT_LANGUAGE


def emit_response(
    *,
    data: Any,
    meta: Mapping[str, Any] | None = None,
    error: Mapping[str, Any] | None = None,
) -> str:
    """Build a standardized `{ data, meta?, error? }` JSON response."""

    payload: dict[str, Any] = {
        "data": data,
        "error": dict(error) if error is not None else None,
    }
    if meta is not None:
        payload["meta"] = dict(meta)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def emit_console_text(text: str) -> None:
    """Echo text safely even when the active console encoding is not UTF-8."""

    try:
        typer.echo(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        fallback = text.encode(encoding, errors="backslashreplace").decode(
            encoding,
            errors="replace",
        )
        typer.echo(fallback)
