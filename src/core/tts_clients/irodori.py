"""Irodori-TTS 向け HTTP クライアント。"""

from __future__ import annotations

import mimetypes
import secrets
from pathlib import Path
from typing import Any

import httpx

from ..tts.schemas import TTSEndpoint
from .audio import (
    DEFAULT_CHUNK_MIN_CHARS,
    TTSServiceError,
    audio_download_candidates,
    component_defaults,
    concat_wav_bytes,
    first_audio_reference,
    first_uploaded_path,
    generation_dependency,
    raise_for_error,
    speech_chunks,
)


class IrodoriGradioClient:
    """Client for Irodori-TTS gradio_app.py at commit 07dfa74."""

    CHECKPOINT = "hf://Aratako/Irodori-TTS-500M-v3"
    FALLBACK_API_NAME = "_run_generation"

    def __init__(self, endpoint: TTSEndpoint) -> None:
        self._base_url = endpoint.base_url
        if not self._base_url:
            raise TTSServiceError("TTS設定でIrodori-TTS GradioのURLを設定してください。")

    async def synthesize(
        self,
        text: str,
        voice_path: Path | None,
        *,
        filename: str = "",
        content_type: str = "",
        chunking_enabled: bool = True,
        chunk_min_chars: int = DEFAULT_CHUNK_MIN_CHARS,
    ) -> bytes:
        chunks = speech_chunks(text, enabled=chunking_enabled, min_chars=chunk_min_chars)
        async with self._client(timeout=httpx.Timeout(300.0, connect=5.0)) as client:
            try:
                config = await self._fetch_config(client)
                api_name = self._generation_api_name(config)
                audio_input = None
                if voice_path is not None:
                    audio_input = await self._upload_audio(
                        client,
                        voice_path,
                        filename=filename,
                        content_type=content_type,
                    )
                audio_chunks = [
                    await self._synthesize_once(client, config, api_name, chunk, audio_input) for chunk in chunks
                ]
                return concat_wav_bytes(audio_chunks)
            except httpx.HTTPError as exc:
                raise TTSServiceError(f"Irodori-TTS Gradioへの接続に失敗しました: {exc}") from exc

    async def _synthesize_once(
        self,
        client: httpx.AsyncClient,
        config: dict[str, Any],
        api_name: str,
        text: str,
        audio_input: dict[str, Any] | None,
    ) -> bytes:
        data = self._generation_request_data(config, text, audio_input)
        result = await self._call_direct_api(client, api_name, data)
        audio_ref = first_audio_reference(result)
        if audio_ref is None:
            raise TTSServiceError("Irodori-TTS Gradioの生成結果に音声が含まれていません。")
        return await self._download_audio(client, audio_ref)

    async def _fetch_config(self, client: httpx.AsyncClient) -> dict[str, Any]:
        response = await client.get("/config")
        raise_for_error(response, "Irodori-TTS Gradio")
        return response.json()

    async def _upload_audio(
        self,
        client: httpx.AsyncClient,
        voice_path: Path,
        *,
        filename: str = "",
        content_type: str = "",
    ) -> dict[str, Any]:
        name = filename or voice_path.name
        media_type = content_type or mimetypes.guess_type(name)[0] or "audio/wav"
        audio_bytes = voice_path.read_bytes()
        response = await self._post_upload(client, name, audio_bytes, media_type)
        raise_for_error(response, "Irodori-TTS Gradio")
        uploaded = response.json()
        path = first_uploaded_path(uploaded)
        if path is None:
            raise TTSServiceError("Irodori-TTS Gradioへの参照音声アップロードに失敗しました。")
        return {
            "path": path,
            "orig_name": name,
            "mime_type": media_type,
            "meta": {"_type": "gradio.FileData"},
        }

    async def _post_upload(
        self,
        client: httpx.AsyncClient,
        name: str,
        audio_bytes: bytes,
        media_type: str,
    ) -> httpx.Response:
        last_response: httpx.Response | None = None
        for path in ("/gradio_api/upload", "/upload"):
            files = [("files", (name, audio_bytes, media_type))]
            response = await client.post(path, files=files)
            if response.status_code != 404:
                return response
            last_response = response
        if last_response is None:
            raise TTSServiceError("Irodori-TTS GradioのアップロードAPIが見つかりません。")
        return last_response

    async def _call_direct_api(
        self,
        client: httpx.AsyncClient,
        api_name: str,
        data: list[Any],
    ) -> Any:
        payload = {
            "data": data,
            "session_hash": secrets.token_hex(8),
        }
        response = await self._post_first_available(
            client,
            [
                f"/run/{api_name}",
                f"/gradio_api/run/{api_name}",
            ],
            json=payload,
        )
        raise_for_error(response, "Irodori-TTS Gradio")
        return response.json()

    async def _download_audio(self, client: httpx.AsyncClient, audio_ref: str) -> bytes:
        candidates = audio_download_candidates(self._base_url, audio_ref)
        response = await self._get_first_available(client, candidates)
        raise_for_error(response, "Irodori-TTS Gradio")
        return response.content

    async def _post_first_available(
        self,
        client: httpx.AsyncClient,
        paths: list[str],
        **kwargs: Any,
    ) -> httpx.Response:
        last_response: httpx.Response | None = None
        for path in paths:
            response = await client.post(path, **kwargs)
            if response.status_code != 404:
                return response
            last_response = response
        if last_response is None:
            raise TTSServiceError("Irodori-TTS GradioのAPIパスが見つかりません。")
        return last_response

    async def _get_first_available(
        self,
        client: httpx.AsyncClient,
        paths: list[str],
    ) -> httpx.Response:
        last_response: httpx.Response | None = None
        for path in paths:
            response = await client.get(path)
            if response.status_code != 404:
                return response
            last_response = response
        if last_response is None:
            raise TTSServiceError("Irodori-TTS GradioのAPIパスが見つかりません。")
        return last_response

    def _client(self, *, timeout: float | httpx.Timeout = 30.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base_url, timeout=timeout)

    def _generation_api_name(self, config: dict[str, Any]) -> str:
        dependency = generation_dependency(config)
        raw_name = dependency.get("api_name") if dependency else None
        if raw_name:
            return str(raw_name).lstrip("/")
        return self.FALLBACK_API_NAME

    def _generation_request_data(
        self,
        config: dict[str, Any],
        text: str,
        uploaded_audio: dict[str, Any] | None,
    ) -> list[Any]:
        defaults = component_defaults(config)
        return [
            defaults.get("Checkpoint (.pt/.safetensors or HF repo id)", self.CHECKPOINT),
            defaults.get("Model Device", "cuda"),
            defaults.get("Model Precision", "fp32"),
            defaults.get("Codec Device", "cuda"),
            defaults.get("Codec Precision", "fp32"),
            text,
            uploaded_audio,
            defaults.get("Num Steps", 40),
            1,
            "",
            "",
            defaults.get("Duration Scale", 1.0),
            defaults.get("Time Schedule", "linear"),
            defaults.get("Sway Coeff", -1.0),
            defaults.get("CFG Guidance Mode", "independent"),
            defaults.get("CFG Scale Text", 3.0),
            defaults.get("CFG Scale Speaker", 5.0),
            "",
            defaults.get("CFG Min t", 0.5),
            defaults.get("CFG Max t", 1.0),
            defaults.get("Context KV Cache", True),
            "",
            "",
            "",
            "",
            defaults.get("Speaker KV Min t (optional)", "0.9"),
            "",
            "",
        ]


