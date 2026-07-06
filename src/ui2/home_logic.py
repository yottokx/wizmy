"""
ホーム(/v2)の純ロジック。

挨拶(時間帯定型+self_intro 流用。LLM呼び出し無し)・相方候補の選定・
最近セッションの統合(1:1+グループ)を、描画から切り離した純関数として持つ。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..core.character.schemas import CharacterSheet
from ..core.chat.sessions import ChatSessionRecord
from ..core.conversation.history import (
    latest_group_message_preview,
    latest_message_preview,
    session_time_label,
)
from ..core.group_chat.schemas import GroupChatRecord
from ..core.group_chat.sessions import GroupChatSessionRecord

MAX_COMPANIONS = 5
MAX_BOOKMARKS = 3

_WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]


def date_label(now: datetime) -> str:
    """モック home.html と同形式の日付表示(例: 2026 . 7 . 7  火曜日)。"""
    return f"{now.year} . {now.month} . {now.day}  {_WEEKDAYS[now.weekday()]}曜日"


def time_greeting(hour: int) -> str:
    """時間帯定型の挨拶(モックと同じ 3 区分: 〜10時 / 〜17時 / それ以降)。"""
    if 5 <= hour < 11:
        return "おはようございます。"
    if 11 <= hour < 18:
        return "おかえりなさい。"
    return "こんばんは。"


def greeting_text(hour: int, self_intro: str) -> str:
    """挨拶 v1: 時間帯定型+self_intro 流用(HANDOFF k項)。"""
    intro = " ".join(self_intro.split())
    # 吹き出し側で「」に包むため、self_intro 自身の外側カギ括弧は剥がす
    while intro.startswith("「") and intro.endswith("」"):
        intro = intro[1:-1].strip()
    intro = intro.replace("「", "『").replace("」", "』")
    greet = time_greeting(hour)
    if not intro:
        return f"{greet}今日は、なにをして過ごしましょうか。"
    return f"{greet}{intro}"


def companion_candidates(
    sheets: list[CharacterSheet],
    limit: int = MAX_COMPANIONS,
) -> list[CharacterSheet]:
    """相方候補: 画像持ちのみ。お気に入り優先、以降は元の並び順を保つ。"""
    with_image = [sheet for sheet in sheets if sheet.media.primary_image() is not None]
    favorites = [sheet for sheet in with_image if sheet.is_favorite]
    others = [sheet for sheet in with_image if not sheet.is_favorite]
    return (favorites + others)[: max(limit, 0)]


def select_companion(
    candidates: list[CharacterSheet],
    stored_id: str,
    recent_character_ids: list[str],
) -> CharacterSheet | None:
    """相方の決定: 保存値 → お気に入り(最近話した順)→ 最近話した子 → 先頭。"""
    if not candidates:
        return None
    by_id = {sheet.id: sheet for sheet in candidates}
    if stored_id in by_id:
        return by_id[stored_id]
    favorite_ids = {sheet.id for sheet in candidates if sheet.is_favorite}
    if favorite_ids:
        for character_id in recent_character_ids:
            if character_id in favorite_ids:
                return by_id[character_id]
        return next(sheet for sheet in candidates if sheet.is_favorite)
    for character_id in recent_character_ids:
        if character_id in by_id:
            return by_id[character_id]
    return candidates[0]


@dataclass(frozen=True)
class RecentSessionItem:
    """ホーム「最近のセッション」1件分の表示データ。"""

    kind: str  # "chat" | "group"
    session_id: str
    target_id: str  # character_id または group_id
    title: str
    preview: str
    time_label: str
    updated_at: datetime
    route: str  # 1:1 は /v2 チャット、グループは /v2 箱庭シェル


def merge_recent_sessions(
    chat_sessions: list[ChatSessionRecord],
    group_sessions: list[GroupChatSessionRecord],
    groups_by_id: dict[str, GroupChatRecord],
    limit: int = MAX_BOOKMARKS,
) -> list[RecentSessionItem]:
    """1:1 とグループの最近セッションを updated_at 降順に統合する。"""
    items: list[RecentSessionItem] = []
    for session in chat_sessions:
        items.append(
            RecentSessionItem(
                kind="chat",
                session_id=session.id,
                target_id=session.character_id,
                title=session.title,
                preview=latest_message_preview(session.messages),
                time_label=session_time_label(session.updated_at),
                updated_at=session.updated_at,
                route=f"/v2/characters/{session.character_id}/chat",
            )
        )
    for session in group_sessions:
        group = groups_by_id.get(session.group_id)
        preview = latest_group_message_preview(session.messages)
        if group is not None and group.name:
            preview = f"グループ: {group.name} — {preview}"
        items.append(
            RecentSessionItem(
                kind="group",
                session_id=session.id,
                target_id=session.group_id,
                title=session.title,
                preview=preview,
                time_label=session_time_label(session.updated_at),
                updated_at=session.updated_at,
                route=f"/v2/groups/{session.group_id}",
            )
        )
    items.sort(key=lambda item: item.updated_at, reverse=True)
    return items[: max(limit, 0)]


def recent_character_ids(chat_sessions: list[ChatSessionRecord]) -> list[str]:
    """最近の 1:1 セッションから重複を除いた character_id 列(新しい順)。"""
    seen: dict[str, Any] = {}
    for session in chat_sessions:
        seen.setdefault(session.character_id, None)
    return list(seen)
