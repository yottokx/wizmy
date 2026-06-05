"""スラッシュコマンドと短文生成結果を扱う純粋関数。"""

from __future__ import annotations

import re

from .models import CHAT_COMMANDS, ChatCommandDefinition


def parse_command_input(value: str) -> tuple[str, str] | None:
    match = re.match(r"(?s)^(.*)/([A-Za-z]*)\s*$", value)
    if match is None:
        return None
    return match.group(1), match.group(2).lower()


def command_suggestions(query: str) -> list[ChatCommandDefinition]:
    query = query.lower()
    if not query:
        return list(CHAT_COMMANDS)
    return [command for command in CHAT_COMMANDS if command.name.startswith(query)]


def resolve_chat_command(query: str) -> str | None:
    query = query.lower()
    if not query:
        return None
    for command in CHAT_COMMANDS:
        if command.name == query:
            return command.name
    suggestions = command_suggestions(query)
    return suggestions[0].name if len(suggestions) == 1 else None


def merge_completion(left_text: str, raw_completion: str) -> str:
    completion = clean_short_llm_text(raw_completion)
    left = left_text.rstrip()
    if not completion:
        return left
    if completion.startswith(left):
        return completion
    if left and completion.startswith(left[-min(len(left), 20):]):
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


def clean_short_llm_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:\w+)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = re.sub(r"^(?:候補|返答|回答|ユーザー|キャラクター|キャラ|地の文|ナラティブ|コメント)\s*[:：]\s*", "", text.strip())
    return text.strip()


def input_mode_label(mode: str) -> str:
    if mode == "narration":
        return "ナラティブ"
    if mode == "memo":
        return "コメント"
    if mode == "character":
        return "キャラクター"
    return "ユーザー"


def input_mode_icon(mode: str) -> str:
    if mode == "narration":
        return "notes"
    if mode == "memo":
        return "comment"
    if mode == "character":
        return "face"
    return "person"
