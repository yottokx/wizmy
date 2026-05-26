"""
OpenAI互換API プロバイダー実装。

OpenAI本家のほか、OpenAI互換インターフェースを持つ
任意のサービス（ローカルサーバー含む）に対応する。
"""

from __future__ import annotations

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from ..base_provider import BaseProvider
from ..schemas import Endpoint, LLMParameterCapabilities, LLMProfile


class OpenAICompatProvider(BaseProvider):
    parameter_capabilities = LLMParameterCapabilities(
        temperature=True,
        reasoning=False,
        max_tokens=True,
    )

    def create_llm(self, profile: LLMProfile, api_key: str | None = None) -> BaseChatModel:
        raise NotImplementedError("OpenAI互換プロバイダーはエンドポイント情報が必要です。")

    def create_llm_with_endpoint(
        self, profile: LLMProfile, endpoint: Endpoint, api_key: str | None = None
    ) -> BaseChatModel:
        base_url = self._normalize_base_url(endpoint.base_url)
        kwargs: dict = {
            "model": profile.model_id,
            "base_url": base_url,
            "api_key": api_key or "dummy-key",
            "temperature": profile.temperature,
        }
        if profile.max_tokens:
            kwargs["max_tokens"] = profile.max_tokens
        kwargs.update(profile.extra_params)
        return ChatOpenAI(**kwargs)

    async def fetch_models(self, endpoint: Endpoint, api_key: str | None = None) -> list[str]:
        try:
            base_url = self._normalize_base_url(endpoint.base_url)
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{base_url}/models", headers=headers)
                resp.raise_for_status()
                return sorted(m["id"] for m in resp.json().get("data", []))
        except Exception:
            return []

    async def validate_connection(self, endpoint: Endpoint, api_key: str | None = None) -> bool:
        try:
            base_url = self._normalize_base_url(endpoint.base_url)
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{base_url}/models", headers=headers)
                return resp.is_success
        except Exception:
            return False

    @staticmethod
    def _normalize_base_url(url: str) -> str:
        url = url.rstrip("/")
        if not url.endswith("/v1"):
            url = f"{url}/v1"
        return url
