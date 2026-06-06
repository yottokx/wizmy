"""Wizmy-Gen-Server 接続設定。"""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator


GEN_SERVER_MODE_IRODORI_VOICE_CLONE = "irodori_voice_clone"
GEN_SERVER_MODE_IRODORI_VOICE_DESIGN = "irodori_voice_design"
GEN_SERVER_MODE_SDXL_IMAGE = "sdxl_image"
GenServerMode = Literal[
    "irodori_voice_clone",
    "irodori_voice_design",
    "sdxl_image",
]

GEN_SERVER_MODES: tuple[GenServerMode, ...] = (
    GEN_SERVER_MODE_SDXL_IMAGE,
    GEN_SERVER_MODE_IRODORI_VOICE_DESIGN,
    GEN_SERVER_MODE_IRODORI_VOICE_CLONE,
)

GEN_SERVER_MODE_LABELS: dict[str, str] = {
    GEN_SERVER_MODE_SDXL_IMAGE: "SDXL画像生成",
    GEN_SERVER_MODE_IRODORI_VOICE_DESIGN: "ボイスデザイン",
    GEN_SERVER_MODE_IRODORI_VOICE_CLONE: "ボイスクローン",
}

GEN_SERVER_DEFAULT_FIELDS: dict[str, dict[str, dict[str, Any]]] = {
    GEN_SERVER_MODE_SDXL_IMAGE: {
        "model_id": {"label": "モデルID", "type": "string", "default": ""},
        "prompt": {"label": "プロンプト", "type": "string", "default": "", "multiline": True},
        "negative_prompt": {"label": "ネガティブプロンプト", "type": "string", "default": "", "multiline": True},
        "width": {"label": "幅", "type": "integer", "default": 832, "minimum": 8, "step": 8},
        "height": {"label": "高さ", "type": "integer", "default": 1216, "minimum": 8, "step": 8},
        "steps": {"label": "ステップ数", "type": "integer", "default": 30, "minimum": 1},
        "cfg_scale": {"label": "CFG Scale", "type": "number", "default": 7.0},
        "seed": {"label": "Seed", "type": "integer", "nullable": True, "default": None},
        "sampler": {"label": "Sampler", "type": "string", "default": "euler_a", "enum": ["euler", "euler_a"]},
        "batch_size": {"label": "Batch Size", "type": "integer", "default": 1, "minimum": 1},
    },
    GEN_SERVER_MODE_IRODORI_VOICE_DESIGN: {
        "model_id": {"label": "モデルID", "type": "string", "default": "Aratako/Irodori-TTS-600M-v3-VoiceDesign"},
        "steps": {"label": "ステップ数", "type": "integer", "default": 40, "minimum": 1},
        "num_candidates": {"label": "候補数", "type": "integer", "default": 1, "minimum": 1},
        "seed": {"label": "Seed", "type": "integer", "nullable": True, "default": None},
        "seconds": {"label": "秒数", "type": "number", "nullable": True, "default": None},
        "duration_scale": {"label": "Duration Scale", "type": "number", "default": 1.0, "exclusiveMinimum": 0},
        "cfg_guidance_mode": {
            "label": "CFG Guidance Mode",
            "type": "string",
            "default": "independent",
            "enum": ["independent", "joint", "alternating"],
        },
        "cfg_scale_text": {"label": "CFG Scale Text", "type": "number", "default": 3.0},
        "cfg_scale_caption": {"label": "CFG Scale Caption", "type": "number", "default": 3.0},
        "cfg_scale_speaker": {"label": "CFG Scale Speaker", "type": "number", "default": 5.0},
        "speaker_kv_scale": {"label": "Speaker KV Scale", "type": "number", "nullable": True, "default": None},
        "speaker_kv_min_t": {"label": "Speaker KV Min T", "type": "number", "nullable": True, "default": None},
        "speaker_kv_max_layers": {
            "label": "Speaker KV Max Layers",
            "type": "integer",
            "nullable": True,
            "default": None,
        },
        "no_ref": {"label": "参照音声を使わない", "type": "boolean", "default": False},
        "cfg_scale": {"label": "CFG Scale Override", "type": "number", "nullable": True, "default": None},
        "cfg_min_t": {"label": "CFG Min T", "type": "number", "default": 0.5},
        "cfg_max_t": {"label": "CFG Max T", "type": "number", "default": 1.0},
        "context_kv_cache": {"label": "Context KV Cache", "type": "boolean", "default": True},
        "truncation_factor": {"label": "Truncation Factor", "type": "number", "nullable": True, "default": None},
        "rescale_k": {"label": "Rescale K", "type": "number", "nullable": True, "default": None},
        "rescale_sigma": {"label": "Rescale Sigma", "type": "number", "nullable": True, "default": None},
        "t_schedule_mode": {
            "label": "Time Schedule",
            "type": "string",
            "default": "linear",
            "enum": ["linear", "sway"],
        },
        "sway_coeff": {"label": "Sway Coeff", "type": "number", "default": -1.0},
        "max_text_len": {"label": "最大テキスト長", "type": "integer", "nullable": True, "default": None},
        "max_caption_len": {"label": "最大キャプション長", "type": "integer", "nullable": True, "default": None},
    },
    GEN_SERVER_MODE_IRODORI_VOICE_CLONE: {
        "model_id": {"label": "モデルID", "type": "string", "default": "Aratako/Irodori-TTS-500M-v3"},
        "steps": {"label": "ステップ数", "type": "integer", "default": 40, "minimum": 1},
        "num_candidates": {"label": "候補数", "type": "integer", "default": 1, "minimum": 1},
        "seed": {"label": "Seed", "type": "integer", "nullable": True, "default": None},
        "seconds": {"label": "秒数", "type": "number", "nullable": True, "default": None},
        "duration_scale": {"label": "Duration Scale", "type": "number", "default": 1.0, "exclusiveMinimum": 0},
        "cfg_guidance_mode": {
            "label": "CFG Guidance Mode",
            "type": "string",
            "default": "independent",
            "enum": ["independent", "joint", "alternating"],
        },
        "cfg_scale_text": {"label": "CFG Scale Text", "type": "number", "default": 3.0},
        "cfg_scale_speaker": {"label": "CFG Scale Speaker", "type": "number", "default": 5.0},
        "cfg_scale": {"label": "CFG Scale Override", "type": "number", "nullable": True, "default": None},
        "cfg_min_t": {"label": "CFG Min T", "type": "number", "default": 0.5},
        "cfg_max_t": {"label": "CFG Max T", "type": "number", "default": 1.0},
        "context_kv_cache": {"label": "Context KV Cache", "type": "boolean", "default": True},
        "truncation_factor": {"label": "Truncation Factor", "type": "number", "nullable": True, "default": None},
        "rescale_k": {"label": "Rescale K", "type": "number", "nullable": True, "default": None},
        "rescale_sigma": {"label": "Rescale Sigma", "type": "number", "nullable": True, "default": None},
        "t_schedule_mode": {
            "label": "Time Schedule",
            "type": "string",
            "default": "linear",
            "enum": ["linear", "sway"],
        },
        "sway_coeff": {"label": "Sway Coeff", "type": "number", "default": -1.0},
    },
}

