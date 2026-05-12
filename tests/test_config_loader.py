from __future__ import annotations

from pathlib import Path

from councilflow.config.loader import (
    build_default_config,
    ensure_config_exists,
    load_config,
    load_default_config_text,
)
from councilflow.models.roles import RoleName


def test_build_default_config_uses_packaged_template_defaults() -> None:
    config = build_default_config()

    assert config.output_language == "zh-CN"
    assert config.roles.for_role(RoleName.IMPLEMENTER) == "codex"
    assert config.discussion.default_models == ["codex", "claude"]
    assert config.discussion.min_rounds == 2
    assert config.discussion.max_rounds == 5
    assert config.providers.default.total_timeout_seconds == 90000
    assert config.providers.default.idle_timeout_seconds is None
    assert config.providers.claude is not None
    assert config.providers.for_model("claude").idle_timeout_seconds == 18000


def test_ensure_config_exists_copies_project_local_default_template(tmp_path: Path) -> None:
    config_path = tmp_path / ".council" / "config.yaml"

    ensured_path = ensure_config_exists(config_path)

    assert ensured_path == config_path
    assert config_path.is_file()
    assert config_path.read_text(encoding="utf-8") == load_default_config_text()


def test_load_config_normalizes_role_and_discussion_model_names(tmp_path: Path) -> None:
    config_path = tmp_path / ".council" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "\n".join(
            [
                "config_version: 1",
                "output_language: en",
                "roles:",
                "  implementer: Gemini-1.5-Flash",
                "  reviewer: claude-code",
                "discussion:",
                "  default_models:",
                "    - Gemini CLI",
                "    - gemini-1.5-flash",
                "    - Claude Code",
                "  min_rounds: 3",
                "  max_rounds: 7",
                "",
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_config(config_path)

    assert loaded.output_language == "en"
    # 0.1.4 preserves Gemini variant instead of collapsing to bare "gemini"
    assert loaded.roles.for_role(RoleName.IMPLEMENTER) == "gemini-1.5-flash"
    assert loaded.roles.for_role(RoleName.REVIEWER) == "claude"
    # discussion.default_models dedup: "Gemini CLI" → "gemini" (controller alias),
    # "gemini-1.5-flash" preserved as variant, "Claude Code" → "claude".
    assert loaded.discussion.default_models == ["gemini", "gemini-1.5-flash", "claude"]
    assert loaded.discussion.min_rounds == 3
    assert loaded.discussion.max_rounds == 7


def test_load_config_keeps_backward_compatible_min_rounds_default(tmp_path: Path) -> None:
    config_path = tmp_path / ".council" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "\n".join(
            [
                "config_version: 1",
                "discussion:",
                "  default_models:",
                "    - gemini",
                "  max_rounds: 1",
                "",
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_config(config_path)

    assert loaded.discussion.default_models == ["gemini"]
    assert loaded.discussion.min_rounds == 1
    assert loaded.discussion.max_rounds == 1
    assert loaded.providers.for_model("claude").idle_timeout_seconds == 180


def test_load_config_supports_provider_runtime_overrides(tmp_path: Path) -> None:
    config_path = tmp_path / ".council" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "\n".join(
            [
                "config_version: 1",
                "providers:",
                "  default:",
                "    total_timeout_seconds: 1200",
                "    idle_timeout_seconds: null",
                "  claude:",
                "    idle_timeout_seconds: 240",
                "  gemini:",
                "    total_timeout_seconds: 600",
                "",
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_config(config_path)

    assert loaded.providers.for_model("claude").total_timeout_seconds == 1200
    assert loaded.providers.for_model("claude").idle_timeout_seconds == 240
    assert loaded.providers.for_model("gemini").total_timeout_seconds == 600
    assert loaded.providers.for_model("gemini").idle_timeout_seconds is None


def test_load_config_rejects_min_rounds_greater_than_max_rounds(tmp_path: Path) -> None:
    config_path = tmp_path / ".council" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "\n".join(
            [
                "config_version: 1",
                "discussion:",
                "  min_rounds: 4",
                "  max_rounds: 2",
                "",
            ]
        ),
        encoding="utf-8",
    )

    try:
        load_config(config_path)
    except ValueError as exc:
        assert "min_rounds" in str(exc)
    else:
        raise AssertionError("Config loading should reject min_rounds > max_rounds.")
