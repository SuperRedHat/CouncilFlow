"""Persistence helpers for CouncilFlow local state."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from councilflow.config.loader import dump_config, ensure_config_exists, load_config
from councilflow.config.schema import CouncilConfig
from councilflow.state.paths import CouncilPaths, build_council_paths, ensure_council_paths


def default_state_payload() -> dict[str, Any]:
    """Return the empty state payload used for bootstrap and corruption recovery."""

    return {
        "current_phase": None,
        "current_controller": None,
        "updated_at": None,
    }


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp."""

    return datetime.now(tz=UTC).isoformat()


class CouncilStateStore:
    """High-level API for managing .council configuration and runtime state."""

    def __init__(self, project_root: str | Path) -> None:
        self.paths = build_council_paths(Path(project_root))

    def initialize(self) -> CouncilPaths:
        """Ensure the standard directory layout exists and bootstrap state.json."""

        ensure_council_paths(self.paths)
        ensure_config_exists(self.paths.config)
        if not self.paths.state.exists():
            self.write_state(default_state_payload())
            return self.paths

        try:
            self._read_json(self.paths.state)
        except (json.JSONDecodeError, OSError):
            self.write_state(default_state_payload())
        return self.paths

    def load_config(self) -> CouncilConfig:
        """Load the persisted configuration or return defaults."""

        return load_config(self.paths.config)

    def save_config(self, config: CouncilConfig) -> Path:
        """Persist project configuration to .council/config.yaml."""

        ensure_council_paths(self.paths)
        dump_config(config, self.paths.config)
        return self.paths.config

    def read_state(self) -> dict[str, Any]:
        """Load state.json, returning the bootstrap payload when absent."""

        if not self.paths.state.exists():
            return default_state_payload()

        try:
            return self._read_json(self.paths.state)
        except (json.JSONDecodeError, OSError):
            return default_state_payload()

    def write_state(self, payload: Mapping[str, Any]) -> Path:
        """Persist the top-level workflow state as JSON."""

        ensure_council_paths(self.paths)
        state_payload = dict(payload)
        state_payload["updated_at"] = utc_timestamp()
        self._write_json(self.paths.state, state_payload)
        return self.paths.state

    def append_run_record(self, kind: str, payload: Mapping[str, Any]) -> Path:
        """Persist a run record under .council/runs with a sortable timestamp."""

        ensure_council_paths(self.paths)
        record = {
            "kind": kind,
            "created_at": utc_timestamp(),
            "payload": dict(payload),
        }
        stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S%fZ")
        record_path = self.paths.runs / f"{stamp}-{kind}.json"
        self._write_json(record_path, record)
        return record_path

    def list_run_records(self) -> list[Path]:
        """Return run record paths in ascending timestamp order."""

        if not self.paths.runs.exists():
            return []
        return sorted(self.paths.runs.glob("*.json"))

    def load_run_record(self, path: Path) -> dict[str, Any]:
        """Read a persisted run record from disk."""

        return self._read_json(path)

    def save_json(self, path: Path, payload: Mapping[str, Any]) -> Path:
        """Persist a JSON artifact relative to the project root."""

        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json(path, payload)
        return path

    def write_text(self, path: Path, content: str) -> Path:
        """Persist a UTF-8 text artifact relative to the project root.

        TASK-121: atomic like _write_json (tmp sibling + replace) so a crash
        mid-write cannot leave a truncated summary/result artifact.
        """

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
        return path

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
        content = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        # Atomic write: write a temp sibling then replace(), so a crash/interrupt
        # mid-write cannot leave a truncated/corrupt JSON file (a reader always
        # sees either the complete old or complete new file).
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
