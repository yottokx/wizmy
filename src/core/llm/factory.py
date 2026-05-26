"""
LLMファクトリー。

Endpoint の type フィールドから適切なプロバイダーを選択し、
LangChain の BaseChatModel インスタンスを生成する。

新しいプロバイダーを追加する際は PROVIDER_REGISTRY に登録するだけでよい。
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from .base_provider import BaseProvider
from .providers.ollama import OllamaProvider
from .providers.openai_compat import OpenAICompatProvider
from .schemas import Endpoint, LLMParameterCapabilities, LLMProfile

PROVIDER_REGISTRY: dict[str, BaseProvider] = {
    "ollama": OllamaProvider(),
    "openai_compat": OpenAICompatProvider(),
}


def create_llm(profile: LLMProfile, endpoint: Endpoint, api_key: str | None = None) -> BaseChatModel:
    """
    プロファイルとエンドポイント情報から LangChain モデルインスタンスを生成する。

    Args:
        profile: LLMの設定（モデルID、温度など）
        endpoint: 接続先エンドポイント
        api_key: APIキー（不要な場合はNone）

    Returns:
        BaseChatModel インスタンス

    Raises:
        ValueError: 未知のエンドポイントタイプが指定された場合
    """
    provider = PROVIDER_REGISTRY.get(endpoint.type)
    if provider is None:
        raise ValueError(f"未対応のエンドポイントタイプ: {endpoint.type}")

    if hasattr(provider, "create_llm_with_endpoint"):
        return provider.create_llm_with_endpoint(profile, endpoint, api_key)
    return provider.create_llm(profile, api_key)


async def fetch_models(endpoint: Endpoint, api_key: str | None = None) -> list[str]:
    """エンドポイントから利用可能なモデル一覧を取得する。"""
    provider = PROVIDER_REGISTRY.get(endpoint.type)
    if provider is None:
        return []
    return await provider.fetch_models(endpoint, api_key)


async def validate_connection(endpoint: Endpoint, api_key: str | None = None) -> bool:
    """エンドポイントへの接続を検証する。"""
    provider = PROVIDER_REGISTRY.get(endpoint.type)
    if provider is None:
        return False
    return await provider.validate_connection(endpoint, api_key)


def get_parameter_capabilities(endpoint: Endpoint | None) -> LLMParameterCapabilities:
    """エンドポイント種別に応じて、UIで編集できるパラメータを返す。"""
    if endpoint is None:
        return LLMParameterCapabilities()
    provider = PROVIDER_REGISTRY.get(endpoint.type)
    if provider is None:
        return LLMParameterCapabilities()
    return provider.parameter_capabilities.model_copy()
