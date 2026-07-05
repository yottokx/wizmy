"""1:1チャット固有の変換ヘルパー。"""

from __future__ import annotations

import re

from ..character.schemas import CharacterSheet
from ..chat.schemas import ChatMode, UserPersona
from ..chat.templates import render_chat_mode

USER_PERSONA_SOURCE_PERSONA = "persona"
USER_PERSONA_SOURCE_CHARACTER = "character"


def chat_user_persona_source(value: str) -> str:
    if value == USER_PERSONA_SOURCE_CHARACTER:
        return USER_PERSONA_SOURCE_CHARACTER
    return USER_PERSONA_SOURCE_PERSONA


def input_mode_for_speaker(speaker: str) -> str:
    if speaker == "character":
        return "character"
    if speaker == "narration":
        return "narration"
    if speaker == "memo":
        return "memo"
    return "user"


def message_target_label(speaker: str) -> str:
    if speaker == "character":
        return "キャラクターの台詞"
    if speaker == "narration":
        return "地の文"
    if speaker == "memo":
        return "コメント"
    return "発言"


def user_persona_tts_id(persona_id: str) -> str:
    return f"user-persona-{persona_id}"


def render_mode_for_sheet(
    mode: ChatMode,
    sheet: CharacterSheet,
    persona: UserPersona,
) -> tuple[str, str]:
    return render_chat_mode(
        mode,
        character_name=sheet.name or "キャラクター",
        user_persona_name=persona.name or "ユーザー",
    )


def clean_situation_enhancement(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r"^```(?:\w+)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    return text
