"""ui2/media_logic.py(メディア編集の純ロジック)の単体テスト。"""

from __future__ import annotations

from types import SimpleNamespace

from src.core.character.schemas import CharacterSheet
from src.ui2.media_logic import (
    PromptTagBox,
    candidate_negative_tags,
    clean_voice_caption,
    generated_image_size_label,
    read_param_value,
    split_prompt_tags,
    voice_caption_sheet_source,
)


def test_split_prompt_tags_handles_commas_and_newlines() -> None:
    assert split_prompt_tags("1girl, solo,\nfull body ,  ") == ["1girl", "solo", "full body"]
    assert split_prompt_tags("") == []


def test_prompt_tag_box_from_profile_dedupes() -> None:
    box = PromptTagBox.from_profile("1girl, solo, 1girl, Solo")
    assert box.base == ["1girl", "solo"]
    assert box.prompt() == "1girl, solo"


def test_prompt_tag_box_apply_candidate_replaces_generated_only() -> None:
    box = PromptTagBox.from_profile("1girl, solo")
    box.apply_candidate("silver hair, ancient library")
    assert box.generated == ["silver hair", "ancient library"]
    # 候補を再適用すると候補由来だけが置き換わる
    box.apply_candidate("red hair")
    assert box.base == ["1girl", "solo"]
    assert box.generated == ["red hair"]
    assert box.prompt() == "1girl, solo, red hair"


def test_prompt_tag_box_apply_candidate_skips_base_duplicates() -> None:
    box = PromptTagBox.from_profile("1girl, solo")
    box.apply_candidate("solo, lamplight")
    assert box.generated == ["lamplight"]


def test_prompt_tag_box_add_and_remove() -> None:
    box = PromptTagBox.from_profile("1girl")
    box.add("solo, 1girl")  # 重複は追加されない
    assert box.base == ["1girl", "solo"]
    box.apply_candidate("lamplight")
    box.remove("solo", generated=False)
    box.remove("lamplight", generated=True)
    assert box.prompt() == "1girl"


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
