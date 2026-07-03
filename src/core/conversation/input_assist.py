"""チャット入力支援の純粋関数。"""

from __future__ import annotations

import re

from .sanitize import clean_short_llm_text


def merge_completion(left_text: str, raw_completion: str) -> str:
    completion = clean_short_llm_text(raw_completion)
    left = left_text.rstrip()
    if not completion:
        return left
    if completion.startswith(left):
        return completion
    if left and completion.startswith(left[-min(len(left), 20) :]):
        overlap = min(len(left), 20)
        return left + completion[overlap:]
    separator = "" if not left or left[-1].isspace() or completion[:1] in "、。！？,.!?" else ""
    return f"{left}{separator}{completion}"


def parse_response_choices(raw_output: str) -> list[str]:
    choices: list[str] = []
    for raw_line in raw_output.splitlines():
        line = clean_short_llm_text(raw_line)
        line = re.sub(r"^\s*(?:\d+|[①②③])[\.\)、:：\s]+", "", line).strip()
        line = line.strip("・-–—*＊ ")
        line = line.strip("「」『』\"'")
        if line and line not in choices:
            choices.append(line)
        if len(choices) >= 3:
            break
    return choices
