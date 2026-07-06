from __future__ import annotations

from dataclasses import dataclass

from src.core.conversation.llm_io import format_llm_input


@dataclass
class _Message:
    type: str
    content: str


def test_format_llm_input_formats_messages_only() -> None:
    assert format_llm_input([_Message("system", "方針"), _Message("human", "こんにちは")]) == (
        "--- system ---\n方針\n\n--- human ---\nこんにちは"
    )
