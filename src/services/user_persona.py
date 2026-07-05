"""
ユーザーペルソナ管理サービス。

ユーザーペルソナの CRUD と、ユーザー側エンティティの
画像・音声・TTS 一時ファイル保存を提供する。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.character.schemas import (
    CharacterTTSSettings,
    CharacterVoiceAsset,
    FaceRect,
)
from ..core.chat.schemas import UserPersona
from ..core.tts.schemas import TTSConfig
from ..storage.api_config_store import ApiConfigStore
from .media import MediaFileService, MediaOwner, VoiceAssetOwner


class UserPersonaService:
    _IMAGE_SUFFIXES = MediaFileService.IMAGE_SUFFIXES
    _VOICE_SUFFIXES = MediaFileService.VOICE_SUFFIXES

    def __init__(self, store: ApiConfigStore, data_dir: Path | None = None) -> None:
        self._store = store
        self._data_dir = data_dir or Path("data")
        self._media_files = MediaFileService(self._data_dir)

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
        return self._media_files.media_path(relative_path)

    async def save_user_persona_image(self, persona_id: str, upload: Any) -> UserPersona:
        persona = self._require_user_persona(persona_id)
        return await self._media_files.save_image_upload(
            self._media_owner(persona_id, persona),
            upload,
        )

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
        self._media_files.validate_image_bytes(image_bytes, content_type)
        persona = self._require_user_persona(persona_id)
        return await self._media_files.save_image_bytes(
            self._media_owner(persona_id, persona),
            image_bytes,
            filename=filename,
            content_type=content_type,
            width=width,
            height=height,
        )

    async def save_user_persona_voice(self, persona_id: str, upload: Any) -> UserPersona:
        persona = self._require_user_persona(persona_id)
        return await self._media_files.save_voice_upload(
            self._media_owner(persona_id, persona),
            upload,
        )

    async def save_user_persona_voice_bytes(
        self,
        persona_id: str,
        audio_bytes: bytes,
        *,
        filename: str = "voice-design.wav",
        content_type: str = "audio/wav",
    ) -> UserPersona:
        self._media_files.validate_non_empty(audio_bytes, "音声データが空です。")
        persona = self._require_user_persona(persona_id)
        return await self._media_files.save_voice_bytes(
            self._media_owner(persona_id, persona),
            audio_bytes,
            filename=filename,
            content_type=content_type,
        )

    def update_user_persona_face_rect(
        self,
        persona_id: str,
        rect: FaceRect,
        *,
        image_width: int = 0,
        image_height: int = 0,
    ) -> UserPersona:
        persona = self._require_user_persona(persona_id)
        return self._media_files.update_primary_image_rect_sync(
            self._media_owner(persona_id, persona),
            rect,
            rect_attribute="face_rect",
            missing_image_message="顔範囲を設定する画像がありません。",
            image_width=image_width,
            image_height=image_height,
        )

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
        return self._media_files.save_tts_preview(
            self._user_persona_media_root(persona_id),
            audio_bytes,
            replace_existing=replace_existing,
            ignore_delete_errors=True,
        )

    def save_user_persona_tts_playback(self, persona_id: str, audio_bytes: bytes) -> Path:
        return self._media_files.save_tts_playback(
            self._user_persona_media_root(persona_id),
            audio_bytes,
            ignore_delete_errors=True,
        )

    def save_narrator_tts_preview(
        self,
        audio_bytes: bytes,
        *,
        replace_existing: bool = True,
    ) -> Path:
        return self._media_files.save_tts_preview(
            self._narrator_media_root(),
            audio_bytes,
            replace_existing=replace_existing,
            ignore_delete_errors=True,
        )

    def save_narrator_tts_playback(self, audio_bytes: bytes) -> Path:
        return self._media_files.save_tts_playback(
            self._narrator_media_root(),
            audio_bytes,
            ignore_delete_errors=True,
        )

    async def save_narrator_voice_bytes(
        self,
        audio_bytes: bytes,
        *,
        filename: str = "narrator-voice-design.wav",
        content_type: str = "audio/wav",
    ) -> CharacterVoiceAsset:
        self._media_files.validate_non_empty(audio_bytes, "音声データが空です。")
        config = self.get_tts_config()
        return await self._media_files.save_voice_asset_bytes(
            VoiceAssetOwner(
                relative_root=self._narrator_media_root(),
                current_path=config.narrator_voice.path if config.narrator_voice else "",
                save=lambda voice: self._save_narrator_voice(config, voice),
                delete_new_file=self._delete_media_file,
                delete_old_file=self._delete_media_file,
            ),
            audio_bytes,
            filename=filename,
            content_type=content_type,
        )

    def save_user_persona_image_preview(
        self,
        persona_id: str,
        image_bytes: bytes,
        *,
        filename: str = "generated-image.png",
        content_type: str = "image/png",
        replace_existing: bool = True,
    ) -> Path:
        return self._media_files.save_image_preview(
            self._user_persona_media_root(persona_id),
            image_bytes,
            filename=filename,
            content_type=content_type,
            replace_existing=replace_existing,
            ignore_delete_errors=True,
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

    def _media_owner(self, persona_id: str, persona: UserPersona) -> MediaOwner[UserPersona]:
        return MediaOwner(
            relative_root=self._user_persona_media_root(persona_id),
            media=persona.media,
            save=lambda: self._save_user_persona_media(persona),
            delete_new_file=self._delete_media_file,
            delete_old_file=self._delete_media_file,
        )

    def _save_user_persona_media(self, persona: UserPersona) -> UserPersona:
        self.update_user_persona(persona)
        return persona

    def _save_narrator_voice(
        self,
        config: TTSConfig,
        voice: CharacterVoiceAsset,
    ) -> CharacterVoiceAsset:
        config.narrator_voice = voice
        self.save_tts_config(config)
        return voice

    @staticmethod
    def _user_persona_media_root(persona_id: str) -> Path:
        return Path("user_personas") / persona_id

    @staticmethod
    def _narrator_media_root() -> Path:
        return Path("narrator")

    def _delete_user_persona_files(self, persona_id: str) -> None:
        self._media_files.delete_owner_files(self._user_persona_media_root(persona_id))

    def _delete_media_file(self, relative_path: str) -> None:
        self._media_files.delete_media_file(relative_path, ignore_errors=True)
