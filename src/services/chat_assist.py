"""1:1チャット周辺の補助 LLM ユースケース。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ..core.character.schemas import CharacterSheet
from ..core.chat.schemas import ChatMode, UserPersona
from ..core.conversation.input_assist import merge_completion, parse_response_choices
from ..core.conversation.llm_io import message_content_to_text
from ..core.conversation.prompts.common import character_summary
from ..core.conversation.prompts.solo import (
    build_response_choice_messages,
    build_tailored_input_messages,
    build_user_completion_messages,
)
from ..core.conversation.sanitize import clean_short_llm_text
from ..core.conversation.schemas import ChatMessagePreview, ChatSessionSettings
from ..core.conversation.solo import clean_situation_enhancement
from .ai_jobs import AIJobKind, AIJobService, AIJobStatus


@dataclass(frozen=True)
class ChatAssistJobResult:
    """補助 LLM ジョブの完了状態と結果。"""

    job_id: str
    status: AIJobStatus
    value: Any = None
    error_message: str = ""

    @property
    def succeeded(self) -> bool:
        return self.status == AIJobStatus.SUCCEEDED


class ChatAssistService:
    """1:1チャット補助機能の LLM 呼び出しを UI 非依存で実行する。"""

    def __init__(self, ai_jobs: AIJobService) -> None:
        self._ai_jobs = ai_jobs

    async def run_assist_job(
        self,
        *,
        label: str,
        scope: str,
        metadata: dict[str, Any],
        runner,
        result_url: str = "",
    ) -> ChatAssistJobResult:
        job = self._ai_jobs.start_job(
            kind=AIJobKind.LLM_ASSIST,
            label=label,
            scope=scope,
            metadata=metadata,
            runner=lambda _: runner(),
        )
        if result_url:
            self._ai_jobs.set_result_meta(job.id, {"result_url": result_url})
        finished = await self._ai_jobs.wait(job.id)
        return ChatAssistJobResult(
            job_id=job.id,
            status=finished.status,
            value=finished.result,
            error_message=finished.error_message,
        )

    async def complete_input_text(
        self,
        *,
        llm: Any,
        sheet: CharacterSheet,
        settings: ChatSessionSettings,
        messages: list[ChatMessagePreview],
        left_text: str,
        input_mode: str,
        scope: str,
        metadata: dict[str, Any],
        result_url: str = "",
    ) -> ChatAssistJobResult:
        async def _runner() -> str:
            response = await llm.ainvoke(
                build_user_completion_messages(
                    sheet,
                    settings,
                    messages,
                    left_text,
                    input_mode=input_mode,
                )
            )
            raw = message_content_to_text(getattr(response, "content", response))
            return merge_completion(left_text, raw)

        return await self.run_assist_job(
            label="入力補完",
            scope=scope,
            metadata=metadata,
            result_url=result_url,
            runner=_runner,
        )

    async def tailor_input_text(
        self,
        *,
        llm: Any,
        sheet: CharacterSheet,
        settings: ChatSessionSettings,
        messages: list[ChatMessagePreview],
        left_text: str,
        input_mode: str,
        scope: str,
        metadata: dict[str, Any],
        result_url: str = "",
    ) -> ChatAssistJobResult:
        async def _runner() -> str:
            response = await llm.ainvoke(
                build_tailored_input_messages(
                    sheet,
                    settings,
                    messages,
                    left_text,
                    input_mode=input_mode,
                )
            )
            raw = message_content_to_text(getattr(response, "content", response))
            return clean_short_llm_text(raw)

        return await self.run_assist_job(
            label="入力書き換え",
            scope=scope,
            metadata=metadata,
            result_url=result_url,
            runner=_runner,
        )

    async def generate_response_choices(
        self,
        *,
        llm: Any,
        sheet: CharacterSheet,
        settings: ChatSessionSettings,
        messages: list[ChatMessagePreview],
        left_text: str,
        input_mode: str,
        scope: str,
        metadata: dict[str, Any],
        result_url: str = "",
    ) -> ChatAssistJobResult:
        async def _runner() -> list[str]:
            response = await llm.ainvoke(
                build_response_choice_messages(
                    sheet,
                    settings,
                    messages,
                    left_text,
                    input_mode=input_mode,
                )
            )
            raw = message_content_to_text(getattr(response, "content", response))
            choices = parse_response_choices(raw)
            if left_text.strip():
                choices = [merge_completion(left_text, choice) for choice in choices]
            return choices

        return await self.run_assist_job(
            label="応答候補生成",
            scope=scope,
            metadata=metadata,
            result_url=result_url,
            runner=_runner,
        )

    async def enhance_situation(
        self,
        *,
        llm: Any,
        sheet: CharacterSheet,
        mode: ChatMode,
        persona: UserPersona,
        premise: str,
        current_situation: str,
        scope: str,
        metadata: dict[str, Any],
        result_url: str = "",
    ) -> ChatAssistJobResult:
        async def _runner() -> str:
            response = await llm.ainvoke(
                [
                    SystemMessage(content="あなたはキャラクターチャット開始時のシチュエーションを整える編集者です。"),
                    HumanMessage(
                        content=(
                            "次のチャット開始シチュエーションを、矛盾を増やさず具体性だけ補ってください。\n"
                            "出力は補強後のシチュエーション本文だけにしてください。箇条書き、解説、前置きは禁止です。\n\n"
                            f"キャラクター名: {sheet.name or 'キャラクター'}\n"
                            f"チャットモード: {mode.name}\n"
                            f"前提: {premise}\n"
                            f"ユーザーペルソナ名: {persona.name}\n"
                            f"ユーザーペルソナ設定:\n{persona.description.strip()}\n\n"
                            f"現在のシチュエーション:\n{current_situation}\n\n"
                            f"キャラクター概要:\n{character_summary(sheet)}"
                        )
                    ),
                ]
            )
            raw = message_content_to_text(getattr(response, "content", response))
            return clean_situation_enhancement(raw)

        return await self.run_assist_job(
            label="シチュエーション補完",
            scope=scope,
            metadata=metadata,
            result_url=result_url,
            runner=_runner,
        )
