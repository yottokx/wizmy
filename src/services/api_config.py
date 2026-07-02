"""
API設定サービス。

エンドポイント・LLMプロファイル・キャラ生成プリセット・KeyVault の
CRUD操作と検証を提供する。
"""

from __future__ import annotations

import mimetypes
import shutil
import uuid
from pathlib import Path
from typing import Any

import httpx

from ..core.chat.schemas import ChatMode, UserPersona
from ..core.character.schemas import (
    CharacterImageAsset,
    CharacterTTSSettings,
    CharacterVoiceAsset,
    FaceRect,
)
from ..core.gen_server.schemas import (
    GenServerConfig,
    GenServerEndpoint,
    gen_server_capabilities_url,
    gen_server_health_url,
    gen_server_models_url,
)
from ..core.image_generation.schemas import ImageGenerationConfig, ImageGenerationProfile
from ..core.llm.factory import fetch_models, get_parameter_capabilities, validate_connection
from ..core.llm.schemas import (
    AppLLMConfig,
    Endpoint,
    GenerationPreset,
    LLMParameterCapabilities,
    LLMProfile,
)
from ..core.tts.schemas import (
    TTS_PROVIDER_IRODORI_GRADIO,
    TTS_PROVIDER_IRODORI_SERVER,
    TTSConfig,
    TTSProvider,
    TTSEndpoint,
)
from ..storage.api_config_store import ApiConfigStore


