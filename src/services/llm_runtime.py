"""LLM 実行時インスタンスの構成処理。"""

from __future__ import annotations

from typing import Literal

from langchain_core.language_models import BaseChatModel

from ..core.llm.factory import create_llm
from .api_config import ApiConfigService

LLMRuntimeErrorKind = Literal[
    "profile_not_found",
    "model_id_missing",
    "endpoint_not_found",
    "api_key_locked",
]

PROFILE_NOT_FOUND: LLMRuntimeErrorKind = "profile_not_found"
MODEL_ID_MISSING: LLMRuntimeErrorKind = "model_id_missing"
ENDPOINT_NOT_FOUND: LLMRuntimeErrorKind = "endpoint_not_found"
API_KEY_LOCKED: LLMRuntimeErrorKind = "api_key_locked"

_DEFAULT_MESSAGES: dict[LLMRuntimeErrorKind, str] = {
    PROFILE_NOT_FOUND: "LLMプロファイルを選択してください",
    MODEL_ID_MISSING: "モデルIDが未設定です。設定画面でLLMプロファイルのモデルを設定してください。",
    ENDPOINT_NOT_FOUND: "エンドポイントが見つかりません",
    API_KEY_LOCKED: "このエンドポイントにはAPIキーが設定されています。APIキーボルトをロック解除してください。",
}


class LLMRuntimeError(RuntimeError):
    """LLM 構成に必要な設定が不足していることを表す例外。"""

    def __init__(self, kind: LLMRuntimeErrorKind, message: str | None = None) -> None:
        self.kind = kind
        self.message = message or _DEFAULT_MESSAGES[kind]
        super().__init__(self.message)


def build_configured_llm(
    api_config: ApiConfigService,
    profile_id: str,
    vault_password: str | None,
) -> BaseChatModel:
    """プロファイル・エンドポイント・Vault から LLM インスタンスを構成する。"""

    profile = api_config.get_llm_profile(profile_id)
    if profile is None:
        raise LLMRuntimeError(PROFILE_NOT_FOUND)
    if not profile.model_id:
        raise LLMRuntimeError(MODEL_ID_MISSING)

    endpoint = api_config.get_endpoint(profile.endpoint_id)
    if endpoint is None:
        raise LLMRuntimeError(ENDPOINT_NOT_FOUND)

    api_key = api_config.get_api_key(profile.endpoint_id, vault_password)
    if api_config.is_api_key_locked(profile.endpoint_id, api_key):
        raise LLMRuntimeError(API_KEY_LOCKED)

    return create_llm(profile, endpoint, api_key)
