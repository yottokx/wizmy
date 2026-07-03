"""グループチャットのターン実行サービス。"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ..core.conversation.history import (
    format_group_history,
    group_message,
    last_dialog_message,
)
from ..core.conversation.llm_io import (
    build_debug_info,
    format_llm_input,
    message_content_to_text,
    sanitize_chat_title,
)
from ..core.conversation.prompts.group import (
    build_group_character_messages,
    build_group_guest_messages,
    build_group_title_messages,
    format_group_relationship_section,
)
from ..core.conversation.sanitize import (
    sanitize_group_character_reply,
    sanitize_group_guest_reply,
)
from ..core.conversation.schemas import ChatDebugInfo
from ..core.conversation.speaker_selection import (
    choose_weighted_speaker,
    format_speaker_selection_debug,
    mentioned_member,
    speaker_weights_from_llm_output,
)
from ..core.group_chat.schemas import GroupChatRecord, GroupMember


@dataclass(frozen=True)
class SpeakerSelectionResult:
    speaker: GroupMember
    debug: ChatDebugInfo | None = None


@dataclass(frozen=True)
class GroupChatTurnResult:
    messages: list[dict[str, Any]]
    message: dict[str, Any]
    speaker: GroupMember | None = None
    speaker_debug: ChatDebugInfo | None = None


class GroupChatTurnService:
    """グループチャットの LLM ターンを UI 非依存で実行する。"""

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng

    async def run_character_turn(
        self,
        *,
        group: GroupChatRecord,
        settings: dict[str, Any],
        messages: list[dict[str, Any]],
        llm: Any,
        active_members: list[GroupMember],
        speaker: GroupMember | None = None,
        turn_instruction: str = "",
    ) -> GroupChatTurnResult:
        prior_messages = [dict(message) for message in messages]
        speaker_result = (
            SpeakerSelectionResult(speaker=speaker)
            if speaker is not None
            else await self.choose_next_speaker(
                group=group,
                settings=settings,
                messages=prior_messages,
                llm=llm,
                active_members=active_members,
            )
        )
        generated = await self.build_character_message(
            group=group,
            settings=settings,
            messages=prior_messages,
            llm=llm,
            speaker=speaker_result.speaker,
            speaker_debug=speaker_result.debug,
            turn_instruction=turn_instruction,
        )
        return GroupChatTurnResult(
            messages=[*prior_messages, generated],
            message=generated,
            speaker=speaker_result.speaker,
            speaker_debug=speaker_result.debug,
        )

    async def run_guest_turn(
        self,
        *,
        group: GroupChatRecord,
        settings: dict[str, Any],
        messages: list[dict[str, Any]],
        llm: Any,
        guest_name: str,
        turn_instruction: str = "",
    ) -> GroupChatTurnResult:
        prior_messages = [dict(message) for message in messages]
        generated = await self.build_guest_message(
            group=group,
            settings=settings,
            messages=prior_messages,
            llm=llm,
            guest_name=guest_name,
            turn_instruction=turn_instruction,
        )
        return GroupChatTurnResult(
            messages=[*prior_messages, generated],
            message=generated,
        )

    async def choose_next_speaker(
        self,
        *,
        group: GroupChatRecord,
        settings: dict[str, Any],
        messages: list[dict[str, Any]],
        llm: Any,
        active_members: list[GroupMember],
    ) -> SpeakerSelectionResult:
        last = last_dialog_message(messages)
        if last is not None and last.get("role") == "user":
            mentioned = mentioned_member(last.get("text", ""), active_members)
            if mentioned is not None:
                return SpeakerSelectionResult(mentioned)
            if len(active_members) == 1:
                return SpeakerSelectionResult(active_members[0])
            return await self.choose_speaker_with_llm(
                group=group,
                settings=settings,
                messages=messages,
                llm=llm,
                candidates=active_members,
            )

        if last is not None and last.get("role") == "character":
            previous_id = str(last.get("speaker_id", ""))
            others = [member for member in active_members if member.id != previous_id]
            if not others:
                return SpeakerSelectionResult(
                    next(
                        (member for member in active_members if member.id == previous_id),
                        active_members[0],
                    )
                )
            if len(others) == 1:
                return SpeakerSelectionResult(others[0])
            return await self.choose_speaker_with_llm(
                group=group,
                settings=settings,
                messages=messages,
                llm=llm,
                candidates=others,
            )

        if len(active_members) == 1:
            return SpeakerSelectionResult(active_members[0])
        return await self.choose_speaker_with_llm(
            group=group,
            settings=settings,
            messages=messages,
            llm=llm,
            candidates=active_members,
        )

    async def choose_speaker_with_llm(
        self,
        *,
        group: GroupChatRecord,
        settings: dict[str, Any],
        messages: list[dict[str, Any]],
        llm: Any,
        candidates: list[GroupMember],
    ) -> SpeakerSelectionResult:
        candidate_lines = "\n".join(
            f"- @{member.handle}: {member.character.name} / {member.character.occupation or '役割未設定'}"
            for member in candidates
        )
        relationship_section = format_group_relationship_section(group, settings)
        llm_messages = [
            SystemMessage(
                content=(
                    "あなたはグループチャットの次の発言者候補の発言可能性を見積もる進行役です。"
                    "候補全員について、次に発言する自然さを0以上の比率で出してください。"
                    "合計は100を目安にし、固定ローテーションを避けてください。"
                    "出力はJSONのみ。形式は {\"weights\":[{\"handle\":\"...\",\"weight\":50}]} です。"
                )
            ),
            HumanMessage(
                content=(
                    f"世界観:\n{group.world or '未設定'}\n\n"
                    f"参加候補:\n{candidate_lines}\n\n"
                    f"{relationship_section}"
                    f"会話履歴:\n{format_group_history(messages)}\n\n"
                    "候補ごとの発言可能性を比率で出力してください。"
                    "明確に特定キャラへ向けた発言なら、そのキャラを高めにしてください。"
                )
            ),
        ]
        debug_input = format_llm_input(llm_messages)
        response = await llm.ainvoke(llm_messages)
        raw = message_content_to_text(getattr(response, "content", response))
        weights = speaker_weights_from_llm_output(raw, candidates)
        selected, normalized_weights, roll = choose_weighted_speaker(
            weights,
            candidates,
            self._rng,
        )
        debug = build_debug_info(
            debug_input,
            format_speaker_selection_debug(raw, normalized_weights, selected, roll),
            response,
        )
        return SpeakerSelectionResult(selected, debug)

    async def build_character_message(
        self,
        *,
        group: GroupChatRecord,
        settings: dict[str, Any],
        messages: list[dict[str, Any]],
        llm: Any,
        speaker: GroupMember,
        speaker_debug: ChatDebugInfo | None = None,
        turn_instruction: str = "",
    ) -> dict[str, Any]:
        llm_messages = build_group_character_messages(
            group,
            settings,
            messages,
            speaker,
            turn_instruction=turn_instruction,
        )
        debug_input = format_llm_input(llm_messages)
        response = await llm.ainvoke(llm_messages)
        raw = message_content_to_text(getattr(response, "content", response))
        reply = sanitize_group_character_reply(raw, speaker)
        if not reply:
            reply = "……ごめん、今はうまく言葉にできなかった。"
        return group_message(
            "character",
            reply,
            member=speaker,
            debug=build_debug_info(debug_input, raw, response),
            speaker_debug=speaker_debug,
        )

    async def build_guest_message(
        self,
        *,
        group: GroupChatRecord,
        settings: dict[str, Any],
        messages: list[dict[str, Any]],
        llm: Any,
        guest_name: str,
        turn_instruction: str = "",
    ) -> dict[str, Any]:
        llm_messages = build_group_guest_messages(
            group,
            settings,
            messages,
            guest_name,
            turn_instruction=turn_instruction,
        )
        debug_input = format_llm_input(llm_messages)
        response = await llm.ainvoke(llm_messages)
        raw = message_content_to_text(getattr(response, "content", response))
        reply = sanitize_group_guest_reply(raw, guest_name)
        if not reply:
            reply = "……。"
        return group_message(
            "guest",
            reply,
            guest_name=guest_name,
            debug=build_debug_info(debug_input, raw, response),
        )

    async def generate_auto_title(
        self,
        *,
        group: GroupChatRecord,
        messages: list[dict[str, Any]],
        llm: Any,
    ) -> str:
        response = await llm.ainvoke(build_group_title_messages(group, messages))
        return sanitize_chat_title(message_content_to_text(getattr(response, "content", response)))
