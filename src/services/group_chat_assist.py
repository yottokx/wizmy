"""グループチャット周辺の補助 LLM ユースケース。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ..core.character.markdown import base_character_markdown, remove_markdown_section
from ..core.character.schemas import CharacterSheet
from ..core.chat.schemas import UserPersona
from ..core.conversation.history import group_message
from ..core.conversation.input_assist import merge_completion, parse_response_choices
from ..core.conversation.llm_io import (
    build_debug_info,
    format_llm_input,
    message_content_to_text,
)
from ..core.conversation.prompts.common import compact_character_summary
from ..core.conversation.prompts.group import (
    build_group_input_completion_messages,
    build_group_narration_messages,
    build_group_response_choice_messages,
    build_group_tailored_input_messages,
    format_group_relationship_section,
)
from ..core.conversation.relationship_drafts import (
    limit_relationship_drafts,
    parse_group_generation_relationship_drafts,
    parse_relationship_draft_response,
    relationship_draft_participants,
)
from ..core.conversation.sanitize import (
    clean_arrival_reason_response,
    clean_character_markdown_response,
    clean_group_situation_enhancement,
    clean_persona_description_response,
    clean_relationship_enhancement,
    clean_short_llm_text,
    sanitize_group_narration,
)
from ..core.conversation.world_adaptation import format_optional_instruction
from ..core.group_chat.schemas import GroupChatRecord, GroupMember
from .ai_jobs import AIJobKind, AIJobService, AIJobStatus
from .api_config import ApiConfigService
from .llm_runtime import build_configured_llm


@dataclass(frozen=True)
class GroupChatAssistJobResult:
    """補助 LLM ジョブの完了状態と結果。"""

    job_id: str
    status: AIJobStatus
    value: Any = None
    error_message: str = ""

    @property
    def succeeded(self) -> bool:
        return self.status == AIJobStatus.SUCCEEDED


class GroupChatAssistService:
    """グループチャット補助機能の LLM 呼び出しを UI 非依存で実行する。"""

    def __init__(self, api_config: ApiConfigService, ai_jobs: AIJobService) -> None:
        self._api_config = api_config
        self._ai_jobs = ai_jobs

    def build_llm(self, profile_id: str, vault_password: str | None) -> Any:
        return build_configured_llm(self._api_config, profile_id, vault_password)

    async def run_assist_job(
        self,
        *,
        label: str,
        scope: str,
        metadata: dict[str, Any],
        runner,
        result_url: str = "",
        on_job_started=None,
    ) -> GroupChatAssistJobResult:
        job = self._ai_jobs.start_job(
            kind=AIJobKind.LLM_ASSIST,
            label=label,
            scope=scope,
            metadata=metadata,
            runner=lambda _: runner(),
        )
        if result_url:
            self._ai_jobs.set_result_meta(job.id, {"result_url": result_url})
        if on_job_started is not None:
            on_job_started(job.id)
        finished = await self._ai_jobs.wait(job.id)
        return GroupChatAssistJobResult(
            job_id=job.id,
            status=finished.status,
            value=finished.result,
            error_message=finished.error_message,
        )

    async def generate_group_generation_relationship_drafts(
        self,
        *,
        profile_id: str,
        vault_password: str | None,
        group: GroupChatRecord,
        generated_sheet: CharacterSheet,
        base_members: list[GroupMember],
    ) -> GroupChatAssistJobResult:
        if not base_members:
            return GroupChatAssistJobResult("", AIJobStatus.SUCCEEDED, {})
        llm = self.build_llm(profile_id, vault_password)
        payload = {
            "world": group.world,
            "generated": {
                "name": generated_sheet.name,
                "summary": compact_character_summary(generated_sheet),
            },
            "bases": [
                {
                    "member_id": member.id,
                    "handle": member.handle,
                    "name": member.character.name,
                    "summary": compact_character_summary(member.character),
                }
                for member in base_members
            ],
        }

        async def _runner() -> dict[str, str]:
            response = await llm.ainvoke(
                [
                    SystemMessage(
                        content=("あなたはグループチャット用の関係性設定を作る編集者です。出力はJSONのみです。")
                    ),
                    HumanMessage(
                        content=(
                            "新規生成キャラクターと各ベースメンバーの関係性説明を作ってください。\n"
                            "制約: それぞれ80〜160文字程度、会話で使いやすい具体性、"
                            "シート本文ではなくグループ関係性として保存する前提。\n"
                            "形式: {\"relationships\":[{\"member_id\":\"...\",\"description\":\"...\"}]}。\n\n"
                            f"{json.dumps(payload, ensure_ascii=False)}"
                        )
                    ),
                ]
            )
            raw = message_content_to_text(getattr(response, "content", response))
            return parse_group_generation_relationship_drafts(raw, base_members)

        return await self.run_assist_job(
            label="関連キャラ関係性生成",
            scope=f"group_generation:{group.id}:relationships",
            metadata={"group_id": group.id, "base_count": len(base_members)},
            result_url=f"/groups/{group.id}/generation",
            runner=_runner,
        )

    async def adapt_character_to_world(
        self,
        *,
        profile_id: str,
        vault_password: str | None,
        sheet: CharacterSheet,
        world: str,
        additional_instruction: str,
        on_job_started=None,
    ) -> GroupChatAssistJobResult:
        llm = self.build_llm(profile_id, vault_password)
        original_markdown = base_character_markdown(sheet)

        async def _runner() -> str:
            response = await llm.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "あなたはキャラクターシートを別ワールド向けに調整する編集者です。"
                            "出力は更新後のMarkdown全文だけにしてください。"
                        )
                    ),
                    HumanMessage(
                        content=(
                            "次のキャラクターが、確定ワールドに元々存在していた人物として自然に成立するように、"
                            "キャラクターシートを最小限改変してください。\n"
                            "グループ全体のワールドは別途保存されるため、世界観・舞台セクションは削除してください。\n"
                            "元の世界観情報も、確定ワールドの本文も、キャラクターシート内には残さないでください。\n"
                            "人物の名前、魅力、口調、主要な性格はできるだけ維持してください。\n"
                            "Markdownの見出し構造は可能な限り維持し、解説や差分説明は出力しないでください。\n\n"
                            f"確定ワールド:\n{world.strip()}\n\n"
                            f"{format_optional_instruction(additional_instruction)}"
                            f"現在のキャラクターシートMarkdown:\n{original_markdown}"
                        )
                    ),
                ]
            )
            return clean_character_markdown_response(message_content_to_text(getattr(response, "content", response)))

        result = await self.run_assist_job(
            label="キャラクターシート調整",
            scope="group_setup:world_adapt",
            metadata={"character_id": sheet.id},
            result_url="/groups",
            runner=_runner,
            on_job_started=on_job_started,
        )
        if result.succeeded:
            return GroupChatAssistJobResult(
                result.job_id,
                result.status,
                remove_markdown_section(str(result.value or "").strip(), "世界観・舞台"),
                result.error_message,
            )
        return result

    async def adapt_user_persona_to_world(
        self,
        *,
        profile_id: str,
        vault_password: str | None,
        display_name: str,
        description: str,
        world: str,
        additional_instruction: str,
        on_job_started=None,
    ) -> GroupChatAssistJobResult:
        llm = self.build_llm(profile_id, vault_password)
        current_description = (description or "").strip()

        async def _runner() -> str:
            response = await llm.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "あなたはユーザーペルソナ設定をグループチャット用に調整する編集者です。"
                            "出力は更新後の説明文だけにしてください。"
                        )
                    ),
                    HumanMessage(
                        content=(
                            "次のユーザーペルソナが、確定ワールドに元々存在していた人物として自然に成立するように、"
                            "説明文を最小限改変してください。\n"
                            "ユーザーペルソナはキャラクターシート化しません。見出し、箇条書き、解説、差分説明は出力しないでください。\n"
                            "名前、口調、主要な人格や役割はできるだけ維持してください。\n"
                            "元の世界観情報がある場合は、確定ワールドの住人として矛盾しない内容に置き換えてください。\n\n"
                            f"表示名: {display_name}\n"
                            f"確定ワールド:\n{world.strip()}\n\n"
                            f"{format_optional_instruction(additional_instruction)}"
                            f"現在のユーザーペルソナ説明:\n{current_description or '未設定'}"
                        )
                    ),
                ]
            )
            return clean_persona_description_response(message_content_to_text(getattr(response, "content", response)))

        result = await self.run_assist_job(
            label="ユーザーペルソナ調整",
            scope="group_setup:user_world_adapt",
            metadata={"display_name": display_name},
            result_url="/groups",
            runner=_runner,
            on_job_started=on_job_started,
        )
        return result

    async def generate_arrival_reason(
        self,
        *,
        profile_id: str,
        vault_password: str | None,
        display_name: str,
        world: str,
        summary: str,
        on_job_started=None,
    ) -> GroupChatAssistJobResult:
        llm = self.build_llm(profile_id, vault_password)

        async def _runner() -> str:
            response = await llm.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "あなたはグループチャット用の来訪理由を作る編集者です。出力は理由本文だけにしてください。"
                        )
                    ),
                    HumanMessage(
                        content=(
                            "参加者が次のワールドに来た理由を、短く自然に補完してください。\n"
                            "1〜3文で、会話に使いやすい具体性にしてください。"
                            "見出し、箇条書き、引用符、解説は出力しないでください。\n\n"
                            f"参加者: {display_name}\n"
                            f"参加者概要:\n{summary or '未設定'}\n\n"
                            f"ワールド:\n{world.strip()}"
                        )
                    ),
                ]
            )
            return clean_arrival_reason_response(message_content_to_text(getattr(response, "content", response)))

        result = await self.run_assist_job(
            label="来訪理由補完",
            scope="group_setup:arrival_reason",
            metadata={"display_name": display_name},
            result_url="/groups",
            runner=_runner,
            on_job_started=on_job_started,
        )
        return result

    async def generate_relationship_drafts(
        self,
        *,
        profile_id: str,
        vault_password: str | None,
        characters: list[CharacterSheet],
        persona: UserPersona | None,
        world: str,
        state: dict[str, Any],
        on_job_started=None,
    ) -> GroupChatAssistJobResult:
        llm = self.build_llm(profile_id, vault_password)
        participants = relationship_draft_participants(characters, persona, state)
        valid_keys = {item["key"] for item in participants}

        async def _runner() -> list[dict[str, str]]:
            response = await llm.ainvoke(
                [
                    SystemMessage(
                        content=("あなたはグループチャット用の参加者関係性を設計する編集者です。出力はJSONのみです。")
                    ),
                    HumanMessage(
                        content=(
                            "参加キャラクターとユーザーペルソナの関係性を設定してください。\n"
                            "各参加者につき最大2人までとの関係にしてください。\n"
                            "全員を無理に総当たりにせず、会話が動きやすい重要な関係だけを作ってください。\n"
                            "重複ペアと自分自身との関係は禁止です。\n"
                            "participant_a_key / participant_b_key には入力参加者の key をそのまま使ってください。\n"
                            "出力形式: {\"relationships\":[{\"participant_a_key\":\"character:...\","
                            "\"participant_b_key\":\"user\",\"description\":\"...\"}]}\n\n"
                            f"ワールド:\n{world or '未設定'}\n\n"
                            f"参加者:\n{json.dumps(participants, ensure_ascii=False)}"
                        )
                    ),
                ]
            )
            raw = message_content_to_text(getattr(response, "content", response))
            parsed = parse_relationship_draft_response(raw, participants)
            return limit_relationship_drafts(
                parsed,
                valid_keys,
                existing=state.get("relationships", []),
                max_per_participant=2,
            )

        result = await self.run_assist_job(
            label="関係性自動設定",
            scope="group_setup:relationships",
            metadata={"participant_count": len(participants)},
            result_url="/groups",
            runner=_runner,
            on_job_started=on_job_started,
        )
        return result

    async def enhance_relationship_description(
        self,
        *,
        profile_id: str,
        vault_password: str | None,
        world: str,
        participants: list[dict[str, str]],
        first_key: str,
        second_key: str,
        current_description: str,
        on_job_started=None,
    ) -> GroupChatAssistJobResult:
        llm = self.build_llm(profile_id, vault_password)
        participant_map = {str(item.get("key") or ""): item for item in participants}
        first = participant_map.get(first_key, {"key": first_key, "name": first_key})
        second = participant_map.get(second_key, {"key": second_key, "name": second_key})

        async def _runner() -> str:
            response = await llm.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "あなたはグループチャット用の関係性設定を整える編集者です。"
                            "出力は補完後の関係性本文だけにしてください。"
                            "箇条書き、解説、前置き、タイトルは禁止です。"
                        )
                    ),
                    HumanMessage(
                        content=(
                            "既存の入力内容を核にして、矛盾を増やさず具体性だけ補ってください。"
                            "会話中に使いやすい短めの関係性説明にしてください。\n\n"
                            f"ワールド:\n{world or '未設定'}\n\n"
                            f"参加者1:\n{json.dumps(first, ensure_ascii=False)}\n\n"
                            f"参加者2:\n{json.dumps(second, ensure_ascii=False)}\n\n"
                            f"現在の関係性:\n{current_description.strip()}"
                        )
                    ),
                ]
            )
            return clean_relationship_enhancement(message_content_to_text(getattr(response, "content", response)))

        result = await self.run_assist_job(
            label="関係性補完",
            scope="group_setup:relationship_enhance",
            metadata={"participant_a_key": first_key, "participant_b_key": second_key},
            result_url="/groups",
            runner=_runner,
            on_job_started=on_job_started,
        )
        return result

    async def generate_scene_message(
        self,
        *,
        llm: Any,
        group: GroupChatRecord,
        settings: dict[str, Any],
        messages: list[dict[str, Any]],
        instruction: str = "",
    ) -> dict[str, Any]:
        llm_messages = build_group_narration_messages(
            group,
            settings,
            messages,
            instruction=instruction,
        )
        debug_input = format_llm_input(llm_messages)
        response = await llm.ainvoke(llm_messages)
        raw = message_content_to_text(getattr(response, "content", response))
        narration = sanitize_group_narration(raw)
        if not narration:
            narration = "場面は静かに次の言葉を待っている。"
        return group_message(
            "narration",
            narration,
            debug=build_debug_info(debug_input, raw, response),
        )

    async def complete_input_text(
        self,
        *,
        profile_id: str,
        vault_password: str | None,
        group: GroupChatRecord,
        settings: dict[str, Any],
        messages: list[dict[str, Any]],
        left_text: str,
        input_mode: str,
        speaker: GroupMember | None,
        guest_name: str,
        scope: str,
        metadata: dict[str, Any],
        result_url: str = "",
    ) -> GroupChatAssistJobResult:
        llm = self.build_llm(profile_id, vault_password)

        async def _runner() -> str:
            response = await llm.ainvoke(
                build_group_input_completion_messages(
                    group,
                    settings,
                    messages,
                    left_text,
                    input_mode=input_mode,
                    speaker=speaker,
                    guest_name=guest_name,
                )
            )
            raw = message_content_to_text(getattr(response, "content", response))
            return merge_completion(left_text, raw)

        return await self.run_assist_job(
            label="グループ入力補完",
            scope=scope,
            metadata=metadata,
            result_url=result_url,
            runner=_runner,
        )

    async def tailor_input_text(
        self,
        *,
        profile_id: str,
        vault_password: str | None,
        group: GroupChatRecord,
        settings: dict[str, Any],
        messages: list[dict[str, Any]],
        left_text: str,
        input_mode: str,
        speaker: GroupMember | None,
        guest_name: str,
        scope: str,
        metadata: dict[str, Any],
        result_url: str = "",
    ) -> GroupChatAssistJobResult:
        llm = self.build_llm(profile_id, vault_password)

        async def _runner() -> str:
            response = await llm.ainvoke(
                build_group_tailored_input_messages(
                    group,
                    settings,
                    messages,
                    left_text,
                    input_mode=input_mode,
                    speaker=speaker,
                    guest_name=guest_name,
                )
            )
            raw = message_content_to_text(getattr(response, "content", response))
            return clean_short_llm_text(raw)

        return await self.run_assist_job(
            label="グループ入力書き換え",
            scope=scope,
            metadata=metadata,
            result_url=result_url,
            runner=_runner,
        )

    async def generate_response_choices(
        self,
        *,
        profile_id: str,
        vault_password: str | None,
        group: GroupChatRecord,
        settings: dict[str, Any],
        messages: list[dict[str, Any]],
        left_text: str,
        input_mode: str,
        speaker: GroupMember | None,
        guest_name: str,
        scope: str,
        metadata: dict[str, Any],
        result_url: str = "",
    ) -> GroupChatAssistJobResult:
        llm = self.build_llm(profile_id, vault_password)

        async def _runner() -> list[str]:
            response = await llm.ainvoke(
                build_group_response_choice_messages(
                    group,
                    settings,
                    messages,
                    left_text,
                    input_mode=input_mode,
                    speaker=speaker,
                    guest_name=guest_name,
                )
            )
            raw = message_content_to_text(getattr(response, "content", response))
            choices = parse_response_choices(raw)
            if left_text.strip():
                choices = [merge_completion(left_text, choice) for choice in choices]
            return choices

        return await self.run_assist_job(
            label="グループ応答候補生成",
            scope=scope,
            metadata=metadata,
            result_url=result_url,
            runner=_runner,
        )

    async def enhance_situation(
        self,
        *,
        profile_id: str,
        vault_password: str | None,
        group: GroupChatRecord,
        participant_ids: list[str],
        current_situation: str,
        scope: str,
        metadata: dict[str, Any],
        result_url: str = "",
    ) -> GroupChatAssistJobResult:
        llm = self.build_llm(profile_id, vault_password)
        active = [member for member in group.members if member.id in set(participant_ids)] or group.members
        member_lines = "\n".join(
            f"- @{member.handle} / {member.character.name}: {compact_character_summary(member.character)}"
            for member in active
        )
        relationship_section = format_group_relationship_section(
            group,
            {"participant_ids": participant_ids},
        )

        async def _runner() -> str:
            response = await llm.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "あなたはグループチャット開始時のシチュエーションを整える編集者です。"
                            "出力は補強後のシチュエーション本文だけにしてください。"
                            "箇条書き、解説、前置き、タイトルは禁止です。"
                        )
                    ),
                    HumanMessage(
                        content=(
                            "既存の入力内容を、矛盾を増やさず具体性だけ補ってください。"
                            "会話を始めやすい短めの場面説明にしてください。\n\n"
                            f"グループ名: {group.name}\n"
                            f"世界観:\n{group.world or '未設定'}\n\n"
                            f"参加キャラクター:\n{member_lines or 'なし'}\n\n"
                            f"{relationship_section}"
                            f"現在のシチュエーション:\n{current_situation.strip()}"
                        )
                    ),
                ]
            )
            raw = message_content_to_text(getattr(response, "content", response))
            return clean_group_situation_enhancement(raw)

        return await self.run_assist_job(
            label="グループシチュエーション補完",
            scope=scope,
            metadata=metadata,
            result_url=result_url,
            runner=_runner,
        )
