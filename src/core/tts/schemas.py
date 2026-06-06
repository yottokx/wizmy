"""TTS integration settings."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from ..character.schemas import CharacterTTSSettings, CharacterVoiceAsset


TTS_PROVIDER_IRODORI_GRADIO = "irodori_gradio_07dfa74"
TTS_PROVIDER_IRODORI_SERVER = "irodori_tts_server"
TTSProvider = Literal["irodori_gradio_07dfa74", "irodori_tts_server"]

_URL_MESSAGE = "URLは http://host:port の形式で入力してください。"


class TTSEndpoint(BaseModel):
    """A configured TTS API endpoint."""

    id: str = ""
    name: str = ""
    provider: TTSProvider = TTS_PROVIDER_IRODORI_GRADIO
    base_url: str = ""

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return validate_tts_base_url(value)


class TTSConfig(BaseModel):
    """Application-level TTS settings."""

    endpoints: list[TTSEndpoint] = Field(default_factory=list)
    default_endpoint_id: str = ""
    narrator: CharacterTTSSettings = Field(default_factory=CharacterTTSSettings)
    narrator_voice: CharacterVoiceAsset | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_config(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        if value.get("endpoints"):
            return value

        endpoints: list[dict[str, str]] = []
        gradio_url = str(value.get("irodori_gradio_url") or "").strip()
        server_url = str(value.get("irodori_server_url") or "").strip()
        if gradio_url:
            endpoints.append({
                "id": "tts-irodori-gradio",
                "name": "Irodori-TTS Gradio",
                "provider": TTS_PROVIDER_IRODORI_GRADIO,
                "base_url": gradio_url,
            })
        if server_url:
            endpoints.append({
                "id": "tts-irodori-server",
                "name": "Irodori-TTS-Server",
                "provider": TTS_PROVIDER_IRODORI_SERVER,
                "base_url": server_url,
            })

        legacy_provider = value.get("provider")
        default_endpoint_id = ""
        if legacy_provider == TTS_PROVIDER_IRODORI_SERVER and server_url:
            default_endpoint_id = "tts-irodori-server"
        elif gradio_url:
            default_endpoint_id = "tts-irodori-gradio"
        elif endpoints:
            default_endpoint_id = endpoints[0]["id"]

        return {
            "endpoints": endpoints,
            "default_endpoint_id": default_endpoint_id,
            "narrator": value.get("narrator", {}),
            "narrator_voice": value.get("narrator_voice"),
        }


def validate_tts_base_url(value: str) -> str:
    url = value.strip().rstrip("/")
    if not url:
        return ""

    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(_URL_MESSAGE) from exc

    if parsed.scheme != "http" or not parsed.hostname or port is None:
        raise ValueError(_URL_MESSAGE)
    if (
        parsed.username
        or parsed.password
        or parsed.path
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(_URL_MESSAGE)

    return url
