from __future__ import annotations

from src.core.conversation.input_assist import merge_completion


def test_merge_completion_adds_space_between_ascii_fragments() -> None:
    assert merge_completion("I will", "bring a lantern.") == "I will bring a lantern."


def test_merge_completion_keeps_punctuation_tight() -> None:
    assert merge_completion("I will wait", ", then listen.") == "I will wait, then listen."


def test_merge_completion_keeps_japanese_fragments_tight() -> None:
    assert merge_completion("霧が濃い", "ほど灯りは遠くまで届く。") == "霧が濃いほど灯りは遠くまで届く。"
