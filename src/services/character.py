"""
キャラクター管理サービス。

キャラクターシートの CRUD 操作と検索を提供する。
"""

from __future__ import annotations

import mimetypes
import shutil
import uuid
from pathlib import Path
from typing import Any

from ..core.character.schemas import (
    CharacterImageAsset,
    CharacterSheet,
    CharacterTTSSettings,
    CharacterVoiceAsset,
    FaceRect,
)
from ..storage.character_repository import CharacterRepository


class CharacterService:
    _IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
    _VOICE_SUFFIXES = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav", ".webm"}

    def __init__(self, repository: CharacterRepository, data_dir: Path | None = None) -> None:
        self._repo = repository
        self._data_dir = data_dir or Path("data")
        self._characters_dir = self._data_dir / "characters"

    async def save(self, sheet: CharacterSheet) -> CharacterSheet:
        return await self._repo.save(sheet)

    async def get(self, character_id: str) -> CharacterSheet | None:
        return await self._repo.get(character_id)

    async def list_all(
        self, search: str = "", tag: str = "", favorites_only: bool = False
    ) -> list[CharacterSheet]:
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
        if not relative_path:
            return None
        path = (self._data_dir / relative_path).resolve()
        data_root = self._data_dir.resolve()
        if not path.is_relative_to(data_root) or not path.is_file():
            return None
        return path

    async def save_image(self, character_id: str, upload: Any) -> CharacterSheet:
        sheet = await self._require_sheet(character_id)
        filename = getattr(upload, "name", "") or ""
        content_type = getattr(upload, "content_type", "") or ""
        if content_type and not content_type.startswith("image/"):
            raise ValueError("画像ファイルを選択してください。")
        if not content_type and Path(filename).suffix.lower() not in self._IMAGE_SUFFIXES:
            raise ValueError("画像ファイルを選択してください。")

        asset_id = uuid.uuid4().hex
        suffix = self._safe_suffix(filename, content_type, self._IMAGE_SUFFIXES, ".png")
        relative_path = Path("characters") / character_id / "images" / f"{asset_id}{suffix}"
        target = self._data_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        await upload.save(target)

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
            saved = await self.save(sheet)
        except Exception:
            self._delete_media_file(image.path)
            raise
        for old_path in old_paths:
            self._delete_media_file(old_path)
        return saved

    async def save_voice(self, character_id: str, upload: Any) -> CharacterSheet:
        sheet = await self._require_sheet(character_id)
        filename = getattr(upload, "name", "") or ""
        content_type = getattr(upload, "content_type", "") or ""
        if content_type and not content_type.startswith("audio/"):
            raise ValueError("音声ファイルを選択してください。")
        if not content_type and Path(filename).suffix.lower() not in self._VOICE_SUFFIXES:
            raise ValueError("音声ファイルを選択してください。")

        asset_id = uuid.uuid4().hex
        suffix = self._safe_suffix(filename, content_type, self._VOICE_SUFFIXES, ".wav")
        relative_path = Path("characters") / character_id / "voices" / f"{asset_id}{suffix}"
        target = self._data_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        await upload.save(target)

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
            saved = await self.save(sheet)
        except Exception:
            self._delete_media_file(voice.path)
            raise
        for old_path in old_paths:
            self._delete_media_file(old_path)
        return saved

    async def update_tts_settings(
        self,
        character_id: str,
        settings: CharacterTTSSettings,
    ) -> CharacterSheet:
        sheet = await self._require_sheet(character_id)
        sheet.media.tts = settings
        return await self.save(sheet)

    def save_tts_preview(self, character_id: str, audio_bytes: bytes) -> Path:
        if not audio_bytes:
            raise ValueError("音声データが空です。")

        preview_dir = (self._characters_dir / character_id / "tts").resolve()
        character_root = (self._characters_dir / character_id).resolve()
        if not preview_dir.is_relative_to(character_root):
            raise ValueError("保存先が不正です。")

        preview_dir.mkdir(parents=True, exist_ok=True)
        for old_file in preview_dir.glob("preview-*.wav"):
            old_file.unlink(missing_ok=True)

        preview_path = preview_dir / f"preview-{uuid.uuid4().hex}.wav"
        preview_path.write_bytes(audio_bytes)
        return preview_path

    def save_tts_playback(self, character_id: str, audio_bytes: bytes) -> Path:
        if not audio_bytes:
            raise ValueError("音声データが空です。")

        playback_dir = (self._characters_dir / character_id / "tts").resolve()
        character_root = (self._characters_dir / character_id).resolve()
        if not playback_dir.is_relative_to(character_root):
            raise ValueError("保存先が不正です。")

        playback_dir.mkdir(parents=True, exist_ok=True)
        for old_file in playback_dir.glob("playback-*.wav"):
            old_file.unlink(missing_ok=True)

        playback_path = playback_dir / f"playback-{uuid.uuid4().hex}.wav"
        playback_path.write_bytes(audio_bytes)
        return playback_path

    async def update_face_rect(
        self,
        character_id: str,
        rect: FaceRect,
        *,
        image_width: int = 0,
        image_height: int = 0,
    ) -> CharacterSheet:
        sheet = await self._require_sheet(character_id)
        image = sheet.media.primary_image()
        if image is None:
            raise ValueError("顔範囲を設定する画像がありません。")

        image.face_rect = self._clamp_rect(rect)
        if image_width > 0:
            image.width = image_width
        if image_height > 0:
            image.height = image_height
        sheet.media.primary_image_id = image.id
        return await self.save(sheet)

    async def update_bust_rect(
        self,
        character_id: str,
        rect: FaceRect,
        *,
        image_width: int = 0,
        image_height: int = 0,
    ) -> CharacterSheet:
        sheet = await self._require_sheet(character_id)
        image = sheet.media.primary_image()
        if image is None:
            raise ValueError("バストショット範囲を設定する画像がありません。")

        image.bust_rect = self._clamp_rect(rect)
        if image_width > 0:
            image.width = image_width
        if image_height > 0:
            image.height = image_height
        sheet.media.primary_image_id = image.id
        return await self.save(sheet)

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

    def _delete_character_files(self, character_id: str) -> None:
        root = self._characters_dir.resolve()
        target = (self._characters_dir / character_id).resolve()
        if target.is_relative_to(root):
            shutil.rmtree(target, ignore_errors=True)

    def _delete_media_file(self, relative_path: str) -> None:
        path = self.media_path(relative_path)
        if path is not None:
            path.unlink(missing_ok=True)

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

    @staticmethod
    def _clamp_rect(rect: FaceRect) -> FaceRect:
        width = min(max(rect.width, 0.01), 1.0)
        height = min(max(rect.height, 0.01), 1.0)
        x = min(max(rect.x, 0.0), 1.0 - width)
        y = min(max(rect.y, 0.0), 1.0 - height)
        return FaceRect(x=x, y=y, width=width, height=height)
