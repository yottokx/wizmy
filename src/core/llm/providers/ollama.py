"""
Ollama プロバイダー実装。

ローカルまたはリモートの Ollama サーバーに接続する。
ツール呼び出し対応モデルの判定ロジックを含む。
"""

from __future__ import annotations

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama

from ..base_provider import BaseProvider
from ..schemas import Endpoint, LLMParameterCapabilities, LLMProfile


class OllamaProvider(BaseProvider):
    parameter_capabilities = LLMParameterCapabilities(
        temperature=True,
        reasoning=True,
        max_tokens=True,
    )

    def create_llm(self, profile: LLMProfile, api_key: str | None = None) -> BaseChatModel:
        kwargs: dict = {
            "model": profile.model_id,
            "temperature": profile.temperature,
            "base_url": "",
        }
        if profile.max_tokens:
            kwargs["num_predict"] = profile.max_tokens
        kwargs.update(profile.extra_params)
        kwargs["reasoning"] = bool(profile.reasoning_enabled)
        return ChatOllama(**kwargs)

    def create_llm_with_endpoint(
        self, profile: LLMProfile, endpoint: Endpoint, api_key: str | None = None
    ) -> BaseChatModel:
        kwargs: dict = {
            "model": profile.model_id,
            "temperature": profile.temperature,
            "base_url": endpoint.base_url,
        }
        if profile.max_tokens:
            kwargs["num_predict"] = profile.max_tokens
        kwargs.update(profile.extra_params)
        kwargs["reasoning"] = bool(profile.reasoning_enabled)
        return ChatOllama(**kwargs)

    async def fetch_models(self, endpoint: Endpoint, api_key: str | None = None) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{endpoint.base_url}/api/tags")
                resp.raise_for_status()
                models = resp.json().get("models", [])
                all_names = sorted(m["name"] for m in models)

            capable = [m for m in all_names if await self._supports_tools(endpoint, m)]
            return capable if capable else all_names
        except Exception:
            return []

    async def _supports_tools(self, endpoint: Endpoint, model: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{endpoint.base_url}/api/show",
                    json={"model": model},
                )
                if resp.is_success:
                    data = resp.json()
                    if "capabilities" in data:
                        return "tools" in data["capabilities"]
        except Exception:
            pass
        return True

    async def validate_connection(self, endpoint: Endpoint, api_key: str | None = None) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{endpoint.base_url}/api/tags")
                return resp.is_success
        except Exception:
            return False
