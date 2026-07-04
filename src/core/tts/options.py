"""TTS API 選択肢の純関数。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..character.schemas import (
    CHARACTER_GEN_SERVER_TTS_MODE_CLONE,
    CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3,
    CHARACTER_TTS_API_DEFAULT,
    CHARACTER_TTS_API_GEN_SERVER,
    CHARACTER_TTS_API_TTS,
    CharacterGenServerTTSMode,
    CharacterTTSApiType,
    CharacterTTSSettings,
)
from ..gen_server.schemas import (
    GEN_SERVER_MODE_IRODORI_VOICE_CLONE,
    GEN_SERVER_MODE_IRODORI_VOICE_DESIGN,
    GenServerConfig,
    GenServerEndpoint,
    GenServerMode,
)
from .schemas import TTS_PROVIDER_IRODORI_GRADIO, TTS_PROVIDER_IRODORI_SERVER, TTSEndpoint

TTS_API_PREFIX = "tts:"
CHARACTER_GEN_SERVER_VOICE_API_VALUE = "gen_server:irodori_voice_clone"
PERSONA_GEN_SERVER_VOICE_API_VALUE = "gen_server:voice"

GEN_SERVER_TTS_MODE_OPTIONS: dict[CharacterGenServerTTSMode, str] = {
    CHARACTER_GEN_SERVER_TTS_MODE_CLONE: "ボイスクローン",
    CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3: "VoiceDesign v3",
}

TTS_PROVIDER_LABELS: dict[str, str] = {
    TTS_PROVIDER_IRODORI_GRADIO: "Irodori-TTS Gradio / 07dfa74",
    TTS_PROVIDER_IRODORI_SERVER: "Irodori-TTS-Server",
}


def tts_provider_label(provider: str, provider_labels: Mapping[str, str] | None = None) -> str:
    labels = TTS_PROVIDER_LABELS if provider_labels is None else provider_labels
    return labels.get(provider, provider)


def voice_api_options(
    endpoints: Sequence[TTSEndpoint],
    gen_server_config: GenServerConfig,
    *,
    gen_server_api_value: str,
    tts_api_prefix: str = TTS_API_PREFIX,
    provider_labels: Mapping[str, str] | None = None,
) -> dict[str, str]:
    options: dict[str, str] = {}
    assigned = assigned_gen_server_voice_endpoints(gen_server_config)
    if assigned:
        names = sorted({endpoint.name for endpoint in assigned if endpoint.name})
        name_label = ", ".join(names) if names else "割り当て済み"
        options[gen_server_api_value] = f"Wizmy-Gen-Server (TTS: {name_label})"
    options.update(
        {
            f"{tts_api_prefix}{endpoint.id}": f"{endpoint.name} ({tts_provider_label(endpoint.provider, provider_labels)})"
            for endpoint in endpoints
        }
    )
    return options


def selected_voice_api_value(
    settings: CharacterTTSSettings,
    endpoints: Sequence[TTSEndpoint],
    has_gen_server: bool,
    *,
    gen_server_api_value: str,
    tts_api_prefix: str = TTS_API_PREFIX,
) -> str:
    if settings.api_type == CHARACTER_TTS_API_GEN_SERVER and has_gen_server:
        return gen_server_api_value
    endpoint_ids = {endpoint.id for endpoint in endpoints}
    if settings.api_type == CHARACTER_TTS_API_TTS and settings.endpoint_id in endpoint_ids:
        return f"{tts_api_prefix}{settings.endpoint_id}"
    if has_gen_server:
        return gen_server_api_value
    if endpoints:
        return f"{tts_api_prefix}{endpoints[0].id}"
    return ""


def parse_voice_api_value(
    value: str | None,
    *,
    gen_server_api_value: str,
    tts_api_prefix: str = TTS_API_PREFIX,
) -> tuple[CharacterTTSApiType, str]:
    selected = str(value or "")
    if selected == gen_server_api_value:
        return CHARACTER_TTS_API_GEN_SERVER, ""
    if selected.startswith(tts_api_prefix):
        return CHARACTER_TTS_API_TTS, selected[len(tts_api_prefix) :]
    return CHARACTER_TTS_API_DEFAULT, ""


def selected_tts_endpoint(
    value: str | None,
    endpoint_by_id: Mapping[str, TTSEndpoint],
    *,
    gen_server_api_value: str,
    tts_api_prefix: str = TTS_API_PREFIX,
) -> TTSEndpoint | None:
    api_type, endpoint_id = parse_voice_api_value(
        value,
        gen_server_api_value=gen_server_api_value,
        tts_api_prefix=tts_api_prefix,
    )
    if api_type != CHARACTER_TTS_API_TTS:
        return None
    return endpoint_by_id.get(endpoint_id)


def is_gen_server_voice_api(
    value: str | None,
    *,
    gen_server_api_value: str,
    tts_api_prefix: str = TTS_API_PREFIX,
) -> bool:
    return (
        parse_voice_api_value(
            value,
            gen_server_api_value=gen_server_api_value,
            tts_api_prefix=tts_api_prefix,
        )[0]
        == CHARACTER_TTS_API_GEN_SERVER
    )


def normalize_gen_server_tts_mode(value: str | None) -> CharacterGenServerTTSMode:
    selected = str(value or "")
    if selected == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3:
        return CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3
    return CHARACTER_GEN_SERVER_TTS_MODE_CLONE


def gen_server_backend_mode(tts_mode: str) -> GenServerMode:
    if tts_mode == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3:
        return GEN_SERVER_MODE_IRODORI_VOICE_DESIGN
    return GEN_SERVER_MODE_IRODORI_VOICE_CLONE


def assigned_gen_server_voice_endpoints(gen_server_config: GenServerConfig) -> list[GenServerEndpoint]:
    endpoints: list[GenServerEndpoint] = []
    seen: set[str] = set()
    for mode in (GEN_SERVER_MODE_IRODORI_VOICE_CLONE, GEN_SERVER_MODE_IRODORI_VOICE_DESIGN):
        assigned_id = gen_server_config.assigned_endpoint_id(mode)
        endpoint = next(
            (candidate for candidate in gen_server_config.endpoints if candidate.id == assigned_id),
            None,
        )
        if endpoint is None or endpoint.id in seen:
            continue
        endpoints.append(endpoint)
        seen.add(endpoint.id)
    return endpoints
