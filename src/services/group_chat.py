"""グループチャット定義のアプリケーションサービス。"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime
from typing import Any

from ..core.chat.schemas import UserPersona
from ..core.character.schemas import CharacterSheet
from ..core.group_chat.schemas import GroupChatRecord, GroupMember, GroupUserPersona
from ..core.group_chat.sessions import DEFAULT_GROUP_CHAT_TITLE, GroupChatSessionRecord
from ..storage.group_chat_repository import GroupChatRepository


class GroupChatService:
    def __init__(self, repo: GroupChatRepository) -> None:
        self._repo = repo

    async def initialize(self) -> None:
        await self._repo.initialize()

    async def list_all(self) -> list[GroupChatRecord]:
        return await self._repo.list_all()

    async def get(self, group_id: str) -> GroupChatRecord | None:
        return await self._repo.get(group_id)

    async def list_sessions_for_group(self, group_id: str) -> list[GroupChatSessionRecord]:
        return await self._repo.list_sessions_for_group(group_id)

    async def get_session(self, session_id: str) -> GroupChatSessionRecord | None:
        return await self._repo.get_session(session_id)

    async def create_group(
        self,
        *,
        name: str,
        world: str,
        completion_profile_id: str,
        members: list[tuple[CharacterSheet, str]],
        user_persona: UserPersona,
        user_handle: str,
    ) -> GroupChatRecord:
        now = datetime.now()
        group = GroupChatRecord(
            id=self._repo.new_id(),
            name=name.strip(),
            world=world.strip(),
            completion_profile_id=completion_profile_id,
            members=[
                GroupMember(
                    id=uuid.uuid4().hex,
                    source_character_id=sheet.id,
                    handle=handle,
                    character=sheet.model_copy(deep=True),
                )
                for sheet, handle in members
            ],
            user_persona=GroupUserPersona(
                id=uuid.uuid4().hex,
                source_persona_id=user_persona.id,
                handle=user_handle,
                name=user_persona.name,
                display_name=user_persona.display_name,
                description=user_persona.description,
                media=user_persona.media.model_copy(deep=True),
            ),
            created_at=now,
            updated_at=now,
        )
        return await self._repo.save(group)

    async def add_members(
        self,
        group_id: str,
        members: list[tuple[CharacterSheet, str]],
    ) -> GroupChatRecord | None:
        group = await self._repo.get(group_id)
        if group is None:
            return None

        added = [
            GroupMember(
                id=uuid.uuid4().hex,
                source_character_id=sheet.id,
                handle=handle,
                character=sheet.model_copy(deep=True),
            )
            for sheet, handle in members
        ]
        return await self._repo.save(
            group.model_copy(update={"members": [*group.members, *added]}, deep=True)
        )

    async def create_session(
        self,
        *,
        group_id: str,
        title: str,
        title_is_auto: bool,
        settings: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> GroupChatSessionRecord:
        now = datetime.now()
        session = GroupChatSessionRecord(
            id=self._repo.new_id(),
            group_id=group_id,
            title=title.strip() or DEFAULT_GROUP_CHAT_TITLE,
            title_is_auto=title_is_auto,
            settings=settings,
            messages=messages,
            created_at=now,
            updated_at=now,
        )
        return await self._repo.save_session(session)

    async def update_session(
        self,
        *,
        session_id: str,
        group_id: str,
        title: str,
        title_is_auto: bool,
        settings: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> GroupChatSessionRecord:
        existing = await self._repo.get_session(session_id)
        created_at = existing.created_at if existing else datetime.now()
        session = GroupChatSessionRecord(
            id=session_id,
            group_id=group_id,
            title=title.strip() or DEFAULT_GROUP_CHAT_TITLE,
            title_is_auto=title_is_auto,
            settings=settings,
            messages=messages,
            created_at=created_at,
            updated_at=datetime.now(),
        )
        return await self._repo.save_session(session)

    async def rename_session(
        self,
        session_id: str,
        title: str,
    ) -> GroupChatSessionRecord | None:
        existing = await self._repo.get_session(session_id)
        if existing is None:
            return None
        return await self._repo.save_session(
            replace(
                existing,
                title=title.strip() or DEFAULT_GROUP_CHAT_TITLE,
                title_is_auto=False,
            )
        )

    async def delete_group(self, group_id: str) -> bool:
        return await self._repo.delete(group_id)

    async def delete_session(self, session_id: str) -> bool:
        return await self._repo.delete_session(session_id)
