"""
キャラクターデータのスキーマ定義。

UIや永続化レイヤーに依存しない純粋なデータモデル。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Relationship(BaseModel):
    name: str
    description: str


class GenerationMeta(BaseModel):
    llm_profile_name: str = ""
    model_id: str = ""
    temperature: float | None = None
    reasoning_enabled: bool = False
    mode: str = "generate"
    tool_count: int = 0
    quality_status: str = ""
    quality_score: float = 0.0


class FaceRect(BaseModel):
    x: float = 0.0
    y: float = 0.0
    width: float = 1.0
    height: float = 1.0


class CharacterImageAsset(BaseModel):
    id: str = ""
    path: str = ""
    original_name: str = ""
    content_type: str = ""
    width: int = 0
    height: int = 0
    face_rect: FaceRect = Field(default_factory=FaceRect)
    bust_rect: FaceRect = Field(default_factory=FaceRect)
    created_at: datetime = Field(default_factory=datetime.now)


class CharacterVoiceAsset(BaseModel):
    id: str = ""
    path: str = ""
    original_name: str = ""
    content_type: str = ""
    created_at: datetime = Field(default_factory=datetime.now)


CharacterTTSApiType = Literal["default", "tts", "gen_server"]
CHARACTER_TTS_API_DEFAULT: CharacterTTSApiType = "default"
CHARACTER_TTS_API_TTS: CharacterTTSApiType = "tts"
CHARACTER_TTS_API_GEN_SERVER: CharacterTTSApiType = "gen_server"

CharacterGenServerTTSMode = Literal["voice_clone", "voice_design_v3"]
CHARACTER_GEN_SERVER_TTS_MODE_CLONE: CharacterGenServerTTSMode = "voice_clone"
CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3: CharacterGenServerTTSMode = "voice_design_v3"


class CharacterTTSSettings(BaseModel):
    api_type: CharacterTTSApiType = CHARACTER_TTS_API_DEFAULT
    endpoint_id: str = ""
    voice_id: str = ""
    gen_server_tts_mode: CharacterGenServerTTSMode = CHARACTER_GEN_SERVER_TTS_MODE_CLONE
    voice_caption: str = ""
    gen_server_params: dict[str, Any] = Field(default_factory=dict)


class CharacterMedia(BaseModel):
    images: list[CharacterImageAsset] = Field(default_factory=list)
    voices: list[CharacterVoiceAsset] = Field(default_factory=list)
    primary_image_id: str = ""
    primary_voice_id: str = ""
    tts: CharacterTTSSettings = Field(default_factory=CharacterTTSSettings)

    def primary_image(self) -> CharacterImageAsset | None:
        for image in self.images:
            if image.id == self.primary_image_id:
                return image
        return self.images[0] if self.images else None

    def primary_voice(self) -> CharacterVoiceAsset | None:
        for voice in self.voices:
            if voice.id == self.primary_voice_id:
                return voice
        return self.voices[0] if self.voices else None


class CharacterSheet(BaseModel):
    id: str
    name: str
    age: str = ""
    gender: str = ""
    occupation: str = ""
    origin: str = ""
    world: str = ""
    appearance: str = ""
    personality: str = ""
    motivation: str = ""
    weakness: str = ""
    background: str = ""
    skills: str = ""
    relationships: list[Relationship] = Field(default_factory=list)
    quirks: str = ""
    story_hooks: str = ""
    self_intro: str = ""
    sample_dialogues: str = ""
    voice_image: str = ""
    media: CharacterMedia = Field(default_factory=CharacterMedia)
    is_favorite: bool = False
    tags: list[str] = Field(default_factory=list)
    raw_markdown: str = ""
    generation_meta: GenerationMeta = Field(default_factory=GenerationMeta)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