_URL_MESSAGE = "URLは http://host:port または http://host:port/v1 の形式で入力してください。"


class GenServerEndpoint(BaseModel):
    """Wizmy-Gen-Server の接続先。"""

    id: str = ""
    name: str = ""
    base_url: str = "http://127.0.0.1:8008/v1"

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return validate_gen_server_base_url(value)


class GenServerConfig(BaseModel):
    """画像・音声生成機能の Gen-Server 割り当て設定。"""

    endpoints: list[GenServerEndpoint] = Field(default_factory=list)
    mode_assignments: dict[str, str] = Field(default_factory=dict)
    mode_defaults: dict[str, dict[str, Any]] = Field(default_factory=dict)
    voice_chunking_enabled: bool = True
    voice_chunk_min_chars: int = 80

    @field_validator("voice_chunk_min_chars")
    @classmethod
    def validate_voice_chunk_min_chars(cls, value: int) -> int:
        return max(1, int(value))

    @model_validator(mode="after")
    def cleanup_assignments(self) -> "GenServerConfig":
        valid_endpoint_ids = {endpoint.id for endpoint in self.endpoints if endpoint.id}
        self.mode_assignments = {
            mode: endpoint_id
            for mode, endpoint_id in self.mode_assignments.items()
            if mode in GEN_SERVER_MODES and endpoint_id in valid_endpoint_ids
        }
        self.mode_defaults = {
            mode: clean_gen_server_mode_defaults(mode, defaults)
            for mode, defaults in self.mode_defaults.items()
            if mode in GEN_SERVER_MODES and isinstance(defaults, dict)
        }
        return self

    def assigned_endpoint_id(self, mode: str) -> str:
        return self.mode_assignments.get(mode, "")

    def defaults_for_mode(self, mode: str) -> dict[str, Any]:
        defaults = default_gen_server_mode_defaults(mode)
        defaults.update(self.mode_defaults.get(mode, {}))
        return defaults


def default_gen_server_mode_defaults(mode: str) -> dict[str, Any]:
    fields = GEN_SERVER_DEFAULT_FIELDS.get(mode, {})
    return {key: spec.get("default") for key, spec in fields.items()}


def clean_gen_server_mode_defaults(mode: str, defaults: dict[str, Any]) -> dict[str, Any]:
    fields = GEN_SERVER_DEFAULT_FIELDS.get(mode, {})
    cleaned: dict[str, Any] = {}
    for key, value in defaults.items():
        if key not in fields:
            continue
        if key == "model_id" and _is_other_voice_mode_default_model_id(mode, value):
            continue
        cleaned[key] = value
    return cleaned


def _is_other_voice_mode_default_model_id(mode: str, value: Any) -> bool:
    voice_modes = {
        GEN_SERVER_MODE_IRODORI_VOICE_CLONE,
        GEN_SERVER_MODE_IRODORI_VOICE_DESIGN,
    }
    if mode not in voice_modes:
        return False
    model_id = str(value or "").strip()
    if not model_id:
        return False
    for other_mode in voice_modes:
        if other_mode == mode:
            continue
        default_model_id = str(
            GEN_SERVER_DEFAULT_FIELDS[other_mode]["model_id"].get("default") or ""
        ).strip()
        if model_id == default_model_id:
            return True
    return False


def validate_gen_server_base_url(value: str) -> str:
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
    if parsed.username or parsed.password or parsed.params or parsed.query or parsed.fragment:
        raise ValueError(_URL_MESSAGE)

    path = parsed.path.rstrip("/")
    if path not in ("", "/v1"):
        raise ValueError(_URL_MESSAGE)

    return url


def gen_server_api_root(base_url: str) -> str:
    base = validate_gen_server_base_url(base_url)
    if base.endswith("/v1"):
        return base[:-3]
    return base


def gen_server_v1_url(base_url: str) -> str:
    base = validate_gen_server_base_url(base_url)
    if base.endswith("/v1"):
        return base
    return f"{base}/v1"


def gen_server_health_url(base_url: str) -> str:
    return f"{gen_server_api_root(base_url)}/health"


def gen_server_capabilities_url(base_url: str) -> str:
    return f"{gen_server_v1_url(base_url)}/capabilities"


def gen_server_models_url(base_url: str) -> str:
    return f"{gen_server_v1_url(base_url)}/models"
