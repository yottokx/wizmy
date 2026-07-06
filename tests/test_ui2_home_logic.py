"""ホーム(/v2)純ロジックの単体テスト。"""

from __future__ import annotations

import unittest
from datetime import datetime

from src.core.character.schemas import CharacterImageAsset, CharacterMedia, CharacterSheet
from src.core.chat.sessions import ChatSessionRecord
from src.core.group_chat.schemas import GroupChatRecord
from src.core.group_chat.sessions import GroupChatSessionRecord
from src.ui2.home_logic import (
    companion_candidates,
    date_label,
    greeting_text,
    merge_recent_sessions,
    recent_character_ids,
    select_companion,
    time_greeting,
)


def _sheet(character_id: str, *, favorite: bool = False, with_image: bool = True) -> CharacterSheet:
    media = CharacterMedia()
    if with_image:
        media = CharacterMedia(
            images=[CharacterImageAsset(id="img-1", path=f"characters/{character_id}/images/a.png")]
        )
    return CharacterSheet(
        id=character_id,
        name=f"名前{character_id}",
        media=media,
        is_favorite=favorite,
        self_intro="トワと申します。星を数えるのが日課です。",
    )


def _chat_session(session_id: str, character_id: str, updated_at: datetime) -> ChatSessionRecord:
    return ChatSessionRecord(
        id=session_id,
        character_id=character_id,
        title=f"タイトル{session_id}",
        messages=[{"speaker": "character", "text": "こんばんは。", "time_label": "00:00"}],
        created_at=updated_at,
        updated_at=updated_at,
    )


class GreetingTest(unittest.TestCase):
    def test_time_greeting_buckets(self) -> None:
        self.assertEqual("おはようございます。", time_greeting(5))
        self.assertEqual("おはようございます。", time_greeting(10))
        self.assertEqual("おかえりなさい。", time_greeting(11))
        self.assertEqual("おかえりなさい。", time_greeting(17))
        self.assertEqual("こんばんは。", time_greeting(18))
        self.assertEqual("こんばんは。", time_greeting(23))
        self.assertEqual("こんばんは。", time_greeting(3))

    def test_greeting_text_uses_self_intro(self) -> None:
        text = greeting_text(9, "トワです。  よろしく。")
        self.assertEqual("おはようございます。トワです。 よろしく。", text)

    def test_greeting_text_unwraps_quoted_self_intro(self) -> None:
        text = greeting_text(9, "「私がトワ。「星」を数える者よ。」")
        self.assertEqual("おはようございます。私がトワ。『星』を数える者よ。", text)

    def test_greeting_text_without_self_intro_has_fallback(self) -> None:
        text = greeting_text(20, "  ")
        self.assertTrue(text.startswith("こんばんは。"))
        self.assertGreater(len(text), len("こんばんは。"))

    def test_date_label_format(self) -> None:
        self.assertEqual("2026 . 7 . 7  火曜日", date_label(datetime(2026, 7, 7, 12, 0)))


class CompanionTest(unittest.TestCase):
    def test_candidates_exclude_no_image_and_prefer_favorites(self) -> None:
        sheets = [
            _sheet("a"),
            _sheet("b", favorite=True),
            _sheet("c", with_image=False),
            _sheet("d"),
        ]
        candidates = companion_candidates(sheets)
        self.assertEqual(["b", "a", "d"], [sheet.id for sheet in candidates])

    def test_candidates_respect_limit(self) -> None:
        sheets = [_sheet(f"c{i}") for i in range(8)]
        self.assertEqual(5, len(companion_candidates(sheets)))

    def test_select_prefers_stored_id(self) -> None:
        candidates = companion_candidates([_sheet("a"), _sheet("b", favorite=True)])
        selected = select_companion(candidates, "a", ["b"])
        assert selected is not None
        self.assertEqual("a", selected.id)

    def test_select_falls_back_to_recently_talked_favorite(self) -> None:
        candidates = companion_candidates(
            [_sheet("a", favorite=True), _sheet("b", favorite=True), _sheet("c")]
        )
        selected = select_companion(candidates, "", ["c", "b", "a"])
        assert selected is not None
        self.assertEqual("b", selected.id)

    def test_select_without_favorites_uses_recent(self) -> None:
        candidates = companion_candidates([_sheet("a"), _sheet("b")])
        selected = select_companion(candidates, "", ["b"])
        assert selected is not None
        self.assertEqual("b", selected.id)

    def test_select_returns_none_without_candidates(self) -> None:
        self.assertIsNone(select_companion([], "a", ["a"]))


class RecentSessionsTest(unittest.TestCase):
    def test_merge_sorts_by_updated_at_and_limits(self) -> None:
        chats = [
            _chat_session("s1", "a", datetime(2026, 7, 5, 10, 0)),
            _chat_session("s2", "b", datetime(2026, 7, 7, 9, 0)),
        ]
        group = GroupChatRecord(
            id="g1",
            name="多元の集い",
            created_at=datetime(2026, 7, 1),
            updated_at=datetime(2026, 7, 6),
        )
        group_sessions = [
            GroupChatSessionRecord(
                id="gs1",
                group_id="g1",
                title="集いの夜",
                messages=[
                    {
                        "role": "character",
                        "text": "ようこそ。",
                        "speaker_name": "トワ",
                        "time_label": "00:00",
                    }
                ],
                created_at=datetime(2026, 7, 6),
                updated_at=datetime(2026, 7, 6, 12, 0),
            )
        ]
        items = merge_recent_sessions(chats, group_sessions, {"g1": group}, limit=2)
        self.assertEqual(["s2", "gs1"], [item.session_id for item in items])
        self.assertEqual("/v2/characters/b/chat", items[0].route)
        self.assertEqual("/groups/g1", items[1].route)
        self.assertIn("グループ: 多元の集い", items[1].preview)
        self.assertIn("トワ", items[1].preview)

    def test_recent_character_ids_dedupes_in_order(self) -> None:
        chats = [
            _chat_session("s1", "b", datetime(2026, 7, 7)),
            _chat_session("s2", "a", datetime(2026, 7, 6)),
            _chat_session("s3", "b", datetime(2026, 7, 5)),
        ]
        self.assertEqual(["b", "a"], recent_character_ids(chats))


if __name__ == "__main__":
    unittest.main()
