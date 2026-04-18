"""Configuration loader for CouncilFlow."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from councilflow.config.schema import CouncilConfig

DEFAULT_CONFIG_PATH = Path(".council/config.yaml")
DEFAULT_CONFIG_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent / "templates" / "default-config.yaml"
)


def default_config_template_path() -> Path:
    """Return the packaged default project config template path."""

    return DEFAULT_CONFIG_TEMPLATE_PATH


def load_default_config_text() -> str:
    """Load the packaged default project config template text."""

    return default_config_template_path().read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _cached_default_payload() -> dict[str, Any]:
    raw = yaml.safe_load(load_default_config_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError("default-config.yaml must deserialize to a mapping.")
    return raw


def default_role_mapping_payload() -> dict[str, str]:
    """Return the `roles` mapping defined in the packaged template.

    RoleMapping falls back to this payload when the user config omits a role so
    the shipped template is the single source of truth for default roles.
    """

    roles = _cached_default_payload().get("roles", {})
    if not isinstance(roles, dict):
        raise ValueError("default-config.yaml must contain a `roles` mapping.")
    return {str(role): str(model) for role, model in roles.items()}


def build_default_config() -> CouncilConfig:
    """Build the default project configuration from the packaged template."""

    return CouncilConfig.model_validate(_cached_default_payload())


def ensure_config_exists(path: Path | None = None) -> Path:
    """Materialize the packaged default config at the target path when missing."""

    config_path = path or DEFAULT_CONFIG_PATH
    if config_path.exists():
        return config_path

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(load_default_config_text(), encoding="utf-8")
    return config_path


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
    config_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
