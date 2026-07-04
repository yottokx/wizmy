from __future__ import annotations

import unittest
from typing import Any

from src.core.chat.schemas import ChatMode, UserPersona
from src.services.ai_jobs import AIJobService, AIJobStatus
from src.services.chat_assist import ChatAssistService
from tests.chat_test_helpers import make_chat_messages, make_chat_settings, make_chat_sheet


class FakeLLMResponse:
    def __init__(self, content: str) -> None:
        self.content = content
        self.usage_metadata = {
            "input_tokens": 9,
            "output_tokens": 6,
            "total_tokens": 15,
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


def _service() -> ChatAssistService:
    return ChatAssistService(AIJobService())


class ChatAssistServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_complete_input_text_merges_completion(self) -> None:
        sheet = make_chat_sheet()
        settings = make_chat_settings()
        llm = FakeLLM(["この灯台は夜になると音が変わる。"])

        result = await _service().complete_input_text(
            llm=llm,
            sheet=sheet,
            settings=settings,
            messages=make_chat_messages(),
            left_text="この灯台は",
            input_mode="user",
            scope="assist:test",
            metadata={"character_id": sheet.id, "session_id": ""},
            result_url=f"/characters/{sheet.id}/chat",
        )

        self.assertEqual(AIJobStatus.SUCCEEDED, result.status)
        self.assertEqual("この灯台は夜になると音が変わる。", result.value)
        self.assertEqual(1, len(llm.calls))

    async def test_tailor_input_text_cleans_short_text(self) -> None:
        sheet = make_chat_sheet()
        settings = make_chat_settings()
        llm = FakeLLM(["キャラクター: 霧が濃いほど灯りは遠くまで届く。"])

        result = await _service().tailor_input_text(
            llm=llm,
            sheet=sheet,
            settings=settings,
            messages=make_chat_messages(),
            left_text="霧が濃いと灯りが届く",
            input_mode="character",
            scope="assist:test",
            metadata={"character_id": sheet.id, "session_id": ""},
        )

        self.assertEqual(AIJobStatus.SUCCEEDED, result.status)
        self.assertEqual("霧が濃いほど灯りは遠くまで届く。", result.value)

    async def test_generate_response_choices_parses_lines(self) -> None:
        sheet = make_chat_sheet()
        settings = make_chat_settings()
        llm = FakeLLM(["1. もう少し近づいてみる\n2. ランタンを掲げる\n3. 静かに待つ"])

        result = await _service().generate_response_choices(
            llm=llm,
            sheet=sheet,
            settings=settings,
            messages=make_chat_messages(),
            left_text="",
            input_mode="user",
            scope="assist:test",
            metadata={"character_id": sheet.id, "session_id": ""},
        )

        self.assertEqual(AIJobStatus.SUCCEEDED, result.status)
        self.assertEqual(["もう少し近づいてみる", "ランタンを掲げる", "静かに待つ"], result.value)

    async def test_enhance_situation_strips_code_fence(self) -> None:
        sheet = make_chat_sheet()
        mode = ChatMode(id="mode-lighthouse", name="灯台巡り")
        persona = UserPersona(id="persona-mika", name="記録係", description="慎重だが好奇心が強い。")
        llm = FakeLLM(["```\n灯台の上階で、雨音が窓を強く叩いている。\n```"])

        result = await _service().enhance_situation(
            llm=llm,
            sheet=sheet,
            mode=mode,
            persona=persona,
            premise="消えた日誌の手がかりを探す。",
            current_situation="灯台の上階にいる。",
            scope="assist:test",
            metadata={"character_id": sheet.id, "session_id": ""},
        )

        self.assertEqual(AIJobStatus.SUCCEEDED, result.status)
        self.assertEqual("灯台の上階で、雨音が窓を強く叩いている。", result.value)

    async def test_failed_runner_reports_failure(self) -> None:
        sheet = make_chat_sheet()
        settings = make_chat_settings()
        llm = FakeLLM([])  # 応答なし → runner が例外

        result = await _service().complete_input_text(
            llm=llm,
            sheet=sheet,
            settings=settings,
            messages=make_chat_messages(),
            left_text="この灯台は",
            input_mode="user",
            scope="assist:test",
            metadata={"character_id": sheet.id, "session_id": ""},
        )

        self.assertEqual(AIJobStatus.FAILED, result.status)
