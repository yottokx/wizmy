"""ピックアップ選出ポリシー(ui2/components/pickup.py)の単体テスト。"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from src.core.character.schemas import CharacterImageAsset, CharacterMedia, CharacterSheet
from src.ui2.components.pickup import (
    PickupCandidate,
    build_pickup_candidates,
    select_pickup,
)

TODAY = date(2026, 7, 7)


def _sheet(character_id: str, *, favorite: bool = False, image: bool = True) -> CharacterSheet:
    media = CharacterMedia()
    if image:
        media.images = [
            CharacterImageAsset(id=f"{character_id}-img", path=f"characters/{character_id}/images/a.png")
        ]
    return CharacterSheet(id=character_id, name=f"キャラ{character_id}", is_favorite=favorite, media=media)


def _candidate(
    character_id: str,
    *,
    favorite: bool = False,
    image: bool = True,
    days_ago: int | None = None,
    sessions: int = 0,
) -> PickupCandidate:
    last = None
    if days_ago is not None:
        last = datetime.combine(TODAY, datetime.min.time()) - timedelta(days=days_ago) + timedelta(hours=12)
    return PickupCandidate(
        sheet=_sheet(character_id, favorite=favorite, image=image),
        last_talked_at=last,
        session_count=sessions if days_ago is None else max(sessions, 1),
        has_image=image,
        is_favorite=favorite,
    )


def _ids(selected: list[PickupCandidate]) -> list[str]:
    return [c.sheet.id for c in selected]


class _Session:
    def __init__(self, character_id: str, updated_at: datetime) -> None:
        self.character_id = character_id
        self.updated_at = updated_at


def test_build_candidates_aggregates_sessions() -> None:
    sheets = [_sheet("a"), _sheet("b", image=False)]
    sessions = [
        _Session("a", datetime(2026, 7, 1, 10, 0)),
        _Session("a", datetime(2026, 7, 5, 9, 0)),
    ]
    candidates = build_pickup_candidates(sheets, sessions)  # type: ignore[arg-type]
    assert candidates[0].last_talked_at == datetime(2026, 7, 5, 9, 0)
    assert candidates[0].session_count == 2
    assert candidates[0].has_image is True
    assert candidates[1].last_talked_at is None
    assert candidates[1].has_image is False


def test_mixed_excludes_no_image() -> None:
    candidates = [
        _candidate("img", days_ago=1),
        _candidate("noimg", image=False, days_ago=0, favorite=True),
    ]
    assert _ids(select_pickup(candidates, "mixed", TODAY)) == ["img"]


def test_mixed_combines_favorites_recent_and_wildcard() -> None:
    candidates = [
        _candidate("fav1", favorite=True, days_ago=2),
        _candidate("fav2", favorite=True, days_ago=5),
        _candidate("fav3", favorite=True, days_ago=9),
        _candidate("fav4", favorite=True, days_ago=20),
        _candidate("rec1", days_ago=1),
        _candidate("rec2", days_ago=3),
        _candidate("rec3", days_ago=4),
        _candidate("stale1", days_ago=60),
        _candidate("stale2", days_ago=90),
        _candidate("never1"),
    ]
    selected = select_pickup(candidates, "mixed", TODAY)
    ids = _ids(selected)
    assert len(ids) == 7
    # お気に入り枠: 最終会話の新しい順で最大3(fav4 は落ちる)
    assert {"fav1", "fav2", "fav3"} <= set(ids)
    assert "fav4" not in ids
    # 最近枠: 会話のある子を新しい順で最大3
    assert {"rec1", "rec2", "rec3"} <= set(ids)
    # きまぐれ枠(残り1): 30日以上会話なし/未会話 から日付シード抽選
    assert len({"stale1", "stale2", "never1"} & set(ids)) == 1
    # デフォルト展開(左端)は全体で最後に話した子
    assert ids[0] == "rec1"


def test_mixed_wildcard_is_stable_within_a_day_and_changes_by_date() -> None:
    candidates = [_candidate(f"stale{i}", days_ago=60 + i) for i in range(10)]
    first = _ids(select_pickup(candidates, "mixed", TODAY))
    assert first == _ids(select_pickup(candidates, "mixed", TODAY))
    other_days = [
        _ids(select_pickup(candidates, "mixed", TODAY + timedelta(days=offset))) for offset in range(1, 8)
    ]
    assert any(ids != first for ids in other_days)


def test_mixed_fills_shortage_from_recent_pool() -> None:
    candidates = [
        _candidate("rec1", days_ago=1),
        _candidate("rec2", days_ago=2),
        _candidate("rec3", days_ago=3),
        _candidate("rec4", days_ago=4),
        _candidate("rec5", days_ago=5),
        _candidate("rec6", days_ago=6),
    ]
    # お気に入り0・きまぐれ対象0 → 最近枠3+補充で全員選ばれる
    assert _ids(select_pickup(candidates, "mixed", TODAY)) == [
        "rec1",
        "rec2",
        "rec3",
        "rec4",
        "rec5",
        "rec6",
    ]


def test_mixed_returns_empty_for_no_image_candidates() -> None:
    candidates = [_candidate("noimg", image=False, favorite=True, days_ago=0)]
    assert select_pickup(candidates, "mixed", TODAY) == []


def test_favorites_policy_orders_by_last_talked() -> None:
    candidates = [
        _candidate("fav-old", favorite=True, days_ago=10),
        _candidate("fav-new", favorite=True, days_ago=1),
        _candidate("fav-never", favorite=True),
        _candidate("plain", days_ago=0),
    ]
    assert _ids(select_pickup(candidates, "favorites", TODAY)) == ["fav-new", "fav-old", "fav-never"]


def test_recent_policy_excludes_never_talked() -> None:
    candidates = [
        _candidate("rec-new", days_ago=1),
        _candidate("rec-old", days_ago=15),
        _candidate("never"),
    ]
    assert _ids(select_pickup(candidates, "recent", TODAY)) == ["rec-new", "rec-old"]


def test_daily_policy_is_deterministic_per_day() -> None:
    candidates = [_candidate(f"c{i}", days_ago=i) for i in range(12)]
    first = _ids(select_pickup(candidates, "daily", TODAY))
    assert len(first) == 7
    assert first == _ids(select_pickup(candidates, "daily", TODAY))


def test_unknown_policy_falls_back_to_mixed() -> None:
    candidates = [_candidate("only", days_ago=1)]
    assert _ids(select_pickup(candidates, "unknown", TODAY)) == ["only"]
