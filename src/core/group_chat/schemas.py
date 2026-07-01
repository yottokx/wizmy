"""グループチャットの保存スキーマ。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ..character.schemas import CharacterMedia, CharacterSheet


class GroupMember(BaseModel):
    id: str
    source_character_id: str = ""
    handle: str
    character: CharacterSheet
    world_entry_type: str = ""
    arrival_reason: str = ""
    world_adaptation_note: str = ""


class GroupUserPersona(BaseModel):
    id: str
    source_persona_id: str = ""
    handle: str
    name: str = ""
    display_name: str = ""
    description: str = ""
    media: CharacterMedia = Field(default_factory=CharacterMedia)
    world_entry_type: str = ""
    arrival_reason: str = ""
    world_adaptation_note: str = ""


class GroupRelationship(BaseModel):
    id: str
    participant_a_key: str
    participant_b_key: str
    description: str = ""


class GroupChatRecord(BaseModel):
    id: str
    name: str
    world: str = ""
    world_source_type: str = "new"
    world_source_character_id: str = ""
    completion_profile_id: str = ""
    members: list[GroupMember] = Field(default_factory=list)
    user_persona: GroupUserPersona | None = None
    relationships: list[GroupRelationship] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
