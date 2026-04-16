"""Configuration loader for CouncilFlow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from councilflow.config.schema import CouncilConfig

DEFAULT_CONFIG_PATH = Path(".council/config.yaml")


def build_default_config() -> CouncilConfig:
    """Build the default project configuration."""

    return CouncilConfig()


def load_config(path: Path | None = None) -> CouncilConfig:
    """Load configuration from disk, falling back to defaults when absent."""

    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return build_default_config()

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("CouncilFlow config must deserialize to a mapping.")

    return CouncilConfig.model_validate(raw)


def dump_config(config: CouncilConfig, path: Path | None = None) -> None:
    """Persist configuration to disk as YAML."""

    config_path = path or DEFAULT_CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = config.model_dump(mode="json")
    config_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

