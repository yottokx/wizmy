"""画像生成プロファイル設定。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ImageGenerationProvider = Literal["wizmy_gen_server"]
IMAGE_PROVIDER_WIZMY_GEN_SERVER: ImageGenerationProvider = "wizmy_gen_server"

IMAGE_PROVIDER_LABELS: dict[str, str] = {
    IMAGE_PROVIDER_WIZMY_GEN_SERVER: "Wizmy-Gen-Server",
}

IMAGE_GENERATION_PARAMETER_FIELDS: dict[str, dict[str, Any]] = {
    "width": {"label": "幅", "type": "integer", "default": 832, "minimum": 8, "step": 8},
    "height": {"label": "高さ", "type": "integer", "default": 1216, "minimum": 8, "step": 8},
    "steps": {"label": "ステップ数", "type": "integer", "default": 30, "minimum": 1},
    "cfg_scale": {"label": "CFG Scale", "type": "number", "default": 7.0},
    "seed": {"label": "Seed", "type": "integer", "nullable": True, "default": None},
    "sampler": {"label": "Sampler", "type": "string", "default": "euler_a", "enum": ["euler", "euler_a"]},
    "batch_size": {"label": "Batch Size", "type": "integer", "default": 1, "minimum": 1},
}


def default_image_generation_params() -> dict[str, Any]:
    """画像生成パラメータの標準値を返す。"""
    return {key: spec.get("default") for key, spec in IMAGE_GENERATION_PARAMETER_FIELDS.items()}


def clean_image_generation_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """プロファイルへ保存できる画像生成パラメータだけを残す。"""
    if not isinstance(params, dict):
        params = {}
    cleaned = default_image_generation_params()
    for key, value in params.items():
        if key in IMAGE_GENERATION_PARAMETER_FIELDS:
            cleaned[key] = value
    return cleaned


class ImageGenerationProfile(BaseModel):
    """画像生成API、モデル、プロンプト、パラメータの組み合わせ。"""

    id: str = ""
    name: str = ""
    provider: ImageGenerationProvider = IMAGE_PROVIDER_WIZMY_GEN_SERVER
    endpoint_id: str = ""
    model_id: str = ""
    prompt: str = ""
    negative_prompt: str = ""
    params: dict[str, Any] = Field(default_factory=default_image_generation_params)

    @field_validator("name", "endpoint_id", "model_id", "prompt", "negative_prompt", mode="before")
    @classmethod
    def stringify(cls, value: object) -> str:
        return "" if value is None else str(value)

    @model_validator(mode="after")
    def cleanup_params(self) -> "ImageGenerationProfile":
        self.params = clean_image_generation_params(self.params)
        return self


class ImageGenerationConfig(BaseModel):
    """画像生成プロファイル一覧と既定プロファイル。"""

    profiles: list[ImageGenerationProfile] = Field(default_factory=list)
    default_profile_id: str = ""

    @model_validator(mode="after")
    def cleanup_default(self) -> "ImageGenerationConfig":
        valid_ids = {profile.id for profile in self.profiles if profile.id}
        if self.default_profile_id not in valid_ids:
            self.default_profile_id = self.profiles[0].id if self.profiles else ""
        return self


def image_generation_profile_values(profile: ImageGenerationProfile) -> dict[str, Any]:
    """UIとAPI呼び出しで扱うプロファイル値を平坦化する。"""
    return {
        "model_id": profile.model_id,
        "prompt": profile.prompt,
        "negative_prompt": profile.negative_prompt,
        **clean_image_generation_params(profile.params),
    }
