"""
ユーザーペルソナ管理サービス。

ユーザーペルソナの CRUD と、ユーザー側エンティティの
画像・音声・TTS 一時ファイル保存を提供する。
"""

from __future__ import annotations

import mimetypes
import shutil
import uuid
from pathlib import Path
from typing import Any

from ..core.chat.schemas import UserPersona
from ..core.character.schemas import (
    CharacterImageAsset,
    CharacterTTSSettings,
    CharacterVoiceAsset,
    FaceRect,
)
from ..core.tts.schemas import TTSConfig
from ..storage.api_config_store import ApiConfigStore


class UserPersonaService:
    _IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
    _VOICE_SUFFIXES = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav", ".webm"}

    def __init__(self, store: ApiConfigStore, data_dir: Path | None = None) -> None:
        self._store = store
        self._data_dir = data_dir or Path("data")
        self._user_personas_dir = self._data_dir / "user_personas"

    # ─── ユーザーペルソナ ───

    def get_user_personas(self) -> list[UserPersona]:
        return self._store.get_user_personas()

    def get_user_persona(self, persona_id: str) -> UserPersona | None:
        return self._store.get_user_persona(persona_id)

    def create_user_persona(self, persona: UserPersona) -> UserPersona:
        if not persona.id:
            persona = persona.model_copy(update={"id": self._store.new_id()})
        self._store.upsert_user_persona(persona)
        self._store.save()
        return persona

    def update_user_persona(self, persona: UserPersona) -> None:
        self._store.upsert_user_persona(persona)
        self._store.save()

    def delete_user_persona(self, persona_id: str) -> None:
        self._store.delete_user_persona(persona_id)
        self._store.save()
        self._delete_user_persona_files(persona_id)

    def reorder_user_personas(self, ordered_ids: list[str]) -> None:
        self._store.reorder_user_personas(ordered_ids)
        self._store.save()

    def media_path(self, relative_path: str) -> Path | None:
        if not relative_path:
            return None
        path = (self._data_dir / relative_path).resolve()
        data_root = self._data_dir.resolve()
        if not path.is_relative_to(data_root) or not path.is_file():
            return None
        return path

    async def save_user_persona_image(self, persona_id: str, upload: Any) -> UserPersona:
        persona = self._require_user_persona(persona_id)
        filename = getattr(upload, "name", "") or ""
        content_type = getattr(upload, "content_type", "") or ""
        if content_type and not content_type.startswith("image/"):
            raise ValueError("画像ファイルを選択してください。")
        if not content_type and Path(filename).suffix.lower() not in self._IMAGE_SUFFIXES:
            raise ValueError("画像ファイルを選択してください。")

        asset_id = uuid.uuid4().hex
        suffix = self._safe_suffix(filename, content_type, self._IMAGE_SUFFIXES, ".png")
        relative_path = Path("user_personas") / persona_id / "images" / f"{asset_id}{suffix}"
        target = self._data_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        await upload.save(target)

        old_paths = [image.path for image in persona.media.images]
        image = CharacterImageAsset(
            id=asset_id,
            path=relative_path.as_posix(),
            original_name=filename,
            content_type=content_type,
        )
        persona.media.images = [image]
        persona.media.primary_image_id = image.id
        try:
            self.update_user_persona(persona)
        except Exception:
            self._delete_media_file(image.path)
            raise
        for old_path in old_paths:
            self._delete_media_file(old_path)
        return persona

    async def save_user_persona_image_bytes(
        self,
        persona_id: str,
        image_bytes: bytes,
        *,
        filename: str = "generated-image.png",
        content_type: str = "image/png",
        width: int = 0,
        height: int = 0,
    ) -> UserPersona:
        if not image_bytes:
            raise ValueError("画像データが空です。")
        if content_type and not content_type.startswith("image/"):
            raise ValueError("画像データを指定してください。")

        persona = self._require_user_persona(persona_id)
        asset_id = uuid.uuid4().hex
        suffix = self._safe_suffix(filename, content_type, self._IMAGE_SUFFIXES, ".png")
        relative_path = Path("user_personas") / persona_id / "images" / f"{asset_id}{suffix}"
        target = self._data_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(image_bytes)

        old_paths = [image.path for image in persona.media.images]
        image = CharacterImageAsset(
            id=asset_id,
            path=relative_path.as_posix(),
            original_name=filename,
            content_type=content_type,
            width=max(0, int(width or 0)),
            height=max(0, int(height or 0)),
        )
        persona.media.images = [image]
        persona.media.primary_image_id = image.id
        try:
            self.update_user_persona(persona)
        except Exception:
            self._delete_media_file(image.path)
            raise
        for old_path in old_paths:
            self._delete_media_file(old_path)
        return persona

    async def save_user_persona_voice(self, persona_id: str, upload: Any) -> UserPersona:
        persona = self._require_user_persona(persona_id)
        filename = getattr(upload, "name", "") or ""
        content_type = getattr(upload, "content_type", "") or ""
        if content_type and not content_type.startswith("audio/"):
            raise ValueError("音声ファイルを選択してください。")
        if not content_type and Path(filename).suffix.lower() not in self._VOICE_SUFFIXES:
            raise ValueError("音声ファイルを選択してください。")

        asset_id = uuid.uuid4().hex
        suffix = self._safe_suffix(filename, content_type, self._VOICE_SUFFIXES, ".wav")
        relative_path = Path("user_personas") / persona_id / "voices" / f"{asset_id}{suffix}"
        target = self._data_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        await upload.save(target)

        old_paths = [voice.path for voice in persona.media.voices]
        voice = CharacterVoiceAsset(
            id=asset_id,
            path=relative_path.as_posix(),
            original_name=filename,
            content_type=content_type,
        )
        persona.media.voices = [voice]
        persona.media.primary_voice_id = voice.id
        try:
            self.update_user_persona(persona)
        except Exception:
            self._delete_media_file(voice.path)
            raise
        for old_path in old_paths:
            self._delete_media_file(old_path)
        return persona

    async def save_user_persona_voice_bytes(
        self,
        persona_id: str,
        audio_bytes: bytes,
        *,
        filename: str = "voice-design.wav",
        content_type: str = "audio/wav",
    ) -> UserPersona:
        if not audio_bytes:
            raise ValueError("音声データが空です。")
        persona = self._require_user_persona(persona_id)
        asset_id = uuid.uuid4().hex
        suffix = self._safe_suffix(filename, content_type, self._VOICE_SUFFIXES, ".wav")
        relative_path = Path("user_personas") / persona_id / "voices" / f"{asset_id}{suffix}"
        target = self._data_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(audio_bytes)

        old_paths = [voice.path for voice in persona.media.voices]
        voice = CharacterVoiceAsset(
            id=asset_id,
            path=relative_path.as_posix(),
            original_name=filename,
            content_type=content_type,
        )
        persona.media.voices = [voice]
        persona.media.primary_voice_id = voice.id
        try:
            self.update_user_persona(persona)
        except Exception:
            self._delete_media_file(voice.path)
            raise
        for old_path in old_paths:
            self._delete_media_file(old_path)
        return persona

    def update_user_persona_face_rect(
        self,
        persona_id: str,
        rect: FaceRect,
        *,
        image_width: int = 0,
        image_height: int = 0,
    ) -> UserPersona:
        persona = self._require_user_persona(persona_id)
        image = persona.media.primary_image()
        if image is None:
            raise ValueError("顔範囲を設定する画像がありません。")

        image.face_rect = self._clamp_rect(rect)
        if image_width > 0:
            image.width = image_width
        if image_height > 0:
            image.height = image_height
        persona.media.primary_image_id = image.id
        self.update_user_persona(persona)
        return persona

    def update_user_persona_tts_settings(
        self,
        persona_id: str,
        settings: CharacterTTSSettings,
    ) -> UserPersona:
        persona = self._require_user_persona(persona_id)
        persona.media.tts = settings
        self.update_user_persona(persona)
        return persona

    def save_user_persona_tts_preview(
        self,
        persona_id: str,
        audio_bytes: bytes,
        *,
        replace_existing: bool = True,
    ) -> Path:
        return self._save_user_persona_temp_file(
            persona_id,
            audio_bytes,
            directory="tts",
            prefix="preview",
            suffix=".wav",
            replace_existing=replace_existing,
        )

    def save_user_persona_tts_playback(self, persona_id: str, audio_bytes: bytes) -> Path:
        return self._save_user_persona_temp_file(
            persona_id,
            audio_bytes,
            directory="tts",
            prefix="playback",
            suffix=".wav",
            replace_existing=True,
        )

    def save_narrator_tts_preview(
        self,
        audio_bytes: bytes,
        *,
        replace_existing: bool = True,
    ) -> Path:
        return self._save_narrator_temp_file(
            audio_bytes,
            prefix="preview",
            suffix=".wav",
            replace_existing=replace_existing,
        )

    def save_narrator_tts_playback(self, audio_bytes: bytes) -> Path:
        return self._save_narrator_temp_file(
            audio_bytes,
            prefix="playback",
            suffix=".wav",
            replace_existing=True,
        )

    async def save_narrator_voice_bytes(
        self,
        audio_bytes: bytes,
        *,
        filename: str = "narrator-voice-design.wav",
        content_type: str = "audio/wav",
    ) -> CharacterVoiceAsset:
        if not audio_bytes:
            raise ValueError("音声データが空です。")

        config = self.get_tts_config()
        old_path = config.narrator_voice.path if config.narrator_voice else ""
        asset_id = uuid.uuid4().hex
        suffix = self._safe_suffix(filename, content_type, self._VOICE_SUFFIXES, ".wav")
        relative_path = Path("narrator") / "voices" / f"{asset_id}{suffix}"
        target = self._data_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(audio_bytes)

        voice = CharacterVoiceAsset(
            id=asset_id,
            path=relative_path.as_posix(),
            original_name=filename,
            content_type=content_type,
        )
        config.narrator_voice = voice
        try:
            self.save_tts_config(config)
        except Exception:
            self._delete_media_file(voice.path)
            raise
        if old_path:
            self._delete_media_file(old_path)
        return voice

    def save_user_persona_image_preview(
        self,
        persona_id: str,
        image_bytes: bytes,
        *,
        filename: str = "generated-image.png",
        content_type: str = "image/png",
        replace_existing: bool = True,
    ) -> Path:
        if not image_bytes:
            raise ValueError("画像データが空です。")
        suffix = self._safe_suffix(filename, content_type, self._IMAGE_SUFFIXES, ".png")
        return self._save_user_persona_temp_file(
            persona_id,
            image_bytes,
            directory="images/previews",
            prefix="preview",
            suffix=suffix,
            replace_existing=replace_existing,
        )

    def get_tts_config(self) -> TTSConfig:
        return self._store.get_tts_config()

    def save_tts_config(self, config: TTSConfig) -> None:
        self._store.save_tts_config(config)
        self._store.save()

    def _require_user_persona(self, persona_id: str) -> UserPersona:
        persona = self.get_user_persona(persona_id)
        if persona is None:
            raise ValueError("ユーザーペルソナが見つかりません。")
        return persona

    def _save_user_persona_temp_file(
        self,
        persona_id: str,
        data: bytes,
        *,
        directory: str,
        prefix: str,
        suffix: str,
        replace_existing: bool,
    ) -> Path:
        if not data:
            raise ValueError("保存するデータが空です。")

        temp_dir = (self._user_personas_dir / persona_id / directory).resolve()
        persona_root = (self._user_personas_dir / persona_id).resolve()
        if not temp_dir.is_relative_to(persona_root):
            raise ValueError("保存先が不正です。")

        temp_dir.mkdir(parents=True, exist_ok=True)
        if replace_existing:
            for old_file in temp_dir.glob(f"{prefix}-*"):
                self._delete_file_if_possible(old_file)

        path = temp_dir / f"{prefix}-{uuid.uuid4().hex}{suffix}"
        path.write_bytes(data)
        return path

    def _save_narrator_temp_file(
        self,
        data: bytes,
        *,
        prefix: str,
        suffix: str,
        replace_existing: bool,
    ) -> Path:
        if not data:
            raise ValueError("保存するデータが空です。")

        temp_dir = (self._data_dir / "narrator" / "tts").resolve()
        data_root = self._data_dir.resolve()
        if not temp_dir.is_relative_to(data_root):
            raise ValueError("保存先が不正です。")

        temp_dir.mkdir(parents=True, exist_ok=True)
        if replace_existing:
            for old_file in temp_dir.glob(f"{prefix}-*"):
                self._delete_file_if_possible(old_file)

        path = temp_dir / f"{prefix}-{uuid.uuid4().hex}{suffix}"
        path.write_bytes(data)
        return path

    def _delete_user_persona_files(self, persona_id: str) -> None:
        root = self._user_personas_dir.resolve()
        target = (self._user_personas_dir / persona_id).resolve()
        if target.is_relative_to(root):
            shutil.rmtree(target, ignore_errors=True)

    def _delete_media_file(self, relative_path: str) -> None:
        path = self.media_path(relative_path)
        if path is not None:
            self._delete_file_if_possible(path)

    @staticmethod
    def _delete_file_if_possible(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

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
