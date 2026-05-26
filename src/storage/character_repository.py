"""
キャラクターシートの SQLite 永続化リポジトリ。

SQLAlchemy Core (非ORM) + aiosqlite で非同期アクセスを提供する。
キャラクターは構造化フィールド + raw_markdown の両方を保持する。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import aiosqlite

from ..core.character.schemas import CharacterMedia, CharacterSheet, GenerationMeta, Relationship

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS characters (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    age TEXT NOT NULL DEFAULT '',
    gender TEXT NOT NULL DEFAULT '',
    occupation TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT '',
    world TEXT NOT NULL DEFAULT '',
    appearance TEXT NOT NULL DEFAULT '',
    personality TEXT NOT NULL DEFAULT '',
    motivation TEXT NOT NULL DEFAULT '',
    weakness TEXT NOT NULL DEFAULT '',
    background TEXT NOT NULL DEFAULT '',
    skills TEXT NOT NULL DEFAULT '',
    relationships TEXT NOT NULL DEFAULT '[]',
    quirks TEXT NOT NULL DEFAULT '',
    story_hooks TEXT NOT NULL DEFAULT '',
    self_intro TEXT NOT NULL DEFAULT '',
    voice_image TEXT NOT NULL DEFAULT '',
    media TEXT NOT NULL DEFAULT '{}',
    is_favorite INTEGER NOT NULL DEFAULT 0,
    tags TEXT NOT NULL DEFAULT '[]',
    raw_markdown TEXT NOT NULL DEFAULT '',
    generation_meta TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_characters_name ON characters(name)
"""

_CREATE_FAVORITE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_characters_favorite ON characters(is_favorite)
"""


def _row_to_sheet(row: aiosqlite.Row) -> CharacterSheet:
    d = dict(row)
    d["relationships"] = [
        Relationship(**r) for r in json.loads(d.get("relationships", "[]"))
    ]
    d["tags"] = json.loads(d.get("tags", "[]"))
    d["generation_meta"] = GenerationMeta(**json.loads(d.get("generation_meta", "{}")))
    try:
        media_data = json.loads(d.get("media") or "{}")
    except json.JSONDecodeError:
        media_data = {}
    d["media"] = CharacterMedia(**media_data)
    d["is_favorite"] = d.get("is_favorite", 0) in (1, True, "1", "true", "True")
    d["created_at"] = datetime.fromisoformat(d["created_at"])
    d["updated_at"] = datetime.fromisoformat(d["updated_at"])
    return CharacterSheet(**d)


def _sheet_to_row(sheet: CharacterSheet) -> dict:
    return {
        "id": sheet.id,
        "name": sheet.name,
        "age": sheet.age,
        "gender": sheet.gender,
        "occupation": sheet.occupation,
        "origin": sheet.origin,
        "world": sheet.world,
        "appearance": sheet.appearance,
        "personality": sheet.personality,
        "motivation": sheet.motivation,
        "weakness": sheet.weakness,
        "background": sheet.background,
        "skills": sheet.skills,
        "relationships": json.dumps(
            [r.model_dump() for r in sheet.relationships], ensure_ascii=False
        ),
        "quirks": sheet.quirks,
        "story_hooks": sheet.story_hooks,
        "self_intro": sheet.self_intro,
        "voice_image": sheet.voice_image,
        "media": json.dumps(sheet.media.model_dump(mode="json"), ensure_ascii=False),
        "is_favorite": 1 if sheet.is_favorite else 0,
        "tags": json.dumps(sheet.tags, ensure_ascii=False),
        "raw_markdown": sheet.raw_markdown,
        "generation_meta": json.dumps(sheet.generation_meta.model_dump(), ensure_ascii=False),
        "created_at": sheet.created_at.isoformat(),
        "updated_at": sheet.updated_at.isoformat(),
    }


class CharacterRepository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_CREATE_TABLE)
            await self._ensure_columns(db)
            await db.execute(_CREATE_INDEX)
            await db.execute(_CREATE_FAVORITE_INDEX)
            await db.commit()

    async def _ensure_columns(self, db: aiosqlite.Connection) -> None:
        async with db.execute("PRAGMA table_info(characters)") as cursor:
            rows = await cursor.fetchall()
        columns = {row[1] for row in rows}
        if "media" not in columns:
            await db.execute("ALTER TABLE characters ADD COLUMN media TEXT NOT NULL DEFAULT '{}'")
        if "is_favorite" not in columns:
            await db.execute("ALTER TABLE characters ADD COLUMN is_favorite INTEGER NOT NULL DEFAULT 0")

    async def save(self, sheet: CharacterSheet) -> CharacterSheet:
        sheet.updated_at = datetime.now()
        row = _sheet_to_row(sheet)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO characters (
                    id, name, age, gender, occupation, origin, world,
                    appearance, personality, motivation, weakness, background,
                    skills, relationships, quirks, story_hooks, self_intro,
                    voice_image, media, is_favorite, tags, raw_markdown, generation_meta,
                    created_at, updated_at
                ) VALUES (
                    :id, :name, :age, :gender, :occupation, :origin, :world,
                    :appearance, :personality, :motivation, :weakness, :background,
                    :skills, :relationships, :quirks, :story_hooks, :self_intro,
                    :voice_image, :media, :is_favorite, :tags, :raw_markdown, :generation_meta,
                    :created_at, :updated_at
                ) ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name, age=excluded.age, gender=excluded.gender,
                    occupation=excluded.occupation, origin=excluded.origin,
                    world=excluded.world, appearance=excluded.appearance,
                    personality=excluded.personality, motivation=excluded.motivation,
                    weakness=excluded.weakness, background=excluded.background,
                    skills=excluded.skills, relationships=excluded.relationships,
                    quirks=excluded.quirks, story_hooks=excluded.story_hooks,
                    self_intro=excluded.self_intro, voice_image=excluded.voice_image,
                    media=excluded.media, is_favorite=excluded.is_favorite,
                    tags=excluded.tags, raw_markdown=excluded.raw_markdown,
                    generation_meta=excluded.generation_meta, updated_at=excluded.updated_at
                """,
                row,
            )
            await db.commit()
        return sheet

    async def get(self, character_id: str) -> CharacterSheet | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM characters WHERE id = ?", (character_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return _row_to_sheet(row) if row else None

    async def list_all(
        self, search: str = "", tag: str = "", favorites_only: bool = False
    ) -> list[CharacterSheet]:
        conditions: list[str] = []
        params: list[object] = []

        if search:
            conditions.append("(name LIKE ? OR world LIKE ? OR occupation LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like, like])
        if tag:
            conditions.append("tags LIKE ?")
            params.append(f'%"{tag}"%')
        if favorites_only:
            conditions.append("is_favorite = 1")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM characters {where} ORDER BY updated_at DESC"

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [_row_to_sheet(row) for row in rows]

    async def delete(self, character_id: str) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "DELETE FROM characters WHERE id = ?", (character_id,)
            )
            await db.commit()
            return cursor.rowcount > 0

    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid4())
