"""1:1チャット特性テスト用の架空データ。"""

from __future__ import annotations

from typing import Any

from src.core.character.schemas import CharacterSheet
from src.ui.chat.models import ChatMessagePreview, ChatSessionSettings


def make_chat_sheet() -> CharacterSheet:
    """プロンプト固定テストで共有する架空キャラクターを返す。"""
    return CharacterSheet(
        id="character-iris",
        name="テストキャラ",
        age="18",
        gender="女性",
        occupation="灯台守",
        origin="霧岬の灯台",
        world="夜霧の港町",
        appearance="紺色のコートと真鍮のランタンを持つ。",
        personality="落ち着いていて、少し皮肉屋。",
        background="古い灯台で育ち、霧の声を聞き分ける。",
        self_intro="霧が濃い夜ほど、灯りは正直なの。",
        sample_dialogues="「焦らなくていい。霧は逃げないから」",
    )


def make_chat_settings() -> ChatSessionSettings:
    """プロンプト固定テストで共有する架空チャット設定を返す。"""
    return ChatSessionSettings(
        profile_id="profile-solo",
        chat_mode_id="mode-lighthouse",
        chat_mode_name="灯台巡り",
        chat_premise="夜霧の灯台で、消えた日誌の手がかりを探す。",
        situation="灯台の上階で、雨音が窓を叩いている。",
        user_persona_id="persona-mika",
        user_persona_name="テストユーザー",
        user_persona_description="港町に来たばかりの記録係。慎重だが好奇心が強い。",
    )


def make_chat_messages() -> list[ChatMessagePreview]:
    """プロンプト履歴用の架空メッセージ列を返す。"""
    return [
        ChatMessagePreview("user", "この灯台、夜になると音が変わるんですね。", "22:00"),
        ChatMessagePreview("memo", "このコメントはLLMに渡さない。", "22:01"),
        ChatMessagePreview("narration", "ランタンの火が、霧の奥で小さく揺れた。", "22:02"),
        ChatMessagePreview("character", "霧が濃いほど、灯りは遠くまで届くんだ。", "22:03"),
    ]


def message_roles_and_contents(messages: list[Any]) -> list[tuple[str, str]]:
    """LangChain メッセージ列を role/content の比較用に変換する。"""
    return [(str(message.type), str(message.content)) for message in messages]
