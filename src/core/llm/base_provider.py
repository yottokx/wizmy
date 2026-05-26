"""
LLMプロバイダーの抽象基底クラス。

新しいプロバイダーを追加する際は BaseProvider を継承し、
providers/ ディレクトリにモジュールを追加するだけでよい。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from langchain_core.language_models import BaseChatModel

from .schemas import Endpoint, LLMParameterCapabilities, LLMProfile


class BaseProvider(ABC):
    """LLMプロバイダーの抽象インターフェース。"""

    parameter_capabilities = LLMParameterCapabilities()

    @abstractmethod
    def create_llm(self, profile: LLMProfile, api_key: str | None) -> BaseChatModel:
        """LangChain の BaseChatModel インスタンスを生成する。"""
        ...

    @abstractmethod
    async def fetch_models(self, endpoint: Endpoint, api_key: str | None) -> list[str]:
        """エンドポイントから利用可能なモデルの一覧を取得する。"""
        ...

    @abstractmethod
    async def validate_connection(self, endpoint: Endpoint, api_key: str | None) -> bool:
        """エンドポイントへの接続を検証する。"""
        ...
