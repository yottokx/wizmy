"""グループチャット定義のアプリケーションサービス。"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime
from typing import Any

from ..core.chat.schemas import UserPersona
from ..core.character.schemas import CharacterSheet
from ..core.group_chat.schemas import (
    GroupChatRecord,
    GroupMember,
    GroupRelationship,
    GroupUserPersona,
)
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
        world_source_type: str = "new",
        world_source_character_id: str = "",
        member_world_settings: dict[str, dict[str, str]] | None = None,
        user_world_settings: dict[str, str] | None = None,
        relationships: list[GroupRelationship] | None = None,
    ) -> GroupChatRecord:
        now = datetime.now()
        member_world_settings = member_world_settings or {}
        user_world_settings = user_world_settings or {}
        created_members: list[GroupMember] = []
        relationship_key_map: dict[str, str] = {}
        for sheet, handle in members:
            settings = member_world_settings.get(sheet.id) or member_world_settings.get(f"character:{sheet.id}") or {}
            member = GroupMember(
                id=uuid.uuid4().hex,
                source_character_id=sheet.id,
                handle=handle,
                character=sheet.model_copy(deep=True),
                world_entry_type=settings.get("world_entry_type", ""),
                arrival_reason=settings.get("arrival_reason", ""),
                world_adaptation_note=settings.get("world_adaptation_note", ""),
            )
            created_members.append(member)
            relationship_key_map[f"character:{sheet.id}"] = f"member:{member.id}"
            relationship_key_map[f"member:{sheet.id}"] = f"member:{member.id}"

        created_user_persona = GroupUserPersona(
            id=uuid.uuid4().hex,
            source_persona_id=user_persona.id,
            handle=user_handle,
            name=user_persona.name,
            display_name=user_persona.display_name,
            description=user_world_settings.get("description", user_persona.description),
            media=user_persona.media.model_copy(deep=True),
            world_entry_type=user_world_settings.get("world_entry_type", ""),
            arrival_reason=user_world_settings.get("arrival_reason", ""),
            world_adaptation_note=user_world_settings.get("world_adaptation_note", ""),
        )
        relationship_key_map["user"] = f"user:{created_user_persona.id}"
        relationship_key_map[f"user:{user_persona.id}"] = f"user:{created_user_persona.id}"

        created_relationships: list[GroupRelationship] = []
        seen_relationship_keys: set[frozenset[str]] = set()
        for relationship in relationships or []:
            first = relationship_key_map.get(relationship.participant_a_key, relationship.participant_a_key)
            second = relationship_key_map.get(relationship.participant_b_key, relationship.participant_b_key)
            if not first or not second or first == second:
                continue
            pair_key = frozenset({first, second})
            if pair_key in seen_relationship_keys:
                continue
            description = relationship.description.strip()
            if not description:
                continue
            seen_relationship_keys.add(pair_key)
            relationship_id = relationship.id
            if not relationship_id or relationship_id.startswith("draft-"):
                relationship_id = uuid.uuid4().hex
            created_relationships.append(
                GroupRelationship(
                    id=relationship_id,
                    participant_a_key=first,
                    participant_b_key=second,
                    description=description,
                )
            )

        group = GroupChatRecord(
            id=self._repo.new_id(),
            name=name.strip(),
            world=world.strip(),
            world_source_type=world_source_type if world_source_type in {"new", "character"} else "new",
            world_source_character_id=world_source_character_id if world_source_type == "character" else "",
            completion_profile_id=completion_profile_id,
            members=created_members,
            user_persona=created_user_persona,
            relationships=created_relationships,
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

    async def update_member_character(
        self,
        group_id: str,
        member_id: str,
        character: CharacterSheet,
    ) -> GroupMember | None:
        group = await self._repo.get(group_id)
        if group is None:
            return None

        updated_members: list[GroupMember] = []
        updated_member: GroupMember | None = None
        for member in group.members:
            if member.id == member_id:
                updated_member = member.model_copy(
                    update={"character": character.model_copy(deep=True)},
                    deep=True,
                )
                updated_members.append(updated_member)
            else:
                updated_members.append(member)

        if updated_member is None:
            return None

        saved = await self._repo.save(
            group.model_copy(update={"members": updated_members}, deep=True)
        )
        for member in saved.members:
            if member.id == member_id:
                return member
        return updated_member

    async def update_user_persona(
        self,
        group_id: str,
        persona: GroupUserPersona,
    ) -> GroupUserPersona | None:
        group = await self._repo.get(group_id)
        if group is None or group.user_persona is None:
            return None

        updated = persona.model_copy(deep=True)
        saved = await self._repo.save(
            group.model_copy(update={"user_persona": updated}, deep=True)
        )
        return saved.user_persona

    async def save_relationship(
        self,
        group_id: str,
        relationship: GroupRelationship,
    ) -> GroupChatRecord | None:
        group = await self._repo.get(group_id)
        if group is None:
            return None

        saved_relationship = relationship.model_copy(
            update={
                "id": relationship.id or uuid.uuid4().hex,
                "description": relationship.description.strip(),
            },
            deep=True,
        )
        relation_keys = {
            saved_relationship.participant_a_key,
            saved_relationship.participant_b_key,
        }
        relationships = [
            item
            for item in group.relationships
            if item.id != saved_relationship.id
            and {item.participant_a_key, item.participant_b_key} != relation_keys
        ]
        relationships.append(saved_relationship)
        return await self._repo.save(
            group.model_copy(update={"relationships": relationships}, deep=True)
        )

    async def delete_relationship(
        self,
        group_id: str,
        relationship_id: str,
    ) -> GroupChatRecord | None:
        group = await self._repo.get(group_id)
        if group is None:
            return None

        relationships = [
            relationship
            for relationship in group.relationships
            if relationship.id != relationship_id
        ]
        return await self._repo.save(
            group.model_copy(update={"relationships": relationships}, deep=True)
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
