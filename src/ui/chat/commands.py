"""スラッシュコマンドと入力モード表示を扱う純粋関数。"""

from __future__ import annotations

import re

from .models import CHAT_COMMANDS, ChatCommandDefinition


def parse_command_input(value: str, *, allow_empty_query: bool = True) -> tuple[str, str] | None:
    match = re.match(r"(?s)^(.*)/([A-Za-z]*)\s*$", value)
    if match is None:
        return None
    left_text = match.group(1)
    query = match.group(2).lower()
    if not query and not allow_empty_query:
        return None
    if query and not command_suggestions(query):
        return None
    return left_text, query


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
