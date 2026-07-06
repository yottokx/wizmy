"""スラッシュコマンドと入力モード表示を扱う純粋関数(ui2 複製)。

旧UI `src/ui/chat/commands.py` とコマンド定義(`src/ui/chat/models.py` の
`CHAT_COMMANDS`)の複製。依存規則(`ui2` は `src/ui/` の描画層を import しない)を
守るための意図的な重複であり、旧UI削除(Phase 7)時に複製元側を消して一本化する。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ChatCommandDefinition:
    name: str
    description: str


CHAT_COMMANDS: tuple[ChatCommandDefinition, ...] = (
    ChatCommandDefinition("hold", "左側の文だけ投稿し、キャラには返さない"),
    ChatCommandDefinition("fill", "左側の文の続きを補完"),
    ChatCommandDefinition("tailor", "左側の文を現在のロール向けに書き換え"),
    ChatCommandDefinition("choices", "返答候補を3つ生成"),
    ChatCommandDefinition("guide", "次のキャラ発言・地の文の方向性を指定"),
    ChatCommandDefinition("skip", "発言をスキップしてキャラに返す"),
    ChatCommandDefinition("narrate", "次の投稿を地の文にする"),
    ChatCommandDefinition("memo", "次の投稿をコメントにする"),
    ChatCommandDefinition("imitate", "次の投稿をキャラ発言にする"),
    ChatCommandDefinition("user", "ユーザー入力に戻す"),
    ChatCommandDefinition("describe", "左側の文があれば投稿して地の文を自動生成"),
)


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
