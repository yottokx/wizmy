"""グループチャット定義のアプリケーションサービス。"""

from __future__ import annotations

import mimetypes
import shutil
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core.chat.schemas import UserPersona
from ..core.character.schemas import (
    CharacterImageAsset,
    CharacterSheet,
    CharacterTTSSettings,
    CharacterVoiceAsset,
    FaceRect,
)
from ..core.group_chat.schemas import (
    GroupChatRecord,
    GroupMember,
    GroupRelationship,
    GroupUserPersona,
)
from ..core.group_chat.sessions import DEFAULT_GROUP_CHAT_TITLE, GroupChatSessionRecord
from ..storage.group_chat_repository import GroupChatRepository


class GroupChatService:
    _IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
    _VOICE_SUFFIXES = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav", ".webm"}

    def __init__(self, repo: GroupChatRepository, data_dir: Path | None = None) -> None:
        self._repo = repo
        self._data_dir = data_dir or Path("data")
        self._groups_dir = self._data_dir / "groups"

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
        member_world_settings: dict[str, dict[str, str]] | None = None,
    ) -> GroupChatRecord | None:
        group = await self._repo.get(group_id)
        if group is None:
            return None

        member_world_settings = member_world_settings or {}
        added: list[GroupMember] = []
        for sheet, handle in members:
            settings = member_world_settings.get(sheet.id) or member_world_settings.get(f"character:{sheet.id}") or {}
            added.append(
                GroupMember(
                    id=uuid.uuid4().hex,
                    source_character_id=sheet.id,
                    handle=handle,
                    character=sheet.model_copy(deep=True),
                    world_entry_type=settings.get("world_entry_type", ""),
                    arrival_reason=settings.get("arrival_reason", ""),
                    world_adaptation_note=settings.get("world_adaptation_note", ""),
                )
            )
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

    def media_path(self, relative_path: str) -> Path | None:
        if not relative_path:
            return None
        path = (self._data_dir / relative_path).resolve()
        data_root = self._data_dir.resolve()
        if not path.is_relative_to(data_root) or not path.is_file():
            return None
        return path

    async def save_member_image(
        self,
        group_id: str,
        member_id: str,
        upload: Any,
    ) -> GroupMember | None:
        filename = getattr(upload, "name", "") or ""
        content_type = getattr(upload, "content_type", "") or ""
        if content_type and not content_type.startswith("image/"):
            raise ValueError("画像ファイルを選択してください。")
        if not content_type and Path(filename).suffix.lower() not in self._IMAGE_SUFFIXES:
            raise ValueError("画像ファイルを選択してください。")

        group, member = await self._get_group_member(group_id, member_id)
        if group is None or member is None:
            return None

        asset_id = uuid.uuid4().hex
        suffix = self._safe_suffix(filename, content_type, self._IMAGE_SUFFIXES, ".png")
        relative_path = (
            Path("groups") / group_id / "members" / member_id / "images" / f"{asset_id}{suffix}"
        )
        target = self._data_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        await upload.save(target)

        sheet = member.character.model_copy(deep=True)
        old_paths = [image.path for image in sheet.media.images]
        image = CharacterImageAsset(
            id=asset_id,
            path=relative_path.as_posix(),
            original_name=filename,
            content_type=content_type,
        )
        sheet.media.images = [image]
        sheet.media.primary_image_id = image.id
        try:
            saved = await self.update_member_character(group.id, member.id, sheet)
        except Exception:
            self._delete_media_file(image.path)
            raise
        if saved is None:
            self._delete_media_file(image.path)
            return None
        for old_path in old_paths:
            self._delete_member_media_file(group.id, member.id, old_path)
        return saved

    async def save_member_image_bytes(
        self,
        group_id: str,
        member_id: str,
        image_bytes: bytes,
        *,
        filename: str = "generated-image.png",
        content_type: str = "image/png",
        width: int = 0,
        height: int = 0,
    ) -> GroupMember | None:
        if not image_bytes:
            raise ValueError("画像データが空です。")
        if content_type and not content_type.startswith("image/"):
            raise ValueError("画像データを指定してください。")

        group, member = await self._get_group_member(group_id, member_id)
        if group is None or member is None:
            return None

        asset_id = uuid.uuid4().hex
        suffix = self._safe_suffix(filename, content_type, self._IMAGE_SUFFIXES, ".png")
        relative_path = (
            Path("groups") / group_id / "members" / member_id / "images" / f"{asset_id}{suffix}"
        )
        target = self._data_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(image_bytes)

        sheet = member.character.model_copy(deep=True)
        old_paths = [image.path for image in sheet.media.images]
        image = CharacterImageAsset(
            id=asset_id,
            path=relative_path.as_posix(),
            original_name=filename,
            content_type=content_type,
            width=max(0, int(width or 0)),
            height=max(0, int(height or 0)),
        )
        sheet.media.images = [image]
        sheet.media.primary_image_id = image.id
        try:
            saved = await self.update_member_character(group.id, member.id, sheet)
        except Exception:
            self._delete_media_file(image.path)
            raise
        if saved is None:
            self._delete_media_file(image.path)
            return None
        for old_path in old_paths:
            self._delete_member_media_file(group.id, member.id, old_path)
        return saved

    async def save_member_voice(
        self,
        group_id: str,
        member_id: str,
        upload: Any,
    ) -> GroupMember | None:
        filename = getattr(upload, "name", "") or ""
        content_type = getattr(upload, "content_type", "") or ""
        if content_type and not content_type.startswith("audio/"):
            raise ValueError("音声ファイルを選択してください。")
        if not content_type and Path(filename).suffix.lower() not in self._VOICE_SUFFIXES:
            raise ValueError("音声ファイルを選択してください。")

        group, member = await self._get_group_member(group_id, member_id)
        if group is None or member is None:
            return None

        asset_id = uuid.uuid4().hex
        suffix = self._safe_suffix(filename, content_type, self._VOICE_SUFFIXES, ".wav")
        relative_path = (
            Path("groups") / group_id / "members" / member_id / "voices" / f"{asset_id}{suffix}"
        )
        target = self._data_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        await upload.save(target)

        sheet = member.character.model_copy(deep=True)
        old_paths = [voice.path for voice in sheet.media.voices]
        voice = CharacterVoiceAsset(
            id=asset_id,
            path=relative_path.as_posix(),
            original_name=filename,
            content_type=content_type,
        )
        sheet.media.voices = [voice]
        sheet.media.primary_voice_id = voice.id
        try:
            saved = await self.update_member_character(group.id, member.id, sheet)
        except Exception:
            self._delete_media_file(voice.path)
            raise
        if saved is None:
            self._delete_media_file(voice.path)
            return None
        for old_path in old_paths:
            self._delete_member_media_file(group.id, member.id, old_path)
        return saved

    async def save_member_voice_bytes(
        self,
        group_id: str,
        member_id: str,
        audio_bytes: bytes,
        *,
        filename: str = "voice-design.wav",
        content_type: str = "audio/wav",
    ) -> GroupMember | None:
        if not audio_bytes:
            raise ValueError("音声データが空です。")

        group, member = await self._get_group_member(group_id, member_id)
        if group is None or member is None:
            return None

        asset_id = uuid.uuid4().hex
        suffix = self._safe_suffix(filename, content_type, self._VOICE_SUFFIXES, ".wav")
        relative_path = (
            Path("groups") / group_id / "members" / member_id / "voices" / f"{asset_id}{suffix}"
        )
        target = self._data_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(audio_bytes)

        sheet = member.character.model_copy(deep=True)
        old_paths = [voice.path for voice in sheet.media.voices]
        voice = CharacterVoiceAsset(
            id=asset_id,
            path=relative_path.as_posix(),
            original_name=filename,
            content_type=content_type,
        )
        sheet.media.voices = [voice]
        sheet.media.primary_voice_id = voice.id
        try:
            saved = await self.update_member_character(group.id, member.id, sheet)
        except Exception:
            self._delete_media_file(voice.path)
            raise
        if saved is None:
            self._delete_media_file(voice.path)
            return None
        for old_path in old_paths:
            self._delete_member_media_file(group.id, member.id, old_path)
        return saved

    async def update_member_tts_settings(
        self,
        group_id: str,
        member_id: str,
        settings: CharacterTTSSettings,
    ) -> GroupMember | None:
        group, member = await self._get_group_member(group_id, member_id)
        if group is None or member is None:
            return None
        sheet = member.character.model_copy(deep=True)
        sheet.media.tts = settings
        return await self.update_member_character(group.id, member.id, sheet)

    async def update_member_face_rect(
        self,
        group_id: str,
        member_id: str,
        rect: FaceRect,
        *,
        image_width: int = 0,
        image_height: int = 0,
    ) -> GroupMember | None:
        group, member = await self._get_group_member(group_id, member_id)
        if group is None or member is None:
            return None
        sheet = member.character.model_copy(deep=True)
        image = sheet.media.primary_image()
        if image is None:
            raise ValueError("顔範囲を設定する画像がありません。")
        image.face_rect = self._clamp_rect(rect)
        if image_width > 0:
            image.width = image_width
        if image_height > 0:
            image.height = image_height
        sheet.media.primary_image_id = image.id
        return await self.update_member_character(group.id, member.id, sheet)

    async def update_member_bust_rect(
        self,
        group_id: str,
        member_id: str,
        rect: FaceRect,
        *,
        image_width: int = 0,
        image_height: int = 0,
    ) -> GroupMember | None:
        group, member = await self._get_group_member(group_id, member_id)
        if group is None or member is None:
            return None
        sheet = member.character.model_copy(deep=True)
        image = sheet.media.primary_image()
        if image is None:
            raise ValueError("バストショット範囲を設定する画像がありません。")
        image.bust_rect = self._clamp_rect(rect)
        if image_width > 0:
            image.width = image_width
        if image_height > 0:
            image.height = image_height
        sheet.media.primary_image_id = image.id
        return await self.update_member_character(group.id, member.id, sheet)

    def save_member_tts_preview(
        self,
        group_id: str,
        member_id: str,
        audio_bytes: bytes,
        *,
        replace_existing: bool = True,
    ) -> Path:
        return self._save_member_temp_file(
            group_id,
            member_id,
            audio_bytes,
            directory="tts",
            prefix="preview",
            suffix=".wav",
            replace_existing=replace_existing,
        )

    def save_member_tts_playback(self, group_id: str, member_id: str, audio_bytes: bytes) -> Path:
        return self._save_member_temp_file(
            group_id,
            member_id,
            audio_bytes,
            directory="tts",
            prefix="playback",
            suffix=".wav",
            replace_existing=True,
        )

    def save_member_image_preview(
        self,
        group_id: str,
        member_id: str,
        image_bytes: bytes,
        *,
        filename: str = "generated-image.png",
        content_type: str = "image/png",
        replace_existing: bool = True,
    ) -> Path:
        if not image_bytes:
            raise ValueError("画像データが空です。")
        suffix = self._safe_suffix(filename, content_type, self._IMAGE_SUFFIXES, ".png")
        return self._save_member_temp_file(
            group_id,
            member_id,
            image_bytes,
            directory="images/previews",
            prefix="preview",
            suffix=suffix,
            replace_existing=replace_existing,
        )

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
        deleted = await self._repo.delete(group_id)
        if deleted:
            self._delete_group_files(group_id)
        return deleted

    async def delete_session(self, session_id: str) -> bool:
        return await self._repo.delete_session(session_id)

    async def _get_group_member(
        self,
        group_id: str,
        member_id: str,
    ) -> tuple[GroupChatRecord | None, GroupMember | None]:
        group = await self._repo.get(group_id)
        if group is None:
            return None, None
        member = next((item for item in group.members if item.id == member_id), None)
        return group, member

    def _save_member_temp_file(
        self,
        group_id: str,
        member_id: str,
        data: bytes,
        *,
        directory: str,
        prefix: str,
        suffix: str,
        replace_existing: bool,
    ) -> Path:
        if not data:
            raise ValueError("保存するデータが空です。")

        member_root = self._member_media_root(group_id, member_id)
        target_dir = (member_root / directory).resolve()
        if not target_dir.is_relative_to(member_root):
            raise ValueError("保存先が不正です。")

        target_dir.mkdir(parents=True, exist_ok=True)
        if replace_existing:
            for old_file in target_dir.glob(f"{prefix}-*"):
                if old_file.is_file():
                    old_file.unlink(missing_ok=True)

        target = target_dir / f"{prefix}-{uuid.uuid4().hex}{suffix}"
        target.write_bytes(data)
        return target

    def _member_media_root(self, group_id: str, member_id: str) -> Path:
        return (self._groups_dir / group_id / "members" / member_id).resolve()

    def _delete_group_files(self, group_id: str) -> None:
        root = self._groups_dir.resolve()
        target = (self._groups_dir / group_id).resolve()
        if target.is_relative_to(root):
            shutil.rmtree(target, ignore_errors=True)

    def _delete_member_media_file(self, group_id: str, member_id: str, relative_path: str) -> None:
        path = self.media_path(relative_path)
        if path is None:
            return
        member_root = self._member_media_root(group_id, member_id)
        if path.resolve().is_relative_to(member_root):
            path.unlink(missing_ok=True)

    def _delete_media_file(self, relative_path: str) -> None:
        path = self.media_path(relative_path)
        if path is not None:
            path.unlink(missing_ok=True)

    @staticmethod
    def _clamp_rect(rect: FaceRect) -> FaceRect:
        x = min(max(float(rect.x), 0.0), 1.0)
        y = min(max(float(rect.y), 0.0), 1.0)
        width = min(max(float(rect.width), 0.0), 1.0 - x)
        height = min(max(float(rect.height), 0.0), 1.0 - y)
        return FaceRect(x=x, y=y, width=width, height=height)

    @staticmethod
    def _safe_suffix(
        filename: str,
        content_type: str,
        allowed: set[str],
        fallback: str,
    ) -> str:
        suffix = Path(filename or "").suffix.lower()
        if suffix in allowed:
            return suffix
        guessed = (mimetypes.guess_extension(content_type) or "").lower()
        if guessed == ".jpe":
            guessed = ".jpg"
        if guessed in allowed:
            return guessed
        return fallback
