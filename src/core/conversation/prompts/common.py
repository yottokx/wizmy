"""会話プロンプトで使うキャラクター概要整形。"""

from __future__ import annotations

import re

from ...character.schemas import CharacterSheet


def character_summary(sheet: CharacterSheet) -> str:
    fields = [
        ("名前", sheet.name),
        ("年齢", sheet.age),
        ("性別", sheet.gender),
        ("職業・役割", sheet.occupation),
        ("出身・所属", sheet.origin),
        ("世界観", sheet.world),
        ("外見", sheet.appearance),
        ("性格", sheet.personality),
        ("背景", sheet.background),
        ("自己紹介", sheet.self_intro),
        ("サンプル台詞", sheet.sample_dialogues),
    ]
    return "\n".join(f"{label}: {value}" for label, value in fields if value)


def compact_character_summary(sheet: CharacterSheet) -> str:
    summary = character_summary(sheet)
    summary = re.sub(r"\s+", " ", summary).strip()
    return summary[:420]
