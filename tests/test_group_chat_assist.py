from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from src.core.character.schemas import CharacterSheet
from src.core.conversation.history import group_message
from src.core.conversation.relationship_drafts import (
    parse_group_generation_relationship_drafts,
    parse_relationship_draft_response,
    relationship_draft_participants,
    relationship_key_from_item,
)
from src.core.conversation.sanitize import clean_group_situation_enhancement
from src.services.ai_jobs import AIJobService, AIJobStatus
from src.services.group_chat_assist import GroupChatAssistService
from tests.group_chat_test_helpers import make_group_chat, make_group_settings


class FakeLLMResponse:
    def __init__(self, content: str) -> None:
        self.content = content
        self.usage_metadata = {
            "input_tokens": 5,
            "output_tokens": 7,
            "total_tokens": 12,
        }


class FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[list[Any]] = []

    async def ainvoke(self, messages: list[Any]) -> FakeLLMResponse:
        self.calls.append(messages)
        if not self.responses:
            raise AssertionError("FakeLLM の応答が不足しています")
        return FakeLLMResponse(self.responses.pop(0))


def _service(llm: FakeLLM) -> tuple[GroupChatAssistService, Any]:
    service = GroupChatAssistService(object(), AIJobService())  # type: ignore[arg-type]
    patcher = patch("src.services.group_chat_assist.build_configured_llm", return_value=llm)
    return service, patcher


