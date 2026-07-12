"""1:1チャット(ui2)の純ロジック。

相手ピッカーの候補集計(list_recent の character_id 集計)と、
キャラクターシートをユーザー役に変換するヘルパを、描画から切り離した純関数として持つ。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..core.character.schemas import CharacterSheet
from ..core.chat.schemas import UserPersona
from ..core.chat.sessions import ChatSessionRecord
from ..core.conversation.history import session_time_label

NEVER_TALKED_LABEL = "まだ話していない"


@dataclass(frozen=True)
class PartnerEntry:
    """相手ピッカー1件分の表示データ。"""

    sheet: CharacterSheet
    last_talked_at: datetime | None
    last_label: str
    session_count: int


def build_partner_entries(
    sheets: list[CharacterSheet],
    sessions: list[ChatSessionRecord],
) -> list[PartnerEntry]:
    """話し相手候補: 話したことのある子(最終会話の新しい順)→ 未会話の子(元の並び順)。"""
    last_by_character: dict[str, datetime] = {}
    count_by_character: dict[str, int] = {}
    for session in sessions:
        count_by_character[session.character_id] = count_by_character.get(session.character_id, 0) + 1
        current = last_by_character.get(session.character_id)
        if current is None or session.updated_at > current:
            last_by_character[session.character_id] = session.updated_at

    talked: list[PartnerEntry] = []
    fresh: list[PartnerEntry] = []
    for sheet in sheets:
        last = last_by_character.get(sheet.id)
        if last is None:
            fresh.append(PartnerEntry(sheet, None, NEVER_TALKED_LABEL, 0))
        else:
            talked.append(
                PartnerEntry(sheet, last, session_time_label(last), count_by_character.get(sheet.id, 0))
            )
    talked.sort(key=lambda entry: entry.last_talked_at, reverse=True)
    return talked + fresh


def filter_partner_entries(
    entries: list[PartnerEntry],
    search: str = "",
    favorites_only: bool = False,
) -> list[PartnerEntry]:
    """相手ピッカーの絞り込み(検索=名前・職業・世界観の部分一致、★お気に入り)。"""
    query = search.strip().lower()
    result: list[PartnerEntry] = []
    for entry in entries:
        sheet = entry.sheet
        if favorites_only and not sheet.is_favorite:
            continue
        if query:
            haystack = " ".join((sheet.name, sheet.occupation, sheet.world)).lower()
            if query not in haystack:
                continue
        result.append(entry)
    return result


def character_persona_description(sheet: CharacterSheet) -> str:
    if sheet.raw_markdown.strip():
        return sheet.raw_markdown.strip()
    fields = [
        ("名前", sheet.name),
        ("年齢", sheet.age),
        ("性別", sheet.gender),
        ("職業・役割", sheet.occupation),
        ("出身・所属", sheet.origin),
        ("世界観", sheet.world),
        ("外見", sheet.appearance),
        ("性格", sheet.personality),
        ("動機", sheet.motivation),
        ("弱点", sheet.weakness),
        ("背景", sheet.background),
        ("スキル", sheet.skills),
        ("個性・クセ", sheet.quirks),
        ("物語のフック", sheet.story_hooks),
        ("自己紹介", sheet.self_intro),
        ("サンプル台詞", sheet.sample_dialogues),
        ("声のイメージ", sheet.voice_image),
    ]
    return "\n".join(f"{label}: {value}" for label, value in fields if value)


def user_persona_from_character_sheet(sheet: CharacterSheet) -> UserPersona:
    return UserPersona(
        id=sheet.id,
        name=sheet.name or "ユーザー",
        description=character_persona_description(sheet),
        media=sheet.media,
    )
