from __future__ import annotations

import random
import unittest
from typing import Any

from src.core.conversation.history import group_message
from src.services.group_chat_turns import GroupChatTurnService
from tests.group_chat_test_helpers import make_group_chat, make_group_settings


class FakeLLMResponse:
    def __init__(self, content: str) -> None:
        self.content = content
        self.usage_metadata = {
            "input_tokens": 11,
            "output_tokens": 7,
            "total_tokens": 18,
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


class GroupChatTurnServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_user_turn_selects_speaker_with_llm_and_builds_sanitized_character_message(self) -> None:
        group = make_group_chat()
        settings = make_group_settings()
        user = group.user_persona
        assert user is not None
        messages = [
            group_message("user", "この天球儀、音がずれています。", user=user),
        ]
        llm = FakeLLM(
            [
                '{"weights":[{"handle":"Minato","weight":100},{"handle":"Akari","weight":0}]}',
                "湊: 歯車の音が変わったね。",
            ]
        )

        result = await GroupChatTurnService(rng=random.Random(0)).run_character_turn(
            group=group,
            settings=settings,
            messages=messages,
            llm=llm,
            active_members=group.members,
        )

        self.assertEqual("member-minato", result.speaker.id if result.speaker else "")
        self.assertEqual(2, len(llm.calls))
        self.assertEqual(2, len(result.messages))
        self.assertEqual("character", result.message["role"])
        self.assertEqual("member-minato", result.message["speaker_id"])
        self.assertEqual("歯車の音が変わったね。", result.message["text"])
        self.assertIsNotNone(result.message.get("debug"))
        self.assertIsNotNone(result.message.get("speaker_debug"))

    async def test_mentioned_member_skips_speaker_llm(self) -> None:
        group = make_group_chat()
        settings = make_group_settings()
        user = group.user_persona
        assert user is not None
        messages = [
            group_message("user", "@Minato この棚を見てください。", user=user),
        ]
        llm = FakeLLM(["湊: もちろん、すぐ確認するよ。"])

        result = await GroupChatTurnService().run_character_turn(
            group=group,
            settings=settings,
            messages=messages,
            llm=llm,
            active_members=group.members,
        )

        self.assertEqual("member-minato", result.speaker.id if result.speaker else "")
        self.assertEqual(1, len(llm.calls))
        self.assertIsNone(result.speaker_debug)
        self.assertNotIn("湊:", result.message["text"])

    async def test_invalid_speaker_weights_fall_back_to_equal_selection(self) -> None:
        group = make_group_chat()
        settings = make_group_settings()
        user = group.user_persona
        assert user is not None
        messages = [
            group_message("user", "次は誰が話すべきでしょう。", user=user),
        ]
        llm = FakeLLM(
            [
                "候補はまだ決められません",
                "灯里: 星図はまだ少し震えています。",
            ]
        )

        result = await GroupChatTurnService(rng=random.Random(1)).run_character_turn(
            group=group,
            settings=settings,
            messages=messages,
            llm=llm,
            active_members=group.members,
        )

        self.assertEqual("member-akari", result.speaker.id if result.speaker else "")
        speaker_debug = result.message.get("speaker_debug")
        self.assertIsInstance(speaker_debug, dict)
        assert isinstance(speaker_debug, dict)
        self.assertIn("候補はまだ決められません", speaker_debug["raw_output"])
        self.assertEqual("星図はまだ少し震えています。", result.message["text"])

    async def test_guest_turn_builds_sanitized_guest_message(self) -> None:
        group = make_group_chat()
        settings = make_group_settings()
        llm = FakeLLM(["巡回司書: 閉館前に片付けてください。"])

        result = await GroupChatTurnService().run_guest_turn(
            group=group,
            settings=settings,
            messages=[],
            llm=llm,
            guest_name="巡回司書",
        )

        self.assertEqual("guest", result.message["role"])
        self.assertEqual("巡回司書【ゲスト】", result.message["speaker_name"])
        self.assertEqual("閉館前に片付けてください。", result.message["text"])
        self.assertIsNotNone(result.message.get("debug"))

    async def test_generate_auto_title_sanitizes_llm_output(self) -> None:
        group = make_group_chat()
        llm = FakeLLM(["タイトル: 星図の異変。"])

        title = await GroupChatTurnService().generate_auto_title(
            group=group,
            messages=[],
            llm=llm,
        )

        self.assertEqual("星図の異変", title)
