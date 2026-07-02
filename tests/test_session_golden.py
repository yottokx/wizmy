"""セッション保存 JSON 形式のゴールデンテスト。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from src.core.chat.sessions import ChatSessionRecord
from src.core.conversation import history as history_module
from src.core.conversation.history import group_message, group_system_event_message
from src.core.conversation.schemas import ChatDebugInfo, ChatMessagePreview
from src.core.group_chat.sessions import GroupChatSessionRecord
from src.storage.chat_repository import ChatRepository
from src.storage.group_chat_repository import GroupChatRepository
from src.ui.chat.controller import chat_message_to_dict, chat_settings_to_dict
from src.ui.chat.models import ChatSessionSettings

from tests.group_chat_test_helpers import make_group_chat, make_group_settings


GOLDEN_DIR = Path(__file__).parent / "golden"
FIXED_CREATED_AT = datetime(2026, 1, 2, 3, 4, 5)
FIXED_UPDATED_AT = datetime(2026, 1, 2, 3, 5, 6)


def _load_golden(name: str) -> dict[str, Any]:
    return json.loads((GOLDEN_DIR / name).read_text(encoding="utf-8"))


async def _stored_session_json(db_path: Path, table_name: str, session_id: str) -> dict[str, Any]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"SELECT settings, messages FROM {table_name} WHERE id = ?",
            (session_id,),
        ) as cursor:
            row = await cursor.fetchone()
    assert row is not None
    return {
        "settings": json.loads(row["settings"]),
        "messages": json.loads(row["messages"]),
    }


async def _insert_chat_session_row(
    db_path: Path,
    *,
    session_id: str,
    settings: str,
    messages: str,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO chat_sessions (
                id, character_id, title, title_is_auto, settings, messages, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                "character-legacy",
                "",
                1,
                settings,
                messages,
                FIXED_CREATED_AT.isoformat(),
                FIXED_UPDATED_AT.isoformat(),
            ),
        )
        await db.commit()


async def _insert_group_chat_session_row(
    db_path: Path,
    *,
    session_id: str,
    settings: str,
    messages: str,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO group_chat_sessions (
                id, group_id, title, title_is_auto, settings, messages, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                "group-legacy",
                "",
                1,
                settings,
                messages,
                FIXED_CREATED_AT.isoformat(),
                FIXED_UPDATED_AT.isoformat(),
            ),
        )
        await db.commit()


async def test_chat_session_roundtrip_json_matches_golden(tmp_path: Path) -> None:
    db_path = tmp_path / "wizmy.db"
    repo = ChatRepository(db_path)
    await repo.initialize()
    settings = ChatSessionSettings(
        profile_id="profile-golden",
        chat_mode_id="mode-golden",
        chat_mode_name="星図相談",
        chat_premise="灯里は星見図書館で案内役をしている。",
        situation="夜の閲覧室で古い星図を確認している。",
        user_persona_id="persona-sora",
        user_persona_name="ソラ",
        user_persona_description="架空の記録係。落ち着いて観察する。",
    )
    debug = ChatDebugInfo(
        llm_input="ユーザー: この星図、昨日と線が違う気がします。",
        raw_output="星図は夜ごとに少しだけ息をするんです。",
        reasoning_output="星図の変化に自然に反応する。",
        input_tokens=128,
        output_tokens=32,
        total_tokens=160,
    )
    messages = [
        ChatMessagePreview(
            "user",
            "この星図、昨日と線が違う気がします。",
            "21:00",
        ),
        ChatMessagePreview(
            "character",
            "星図は夜ごとに少しだけ息をするんです。",
            "21:01",
            debug=debug,
        ),
        ChatMessagePreview(
            "narration",
            "窓辺の天球儀が、かすかに青く光った。",
            "21:02",
        ),
        ChatMessagePreview(
            "memo",
            "次は天球儀について聞く。",
            "21:03",
        ),
    ]
    session = ChatSessionRecord(
        id="chat-session-golden",
        character_id="character-akari",
        title="星図の相談",
        title_is_auto=False,
        settings=chat_settings_to_dict(settings),
        messages=[chat_message_to_dict(message) for message in messages],
        created_at=FIXED_CREATED_AT,
        updated_at=FIXED_UPDATED_AT,
    )

    await repo.save(session)
    loaded = await repo.get(session.id)

    assert loaded is not None
    expected = _load_golden("chat_session_roundtrip.json")
    assert {"settings": loaded.settings, "messages": loaded.messages} == expected
    assert await _stored_session_json(db_path, "chat_sessions", session.id) == expected


async def test_group_chat_session_roundtrip_json_matches_golden(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "wizmy.db"
    repo = GroupChatRepository(db_path)
    await repo.initialize()
    group = make_group_chat()
    member = group.members[0]
    user = group.user_persona
    assert user is not None
    time_labels = iter(["21:00", "21:01", "21:02", "21:03", "21:04", "21:05"])
    monkeypatch.setattr(history_module, "time_label", lambda: next(time_labels))
    settings = {
        **make_group_settings(),
        "profile_id": "profile-golden",
    }
    debug = ChatDebugInfo(
        llm_input="ソラ: この星図、昨日と線が違う気がします。",
        raw_output="星図は夜ごとに少しだけ息をするんです。",
        reasoning_output="灯里として星図の変化を説明する。",
        input_tokens=192,
        output_tokens=48,
        total_tokens=240,
    )
    speaker_debug = ChatDebugInfo(
        llm_input="次の話者を選ぶ。",
        raw_output='{"speaker": "member-akari", "weight": 0.8}',
        reasoning_output="灯里が星図に詳しい。",
        input_tokens=64,
        output_tokens=12,
        total_tokens=76,
    )
    messages = [
        group_system_event_message("灯里が入場しました"),
        group_message(
            "user",
            "この星図、昨日と線が違う気がします。",
            user=user,
        ),
        group_message(
            "character",
            "星図は夜ごとに少しだけ息をするんです。",
            member=member,
            debug=debug,
            speaker_debug=speaker_debug,
        ),
        group_message(
            "guest",
            "返却台へお願いします。",
            guest_name="guest:巡回司書",
        ),
        group_message(
            "narration",
            "天球儀の青い光が床に広がった。",
        ),
        group_message(
            "memo",
            "次は湊に星図の修理を促す。",
        ),
    ]
    session = GroupChatSessionRecord(
        id="group-chat-session-golden",
        group_id=group.id,
        title="星図の夜会",
        title_is_auto=False,
        settings=settings,
        messages=messages,
        created_at=FIXED_CREATED_AT,
        updated_at=FIXED_UPDATED_AT,
    )

    await repo.save_session(session)
    loaded = await repo.get_session(session.id)

    assert loaded is not None
    expected = _load_golden("group_chat_session_roundtrip.json")
    assert {"settings": loaded.settings, "messages": loaded.messages} == expected
    assert await _stored_session_json(db_path, "group_chat_sessions", session.id) == expected


async def test_chat_repository_loads_legacy_json_with_missing_fields_and_fallback(tmp_path: Path) -> None:
    db_path = tmp_path / "wizmy.db"
    repo = ChatRepository(db_path)
    await repo.initialize()
    legacy_settings = {"profile_id": "legacy-profile"}
    legacy_messages = [{"speaker": "user", "text": "古い形式の発言"}]

    await _insert_chat_session_row(
        db_path,
        session_id="legacy-chat-missing-fields",
        settings=json.dumps(legacy_settings, ensure_ascii=False),
        messages=json.dumps(legacy_messages, ensure_ascii=False),
    )
    await _insert_chat_session_row(
        db_path,
        session_id="legacy-chat-invalid-json",
        settings="{invalid",
        messages="[invalid",
    )

    missing_fields = await repo.get("legacy-chat-missing-fields")
    invalid_json = await repo.get("legacy-chat-invalid-json")

    assert missing_fields is not None
    assert missing_fields.settings == legacy_settings
    assert missing_fields.messages == legacy_messages
    assert invalid_json is not None
    assert invalid_json.settings == {}
    assert invalid_json.messages == []


async def test_group_chat_repository_loads_legacy_json_with_missing_fields_and_fallback(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "wizmy.db"
    repo = GroupChatRepository(db_path)
    await repo.initialize()
    legacy_settings = {"participant_ids": ["member-legacy"]}
    legacy_messages = [{"role": "system", "text": "古い形式の通知"}]

    await _insert_group_chat_session_row(
        db_path,
        session_id="legacy-group-missing-fields",
        settings=json.dumps(legacy_settings, ensure_ascii=False),
        messages=json.dumps(legacy_messages, ensure_ascii=False),
    )
    await _insert_group_chat_session_row(
        db_path,
        session_id="legacy-group-invalid-json",
        settings="{invalid",
        messages="[invalid",
    )

    missing_fields = await repo.get_session("legacy-group-missing-fields")
    invalid_json = await repo.get_session("legacy-group-invalid-json")

    assert missing_fields is not None
    assert missing_fields.settings == legacy_settings
    assert missing_fields.messages == legacy_messages
    assert invalid_json is not None
    assert invalid_json.settings == {}
    assert invalid_json.messages == []
