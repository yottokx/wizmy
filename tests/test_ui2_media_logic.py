"""ui2/media_logic.py(メディア編集の純ロジック)の単体テスト。"""

from __future__ import annotations

from types import SimpleNamespace

from src.core.character.schemas import CharacterSheet
from src.ui2.media_logic import (
    candidate_negative_tags,
    clean_voice_caption,
    editor_html_to_prompt,
    generated_image_size_label,
    prompt_text_to_editor_html,
    read_param_value,
    replace_generated_prompt_html,
    split_prompt_tags,
    voice_caption_sheet_source,
)


def test_split_prompt_tags_handles_commas_and_newlines() -> None:
    assert split_prompt_tags("1girl, solo,\nfull body ,  ") == ["1girl", "solo", "full body"]
    assert split_prompt_tags("") == []


def test_editor_html_roundtrip() -> None:
    html_value = prompt_text_to_editor_html("1girl, solo\nfull body")
    assert html_value == "1girl, solo<br>full body"
    assert editor_html_to_prompt(html_value) == "1girl, solo full body"
    assert editor_html_to_prompt("") == ""


def test_replace_generated_prompt_html_replaces_generated_only() -> None:
    base = prompt_text_to_editor_html("1girl, solo")
    first = replace_generated_prompt_html(base, "silver hair, ancient library")
    assert "wizmy-generated-prompt" in first
    assert editor_html_to_prompt(first) == "silver hair, ancient library, 1girl, solo"
    # 候補を再適用すると候補由来だけが置き換わる(手入力・プロファイル分は保持)
    second = replace_generated_prompt_html(first, "red hair")
    assert editor_html_to_prompt(second) == "red hair, 1girl, solo"
    assert second.count("wizmy-generated-prompt") == 2  # marker 属性+class の1組のみ


def test_replace_generated_prompt_html_without_existing_body() -> None:
    result = replace_generated_prompt_html("", "lamplight")
    assert editor_html_to_prompt(result) == "lamplight"
    # 空候補は既存の生成スパンを除去するだけ
    assert editor_html_to_prompt(replace_generated_prompt_html(result, "")) == ""


def test_candidate_negative_tags_merges_and_dedupes() -> None:
    candidate = SimpleNamespace(
        negative_prompt="lowres, bad hands",
        negative_tags=["bad_hands", "text", "o_o"],
    )
    assert candidate_negative_tags(candidate) == ["lowres", "bad hands", "text", "o_o"]


def test_read_param_value_types() -> None:
    assert read_param_value({"type": "integer", "default": 30}, "28") == 28
    assert read_param_value({"type": "integer", "default": 30}, "") == 30
    assert read_param_value({"type": "number", "default": 7.0}, "5.5") == 5.5
    assert read_param_value({"type": "boolean"}, 1) is True
    assert read_param_value({"type": "integer", "nullable": True, "default": None}, "") is None
    assert read_param_value({"type": "string", "default": ""}, None) == ""


def test_generated_image_size_label() -> None:
    assert generated_image_size_label(SimpleNamespace(width=832, height=1216)) == "832 × 1216"
    assert generated_image_size_label(SimpleNamespace(width=0, height=0)) == ""


def test_clean_voice_caption_strips_labels_and_quotes() -> None:
    assert clean_voice_caption("キャプション: 「明るい若い女性の声」") == "明るい若い女性の声"
    assert clean_voice_caption("```\n- Caption: 落ち着いた声\n補足行\n```") == "落ち着いた声"
    assert clean_voice_caption("") == ""


def test_voice_caption_sheet_source_prefers_markdown_without_voice_section() -> None:
    sheet = CharacterSheet(
        id="c1",
        name="トワ",
        raw_markdown="# トワ\n\n## 性格・内面\n物静か。\n\n## 声のイメージ\n高めの声。\n\n## 過去\n星の塔育ち。",
    )
    source = voice_caption_sheet_source(sheet)
    assert "声のイメージ" not in source
    assert "物静か。" in source
    assert "星の塔育ち。" in source


def test_voice_caption_sheet_source_falls_back_to_fields() -> None:
    sheet = CharacterSheet(
        id="c1",
        name="トワ",
        age="17",
        occupation="観測者",
        personality="物静かで観察好き。",
        self_intro="トワです。",
    )
    source = voice_caption_sheet_source(sheet)
    assert source.startswith("# トワ")
    assert "- 年齢: 17" in source
    assert "## 性格・内面\n物静かで観察好き。" in source
