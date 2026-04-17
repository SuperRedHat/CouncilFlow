from __future__ import annotations

from pathlib import Path

from councilflow.config.loader import (
    build_default_config,
    ensure_config_exists,
    load_config,
    load_default_config_text,
)


def test_build_default_config_uses_packaged_template_defaults() -> None:
    config = build_default_config()

    assert config.output_language == "zh-CN"
    assert config.roles.implementer == "claude"
    assert config.discussion.default_models == []
    assert config.discussion.max_rounds == 5


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
                "  max_rounds: 7",
                "",
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_config(config_path)

    assert loaded.output_language == "en"
    assert loaded.roles.implementer == "gemini"
    assert loaded.roles.reviewer == "claude"
    assert loaded.discussion.default_models == ["gemini", "claude"]
    assert loaded.discussion.max_rounds == 7
