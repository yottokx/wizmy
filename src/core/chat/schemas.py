"""Chat setup schemas."""

from __future__ import annotations

from pydantic import BaseModel


class ChatMode(BaseModel):
    id: str
    name: str
    premise_template: str = ""
    situation_template: str = ""


class UserPersona(BaseModel):
    id: str
    name: str
    description: str = ""


_DEFAULT_CHAT_MODES = (
    ChatMode(
        id="smalltalk",
        name="雑談",
        premise_template=(
            "{{ character_name }}が世界観やストーリーには執着せず、"
            "どんな会話をしても自然に受け入れる。"
        ),
        situation_template="{{ user_persona_name }}は{{ character_name }}の友人として会話する。",
    ),
    ChatMode(
        id="roleplay",
        name="異世界転移",
        premise_template=(
            "{{ character_name }}は自身の世界にいて、"
            "その世界の価値観で会話する。"
        ),
        situation_template=(
            "{{ user_persona_name }}は{{ character_name }}の世界に転移した人物として会話する。"
        ),
    ),
    ChatMode(
        id="summon",
        name="召喚",
        premise_template=(
            "{{ character_name }}が{{ user_persona_name }}の世界に転移した設定で会話する。"
        ),
        situation_template=(
            "{{ user_persona_name }}はこちらの世界で{{ character_name }}と出会った人物として会話する。"
        ),
    ),
)


def default_chat_modes() -> list[ChatMode]:
    return [mode.model_copy(deep=True) for mode in _DEFAULT_CHAT_MODES]
