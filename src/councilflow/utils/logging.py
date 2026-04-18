"""Structured logging helpers for CouncilFlow.

`configure_logging()` wires a sensible default for every CLI invocation:
level defaults to WARNING and flips to DEBUG when ``COUNCILFLOW_DEBUG=1`` is
set, output goes to stderr so it never contaminates the structured JSON that
CLI subcommands print to stdout, and formatting includes the module name so a
reader can tell orchestrator vs provider events apart at a glance.

Call sites must NEVER log raw prompt bodies, handoff content, or user text —
the contract is metrics and decisions (delegation id, role, elapsed time,
guardrail reason, event counters) only.
"""

from __future__ import annotations

import logging
import os
import sys

DEBUG_ENV_FLAG = "COUNCILFLOW_DEBUG"
_LOGGER_NAMESPACE = "councilflow"


def configure_logging() -> logging.Logger:
    """Install the CouncilFlow logging configuration; idempotent."""

    level = logging.DEBUG if os.environ.get(DEBUG_ENV_FLAG) == "1" else logging.WARNING

    root = logging.getLogger(_LOGGER_NAMESPACE)
    root.setLevel(level)

    # Always reset handlers so `configure_logging` stays idempotent across
    # CliRunner invocations inside pytest.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root.addHandler(handler)
    root.propagate = False
    return root


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the councilflow namespace."""

    if name.startswith(_LOGGER_NAMESPACE + "."):
        suffix = name[len(_LOGGER_NAMESPACE) + 1 :]
    else:
        suffix = name
    return logging.getLogger(f"{_LOGGER_NAMESPACE}.{suffix}")
