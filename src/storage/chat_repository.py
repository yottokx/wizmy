"""SQLite persistence for character chat sessions."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from ..core.chat.sessions import DEFAULT_CHAT_TITLE, ChatSessionRecord

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    character_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '新しいチャット',
    title_is_auto INTEGER NOT NULL DEFAULT 1,
    settings TEXT NOT NULL DEFAULT '{}',
    messages TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_CREATE_CHARACTER_INDEX = """
CREATE INDEX IF NOT EXISTS idx_chat_sessions_character ON chat_sessions(character_id, updated_at DESC)
"""


def _loads_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _row_to_session(row: aiosqlite.Row) -> ChatSessionRecord:
    data = dict(row)
    return ChatSessionRecord(
        id=data["id"],
        character_id=data["character_id"],
        title=data.get("title") or DEFAULT_CHAT_TITLE,
        title_is_auto=data.get("title_is_auto", 1) in (1, True, "1", "true", "True"),
        settings=_loads_json(data.get("settings", "{}"), {}),
        messages=_loads_json(data.get("messages", "[]"), []),
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data["updated_at"]),
    )


def _session_to_row(session: ChatSessionRecord) -> dict[str, Any]:
    return {
        "id": session.id,
        "character_id": session.character_id,
        "title": session.title or DEFAULT_CHAT_TITLE,
        "title_is_auto": 1 if session.title_is_auto else 0,
        "settings": json.dumps(session.settings, ensure_ascii=False),
        "messages": json.dumps(session.messages, ensure_ascii=False),
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
    }


class ChatRepository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_CREATE_TABLE)
            await db.execute(_CREATE_CHARACTER_INDEX)
            await db.commit()

    async def save(self, session: ChatSessionRecord) -> ChatSessionRecord:
        saved = replace(session, updated_at=datetime.now())
        row = _session_to_row(saved)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO chat_sessions (
                    id, character_id, title, title_is_auto, settings, messages,
                    created_at, updated_at
                ) VALUES (
                    :id, :character_id, :title, :title_is_auto, :settings, :messages,
                    :created_at, :updated_at
                ) ON CONFLICT(id) DO UPDATE SET
                    character_id=excluded.character_id,
                    title=excluded.title,
                    title_is_auto=excluded.title_is_auto,
                    settings=excluded.settings,
                    messages=excluded.messages,
                    updated_at=excluded.updated_at
                """,
                row,
            )
            await db.commit()
        return saved

    async def get(self, session_id: str) -> ChatSessionRecord | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)) as cursor:
                row = await cursor.fetchone()
                return _row_to_session(row) if row else None

    async def list_for_character(self, character_id: str) -> list[ChatSessionRecord]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM chat_sessions
                WHERE character_id = ?
                ORDER BY updated_at DESC
                """,
                (character_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [_row_to_session(row) for row in rows]

    async def delete(self, session_id: str) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
            await db.commit()
            return cursor.rowcount > 0

    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid4())
