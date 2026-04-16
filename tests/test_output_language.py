from __future__ import annotations

from councilflow.utils.lang import DEFAULT_OUTPUT_LANGUAGE, resolve_output_language


def test_output_language_defaults_to_zh_cn_and_supports_en() -> None:
    assert DEFAULT_OUTPUT_LANGUAGE == "zh-CN"
    assert resolve_output_language(None) == "zh-CN"
    assert resolve_output_language("en") == "en"
    assert resolve_output_language("fr-FR") == "zh-CN"
