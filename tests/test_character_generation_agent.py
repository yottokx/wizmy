from __future__ import annotations

import unittest
from unittest.mock import patch

from langchain_core.messages import ToolMessage

from src.core.character_generation.agent import run_generation
from src.core.character_generation.schemas import GenerationMode, GenerationPreferences, GenerationRequest


class _FakeGraph:
    def __init__(self, messages: list[ToolMessage]) -> None:
        self._messages = messages

    def stream(self, _payload, *, stream_mode: str, config: dict):
        yield {"tools": {"messages": self._messages}}


class CharacterGenerationAgentTest(unittest.TestCase):
    def test_tool_result_containing_error_word_is_recorded(self) -> None:
        message = ToolMessage(
            content="[職業・役割] 🎲 選択: 「エラーに厳しいエンジニア」 (1/1番目)",
            tool_call_id="tool-call-1",
            name="random_select",
        )

        with patch("src.core.character_generation.agent.create_agent", return_value=_FakeGraph([message])):
            result = run_generation(
                object(),  # type: ignore[arg-type]
                GenerationRequest(preferences=GenerationPreferences(), mode=GenerationMode.NEW),
            )

        self.assertEqual(1, len(result.tool_calls))
        self.assertIn("エラーに厳しいエンジニア", result.tool_calls[0].result)

    def test_explicit_tool_error_result_is_not_recorded(self) -> None:
        message = ToolMessage(
            content="エラー: 選択肢がありません",
            tool_call_id="tool-call-1",
            name="random_select",
        )

        with patch("src.core.character_generation.agent.create_agent", return_value=_FakeGraph([message])):
            result = run_generation(
                object(),  # type: ignore[arg-type]
                GenerationRequest(preferences=GenerationPreferences(), mode=GenerationMode.NEW),
            )

        self.assertEqual([], result.tool_calls)


if __name__ == "__main__":
    unittest.main()
