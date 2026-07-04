from __future__ import annotations

import unittest
from typing import Any

from src.core.conversation.schemas import ChatMessagePreview
from src.services.chat_turns import ChatTurnService
from tests.chat_test_helpers import make_chat_messages, make_chat_settings, make_chat_sheet


class FakeLLMResponse:
    def __init__(self, content: str) -> None:
        self.content = content
        self.usage_metadata = {
            "input_tokens": 13,
            "output_tokens": 8,
            "total_tokens": 21,
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


class ChatTurnServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_user_turn_builds_sanitized_character_message(self) -> None:
        sheet = make_chat_sheet()
        settings = make_chat_settings()
        messages = [ChatMessagePreview("user", "霧の奥に何か見えます。", "22:10")]
        llm = FakeLLM(["テストキャラ: ランタンを下げて。光が輪郭を拾うはず。"])

        result = await ChatTurnService().run_character_turn(
            sheet=sheet,
            settings=settings,
            messages=messages,
            llm=llm,
        )

        self.assertEqual(1, len(llm.calls))
        self.assertEqual(2, len(result.messages))
        self.assertEqual("character", result.message.speaker)
        self.assertEqual("ランタンを下げて。光が輪郭を拾うはず。", result.message.text)
        self.assertIsNotNone(result.message.debug)
        assert result.message.debug is not None
        self.assertEqual(13, result.message.debug.input_tokens)

    async def test_first_character_turn_uses_first_turn_prompt_and_empty_fallback(self) -> None:
        sheet = make_chat_sheet()
        settings = make_chat_settings()
        messages = [
            ChatMessagePreview("memo", "初回前のメモ", "22:00"),
            ChatMessagePreview("narration", "灯台の扉が軋んだ。", "22:01"),
        ]
        llm = FakeLLM([""])

        result = await ChatTurnService().run_character_turn(
            sheet=sheet,
            settings=settings,
            messages=messages,
            llm=llm,
            empty_reply="……ごめん、うまく言葉にできなかった。",
            first_turn_empty_reply="こんにちは。少し話そう。",
        )

        self.assertEqual("こんにちは。少し話そう。", result.message.text)
        self.assertEqual(1, len(llm.calls))
        call_text = "\n".join(str(message.content) for message in llm.calls[0])
        self.assertIn("まだ話していません", call_text)

    async def test_narration_turn_builds_sanitized_narration_message(self) -> None:
        sheet = make_chat_sheet()
        settings = make_chat_settings()
        llm = FakeLLM(["ナレーション: 霧が窓を白く塗りつぶす。\n- ランタンが低く鳴る。"])

        result = await ChatTurnService().run_narration_turn(
            sheet=sheet,
            settings=settings,
            messages=make_chat_messages(),
            llm=llm,
            instruction="霧の濃さを描写する。",
        )

        self.assertEqual("narration", result.message.speaker)
        self.assertEqual("霧が窓を白く塗りつぶす。\nランタンが低く鳴る。", result.message.text)
        self.assertIsNotNone(result.message.debug)

    async def test_generate_auto_title_sanitizes_llm_output(self) -> None:
        sheet = make_chat_sheet()
        settings = make_chat_settings()
        llm = FakeLLM(["タイトル: 霧灯台の手がかり。"])

        title = await ChatTurnService().generate_auto_title(
            sheet=sheet,
            settings=settings,
            messages=make_chat_messages(),
            llm=llm,
        )

        self.assertEqual("霧灯台の手がかり", title)
