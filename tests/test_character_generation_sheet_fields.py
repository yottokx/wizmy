from src.core.character_generation.prompts import (
    ASSEMBLY_SYSTEM,
    ASSEMBLY_USER_TEMPLATE,
    MODIFY_ASSEMBLY_SYSTEM,
    MODIFY_ASSEMBLY_USER_TEMPLATE,
    RELATED_ASSEMBLY_SYSTEM,
    REQUIRED_SHEET_HEADERS,
)
from src.services.character_generation import parse_markdown_to_sheet


def test_parse_markdown_extracts_sample_dialogues() -> None:
    sheet = parse_markdown_to_sheet(
        """# テストキャラ

## 基本情報
| 項目 | 内容 |
|------|------|
| 名前 | テストキャラ |

## 自己紹介台詞
「私はテストキャラ。よろしく。」

## サンプル台詞
- 「少し考えさせて。」
- 「無理はしなくていいよ。」
- 「ここは落ち着いて進めよう。」
""",
        "character-1",
    )

    assert sheet.name == "テストキャラ"
    assert "少し考えさせて" in sheet.sample_dialogues
    assert sheet.story_hooks == ""
    assert sheet.relationships == []


def test_required_headers_use_sample_dialogues_instead_of_story_hooks() -> None:
    assert "## サンプル台詞" in REQUIRED_SHEET_HEADERS
    assert "## 物語のフック" not in REQUIRED_SHEET_HEADERS


def test_sample_dialogue_prompt_requires_three_sequential_lines() -> None:
    prompt_text = f"{ASSEMBLY_SYSTEM}\n{ASSEMBLY_USER_TEMPLATE}"

    assert "必ず3つ" in prompt_text
    assert "2つ目は自己紹介台詞と1つ目" in prompt_text
    assert "3つ目は自己紹介台詞と1つ目・2つ目" in prompt_text


def test_dialogue_prompt_requires_first_person_and_bans_parenthetical_stage_directions() -> None:
    prompt_text = f"{ASSEMBLY_SYSTEM}\n{ASSEMBLY_USER_TEMPLATE}"

    assert "一人称を必ず含め" in prompt_text
    assert "括弧付きのト書き" in prompt_text


def test_prompt_requires_character_name() -> None:
    prompt_text = f"{ASSEMBLY_SYSTEM}\n{ASSEMBLY_USER_TEMPLATE}"

    assert "名前」欄には、キャラクター名の選択結果を必ず設定" in prompt_text
    assert "プレースホルダは禁止" in prompt_text


def test_generation_prompts_do_not_request_voice_image() -> None:
    prompt_text = "\n".join([
        ASSEMBLY_SYSTEM,
        ASSEMBLY_USER_TEMPLATE,
        MODIFY_ASSEMBLY_SYSTEM,
        MODIFY_ASSEMBLY_USER_TEMPLATE,
        RELATED_ASSEMBLY_SYSTEM,
    ])

    assert "声のイメージ" not in prompt_text
