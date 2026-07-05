"""Application service for saved character chat sessions."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from ..core.chat.sessions import DEFAULT_CHAT_TITLE, ChatSessionRecord
from ..storage.chat_repository import ChatRepository


class ChatService:
    def __init__(self, repo: ChatRepository) -> None:
        self._repo = repo

    async def initialize(self) -> None:
        await self._repo.initialize()

    async def list_for_character(self, character_id: str) -> list[ChatSessionRecord]:
        return await self._repo.list_for_character(character_id)

    async def get(self, session_id: str) -> ChatSessionRecord | None:
        return await self._repo.get(session_id)

    async def create_session(
        self,
        *,
        character_id: str,
        title: str,
        title_is_auto: bool,
        settings: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> ChatSessionRecord:
        now = datetime.now()
        session = ChatSessionRecord(
            id=self._repo.new_id(),
            character_id=character_id,
            title=title.strip() or DEFAULT_CHAT_TITLE,
            title_is_auto=title_is_auto,
            settings=settings,
            messages=messages,
            created_at=now,
            updated_at=now,
        )
        return await self._repo.save(session)

    async def update_session(
        self,
        *,
        session_id: str,
        character_id: str,
        title: str,
        title_is_auto: bool,
        settings: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> ChatSessionRecord:
        existing = await self._repo.get(session_id)
        created_at = existing.created_at if existing else datetime.now()
        session = ChatSessionRecord(
            id=session_id,
            character_id=character_id,
            title=title.strip() or DEFAULT_CHAT_TITLE,
            title_is_auto=title_is_auto,
            settings=settings,
            messages=messages,
            created_at=created_at,
            updated_at=datetime.now(),
        )
        return await self._repo.save(session)

    async def rename_session(self, session_id: str, title: str) -> ChatSessionRecord | None:
        existing = await self._repo.get(session_id)
        if existing is None:
            return None
        renamed = replace(
            existing,
            title=title.strip() or DEFAULT_CHAT_TITLE,
            title_is_auto=False,
        )
        return await self._repo.save(renamed)

    async def delete_session(self, session_id: str) -> bool:
        return await self._repo.delete(session_id)
