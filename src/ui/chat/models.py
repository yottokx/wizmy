"""キャラクターチャット UI の共有モデル。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...core.conversation.schemas import (
    ChatDebugInfo,
    ChatMessagePreview,
    ChatSessionSettings,
    time_label,
)

__all__ = [
    "CHAT_COMMANDS",
    "ChatCommandDefinition",
    "ChatDebugInfo",
    "ChatMessagePreview",
    "ChatRefs",
    "ChatSessionSettings",
    "ChatState",
    "ChatThreadPreview",
    "time_label",
]


@dataclass(frozen=True)
class ChatThreadPreview:
    id: str
    title: str
    preview: str
    time_label: str
    active: bool = False


@dataclass(frozen=True)
class ChatCommandDefinition:
    name: str
    description: str


CHAT_COMMANDS: tuple[ChatCommandDefinition, ...] = (
    ChatCommandDefinition("hold", "左側の文だけ投稿し、キャラには返さない"),
    ChatCommandDefinition("fill", "左側の文の続きを補完"),
    ChatCommandDefinition("tailor", "左側の文を現在のロール向けに書き換え"),
    ChatCommandDefinition("choices", "返答候補を3つ生成"),
    ChatCommandDefinition("guide", "次のキャラ発言・地の文の方向性を指定"),
    ChatCommandDefinition("skip", "発言をスキップしてキャラに返す"),
    ChatCommandDefinition("narrate", "次の投稿を地の文にする"),
    ChatCommandDefinition("memo", "次の投稿をコメントにする"),
    ChatCommandDefinition("imitate", "次の投稿をキャラ発言にする"),
    ChatCommandDefinition("user", "ユーザー入力に戻す"),
    ChatCommandDefinition("describe", "左側の文があれば投稿して地の文を自動生成"),
)


@dataclass
class ChatState:
    title: str = "チャットを開始"
    settings: ChatSessionSettings | None = None
    messages: list[ChatMessagePreview] = field(default_factory=list)
    sending: bool = False
    tts_generating_index: int | None = None
    input_mode: str = "user"


@dataclass
class ChatRefs:
    title: Any = None
    subtitle: Any = None
    messages: Any = None
    send_btn: Any = None
    input: Any = None
    input_mode_icon: Any = None
    history_sections: list[Any] = field(default_factory=list)
