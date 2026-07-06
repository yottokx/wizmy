"""ui2 チャット純ロジック(src/ui2/chat_logic.py)の単体テスト。"""

from __future__ import annotations

from datetime import datetime

from src.core.character.schemas import CharacterSheet
from src.core.chat.sessions import ChatSessionRecord
from src.ui2.chat_logic import (
    NEVER_TALKED_LABEL,
    build_partner_entries,
    character_persona_description,
    filter_partner_entries,
    most_recent_partner_id,
    user_persona_from_character_sheet,
)


def _sheet(character_id: str, name: str = "", **kwargs) -> CharacterSheet:
    return CharacterSheet(id=character_id, name=name or character_id, **kwargs)


def _session(session_id: str, character_id: str, updated_at: datetime) -> ChatSessionRecord:
    return ChatSessionRecord(
        id=session_id,
        character_id=character_id,
        title="t",
        title_is_auto=False,
        settings={},
        messages=[],
        created_at=updated_at,
        updated_at=updated_at,
    )


def test_partner_entries_talked_first_by_recency_then_untalked_in_order() -> None:
    sheets = [_sheet("a"), _sheet("b"), _sheet("c"), _sheet("d")]
    sessions = [
        _session("s1", "b", datetime(2026, 7, 5, 10, 0)),
        _session("s2", "c", datetime(2026, 7, 7, 9, 0)),
        _session("s3", "b", datetime(2026, 7, 6, 9, 0)),
    ]
    entries = build_partner_entries(sheets, sessions)
    assert [entry.sheet.id for entry in entries] == ["c", "b", "a", "d"]
    assert entries[0].session_count == 1
    assert entries[1].session_count == 2
    assert entries[1].last_talked_at == datetime(2026, 7, 6, 9, 0)
    assert entries[2].last_label == NEVER_TALKED_LABEL
    assert entries[2].last_talked_at is None


def test_partner_entries_empty_sessions_keeps_sheet_order() -> None:
    sheets = [_sheet("a"), _sheet("b")]
    entries = build_partner_entries(sheets, [])
    assert [entry.sheet.id for entry in entries] == ["a", "b"]
    assert all(entry.last_label == NEVER_TALKED_LABEL for entry in entries)


def test_filter_partner_entries_by_search_and_favorites() -> None:
    sheets = [
        _sheet("a", "アステル", occupation="観測者", is_favorite=True),
        _sheet("b", "ミラベル", world="夜霧の港町"),
        _sheet("c", "トワ"),
    ]
    entries = build_partner_entries(sheets, [])

    assert [e.sheet.id for e in filter_partner_entries(entries)] == ["a", "b", "c"]
    assert [e.sheet.id for e in filter_partner_entries(entries, search="観測")] == ["a"]
    assert [e.sheet.id for e in filter_partner_entries(entries, search="港町")] == ["b"]  # 世界観も対象
    assert [e.sheet.id for e in filter_partner_entries(entries, favorites_only=True)] == ["a"]
    assert filter_partner_entries(entries, search="トワ", favorites_only=True) == []
    assert [e.sheet.id for e in filter_partner_entries(entries, search="  ")] == ["a", "b", "c"]


def test_most_recent_partner_id() -> None:
    assert most_recent_partner_id([]) == ""
    sessions = [
        _session("s1", "a", datetime(2026, 7, 5)),
        _session("s2", "b", datetime(2026, 7, 7)),
        _session("s3", "c", datetime(2026, 7, 6)),
    ]
    assert most_recent_partner_id(sessions) == "b"


def test_character_persona_description_prefers_raw_markdown() -> None:
    sheet = _sheet("a", "トワ", raw_markdown="# トワ\n\n観測者。")
    assert character_persona_description(sheet) == "# トワ\n\n観測者。"


def test_character_persona_description_falls_back_to_fields() -> None:
    sheet = _sheet("a", "トワ", occupation="観測者", personality="物静か")
    description = character_persona_description(sheet)
    assert "名前: トワ" in description
    assert "職業・役割: 観測者" in description
    assert "性格: 物静か" in description
    assert "年齢" not in description  # 空の項目は含めない


def test_user_persona_from_character_sheet() -> None:
    sheet = _sheet("a", "トワ", occupation="観測者")
    persona = user_persona_from_character_sheet(sheet)
    assert persona.id == "a"
    assert persona.name == "トワ"
    assert "職業・役割: 観測者" in persona.description
    assert persona.media is sheet.media
