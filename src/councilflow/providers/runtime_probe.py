"""Detect whether Codex / Gemini CLIs support streaming event output.

The probe runs ``<cli> --help`` (short, offline-safe) and scans the stdout for
published streaming flags. Results are cached under
``.council/runtime/providers.json`` so later adapter invocations can pick the
stream-monitored execution path without paying the probe cost each time.

The cache is intentionally best-effort: any error during the probe simply
falls back to ``streaming=False`` and the adapter keeps its historical
``subprocess.run`` behavior, preserving TASK-044 guarantees.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from councilflow.utils.logging import get_logger

_logger = get_logger(__name__)

_CACHE_RELATIVE_PATH = Path("runtime") / "providers.json"
_PROBE_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class ProviderCapabilities:
    """Streaming capabilities observed for each supported CLI."""

    codex_streaming: bool = False
    gemini_streaming: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {
            "codex_streaming": self.codex_streaming,
            "gemini_streaming": self.gemini_streaming,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> ProviderCapabilities:
        return cls(
            codex_streaming=bool(payload.get("codex_streaming", False)),
            gemini_streaming=bool(payload.get("gemini_streaming", False)),
        )


def _run_help(cli: str) -> str:
    """Return stdout of ``<cli> --help`` or empty string on any error."""

    resolved = shutil.which(cli)
    if resolved is None:
        return ""
    try:
        completed = subprocess.run(
            [resolved, "--help"],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        _logger.debug("runtime_probe.help_failed cli=%s reason=%s", cli, exc)
        return ""
    return (completed.stdout or "") + "\n" + (completed.stderr or "")


def probe_codex_streaming() -> bool:
    """Return True when ``codex exec --json`` appears supported by the CLI."""

    help_text = _run_help("codex").lower()
    return "--json" in help_text and "exec" in help_text


def probe_gemini_streaming() -> bool:
    """Return True when Gemini CLI exposes ``--output-format stream-json``."""

    help_text = _run_help("gemini").lower()
    return "stream-json" in help_text or "streamjson" in help_text


def detect_provider_capabilities() -> ProviderCapabilities:
    """Run every probe and return the aggregated capabilities object."""

    capabilities = ProviderCapabilities(
        codex_streaming=probe_codex_streaming(),
        gemini_streaming=probe_gemini_streaming(),
    )
    _logger.info(
        "runtime_probe.detected codex_streaming=%s gemini_streaming=%s",
        capabilities.codex_streaming,
        capabilities.gemini_streaming,
    )
    return capabilities


def _cache_path(council_root: Path) -> Path:
    return council_root / _CACHE_RELATIVE_PATH


def load_cached_capabilities(council_root: Path) -> ProviderCapabilities | None:
    """Load a previously-cached capability snapshot, if any."""

    path = _cache_path(council_root)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return ProviderCapabilities.from_dict(payload)


def save_capabilities(council_root: Path, capabilities: ProviderCapabilities) -> Path:
    """Persist the capability snapshot so future runs skip the probe."""

    path = _cache_path(council_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(capabilities.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def get_or_detect_capabilities(
    council_root: Path,
    *,
    refresh: bool = False,
) -> ProviderCapabilities:
    """Return cached capabilities or run a fresh probe + cache the result."""

    if not refresh:
        cached = load_cached_capabilities(council_root)
        if cached is not None:
            return cached

    capabilities = detect_provider_capabilities()
    try:
        save_capabilities(council_root, capabilities)
    except OSError as exc:
        _logger.debug("runtime_probe.cache_write_failed reason=%s", exc)
    return capabilities
