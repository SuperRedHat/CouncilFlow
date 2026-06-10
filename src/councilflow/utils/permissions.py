"""Command availability helpers used by the tester preflight.

CouncilFlow 0.1.1 switched all three provider adapters to an
auto-approve-in-delegation posture (Claude
``--dangerously-skip-permissions``, Gemini ``--approval-mode yolo``, Codex
user-configured policy). That removed the old Claude-specific allow-list
preflight; the only runtime check left here is "does this verification
command resolve to an executable on PATH?".

Keeping the module (and name) for now so we can layer opt-in allow-list
preflight back on in a future minor release without juggling imports across
callers. See ``docs/integration.md::Permission and approval model``.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from shlex import split as shlex_split


def split_command(command: str) -> list[str]:
    """Tokenize a shell command without executing it.

    Falls back to whitespace split when the command cannot be parsed as a
    valid POSIX-style shell token stream (rare, but safer than raising).
    """

    try:
        tokens = shlex_split(command, posix=False)
    except ValueError:
        tokens = command.split()
    return [token for token in tokens if token]


def command_is_available(command: str) -> bool:
    """Return True when the command's executable resolves in the current PATH."""

    tokens = split_command(command)
    if not tokens:
        return False
    # TASK-122: posix=False tokenizing keeps surrounding quotes on the token
    # ("C:/Program Files/x.exe" stays quoted) — strip them before resolving,
    # or quoted absolute paths false-negative as missing and hard-block tester
    # delegations.
    executable = tokens[0].strip('"').strip("'")
    path = Path(executable)
    if path.is_absolute():
        return path.exists()
    return shutil.which(executable) is not None
