"""Wizmy-Gen-Server 設定モデル。"""

from .schemas import (
    GEN_SERVER_MODE_IRODORI_VOICE_CLONE,
    GEN_SERVER_MODE_IRODORI_VOICE_DESIGN,
    GEN_SERVER_DEFAULT_FIELDS,
    GEN_SERVER_MODE_LABELS,
    GEN_SERVER_MODE_SDXL_IMAGE,
    GEN_SERVER_MODES,
    GenServerConfig,
    GenServerEndpoint,
    clean_gen_server_mode_defaults,
    default_gen_server_mode_defaults,
    gen_server_capabilities_url,
    gen_server_health_url,
    gen_server_models_url,
)

__all__ = [
    "GEN_SERVER_MODE_IRODORI_VOICE_CLONE",
    "GEN_SERVER_MODE_IRODORI_VOICE_DESIGN",
    "GEN_SERVER_DEFAULT_FIELDS",
    "GEN_SERVER_MODE_LABELS",
    "GEN_SERVER_MODE_SDXL_IMAGE",
    "GEN_SERVER_MODES",
    "GenServerConfig",
    "GenServerEndpoint",
    "clean_gen_server_mode_defaults",
    "default_gen_server_mode_defaults",
    "gen_server_capabilities_url",
    "gen_server_health_url",
    "gen_server_models_url",
]