class ApiConfigService:
    _IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
    _VOICE_SUFFIXES = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav", ".webm"}

    def __init__(self, store: ApiConfigStore, data_dir: Path | None = None) -> None:
        self._store = store
        self._data_dir = data_dir or Path("data")
        self._user_personas_dir = self._data_dir / "user_personas"

    # ─── エンドポイント ───

    def get_endpoints(self) -> list[Endpoint]:
        return self._store.get_endpoints()

    def get_endpoint(self, endpoint_id: str) -> Endpoint | None:
        return self._store.get_endpoint(endpoint_id)

    def create_endpoint(self, name: str, ep_type: str, base_url: str) -> Endpoint:
        ep = Endpoint(
            id=self._store.new_id(),
            name=name,
            type=ep_type,  # type: ignore[arg-type]  # 理由: 既存UIから渡る文字列を保存時のモデル検証に委ねるため。
            base_url=base_url,
        )
        self._store.upsert_endpoint(ep)
        self._store.save()
        return ep

    def update_endpoint(self, endpoint: Endpoint) -> None:
        self._store.upsert_endpoint(endpoint)
        self._store.save()

    def delete_endpoint(self, endpoint_id: str) -> None:
        self._store.delete_endpoint(endpoint_id)
        self._store.save()

    def reorder_endpoints(self, ordered_ids: list[str]) -> None:
        self._store.reorder_endpoints(ordered_ids)
        self._store.save()

    async def test_connection(self, endpoint_id: str, vault_password: str | None = None) -> bool:
        ep = self._store.get_endpoint(endpoint_id)
        if ep is None:
            return False
        api_key = self._get_api_key(endpoint_id, vault_password)
        if self.is_api_key_locked(endpoint_id, api_key):
            return False
        return await validate_connection(ep, api_key)

    async def fetch_endpoint_models(
        self, endpoint_id: str, vault_password: str | None = None
    ) -> list[str]:
        ep = self._store.get_endpoint(endpoint_id)
        if ep is None:
            return []
        api_key = self._get_api_key(endpoint_id, vault_password)
        if self.is_api_key_locked(endpoint_id, api_key):
            return []
        return await fetch_models(ep, api_key)

    # ─── LLMプロファイル ───

    def get_llm_profiles(self) -> list[LLMProfile]:
        return self._store.get_llm_profiles()

    def get_llm_profile(self, profile_id: str) -> LLMProfile | None:
        return self._store.get_llm_profile(profile_id)

    def create_llm_profile(
        self,
        name: str,
        endpoint_id: str,
        model_id: str,
        temperature: float = 0.8,
        reasoning_enabled: bool = False,
        max_tokens: int | None = None,
    ) -> LLMProfile:
        profile = LLMProfile(
            id=self._store.new_id(),
            name=name,
            endpoint_id=endpoint_id,
            model_id=model_id,
            temperature=temperature,
            reasoning_enabled=reasoning_enabled,
            max_tokens=max_tokens,
        )
        self._store.upsert_llm_profile(profile)
        config = self._store.get_app_llm_config()
        if not config.generation_profile_id:
            config.generation_profile_id = profile.id
        if not config.chat_profile_id:
            config.chat_profile_id = profile.id
        self._store.save_app_llm_config(config)
        self._store.save()
        return profile

    def update_llm_profile(self, profile: LLMProfile) -> None:
        self._store.upsert_llm_profile(profile)
        self._store.save()

    def delete_llm_profile(self, profile_id: str) -> None:
        self._store.delete_llm_profile(profile_id)
        self._store.save()

    def move_llm_profile_up(self, profile_id: str) -> None:
        self._store.move_llm_profile(profile_id, -1)
        self._store.save()

    def move_llm_profile_down(self, profile_id: str) -> None:
        self._store.move_llm_profile(profile_id, 1)
        self._store.save()

    def reorder_llm_profiles(self, ordered_ids: list[str]) -> None:
        self._store.reorder_llm_profiles(ordered_ids)
        self._store.save()

    def is_api_key_set(self, endpoint_id: str, vault_pw: str | None) -> bool:
        """指定エンドポイントのAPIキーが設定済みかを返す。"""
        if not vault_pw or not self._store.vault.is_setup():
            return False
        keys = self._store.vault.load_keys(vault_pw)
        return endpoint_id in keys

    def is_api_key_configured(self, endpoint_id: str) -> bool:
        """指定エンドポイントに暗号化済みAPIキーが保存されているかを返す。"""
        return self._store.vault.is_setup() and self._store.vault.has_key(endpoint_id)

    def is_api_key_locked(self, endpoint_id: str, api_key: str | None) -> bool:
        """保存済みAPIキーがあるのに利用可能な復号済みキーがないかを返す。"""
        return self.is_api_key_configured(endpoint_id) and not api_key

    def duplicate_llm_profile(self, profile_id: str) -> LLMProfile | None:
        original = self._store.get_llm_profile(profile_id)
        if original is None:
            return None
        copy = original.model_copy(update={"id": self._store.new_id(), "name": f"{original.name} (コピー)"})
        self._store.upsert_llm_profile(copy)
        self._store.save()
        return copy

    # ─── キャラ生成プリセット ───

    def get_generation_presets(self) -> list[GenerationPreset]:
        return self._store.get_generation_presets()

    def get_generation_preset(self, preset_id: str) -> GenerationPreset | None:
        return self._store.get_generation_preset(preset_id)

    def create_generation_preset(self, preset: GenerationPreset) -> GenerationPreset:
        if not preset.id:
            preset = preset.model_copy(update={"id": self._store.new_id()})
        self._store.upsert_generation_preset(preset)
        self._store.save()
        return preset

    def update_generation_preset(self, preset: GenerationPreset) -> None:
        self._store.upsert_generation_preset(preset)
        self._store.save()

    def delete_generation_preset(self, preset_id: str) -> None:
        self._store.delete_generation_preset(preset_id)
        self._store.save()

    def reorder_generation_presets(self, ordered_ids: list[str]) -> None:
        self._store.reorder_generation_presets(ordered_ids)
        self._store.save()

    # ─── チャットモード ───

    def get_chat_modes(self) -> list[ChatMode]:
        return self._store.get_chat_modes()

    def get_chat_mode(self, mode_id: str) -> ChatMode | None:
        return self._store.get_chat_mode(mode_id)

    def create_chat_mode(self, mode: ChatMode) -> ChatMode:
        if not mode.id:
            mode = mode.model_copy(update={"id": self._store.new_id()})
        self._store.upsert_chat_mode(mode)
        self._store.save()
        return mode

    def update_chat_mode(self, mode: ChatMode) -> None:
        self._store.upsert_chat_mode(mode)
        self._store.save()

    def delete_chat_mode(self, mode_id: str) -> None:
        self._store.delete_chat_mode(mode_id)
        self._store.save()

    def reorder_chat_modes(self, ordered_ids: list[str]) -> None:
        self._store.reorder_chat_modes(ordered_ids)
        self._store.save()

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

    # ─── 生成選択肢 ───

    def get_option_lists(self) -> dict[str, list[str]]:
        return self._store.get_option_lists()

    def save_option_lists(self, lists: dict[str, list[str]]) -> None:
        self._store.save_option_lists(lists)

    # ─── アプリLLM設定 ───

    def get_app_llm_config(self) -> AppLLMConfig:
        return self._store.get_app_llm_config()

    def set_generation_profile(self, profile_id: str) -> None:
        config = self._store.get_app_llm_config()
        config.generation_profile_id = profile_id
        self._store.save_app_llm_config(config)
        self._store.save()

    def set_chat_profile(self, profile_id: str) -> None:
        config = self._store.get_app_llm_config()
        config.chat_profile_id = profile_id
        self._store.save_app_llm_config(config)
        self._store.save()

    def set_default_profiles(self, generation_profile_id: str, chat_profile_id: str) -> None:
        config = self._store.get_app_llm_config()
        config.generation_profile_id = generation_profile_id
        config.chat_profile_id = chat_profile_id
        self._store.save_app_llm_config(config)
        self._store.save()

    def get_llm_parameter_capabilities(self, endpoint_id: str) -> LLMParameterCapabilities:
        endpoint = self._store.get_endpoint(endpoint_id)
        return get_parameter_capabilities(endpoint)

    # ─── 画像生成プロファイル ───

    def get_image_generation_config(self) -> ImageGenerationConfig:
        return self._store.get_image_generation_config()

    def get_image_generation_profiles(self) -> list[ImageGenerationProfile]:
        return self._store.get_image_generation_profiles()

    def get_image_generation_profile(self, profile_id: str) -> ImageGenerationProfile | None:
        return self._store.get_image_generation_profile(profile_id)

    def get_default_image_generation_profile(self) -> ImageGenerationProfile | None:
        config = self._store.get_image_generation_config()
        if config.default_profile_id:
            return self._store.get_image_generation_profile(config.default_profile_id)
        return config.profiles[0] if config.profiles else None

    def create_image_generation_profile(self, profile: ImageGenerationProfile) -> ImageGenerationProfile:
        if not profile.id:
            profile = profile.model_copy(update={"id": self._store.new_id()})
        self._store.upsert_image_generation_profile(profile)
        self._store.save()
        return profile

    def update_image_generation_profile(self, profile: ImageGenerationProfile) -> None:
        self._store.upsert_image_generation_profile(profile)
        self._store.save()

    def duplicate_image_generation_profile(self, profile_id: str) -> ImageGenerationProfile | None:
        original = self._store.get_image_generation_profile(profile_id)
        if original is None:
            return None
        copy = original.model_copy(update={
            "id": self._store.new_id(),
            "name": f"{original.name} (コピー)",
        })
        self._store.upsert_image_generation_profile(copy)
        self._store.save()
        return copy

    def delete_image_generation_profile(self, profile_id: str) -> None:
        self._store.delete_image_generation_profile(profile_id)
        self._store.save()

    def reorder_image_generation_profiles(self, ordered_ids: list[str]) -> None:
        self._store.reorder_image_generation_profiles(ordered_ids)
        self._store.save()

    def set_default_image_generation_profile(self, profile_id: str) -> None:
        config = self._store.get_image_generation_config()
        if profile_id and not any(profile.id == profile_id for profile in config.profiles):
            return
        config.default_profile_id = profile_id
        self._store.save_image_generation_config(config)
        self._store.save()

    # ─── TTS設定 ───

    def get_tts_config(self) -> TTSConfig:
        return self._store.get_tts_config()

    def save_tts_config(self, config: TTSConfig) -> None:
        self._store.save_tts_config(config)
        self._store.save()

    def get_tts_endpoints(self) -> list[TTSEndpoint]:
        return self._store.get_tts_config().endpoints

    def get_tts_endpoint(self, endpoint_id: str) -> TTSEndpoint | None:
        return self._store.get_tts_endpoint(endpoint_id)

    def create_tts_endpoint(
        self,
        name: str,
        provider: TTSProvider,
        base_url: str,
    ) -> TTSEndpoint:
        endpoint = TTSEndpoint(
            id=self._store.new_id(),
            name=name,
            provider=provider,
            base_url=base_url,
        )
        self._store.upsert_tts_endpoint(endpoint)
        self._store.save()
        return endpoint

    def update_tts_endpoint(self, endpoint: TTSEndpoint) -> None:
        endpoint = TTSEndpoint(**endpoint.model_dump())
        self._store.upsert_tts_endpoint(endpoint)
        self._store.save()

    def delete_tts_endpoint(self, endpoint_id: str) -> None:
        self._store.delete_tts_endpoint(endpoint_id)
        self._store.save()

    def reorder_tts_endpoints(self, ordered_ids: list[str]) -> None:
        self._store.reorder_tts_endpoints(ordered_ids)
        self._store.save()

    def set_default_tts_endpoint(self, endpoint_id: str) -> None:
        config = self._store.get_tts_config()
        if endpoint_id and not any(ep.id == endpoint_id for ep in config.endpoints):
            return
        config.default_endpoint_id = endpoint_id
        self.save_tts_config(config)

    def set_irodori_gradio_url(self, url: str) -> TTSConfig:
        config = self._store.get_tts_config()
        endpoint = next(
            (ep for ep in config.endpoints if ep.provider == TTS_PROVIDER_IRODORI_GRADIO),
            None,
        )
        if endpoint is None:
            endpoint = TTSEndpoint(
                id=self._store.new_id(),
                name="Irodori-TTS Gradio",
                provider=TTS_PROVIDER_IRODORI_GRADIO,
                base_url=url,
            )
            config.endpoints.append(endpoint)
        else:
            endpoint = TTSEndpoint(**{**endpoint.model_dump(), "base_url": url})
            config.endpoints = [
                endpoint if current.id == endpoint.id else current for current in config.endpoints
            ]
        config.default_endpoint_id = endpoint.id
        self.save_tts_config(config)
        return config

    def set_irodori_tts_server_url(self, url: str) -> TTSConfig:
        config = self._store.get_tts_config()
        endpoint = next(
            (ep for ep in config.endpoints if ep.provider == TTS_PROVIDER_IRODORI_SERVER),
            None,
        )
        if endpoint is None:
            endpoint = TTSEndpoint(
                id=self._store.new_id(),
                name="Irodori-TTS-Server",
                provider=TTS_PROVIDER_IRODORI_SERVER,
                base_url=url,
            )
            config.endpoints.append(endpoint)
        else:
            endpoint = TTSEndpoint(**{**endpoint.model_dump(), "base_url": url})
            config.endpoints = [
                endpoint if current.id == endpoint.id else current for current in config.endpoints
            ]
        config.default_endpoint_id = endpoint.id
        self.save_tts_config(config)
        return config

    # ─── Wizmy-Gen-Server設定 ───

    def get_gen_server_config(self) -> GenServerConfig:
        return self._store.get_gen_server_config()

    def get_gen_server_endpoints(self) -> list[GenServerEndpoint]:
        return self._store.get_gen_server_config().endpoints

    def get_gen_server_endpoint(self, endpoint_id: str) -> GenServerEndpoint | None:
        return self._store.get_gen_server_endpoint(endpoint_id)

    def create_gen_server_endpoint(self, name: str, base_url: str) -> GenServerEndpoint:
        endpoint = GenServerEndpoint(
            id=self._store.new_id(),
            name=name,
            base_url=base_url,
        )
        self._store.upsert_gen_server_endpoint(endpoint)
        self._store.save()
        return endpoint

    def update_gen_server_endpoint(self, endpoint: GenServerEndpoint) -> None:
        endpoint = GenServerEndpoint(**endpoint.model_dump())
        self._store.upsert_gen_server_endpoint(endpoint)
        self._store.save()

    def delete_gen_server_endpoint(self, endpoint_id: str) -> None:
        self._store.delete_gen_server_endpoint(endpoint_id)
        self._store.save()

    def reorder_gen_server_endpoints(self, ordered_ids: list[str]) -> None:
        self._store.reorder_gen_server_endpoints(ordered_ids)
        self._store.save()

    def set_gen_server_mode_assignment(self, mode: str, endpoint_id: str) -> None:
        self._store.set_gen_server_mode_assignment(mode, endpoint_id)
        self._store.save()

    def set_gen_server_mode_defaults(self, mode: str, defaults: dict) -> None:
        self._store.set_gen_server_mode_defaults(mode, defaults)
        self._store.save()

    def set_gen_server_voice_chunking(self, *, enabled: bool, min_chars: int) -> None:
        self._store.set_gen_server_voice_chunking(enabled=enabled, min_chars=min_chars)
        self._store.save()

    async def fetch_gen_server_capabilities(self, endpoint_id: str) -> dict | None:
        endpoint = self._store.get_gen_server_endpoint(endpoint_id)
        if endpoint is None:
            return None

        async with httpx.AsyncClient(timeout=5.0) as client:
            health = await client.get(gen_server_health_url(endpoint.base_url))
            health.raise_for_status()
            capabilities = await client.get(gen_server_capabilities_url(endpoint.base_url))
            capabilities.raise_for_status()
            return capabilities.json()

    async def fetch_gen_server_models(self, endpoint_id: str, mode: str = "") -> list[dict]:
        endpoint = self._store.get_gen_server_endpoint(endpoint_id)
        if endpoint is None:
            return []

        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(gen_server_models_url(endpoint.base_url))
            response.raise_for_status()
            models = response.json().get("models", [])
            if not isinstance(models, list):
                return []
            if mode:
                models = [model for model in models if model.get("mode") == mode]
            return [model for model in models if isinstance(model, dict) and model.get("id")]

    # ─── KeyVault ───

    def is_vault_setup(self) -> bool:
        return self._store.vault.is_setup()

    def setup_vault(self, password: str, carry_keys: dict[str, str] | None = None) -> None:
        self._store.vault.setup(password, carry_keys)
        self._store.save()

    def verify_vault_password(self, password: str) -> bool:
        return self._store.vault.verify_password(password)

    def save_api_key(self, endpoint_id: str, api_key: str, password: str) -> None:
        self._store.vault.save_key(endpoint_id, api_key, password)
        self._store.save()

    def delete_api_key(self, endpoint_id: str) -> None:
        self._store.vault.delete_key(endpoint_id)
        self._store.save()

    def teardown_vault(self) -> None:
        self._store.vault.teardown()
        self._store.save()

    def get_api_key(self, endpoint_id: str, password: str | None) -> str | None:
        """指定エンドポイントのAPIキーをVaultから取得する。"""
        if not self._store.vault.is_setup() or not password:
            return None
        return self._store.vault.get_key(endpoint_id, password)

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

    def _get_api_key(self, endpoint_id: str, password: str | None) -> str | None:
        return self.get_api_key(endpoint_id, password)
