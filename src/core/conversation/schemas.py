"""会話ドメインの共通スキーマ。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ChatDebugInfo:
    llm_input: str
    raw_output: str
    reasoning_output: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class ChatMessagePreview:
    speaker: str
    text: str
    time_label: str
    debug: ChatDebugInfo | None = None


@dataclass(frozen=True)
class ChatSessionSettings:
    profile_id: str
    chat_mode_id: str
    chat_mode_name: str
    chat_premise: str
    situation: str
    user_persona_id: str
    user_persona_name: str
    user_persona_description: str
    user_persona_source: str = "persona"


def time_label() -> str:
    return datetime.now().strftime("%H:%M")
