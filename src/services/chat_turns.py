"""1:1チャットのターン実行サービス。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.character.schemas import CharacterSheet
from ..core.conversation.llm_io import (
    build_debug_info,
    format_llm_input,
    message_content_to_text,
    sanitize_chat_title,
)
from ..core.conversation.prompts.solo import (
    build_chat_title_messages,
    build_llm_messages,
    build_narration_llm_messages,
    is_first_character_turn,
    sanitize_narration,
)
from ..core.conversation.sanitize import sanitize_character_reply
from ..core.conversation.schemas import ChatMessagePreview, ChatSessionSettings, time_label


@dataclass(frozen=True)
class ChatTurnResult:
    messages: list[ChatMessagePreview]
    message: ChatMessagePreview


class ChatTurnService:
    """1:1チャットの LLM ターンを UI 非依存で実行する。"""

    async def run_character_turn(
        self,
        *,
        sheet: CharacterSheet,
        settings: ChatSessionSettings,
        messages: list[ChatMessagePreview],
        llm: Any,
        turn_instruction: str = "",
        empty_reply: str = "……少し考え込んでしまった。",
        first_turn_empty_reply: str | None = None,
    ) -> ChatTurnResult:
        prior_messages = list(messages)
        first_turn = is_first_character_turn(prior_messages)
        resolved_empty_reply = (
            first_turn_empty_reply if first_turn and first_turn_empty_reply is not None else empty_reply
        )
        generated = await self.build_character_message(
            sheet=sheet,
            settings=settings,
            messages=prior_messages,
            llm=llm,
            first_turn=first_turn,
            turn_instruction=turn_instruction,
            empty_reply=resolved_empty_reply,
        )
        return ChatTurnResult(
            messages=[*prior_messages, generated],
            message=generated,
        )

    async def run_narration_turn(
        self,
        *,
        sheet: CharacterSheet,
        settings: ChatSessionSettings,
        messages: list[ChatMessagePreview],
        llm: Any,
        instruction: str = "",
        empty_reply: str = "場面は静かに次の言葉を待っている。",
    ) -> ChatTurnResult:
        prior_messages = list(messages)
        generated = await self.build_narration_message(
            sheet=sheet,
            settings=settings,
            messages=prior_messages,
            llm=llm,
            instruction=instruction,
            empty_reply=empty_reply,
        )
        return ChatTurnResult(
            messages=[*prior_messages, generated],
            message=generated,
        )

    async def build_character_message(
        self,
        *,
        sheet: CharacterSheet,
        settings: ChatSessionSettings,
        messages: list[ChatMessagePreview],
        llm: Any,
        first_turn: bool = False,
        turn_instruction: str = "",
        empty_reply: str = "……ごめん、うまく言葉にできなかった。",
    ) -> ChatMessagePreview:
        llm_messages = build_llm_messages(
            sheet,
            settings,
            messages,
            first_turn=first_turn,
            turn_instruction=turn_instruction,
        )
        debug_input = format_llm_input(llm_messages)
        response = await llm.ainvoke(llm_messages)
        raw_output = message_content_to_text(getattr(response, "content", response))
        reply = sanitize_character_reply(raw_output, sheet.name)
        if not reply:
            reply = empty_reply
        return ChatMessagePreview(
            "character",
            reply,
            time_label(),
            build_debug_info(debug_input, raw_output, response),
        )

    async def build_narration_message(
        self,
        *,
        sheet: CharacterSheet,
        settings: ChatSessionSettings,
        messages: list[ChatMessagePreview],
        llm: Any,
        instruction: str = "",
        empty_reply: str = "場面は静かに次の言葉を待っている。",
    ) -> ChatMessagePreview:
        llm_messages = build_narration_llm_messages(
            sheet,
            settings,
            messages,
            instruction=instruction,
        )
        debug_input = format_llm_input(llm_messages)
        response = await llm.ainvoke(llm_messages)
        raw_output = message_content_to_text(getattr(response, "content", response))
        narration = sanitize_narration(raw_output)
        if not narration:
            narration = empty_reply
        return ChatMessagePreview(
            "narration",
            narration,
            time_label(),
            build_debug_info(debug_input, raw_output, response),
        )

    async def generate_auto_title(
        self,
        *,
        sheet: CharacterSheet,
        settings: ChatSessionSettings,
        messages: list[ChatMessagePreview],
        llm: Any,
    ) -> str:
        response = await llm.ainvoke(build_chat_title_messages(sheet, settings, messages))
        return sanitize_chat_title(message_content_to_text(getattr(response, "content", response)))
