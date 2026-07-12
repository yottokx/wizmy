"""
キャラクター管理サービス。

キャラクターシートの CRUD 操作と検索を提供する。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.character.schemas import (
    CharacterSheet,
    CharacterTTSSettings,
    FaceRect,
)
from ..storage.character_repository import CharacterRepository
from .media import MediaFileService, MediaOwner


class CharacterService:
    _IMAGE_SUFFIXES = MediaFileService.IMAGE_SUFFIXES
    _VOICE_SUFFIXES = MediaFileService.VOICE_SUFFIXES

    def __init__(self, repository: CharacterRepository, data_dir: Path | None = None) -> None:
        self._repo = repository
        self._data_dir = data_dir or Path("data")
        self._media_files = MediaFileService(self._data_dir)

    async def save(self, sheet: CharacterSheet) -> CharacterSheet:
        return await self._repo.save(sheet)

    async def get(self, character_id: str) -> CharacterSheet | None:
        return await self._repo.get(character_id)

    async def list_all(self, search: str = "", tag: str = "", favorites_only: bool = False) -> list[CharacterSheet]:
        return await self._repo.list_all(
            search=search,
            tag=tag,
            favorites_only=favorites_only,
        )

    async def set_favorite(self, character_id: str, is_favorite: bool) -> CharacterSheet:
        sheet = await self._require_sheet(character_id)
        sheet.is_favorite = is_favorite
        return await self.save(sheet)

    async def delete(self, character_id: str) -> bool:
        deleted = await self._repo.delete(character_id)
        if deleted:
            self._delete_character_files(character_id)
        return deleted

    def new_id(self) -> str:
        return self._repo.new_id()

    def media_path(self, relative_path: str) -> Path | None:
        return self._media_files.media_path(relative_path)

    async def save_image(self, character_id: str, upload: Any) -> CharacterSheet:
        sheet = await self._require_sheet(character_id)
        return await self._media_files.save_image_upload(
            self._media_owner(character_id, sheet),
            upload,
        )

    async def save_image_bytes(
        self,
        character_id: str,
        image_bytes: bytes,
        *,
        filename: str = "generated-image.png",
        content_type: str = "image/png",
        width: int = 0,
        height: int = 0,
    ) -> CharacterSheet:
        self._media_files.validate_image_bytes(image_bytes, content_type)
        sheet = await self._require_sheet(character_id)
        return await self._media_files.save_image_bytes(
            self._media_owner(character_id, sheet),
            image_bytes,
            filename=filename,
            content_type=content_type,
            width=width,
            height=height,
        )

    async def save_voice(self, character_id: str, upload: Any) -> CharacterSheet:
        sheet = await self._require_sheet(character_id)
        return await self._media_files.save_voice_upload(
            self._media_owner(character_id, sheet),
            upload,
        )

    async def save_voice_bytes(
        self,
        character_id: str,
        audio_bytes: bytes,
        *,
        filename: str = "voice-design.wav",
        content_type: str = "audio/wav",
    ) -> CharacterSheet:
        self._media_files.validate_non_empty(audio_bytes, "音声データが空です。")
        sheet = await self._require_sheet(character_id)
        return await self._media_files.save_voice_bytes(
            self._media_owner(character_id, sheet),
            audio_bytes,
            filename=filename,
            content_type=content_type,
        )

    async def update_tts_settings(
        self,
        character_id: str,
        settings: CharacterTTSSettings,
    ) -> CharacterSheet:
        sheet = await self._require_sheet(character_id)
        sheet.media.tts = settings
        return await self.save(sheet)

    def save_tts_preview(
        self,
        character_id: str,
        audio_bytes: bytes,
        *,
        replace_existing: bool = True,
        prefix: str = "preview",
    ) -> Path:
        return self._media_files.save_tts_preview(
            self._character_media_root(character_id),
            audio_bytes,
            replace_existing=replace_existing,
            empty_error_message="音声データが空です。",
            replace_glob=f"{prefix}-*.wav",
            prefix=prefix,
        )

    def save_image_preview(
        self,
        character_id: str,
        image_bytes: bytes,
        *,
        filename: str = "generated-image.png",
        content_type: str = "image/png",
        replace_existing: bool = True,
    ) -> Path:
        return self._media_files.save_image_preview(
            self._character_media_root(character_id),
            image_bytes,
            filename=filename,
            content_type=content_type,
            replace_existing=replace_existing,
        )

    def save_tts_playback(self, character_id: str, audio_bytes: bytes) -> Path:
        return self._media_files.save_tts_playback(
            self._character_media_root(character_id),
            audio_bytes,
            empty_error_message="音声データが空です。",
            replace_glob="playback-*.wav",
        )

    async def update_face_rect(
        self,
        character_id: str,
        rect: FaceRect,
        *,
        image_width: int = 0,
        image_height: int = 0,
    ) -> CharacterSheet:
        sheet = await self._require_sheet(character_id)
        return await self._media_files.update_primary_image_rect(
            self._media_owner(character_id, sheet),
            rect,
            rect_attribute="face_rect",
            missing_image_message="顔範囲を設定する画像がありません。",
            image_width=image_width,
            image_height=image_height,
        )

    async def update_bust_rect(
        self,
        character_id: str,
        rect: FaceRect,
        *,
        image_width: int = 0,
        image_height: int = 0,
    ) -> CharacterSheet:
        sheet = await self._require_sheet(character_id)
        return await self._media_files.update_primary_image_rect(
            self._media_owner(character_id, sheet),
            rect,
            rect_attribute="bust_rect",
            missing_image_message="バストショット範囲を設定する画像がありません。",
            image_width=image_width,
            image_height=image_height,
        )

    async def get_all_tags(self) -> list[str]:
        """全キャラクターに使用されているタグの一覧を返す（重複なし）。"""
        sheets = await self._repo.list_all()
        tags: set[str] = set()
        for sheet in sheets:
            tags.update(sheet.tags)
        return sorted(tags)

    async def _require_sheet(self, character_id: str) -> CharacterSheet:
        sheet = await self.get(character_id)
        if sheet is None:
            raise ValueError("キャラクターが見つかりません。")
        return sheet

    def _media_owner(self, character_id: str, sheet: CharacterSheet) -> MediaOwner[CharacterSheet]:
        return MediaOwner(
            relative_root=self._character_media_root(character_id),
            media=sheet.media,
            save=lambda: self.save(sheet),
        )

    @staticmethod
    def _character_media_root(character_id: str) -> Path:
        return Path("characters") / character_id

    def _delete_character_files(self, character_id: str) -> None:
        self._media_files.delete_owner_files(self._character_media_root(character_id))