class GroupChatAssistServiceTest(unittest.IsolatedAsyncioTestCase):
    def test_relationship_parse_functions_reject_invalid_output(self) -> None:
        group = make_group_chat()
        participants = relationship_draft_participants(
            [member.character for member in group.members],
            group.user_persona,
            {"entry_modes": {}, "arrival_reasons": {}, "adaptation_notes": {}},
        )

        self.assertEqual({}, parse_group_generation_relationship_drafts("関係性を作ります", group.members))
        self.assertEqual([], parse_relationship_draft_response("関係性を作ります", participants))
        self.assertEqual(
            "夜の閲覧室に淡い灯りが差す。", clean_group_situation_enhancement("補強結果: 夜の閲覧室に淡い灯りが差す。")
        )

    def test_relationship_key_from_item_uses_identifier_map(self) -> None:
        key_by_identifier = {
            "character:character-akari": "member:member-akari",
            "user": "user:persona-sora",
        }

        self.assertEqual(
            "member:member-akari",
            relationship_key_from_item(
                {"participant_a_key": "character:character-akari"},
                key_by_identifier,
                ("participant_a_key",),
            ),
        )
        self.assertEqual(
            "",
            relationship_key_from_item(
                {"participant_a_key": "character:missing"},
                key_by_identifier,
                ("participant_a_key",),
            ),
        )

    async def test_setup_use_cases_run_as_jobs_with_stub_llm(self) -> None:
        group = make_group_chat()
        generated = CharacterSheet(id="character-new", name="新規人物", personality="観察眼が鋭い。")
        llm = FakeLLM(
            [
                '{"relationships":[{"member_id":"member-akari","description":"星図をめぐる相談相手。"}]}',
                "# 灯里\n\n## 世界観・舞台\n消える世界\n\n## 性格・内面\n星図を守る。",
                "説明: 記録係として図書館に馴染んでいる。",
                "理由: 古い招待状を受け取った。",
                '{"relationships":[{"participant_a_key":"character:character-akari","participant_b_key":"user","description":"記録を一緒に整理する。"}]}',
                "関係性: 互いに星図の秘密を共有している。",
            ]
        )
        service, patcher = _service(llm)

        with patcher:
            related = await service.generate_group_generation_relationship_drafts(
                profile_id="profile-test",
                vault_password=None,
                group=group,
                generated_sheet=generated,
                base_members=group.members,
            )
            adapted = await service.adapt_character_to_world(
                profile_id="profile-test",
                vault_password=None,
                sheet=group.members[0].character,
                world=group.world,
                additional_instruction="",
            )
            persona = await service.adapt_user_persona_to_world(
                profile_id="profile-test",
                vault_password=None,
                display_name="ソラ",
                description="旅人。",
                world=group.world,
                additional_instruction="",
            )
            reason = await service.generate_arrival_reason(
                profile_id="profile-test",
                vault_password=None,
                display_name="ソラ",
                world=group.world,
                summary="記録係",
            )
            drafts = await service.generate_relationship_drafts(
                profile_id="profile-test",
                vault_password=None,
                characters=[member.character for member in group.members],
                persona=group.user_persona,  # type: ignore[arg-type]
                world=group.world,
                state={"entry_modes": {}, "arrival_reasons": {}, "adaptation_notes": {}, "relationships": []},
            )
            enhanced = await service.enhance_relationship_description(
                profile_id="profile-test",
                vault_password=None,
                world=group.world,
                participants=relationship_draft_participants(
                    [member.character for member in group.members],
                    group.user_persona,
                    {"entry_modes": {}, "arrival_reasons": {}, "adaptation_notes": {}},
                ),
                first_key="character:character-akari",
                second_key="user",
                current_description="秘密を知っている。",
            )

        self.assertEqual(AIJobStatus.SUCCEEDED, related.status)
        self.assertEqual("星図をめぐる相談相手。", related.value["member-akari"])
        self.assertNotIn("## 世界観・舞台", adapted.value)
        self.assertEqual("記録係として図書館に馴染んでいる。", persona.value)
        self.assertEqual("古い招待状を受け取った。", reason.value)
        self.assertEqual("記録を一緒に整理する。", drafts.value[0]["description"])
        self.assertEqual("互いに星図の秘密を共有している。", enhanced.value)

    async def test_chat_input_use_cases_run_as_jobs_with_stub_llm(self) -> None:
        group = make_group_chat()
        settings = make_group_settings()
        user = group.user_persona
        assert user is not None
        messages = [group_message("user", "この星図は", user=user)]
        llm = FakeLLM(
            [
                "この星図は夜ごとに少し変わる。",
                "灯里なら、星図の線が震えていると告げる。",
                "1. もう少し詳しく見せてください\n2. 窓辺へ移動しましょう",
                "地の文: 天球儀が青く光った。",
                "補強結果: 閲覧室の机に古い星図が広げられている。",
            ]
        )
        service, patcher = _service(llm)

        with patcher:
            completed = await service.complete_input_text(
                profile_id="profile-test",
                vault_password=None,
                group=group,
                settings=settings,
                messages=messages,
                left_text="この星図は",
                input_mode="user",
                speaker=None,
                guest_name="",
                scope="group_assist:test",
                metadata={"group_id": group.id},
            )
            tailored = await service.tailor_input_text(
                profile_id="profile-test",
                vault_password=None,
                group=group,
                settings=settings,
                messages=messages,
                left_text="星図が変です",
                input_mode="character",
                speaker=group.members[0],
                guest_name="",
                scope="group_assist:test",
                metadata={"group_id": group.id},
            )
            choices = await service.generate_response_choices(
                profile_id="profile-test",
                vault_password=None,
                group=group,
                settings=settings,
                messages=messages,
                left_text="",
                input_mode="user",
                speaker=None,
                guest_name="",
                scope="group_assist:test",
                metadata={"group_id": group.id},
            )
            scene = await service.generate_scene_message(
                llm=llm,
                group=group,
                settings=settings,
                messages=messages,
            )
            situation = await service.enhance_situation(
                profile_id="profile-test",
                vault_password=None,
                group=group,
                participant_ids=[member.id for member in group.members],
                current_situation="閲覧室にいる。",
                scope="group_assist:test",
                metadata={"group_id": group.id},
            )

        self.assertEqual("この星図は夜ごとに少し変わる。", completed.value)
        self.assertEqual("灯里なら、星図の線が震えていると告げる。", tailored.value)
        self.assertEqual(["もう少し詳しく見せてください", "窓辺へ移動しましょう"], choices.value)
        self.assertEqual("天球儀が青く光った。", scene["text"])
        self.assertEqual("閲覧室の机に古い星図が広げられている。", situation.value)

    async def test_group_setup_generation_use_cases_run_as_jobs_with_stub_llm(self) -> None:
        group = make_group_chat()
        assert group.user_persona is not None
        llm = FakeLLM(
            [
                '{"characters":[{"id":"character-akari","handle":"Akari_Star"}],"user":"SoraNote"}',
                "世界観: 星明かりの蔵書室では、古い星図が夜ごとに線を変える。",
                "グループ名: 星屑街の夜会",
            ]
        )
        service, patcher = _service(llm)

        with patcher:
            handles = await service.generate_handles(
                profile_id="profile-test",
                vault_password=None,
                characters=[member.character for member in group.members],
                persona=group.user_persona,
            )
            world = await service.enhance_world(
                profile_id="profile-test",
                vault_password=None,
                current_world="古い星図がある図書館。",
                group_name=group.name,
                characters=[member.character for member in group.members],
                persona=group.user_persona,
            )
            name = await service.generate_group_name_from_world(
                profile_id="profile-test",
                vault_password=None,
                world=group.world,
                characters=[member.character for member in group.members],
                persona=group.user_persona,
            )

        self.assertEqual("Akari_Star", handles.value["character-akari"])
        self.assertEqual("SoraNote", handles.value["user"])
        self.assertEqual("星明かりの蔵書室では、古い星図が夜ごとに線を変える。", world.value)
        self.assertEqual("星屑街の夜会", name.value)
