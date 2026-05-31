"""画像生成サービス。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from ..core.gen_server.schemas import (
    GEN_SERVER_MODE_SDXL_IMAGE,
    GenServerEndpoint,
    gen_server_api_root,
)
from ..core.image_generation.schemas import (
    IMAGE_PROVIDER_WIZMY_GEN_SERVER,
    ImageGenerationProfile,
    clean_image_generation_params,
    image_generation_profile_values,
)
from .api_config import ApiConfigService


class ImageGenerationError(RuntimeError):
    """画像生成APIの呼び出しに失敗した場合の例外。"""


@dataclass(frozen=True)
class GeneratedImage:
    data: bytes
    content_type: str = "image/png"
    filename: str = "generated-image.png"
    width: int = 0
    height: int = 0


class ImageGenerationService:
    def __init__(self, api_config: ApiConfigService) -> None:
        self._api_config = api_config

    def resolve_gen_server_sdxl_endpoint(
        self,
        *,
        raise_on_missing: bool = True,
    ) -> GenServerEndpoint | None:
        config = self._api_config.get_gen_server_config()
        endpoint_id = config.assigned_endpoint_id(GEN_SERVER_MODE_SDXL_IMAGE)
        if not endpoint_id:
            if raise_on_missing:
                raise ImageGenerationError("Wizmy-Gen-ServerのSDXL画像生成割り当てを設定してください。")
            return None
        endpoint = self._api_config.get_gen_server_endpoint(endpoint_id)
        if endpoint is None:
            if raise_on_missing:
                raise ImageGenerationError("割り当てられたWizmy-Gen-Serverが見つかりません。")
            return None
        return endpoint

    def resolve_image_profile(
        self,
        profile_id: str = "",
        *,
        raise_on_missing: bool = True,
    ) -> ImageGenerationProfile | None:
        profile = (
            self._api_config.get_image_generation_profile(profile_id)
            if profile_id
            else self._api_config.get_default_image_generation_profile()
        )
        if profile is None and raise_on_missing:
            raise ImageGenerationError("画像生成プロファイルを設定してください。")
        return profile

    async def generate_sdxl(
        self,
        *,
        profile_id: str = "",
        gen_server_params: dict[str, Any] | None = None,
    ) -> list[GeneratedImage]:
        profile = self.resolve_image_profile(profile_id)
        if profile is None:
            raise ImageGenerationError("画像生成プロファイルを設定してください。")
        endpoint = self._resolve_wizmy_gen_server_endpoint(profile)
        payload = self._sdxl_payload(profile, gen_server_params or {})
        return await WizmyGenServerSdxlClient(endpoint).generate(payload)

    def _resolve_wizmy_gen_server_endpoint(self, profile: ImageGenerationProfile) -> GenServerEndpoint:
        if profile.provider != IMAGE_PROVIDER_WIZMY_GEN_SERVER:
            raise ImageGenerationError("この画像生成APIはまだ実装されていません。")
        endpoint_id = profile.endpoint_id
        if not endpoint_id:
            raise ImageGenerationError("画像生成プロファイルのAPIを設定してください。")
        endpoint = self._api_config.get_gen_server_endpoint(endpoint_id)
        if endpoint is None:
            raise ImageGenerationError("画像生成プロファイルのWizmy-Gen-Serverが見つかりません。")
        return endpoint

    def _sdxl_payload(self, profile: ImageGenerationProfile, overrides: dict[str, Any]) -> dict[str, Any]:
        merged = {
            **image_generation_profile_values(profile),
            **_clean_image_generation_overrides(overrides),
        }
        model_id = str(merged.get("model_id", "") or "").strip()
        prompt = str(merged.get("prompt", "") or "").strip()
        if not model_id:
            raise ImageGenerationError("モデルIDを入力してください。")
        if not prompt:
            raise ImageGenerationError("プロンプトを入力してください。")

        payload = {
            key: value
            for key, value in clean_image_generation_params(merged).items()
            if value is not None
        }
        negative_prompt = str(merged.get("negative_prompt") or "").strip()
        payload["model_id"] = model_id
        payload["prompt"] = prompt
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        width = int(payload.get("width") or 0)
        height = int(payload.get("height") or 0)
        if width <= 0 or height <= 0:
            raise ImageGenerationError("幅と高さを入力してください。")
        if width % 8 != 0 or height % 8 != 0:
            raise ImageGenerationError("幅と高さは8の倍数にしてください。")

        batch_size = int(payload.get("batch_size") or 1)
        if batch_size < 1:
            raise ImageGenerationError("Batch Sizeは1以上にしてください。")
        payload["batch_size"] = batch_size
        return payload


class WizmyGenServerSdxlClient:
    POLL_LIMIT = 600

    def __init__(self, endpoint: GenServerEndpoint) -> None:
        self._base_url = gen_server_api_root(endpoint.base_url)
        if not self._base_url:
            raise ImageGenerationError("Wizmy-Gen-ServerのURLを設定してください。")

    async def generate(self, payload: dict[str, Any]) -> list[GeneratedImage]:
        async with self._client(timeout=httpx.Timeout(300.0, connect=5.0)) as client:
            try:
                response = await client.post("/v1/images/sdxl/jobs", json=payload)
                _raise_for_error(response, "Wizmy-Gen-Server")
                job_id = str(response.json().get("job_id") or "")
                if not job_id:
                    raise ImageGenerationError("Wizmy-Gen-ServerのジョブIDを取得できませんでした。")
                result = await self._wait_job_result(client, job_id)
                artifacts = _image_artifacts(result)
                if not artifacts:
                    raise ImageGenerationError("Wizmy-Gen-Serverの生成結果に画像が含まれていません。")
                return [await self._download_image(client, artifact) for artifact in artifacts]
            except httpx.HTTPError as exc:
                raise ImageGenerationError(f"Wizmy-Gen-Serverへの接続に失敗しました: {exc}") from exc

    async def _wait_job_result(self, client: httpx.AsyncClient, job_id: str) -> dict[str, Any]:
        for _ in range(self.POLL_LIMIT):
            response = await client.get(f"/v1/jobs/{job_id}/result")
            if response.status_code == 202:
                retry_after = response.json().get("retry_after_seconds", 1)
                try:
                    delay = max(0.2, min(5.0, float(retry_after)))
                except (TypeError, ValueError):
                    delay = 1.0
                await asyncio.sleep(delay)
                continue
            _raise_for_error(response, "Wizmy-Gen-Server")
            return response.json()
        raise ImageGenerationError("Wizmy-Gen-Serverの画像生成がタイムアウトしました。")

    async def _download_image(self, client: httpx.AsyncClient, artifact: dict[str, Any]) -> GeneratedImage:
        url = str(artifact.get("url") or "")
        if not url:
            raise ImageGenerationError("Wizmy-Gen-Serverの画像URLを取得できませんでした。")
        response = await client.get(url)
        _raise_for_error(response, "Wizmy-Gen-Server")
        content_type = str(response.headers.get("content-type") or artifact.get("mime_type") or "image/png")
        return GeneratedImage(
            data=response.content,
            content_type=content_type.split(";", 1)[0],
            filename=_artifact_filename(url),
            width=_safe_int(artifact.get("width")),
            height=_safe_int(artifact.get("height")),
        )

    def _client(self, *, timeout: float | httpx.Timeout = 30.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base_url, timeout=timeout)


def _image_artifacts(result: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = result.get("artifacts") if isinstance(result, dict) else None
    if not isinstance(artifacts, list):
        return []
    images: list[dict[str, Any]] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        mime_type = str(artifact.get("mime_type") or "")
        artifact_type = str(artifact.get("type") or "")
        url = str(artifact.get("url") or "")
        if url and (artifact_type == "image" or mime_type.startswith("image/")):
            images.append(artifact)
    return images


def _artifact_filename(url: str) -> str:
    name = url.rstrip("/").rsplit("/", 1)[-1]
    return name or "generated-image.png"


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _clean_image_generation_overrides(overrides: dict[str, Any]) -> dict[str, Any]:
    allowed = {"model_id", "prompt", "negative_prompt"} | set(clean_image_generation_params({}))
    return {
        key: value
        for key, value in overrides.items()
        if key in allowed
    }


def _raise_for_error(response: httpx.Response, provider_name: str) -> None:
    if response.is_success:
        return
    raise ImageGenerationError(_response_error_message(response, provider_name))


def _response_error_message(response: httpx.Response, provider_name: str) -> str:
    try:
        body = response.json()
    except ValueError:
        text = response.text.strip()
        return text or f"{provider_name}がHTTP {response.status_code}を返しました。"

    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        detail = body.get("detail")
        if detail:
            return str(detail)
    return f"{provider_name}がHTTP {response.status_code}を返しました。"