class IrodoriTTSServerClient:
    MODEL_ID = "irodori-tts"
    RESPONSE_FORMAT = "wav"

    def __init__(self, endpoint: TTSEndpoint) -> None:
        self._base_url = endpoint.base_url
        if not self._base_url:
            raise TTSServiceError("TTS設定でIrodori-TTS-ServerのURLを設定してください。")

    async def register_voice(
        self,
        voice_id: str,
        voice_path: Path,
        *,
        filename: str = "",
        content_type: str = "",
    ) -> dict[str, Any]:
        name = filename or voice_path.name
        media_type = content_type or mimetypes.guess_type(name)[0] or "audio/wav"
        with voice_path.open("rb") as handle:
            files = {"file": (name, handle, media_type)}
            data = {"voice_id": voice_id}
            async with self._client(timeout=httpx.Timeout(60.0, connect=5.0)) as client:
                response = await client.post("/v1/audio/voices", files=files, data=data)
                if response.status_code == 409:
                    handle.seek(0)
                    files = {"file": (name, handle, media_type)}
                    response = await client.put(f"/v1/audio/voices/{voice_id}", files=files)
        raise_for_error(response, "Irodori-TTS-Server")
        return response.json()

    async def delete_voice(self, voice_id: str) -> bool:
        async with self._client(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
            response = await client.delete(f"/v1/audio/voices/{voice_id}")
        if response.status_code == 404:
            return False
        raise_for_error(response, "Irodori-TTS-Server")
        return True

    async def synthesize(
        self,
        voice_id: str,
        text: str,
        *,
        chunking_enabled: bool = True,
        chunk_min_chars: int = DEFAULT_CHUNK_MIN_CHARS,
    ) -> bytes:
        payload = {
            "model": self.MODEL_ID,
            "input": text,
            "voice": voice_id,
            "response_format": self.RESPONSE_FORMAT,
            "irodori": {
                "chunking_enabled": chunking_enabled,
                "chunk_min_chars": chunk_min_chars,
            },
        }
        async with self._client(timeout=httpx.Timeout(300.0, connect=5.0)) as client:
            response = await client.post("/v1/audio/speech", json=payload)
        raise_for_error(response, "Irodori-TTS-Server")
        return response.content

    def _client(self, *, timeout: float | httpx.Timeout = 30.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base_url, timeout=timeout)
