"""
LLM接続・設定に関するスキーマ定義。

- Endpoint: APIエンドポイント（URLとプロバイダー種別）
- LLMProfile: モデルとパラメータの設定（旧称「モデルプリセット」を改称）

「プリセット」という語はキャラ生成プリセット (GenerationPreset) に使用するため、
LLM設定には「プロファイル」を使用する。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Endpoint(BaseModel):
    id: str
    name: str
    type: Literal["ollama", "openai_compat"] = "ollama"
    base_url: str = "http://localhost:11434"

    @field_validator("base_url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")


class LLMProfile(BaseModel):
    id: str
    name: str
    endpoint_id: str
    model_id: str = ""
    temperature: float = Field(default=0.8, ge=0.0, le=2.0)
    reasoning_enabled: bool = False
    max_tokens: int | None = None
    extra_params: dict[str, Any] = Field(default_factory=dict)


class LLMParameterCapabilities(BaseModel):
    """プロバイダーがUIで編集できるLLMパラメータ。"""

    temperature: bool = True
    reasoning: bool = False
    max_tokens: bool = True


class GenerationPreset(BaseModel):
    """生成画面のフォームへ一括コピーするテンプレート（生成時はフォームの入力が使われる）。"""

    id: str
    name: str
    world: str = ""
    gender: str = ""
    age: str = ""
    theme: str = ""
    extra: str = ""


class AppLLMConfig(BaseModel):
    """機能ごとのデフォルトLLMプロファイル設定。"""

    generation_profile_id: str = ""
    chat_profile_id: str = ""
