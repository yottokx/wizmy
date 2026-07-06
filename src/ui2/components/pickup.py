"""
キャラクター一覧 上段「ピックアップ」の選出ロジック(純関数)。

差し替え可能なポリシーを名前で登録する(HANDOFF j項 / INTEGRATION Phase 2)。
選択値は `app.storage.user["ui2_pickup_policy"]`(既定 "mixed")。
画像なしは候補から除外。候補 0 件ならストリップ自体を非表示(ページ側)。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

from ...core.character.schemas import CharacterSheet
from ...core.chat.sessions import ChatSessionRecord

PICKUP_POLICY_KEY = "ui2_pickup_policy"
DEFAULT_POLICY = "mixed"
DEFAULT_SLOTS = 7

_FAVORITE_SLOTS = 3
_RECENT_SLOTS = 3
_WILDCARD_SLOTS = 2
_STALE_DAYS = 30


@dataclass(frozen=True)
class PickupCandidate:
    """ピックアップ選出の入力 1 件分。"""

    sheet: CharacterSheet
    last_talked_at: datetime | None
    session_count: int
    has_image: bool
    is_favorite: bool


def build_pickup_candidates(
    sheets: list[CharacterSheet],
    chat_sessions: list[ChatSessionRecord],
) -> list[PickupCandidate]:
    """シート一覧+1:1 セッション履歴から候補リストを作る(集計は list_recent 系)。"""
    last_talked: dict[str, datetime] = {}
    counts: dict[str, int] = {}
    for session in chat_sessions:
        counts[session.character_id] = counts.get(session.character_id, 0) + 1
        current = last_talked.get(session.character_id)
        if current is None or session.updated_at > current:
            last_talked[session.character_id] = session.updated_at
    return [
        PickupCandidate(
            sheet=sheet,
            last_talked_at=last_talked.get(sheet.id),
            session_count=counts.get(sheet.id, 0),
            has_image=sheet.media.primary_image() is not None,
            is_favorite=sheet.is_favorite,
        )
        for sheet in sheets
    ]


def _talk_sort_key(candidate: PickupCandidate) -> tuple:
    """最終会話の新しい順(未会話は最後)。同着は元の並びを保つ(stable sort 前提)。"""
    if candidate.last_talked_at is None:
        return (1, datetime.min)
    return (0, -candidate.last_talked_at.timestamp())


def _by_recent(candidates: list[PickupCandidate]) -> list[PickupCandidate]:
    return sorted(candidates, key=_talk_sort_key)


def _image_pool(candidates: list[PickupCandidate]) -> list[PickupCandidate]:
    return [c for c in candidates if c.has_image]


def _daily_shuffle(pool: list[PickupCandidate], today: date) -> list[PickupCandidate]:
    """日付シードの決定的シャッフル(1日の中では安定、日ごとに顔ぶれが変わる)。"""
    shuffled = list(pool)
    random.Random(today.toordinal()).shuffle(shuffled)
    return shuffled


def _is_stale(candidate: PickupCandidate, today: date) -> bool:
    """「30日以上会話なし or 未会話」(きまぐれ枠の対象)。"""
    if candidate.last_talked_at is None:
        return True
    return candidate.last_talked_at < datetime.combine(today, datetime.min.time()) - timedelta(days=_STALE_DAYS)


def _front_load_last_talked(selected: list[PickupCandidate]) -> list[PickupCandidate]:
    """デフォルト展開(左端)を「全体で最後に話した子」にする。"""
    talked = [c for c in selected if c.last_talked_at is not None]
    if not talked:
        return selected
    front = max(talked, key=lambda c: c.last_talked_at)
    return [front] + [c for c in selected if c is not front]


def _policy_mixed(candidates: list[PickupCandidate], today: date, limit: int) -> list[PickupCandidate]:
    """既定「混成+きまぐれ枠」: お気に入り最大3+最近最大3+日付シード抽選1〜2。"""
    pool = _image_pool(candidates)
    selected: list[PickupCandidate] = []

    favorites = _by_recent([c for c in pool if c.is_favorite])
    selected.extend(favorites[:_FAVORITE_SLOTS])

    recent_pool = [c for c in _by_recent(pool) if c.last_talked_at is not None and c not in selected]
    selected.extend(recent_pool[: min(_RECENT_SLOTS, max(limit - len(selected), 0))])

    wildcard_pool = [c for c in _daily_shuffle(pool, today) if _is_stale(c, today) and c not in selected]
    selected.extend(wildcard_pool[: min(_WILDCARD_SLOTS, max(limit - len(selected), 0))])

    # 不足分の補充: 最近 → お気に入り(上で尽きているはず)→ 画像持ち全体
    if len(selected) < limit:
        for candidate in _by_recent(pool):
            if candidate not in selected:
                selected.append(candidate)
            if len(selected) >= limit:
                break

    return _front_load_last_talked(selected[:limit])


def _policy_favorites(candidates: list[PickupCandidate], today: date, limit: int) -> list[PickupCandidate]:
    """お気に入りのみ(最終会話の新しい順)。"""
    favorites = _by_recent([c for c in _image_pool(candidates) if c.is_favorite])
    return favorites[:limit]


def _policy_recent(candidates: list[PickupCandidate], today: date, limit: int) -> list[PickupCandidate]:
    """最近話した順(未会話は選ばない)。"""
    recent = [c for c in _by_recent(_image_pool(candidates)) if c.last_talked_at is not None]
    return recent[:limit]


def _policy_daily(candidates: list[PickupCandidate], today: date, limit: int) -> list[PickupCandidate]:
    """日替わり: 画像持ち全体から日付シードの決定的抽選。"""
    return _daily_shuffle(_image_pool(candidates), today)[:limit]


PickupPolicy = Callable[[list[PickupCandidate], date, int], list[PickupCandidate]]

POLICIES: dict[str, PickupPolicy] = {
    "mixed": _policy_mixed,
    "favorites": _policy_favorites,
    "recent": _policy_recent,
    "daily": _policy_daily,
}


def select_pickup(
    candidates: list[PickupCandidate],
    policy: str = DEFAULT_POLICY,
    today: date | None = None,
    limit: int = DEFAULT_SLOTS,
) -> list[PickupCandidate]:
    """ポリシー名でピックアップを選出する(未知のポリシーは既定 mixed)。"""
    chosen = POLICIES.get(policy, POLICIES[DEFAULT_POLICY])
    return chosen(candidates, today or date.today(), max(limit, 0))
