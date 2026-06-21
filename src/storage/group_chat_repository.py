"""グループチャット定義の SQLite 永続化リポジトリ。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from ..core.group_chat.schemas import GroupChatRecord, GroupMember, GroupUserPersona
from ..core.group_chat.sessions import DEFAULT_GROUP_CHAT_TITLE, GroupChatSessionRecord


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS group_chats (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    world TEXT NOT NULL DEFAULT '',
    completion_profile_id TEXT NOT NULL DEFAULT '',
    members TEXT NOT NULL DEFAULT '[]',
    user_persona TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_CREATE_UPDATED_INDEX = """
CREATE INDEX IF NOT EXISTS idx_group_chats_updated ON group_chats(updated_at DESC)
"""

_CREATE_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS group_chat_sessions (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '新しいグループチャット',
    title_is_auto INTEGER NOT NULL DEFAULT 1,
    settings TEXT NOT NULL DEFAULT '{}',
    messages TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_CREATE_SESSIONS_GROUP_INDEX = """
CREATE INDEX IF NOT EXISTS idx_group_chat_sessions_group
ON group_chat_sessions(group_id, updated_at DESC)
"""


def _loads_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _row_to_group(row: aiosqlite.Row) -> GroupChatRecord:
    data = dict(row)
    persona_data = _loads_json(data.get("user_persona", "{}"), {})
    persona = GroupUserPersona(**persona_data) if persona_data else None
    return GroupChatRecord(
        id=data["id"],
        name=data.get("name") or "名称未設定",
        world=data.get("world") or "",
        completion_profile_id=data.get("completion_profile_id") or "",
        members=[
            GroupMember(**member)
            for member in _loads_json(data.get("members", "[]"), [])
            if isinstance(member, dict)
        ],
        user_persona=persona,
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data["updated_at"]),
    )


def _group_to_row(group: GroupChatRecord) -> dict[str, Any]:
    return {
        "id": group.id,
        "name": group.name,
        "world": group.world,
        "completion_profile_id": group.completion_profile_id,
        "members": json.dumps(
            [member.model_dump(mode="json") for member in group.members],
            ensure_ascii=False,
        ),
        "user_persona": json.dumps(
            group.user_persona.model_dump(mode="json") if group.user_persona else {},
            ensure_ascii=False,
        ),
        "created_at": group.created_at.isoformat(),
        "updated_at": group.updated_at.isoformat(),
    }


def _row_to_session(row: aiosqlite.Row) -> GroupChatSessionRecord:
    data = dict(row)
    return GroupChatSessionRecord(
        id=data["id"],
        group_id=data["group_id"],
        title=data.get("title") or DEFAULT_GROUP_CHAT_TITLE,
        title_is_auto=data.get("title_is_auto", 1) in (1, True, "1", "true", "True"),
        settings=_loads_json(data.get("settings", "{}"), {}),
        messages=_loads_json(data.get("messages", "[]"), []),
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data["updated_at"]),
    )


def _session_to_row(session: GroupChatSessionRecord) -> dict[str, Any]:
    return {
        "id": session.id,
        "group_id": session.group_id,
        "title": session.title or DEFAULT_GROUP_CHAT_TITLE,
        "title_is_auto": 1 if session.title_is_auto else 0,
        "settings": json.dumps(session.settings, ensure_ascii=False),
        "messages": json.dumps(session.messages, ensure_ascii=False),
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
    }


class GroupChatRepository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_CREATE_TABLE)
            await db.execute(_CREATE_UPDATED_INDEX)
            await db.execute(_CREATE_SESSIONS_TABLE)
            await db.execute(_CREATE_SESSIONS_GROUP_INDEX)
            await db.commit()

    async def save(self, group: GroupChatRecord) -> GroupChatRecord:
        saved = group.model_copy(update={"updated_at": datetime.now()}, deep=True)
        row = _group_to_row(saved)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO group_chats (
                    id, name, world, completion_profile_id, members, user_persona,
                    created_at, updated_at
                ) VALUES (
                    :id, :name, :world, :completion_profile_id, :members, :user_persona,
                    :created_at, :updated_at
                ) ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    world=excluded.world,
                    completion_profile_id=excluded.completion_profile_id,
                    members=excluded.members,
                    user_persona=excluded.user_persona,
                    updated_at=excluded.updated_at
                """,
                row,
            )
            await db.commit()
        return saved

    async def get(self, group_id: str) -> GroupChatRecord | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM group_chats WHERE id = ?",
                (group_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return _row_to_group(row) if row else None

    async def list_all(self) -> list[GroupChatRecord]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM group_chats ORDER BY updated_at DESC"
            ) as cursor:
                rows = await cursor.fetchall()
                return [_row_to_group(row) for row in rows]

    async def delete(self, group_id: str) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute("DELETE FROM group_chats WHERE id = ?", (group_id,))
            await db.execute("DELETE FROM group_chat_sessions WHERE group_id = ?", (group_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def save_session(self, session: GroupChatSessionRecord) -> GroupChatSessionRecord:
        saved = GroupChatSessionRecord(
            id=session.id,
            group_id=session.group_id,
            title=session.title,
            title_is_auto=session.title_is_auto,
            settings=session.settings,
            messages=session.messages,
            created_at=session.created_at,
            updated_at=datetime.now(),
        )
        row = _session_to_row(saved)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO group_chat_sessions (
                    id, group_id, title, title_is_auto, settings, messages,
                    created_at, updated_at
                ) VALUES (
                    :id, :group_id, :title, :title_is_auto, :settings, :messages,
                    :created_at, :updated_at
                ) ON CONFLICT(id) DO UPDATE SET
                    group_id=excluded.group_id,
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

    async def get_session(self, session_id: str) -> GroupChatSessionRecord | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM group_chat_sessions WHERE id = ?",
                (session_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return _row_to_session(row) if row else None

    async def list_sessions_for_group(self, group_id: str) -> list[GroupChatSessionRecord]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM group_chat_sessions
                WHERE group_id = ?
                ORDER BY updated_at DESC
                """,
                (group_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [_row_to_session(row) for row in rows]

    async def delete_session(self, session_id: str) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "DELETE FROM group_chat_sessions WHERE id = ?",
                (session_id,),
            )
            await db.commit()
            return cursor.rowcount > 0

    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid4())
