"""TTS provider integration service."""

from __future__ import annotations

import asyncio
import inspect
import json
import mimetypes
import secrets
import wave
from collections.abc import Awaitable, Callable
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import httpx

from ..core.character.schemas import (
    CHARACTER_GEN_SERVER_TTS_MODE_CLONE,
    CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3,
    CHARACTER_TTS_API_DEFAULT,
    CHARACTER_TTS_API_GEN_SERVER,
    CHARACTER_TTS_API_TTS,
)
from ..core.gen_server.schemas import (
    GEN_SERVER_MODE_IRODORI_VOICE_CLONE,
    GEN_SERVER_MODE_IRODORI_VOICE_DESIGN,
    GenServerEndpoint,
    clean_gen_server_mode_defaults,
    gen_server_api_root,
)
from ..core.tts.schemas import (
    TTS_PROVIDER_IRODORI_GRADIO,
    TTS_PROVIDER_IRODORI_SERVER,
    TTSEndpoint,
)
from .api_config import ApiConfigService
from .ai_jobs import AIJobKind, AIJobRecord, AIJobService


CHUNK_BOUNDARIES = frozenset("。、，,．.!！?？\n\r")
DEFAULT_CHUNK_MIN_CHARS = 80


class TTSServiceError(RuntimeError):
    """Raised when a TTS provider request fails."""


class TTSService:
    def __init__(
        self,
        api_config: ApiConfigService,
        ai_jobs: AIJobService | None = None,
    ) -> None:
        self._api_config = api_config
        self._ai_jobs = ai_jobs

    def get_endpoints(self) -> list[TTSEndpoint]:
        return self._api_config.get_tts_endpoints()

    def has_voice_playback_api(self, api_type: str = "", endpoint_id: str = "") -> bool:
        gen_server_available = self._has_gen_server_voice_endpoint()
        endpoints = self.get_endpoints()
        if api_type == CHARACTER_TTS_API_TTS and endpoint_id and any(
            endpoint.id == endpoint_id for endpoint in endpoints
        ):
            return True
        return gen_server_available or bool(endpoints)

    def _voice_clone_client(self, endpoint: GenServerEndpoint):
        try:
            return WizmyGenServerVoiceCloneClient(endpoint, self._ai_jobs)
        except TypeError:
            return WizmyGenServerVoiceCloneClient(endpoint)

    def _voice_design_client(self, endpoint: GenServerEndpoint):
        try:
            return WizmyGenServerVoiceDesignClient(endpoint, self._ai_jobs)
        except TypeError:
            return WizmyGenServerVoiceDesignClient(endpoint)

    def _has_gen_server_voice_endpoint(self) -> bool:
        return (
            self.resolve_gen_server_voice_clone_endpoint(raise_on_missing=False) is not None
            or self.resolve_gen_server_voice_design_endpoint(raise_on_missing=False) is not None
        )

    def default_endpoint_id(self) -> str:
        config = self._api_config.get_tts_config()
        return config.endpoints[0].id if config.endpoints else ""

    def chunk_settings(self) -> tuple[bool, int]:
        config = self._api_config.get_gen_server_config()
        return (
            bool(config.voice_chunking_enabled),
            max(1, int(config.voice_chunk_min_chars or DEFAULT_CHUNK_MIN_CHARS)),
        )

    def resolve_endpoint(self, endpoint_id: str = "") -> TTSEndpoint:
        endpoints = self.get_endpoints()
        if not endpoints:
            raise TTSServiceError("TTS設定でAPIを登録してください。")
        selected_id = endpoint_id or self.default_endpoint_id()
        for endpoint in endpoints:
            if endpoint.id == selected_id:
                return endpoint
        raise TTSServiceError("選択されたTTS APIが見つかりません。")

    def supports_voice_registry(self, endpoint_id: str = "") -> bool:
        try:
            return self.resolve_endpoint(endpoint_id).provider == TTS_PROVIDER_IRODORI_SERVER
        except TTSServiceError:
            return False

    def voice_id_for_character(self, character_id: str, voice_id: str = "") -> str:
        return voice_id.strip() or _voice_id_for_character(character_id)

    def resolve_gen_server_voice_clone_endpoint(
        self,
        *,
        raise_on_missing: bool = True,
    ) -> GenServerEndpoint | None:
        return self._resolve_gen_server_endpoint(
            GEN_SERVER_MODE_IRODORI_VOICE_CLONE,
            "ボイスクローン",
            raise_on_missing=raise_on_missing,
        )

    def resolve_gen_server_voice_design_endpoint(
        self,
        *,
        raise_on_missing: bool = True,
    ) -> GenServerEndpoint | None:
        return self._resolve_gen_server_endpoint(
            GEN_SERVER_MODE_IRODORI_VOICE_DESIGN,
            "ボイスデザイン",
            raise_on_missing=raise_on_missing,
        )

    def _resolve_gen_server_endpoint(
        self,
        mode: str,
        label: str,
        *,
        raise_on_missing: bool = True,
    ) -> GenServerEndpoint | None:
        config = self._api_config.get_gen_server_config()
        endpoint_id = config.assigned_endpoint_id(mode)
        if not endpoint_id:
            if raise_on_missing:
                raise TTSServiceError(f"Wizmy-Gen-Serverの{label}割り当てを設定してください。")
            return None
        endpoint = self._api_config.get_gen_server_endpoint(endpoint_id)
        if endpoint is None:
            if raise_on_missing:
                raise TTSServiceError("割り当てられたWizmy-Gen-Serverが見つかりません。")
            return None
        return endpoint

    async def design_voice(
        self,
        text: str,
        caption: str,
        *,
        voice_path: Path | None = None,
        filename: str = "",
        content_type: str = "",
        gen_server_params: dict[str, Any] | None = None,
        ai_job: AIJobRecord | None = None,
    ) -> bytes:
        endpoint = self.resolve_gen_server_voice_design_endpoint()
        model_id, params = self._gen_server_voice_design_options(gen_server_params or {})
        return await self._voice_design_client(endpoint).synthesize(
            text,
            caption,
            voice_path,
            model_id=model_id,
            params=params,
            filename=filename,
            content_type=content_type,
            ai_job=ai_job,
        )

    async def register_voice(
        self,
        character_id: str,
        voice_path: Path,
        *,
        endpoint_id: str = "",
        voice_id: str = "",
        filename: str = "",
        content_type: str = "",
    ) -> dict[str, Any]:
        endpoint = self.resolve_endpoint(endpoint_id)
        if endpoint.provider != TTS_PROVIDER_IRODORI_SERVER:
            raise TTSServiceError("現在のTTS APIはボイス登録に対応していません。")
        return await IrodoriTTSServerClient(endpoint).register_voice(
            self.voice_id_for_character(character_id, voice_id),
            voice_path,
            filename=filename,
            content_type=content_type,
        )

    async def delete_voice(
        self,
        character_id: str,
        *,
        endpoint_id: str = "",
        voice_id: str = "",
    ) -> bool:
        endpoint = self.resolve_endpoint(endpoint_id)
        if endpoint.provider != TTS_PROVIDER_IRODORI_SERVER:
            raise TTSServiceError("現在のTTS APIはボイス削除に対応していません。")
        return await IrodoriTTSServerClient(endpoint).delete_voice(
            self.voice_id_for_character(character_id, voice_id)
        )

    async def synthesize(
        self,
        character_id: str,
        voice_path: Path | None,
        text: str,
        *,
        endpoint_id: str = "",
        voice_id: str = "",
        filename: str = "",
        content_type: str = "",
        api_type: str = CHARACTER_TTS_API_TTS,
        gen_server_tts_mode: str = CHARACTER_GEN_SERVER_TTS_MODE_CLONE,
        voice_caption: str = "",
        gen_server_params: dict[str, Any] | None = None,
        chunking_enabled: bool | None = None,
        chunk_min_chars: int | None = None,
        ai_job: AIJobRecord | None = None,
    ) -> bytes:
        resolved_chunking_enabled, resolved_chunk_min_chars = self._resolve_chunk_settings(
            chunking_enabled,
            chunk_min_chars,
        )
        resolved_api_type = self._resolve_api_type(api_type, endpoint_id)
        if resolved_api_type == CHARACTER_TTS_API_GEN_SERVER:
            if gen_server_tts_mode == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3:
                caption = voice_caption.strip()
                if not caption:
                    raise TTSServiceError("VoiceDesign v3で読み上げるにはキャプションが必要です。")
                endpoint = self.resolve_gen_server_voice_design_endpoint()
                model_id, params = self._gen_server_voice_design_options(gen_server_params or {})
                return await self._voice_design_client(endpoint).synthesize(
                    text,
                    caption,
                    voice_path,
                    model_id=model_id,
                    params=params,
                    filename=filename,
                    content_type=content_type,
                    chunking_enabled=resolved_chunking_enabled,
                    chunk_min_chars=resolved_chunk_min_chars,
                    ai_job=ai_job,
                )

            endpoint = self.resolve_gen_server_voice_clone_endpoint()
            model_id, params = self._gen_server_voice_clone_options(gen_server_params or {})
            return await self._voice_clone_client(endpoint).synthesize(
                text,
                voice_path,
                model_id=model_id,
                params=params,
                filename=filename,
                content_type=content_type,
                chunking_enabled=resolved_chunking_enabled,
                chunk_min_chars=resolved_chunk_min_chars,
                ai_job=ai_job,
            )

        endpoint = self.resolve_endpoint(self._resolve_tts_endpoint_id(endpoint_id))
        if endpoint.provider == TTS_PROVIDER_IRODORI_SERVER:
            return await IrodoriTTSServerClient(endpoint).synthesize(
                self.voice_id_for_character(character_id, voice_id),
                text,
                chunking_enabled=resolved_chunking_enabled,
                chunk_min_chars=resolved_chunk_min_chars,
            )
        return await IrodoriGradioClient(endpoint).synthesize(
            text,
            voice_path,
            filename=filename,
            content_type=content_type,
            chunking_enabled=resolved_chunking_enabled,
            chunk_min_chars=resolved_chunk_min_chars,
        )

    def start_synthesize_job(
        self,
        character_id: str,
        voice_path: Path | None,
        text: str,
        *,
        endpoint_id: str = "",
        voice_id: str = "",
        filename: str = "",
        content_type: str = "",
        api_type: str = CHARACTER_TTS_API_TTS,
        gen_server_tts_mode: str = CHARACTER_GEN_SERVER_TTS_MODE_CLONE,
        voice_caption: str = "",
        gen_server_params: dict[str, Any] | None = None,
        chunking_enabled: bool | None = None,
        chunk_min_chars: int | None = None,
        label: str = "読み上げ",
        scope: str = "",
        metadata: dict[str, Any] | None = None,
        result_handler: Callable[[bytes, AIJobRecord], Awaitable[Any] | Any] | None = None,
    ) -> AIJobRecord:
        if self._ai_jobs is None:
            raise TTSServiceError("AIジョブサービスが初期化されていません。")

        async def _runner(job: AIJobRecord) -> Any:
            audio = await self.synthesize(
                character_id,
                voice_path,
                text,
                endpoint_id=endpoint_id,
                voice_id=voice_id,
                filename=filename,
                content_type=content_type,
                api_type=api_type,
                gen_server_tts_mode=gen_server_tts_mode,
                voice_caption=voice_caption,
                gen_server_params=gen_server_params,
                chunking_enabled=chunking_enabled,
                chunk_min_chars=chunk_min_chars,
                ai_job=job,
            )
            if result_handler is None:
                return audio
            handled = result_handler(audio, job)
            if inspect.isawaitable(handled):
                handled = await handled
            if isinstance(handled, dict):
                self._ai_jobs.set_result_meta(job.id, handled)
            return handled if handled is not None else audio

        return self._ai_jobs.start_job(
            kind=AIJobKind.TTS_SYNTHESIS,
            label=label,
            scope=scope,
            metadata=metadata,
            runner=_runner,
        )

    def start_design_voice_job(
        self,
        text: str,
        caption: str,
        *,
        voice_path: Path | None = None,
        filename: str = "",
        content_type: str = "",
        gen_server_params: dict[str, Any] | None = None,
        label: str = "ボイスデザイン",
        scope: str = "",
        metadata: dict[str, Any] | None = None,
        result_handler: Callable[[bytes, AIJobRecord], Awaitable[Any] | Any] | None = None,
    ) -> AIJobRecord:
        if self._ai_jobs is None:
            raise TTSServiceError("AIジョブサービスが初期化されていません。")

        async def _runner(job: AIJobRecord) -> Any:
            audio = await self.design_voice(
                text,
                caption,
                voice_path=voice_path,
                filename=filename,
                content_type=content_type,
                gen_server_params=gen_server_params,
                ai_job=job,
            )
            if result_handler is None:
                return audio
            handled = result_handler(audio, job)
            if inspect.isawaitable(handled):
                handled = await handled
            if isinstance(handled, dict):
                self._ai_jobs.set_result_meta(job.id, handled)
            return handled if handled is not None else audio

        return self._ai_jobs.start_job(
            kind=AIJobKind.TTS_DESIGN,
            label=label,
            scope=scope,
            metadata=metadata,
            runner=_runner,
        )

    def _resolve_api_type(self, api_type: str, endpoint_id: str = "") -> str:
        gen_server_available = self._has_gen_server_voice_endpoint()
        endpoint_exists = bool(endpoint_id) and any(
            endpoint.id == endpoint_id for endpoint in self.get_endpoints()
        )
        if api_type == CHARACTER_TTS_API_GEN_SERVER and gen_server_available:
            return CHARACTER_TTS_API_GEN_SERVER
        if api_type == CHARACTER_TTS_API_TTS and endpoint_exists:
            return CHARACTER_TTS_API_TTS
        if gen_server_available:
            return CHARACTER_TTS_API_GEN_SERVER
        return CHARACTER_TTS_API_TTS

    def _resolve_tts_endpoint_id(self, endpoint_id: str = "") -> str:
        endpoint_ids = {endpoint.id for endpoint in self.get_endpoints()}
        return endpoint_id if endpoint_id in endpoint_ids else ""

    def _resolve_chunk_settings(
        self,
        chunking_enabled: bool | None,
        chunk_min_chars: int | None,
    ) -> tuple[bool, int]:
        default_enabled, default_min_chars = self.chunk_settings()
        enabled = default_enabled if chunking_enabled is None else bool(chunking_enabled)
        min_chars = default_min_chars if chunk_min_chars is None else int(chunk_min_chars)
        return enabled, max(1, min_chars)

    def _gen_server_voice_clone_options(self, overrides: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        return self._gen_server_mode_options(GEN_SERVER_MODE_IRODORI_VOICE_CLONE, overrides)

    def _gen_server_voice_design_options(self, overrides: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        return self._gen_server_mode_options(GEN_SERVER_MODE_IRODORI_VOICE_DESIGN, overrides)

    def _gen_server_mode_options(self, mode: str, overrides: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        config = self._api_config.get_gen_server_config()
        defaults = config.defaults_for_mode(mode)
        merged = {
            **defaults,
            **clean_gen_server_mode_defaults(mode, overrides),
        }
        model_id = str(merged.pop("model_id", "") or "").strip()
        params = {
            key: value
            for key, value in clean_gen_server_mode_defaults(mode, merged).items()
            if value is not None
        }
        return model_id, params


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
        chunks = _speech_chunks(text, enabled=chunking_enabled, min_chars=chunk_min_chars)
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
                    await self._synthesize_once(client, config, api_name, chunk, audio_input)
                    for chunk in chunks
                ]
                return _concat_wav_bytes(audio_chunks)
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
        audio_ref = self._first_audio_reference(result)
        if audio_ref is None:
            raise TTSServiceError("Irodori-TTS Gradioの生成結果に音声が含まれていません。")
        return await self._download_audio(client, audio_ref)

    async def _fetch_config(self, client: httpx.AsyncClient) -> dict[str, Any]:
        response = await client.get("/config")
        _raise_for_error(response, "Irodori-TTS Gradio")
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
        _raise_for_error(response, "Irodori-TTS Gradio")
        uploaded = response.json()
        path = _first_uploaded_path(uploaded)
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
        _raise_for_error(response, "Irodori-TTS Gradio")
        return response.json()

    async def _download_audio(self, client: httpx.AsyncClient, audio_ref: str) -> bytes:
        candidates = _audio_download_candidates(self._base_url, audio_ref)
        response = await self._get_first_available(client, candidates)
        _raise_for_error(response, "Irodori-TTS Gradio")
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
        dependency = _generation_dependency(config)
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
        defaults = _component_defaults(config)
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

    def _first_audio_reference(self, result: Any) -> str | None:
        if isinstance(result, dict):
            data = result.get("data")
            if isinstance(data, list):
                found = self._first_audio_reference(data)
                if found:
                    return found
            for key in ["output", *(f"output_{index}" for index in range(1, 32))]:
                if key in result:
                    found = _extract_audio_reference(result[key])
                    if found:
                        return found
            return _extract_audio_reference(result)
        if not isinstance(result, list):
            return _extract_audio_reference(result)
        for item in result[:32]:
            ref = _extract_audio_reference(item)
            if ref:
                return ref
        return None


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
        _raise_for_error(response, "Irodori-TTS-Server")
        return response.json()

    async def delete_voice(self, voice_id: str) -> bool:
        async with self._client(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
            response = await client.delete(f"/v1/audio/voices/{voice_id}")
        if response.status_code == 404:
            return False
        _raise_for_error(response, "Irodori-TTS-Server")
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
        _raise_for_error(response, "Irodori-TTS-Server")
        return response.content

    def _client(self, *, timeout: float | httpx.Timeout = 30.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base_url, timeout=timeout)


class WizmyGenServerVoiceCloneClient:
    RESPONSE_FORMAT = "wav"
    POLL_LIMIT = 600

    def __init__(
        self,
        endpoint: GenServerEndpoint,
        ai_jobs: AIJobService | None = None,
    ) -> None:
        self._base_url = gen_server_api_root(endpoint.base_url)
        self._ai_jobs = ai_jobs
        if not self._base_url:
            raise TTSServiceError("Wizmy-Gen-ServerのURLを設定してください。")

    async def synthesize(
        self,
        text: str,
        voice_path: Path | None,
        *,
        model_id: str,
        params: dict[str, Any],
        filename: str = "",
        content_type: str = "",
        chunking_enabled: bool = True,
        chunk_min_chars: int = DEFAULT_CHUNK_MIN_CHARS,
        ai_job: AIJobRecord | None = None,
    ) -> bytes:
        if voice_path is None:
            raise TTSServiceError("Wizmy-Gen-Serverで読み上げるには参照音声が必要です。")
        chunks = _speech_chunks(text, enabled=chunking_enabled, min_chars=chunk_min_chars)
        async with self._client(timeout=httpx.Timeout(300.0, connect=5.0)) as client:
            try:
                audio_chunks = [
                    await self._synthesize_once(
                        client,
                        chunk,
                        voice_path,
                        model_id=model_id,
                        params=params,
                        filename=filename,
                        content_type=content_type,
                        ai_job=ai_job,
                    )
                    for chunk in chunks
                ]
                return _concat_wav_bytes(audio_chunks)
            except httpx.HTTPError as exc:
                raise TTSServiceError(f"Wizmy-Gen-Serverへの接続に失敗しました: {exc}") from exc

    async def _synthesize_once(
        self,
        client: httpx.AsyncClient,
        text: str,
        voice_path: Path,
        *,
        model_id: str,
        params: dict[str, Any],
        filename: str,
        content_type: str,
        ai_job: AIJobRecord | None = None,
    ) -> bytes:
        name = filename or voice_path.name
        media_type = content_type or mimetypes.guess_type(name)[0] or "audio/wav"
        data = {
            "text": text,
            "params": json.dumps(params, ensure_ascii=False),
        }
        if model_id:
            data["model_id"] = model_id
        with voice_path.open("rb") as handle:
            files = {"reference_audio": (name, handle, media_type)}
            response = await client.post("/v1/tts/clone/jobs", data=data, files=files)
        _raise_for_error(response, "Wizmy-Gen-Server")
        job_id = str(response.json().get("job_id") or "")
        if not job_id:
            raise TTSServiceError("Wizmy-Gen-ServerのジョブIDを取得できませんでした。")
        self._attach_external_job(ai_job, job_id, "tts.clone")
        result = await self._wait_job_result(client, job_id, ai_job=ai_job)
        audio_url = _first_audio_artifact_url(result)
        if not audio_url:
            raise TTSServiceError("Wizmy-Gen-Serverの生成結果に音声が含まれていません。")
        audio_response = await client.get(audio_url)
        _raise_for_error(audio_response, "Wizmy-Gen-Server")
        return audio_response.content

    async def _wait_job_result(
        self,
        client: httpx.AsyncClient,
        job_id: str,
        *,
        ai_job: AIJobRecord | None = None,
    ) -> dict[str, Any]:
        for _ in range(self.POLL_LIMIT):
            response = await client.get(f"/v1/jobs/{job_id}/result")
            if response.status_code == 202:
                retry_after = response.json().get("retry_after_seconds", 1)
                try:
                    delay = max(0.2, min(5.0, float(retry_after)))
                except (TypeError, ValueError):
                    delay = 1.0
                if self._ai_jobs is not None and ai_job is not None:
                    self._ai_jobs.update_progress(ai_job.id, "音声生成中...")
                await asyncio.sleep(delay)
                continue
            _raise_for_error(response, "Wizmy-Gen-Server")
            return response.json()
        raise TTSServiceError("Wizmy-Gen-Serverの音声生成がタイムアウトしました。")

    def _attach_external_job(
        self,
        ai_job: AIJobRecord | None,
        job_id: str,
        kind: str,
    ) -> None:
        if ai_job is None:
            return
        if self._ai_jobs is not None:
            self._ai_jobs.add_external_job(
                ai_job.id,
                {
                    "provider": "wizmy-gen-server",
                    "job_id": job_id,
                    "kind": kind,
                },
            )

        async def _cancel_external(_: AIJobRecord) -> None:
            async with self._client(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
                await client.post(f"/v1/jobs/{job_id}/cancel")

        ai_job.add_cancel_callback(_cancel_external)

    def _client(self, *, timeout: float | httpx.Timeout = 30.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base_url, timeout=timeout)


class WizmyGenServerVoiceDesignClient(WizmyGenServerVoiceCloneClient):
    async def synthesize(
        self,
        text: str,
        caption: str,
        voice_path: Path | None = None,
        *,
        model_id: str,
        params: dict[str, Any],
        filename: str = "",
        content_type: str = "",
        chunking_enabled: bool = True,
        chunk_min_chars: int = DEFAULT_CHUNK_MIN_CHARS,
        ai_job: AIJobRecord | None = None,
    ) -> bytes:
        if voice_path is None:
            params = {**params, "no_ref": True}
        else:
            params = {**params, "no_ref": False}
        chunks = _speech_chunks(text, enabled=chunking_enabled, min_chars=chunk_min_chars)
        async with self._client(timeout=httpx.Timeout(300.0, connect=5.0)) as client:
            try:
                audio_chunks = [
                    await self._synthesize_once(
                        client,
                        chunk,
                        caption,
                        voice_path,
                        model_id=model_id,
                        params=params,
                        filename=filename,
                        content_type=content_type,
                        ai_job=ai_job,
                    )
                    for chunk in chunks
                ]
                return _concat_wav_bytes(audio_chunks)
            except httpx.HTTPError as exc:
                raise TTSServiceError(f"Wizmy-Gen-Serverへの接続に失敗しました: {exc}") from exc

    async def _synthesize_once(
        self,
        client: httpx.AsyncClient,
        text: str,
        caption: str,
        voice_path: Path | None,
        *,
        model_id: str,
        params: dict[str, Any],
        filename: str,
        content_type: str,
        ai_job: AIJobRecord | None = None,
    ) -> bytes:
        data = {
            "text": text,
            "caption": caption,
            "params": json.dumps(params, ensure_ascii=False),
        }
        if model_id:
            data["model_id"] = model_id
        if voice_path is None:
            response = await client.post("/v1/tts/design/jobs", data=data)
        else:
            name = filename or voice_path.name
            media_type = content_type or mimetypes.guess_type(name)[0] or "audio/wav"
            with voice_path.open("rb") as handle:
                files = {"reference_audio": (name, handle, media_type)}
                response = await client.post("/v1/tts/design/jobs", data=data, files=files)
        _raise_for_error(response, "Wizmy-Gen-Server")
        job_id = str(response.json().get("job_id") or "")
        if not job_id:
            raise TTSServiceError("Wizmy-Gen-ServerのジョブIDを取得できませんでした。")
        self._attach_external_job(ai_job, job_id, "tts.design")
        result = await self._wait_job_result(client, job_id, ai_job=ai_job)
        audio_url = _first_audio_artifact_url(result)
        if not audio_url:
            raise TTSServiceError("Wizmy-Gen-Serverの生成結果に音声が含まれていません。")
        audio_response = await client.get(audio_url)
        _raise_for_error(audio_response, "Wizmy-Gen-Server")
        return audio_response.content


def _voice_id_for_character(character_id: str) -> str:
    return f"charagen-{character_id}"


def _speech_chunks(
    text: str,
    *,
    enabled: bool,
    min_chars: int,
) -> list[str]:
    if not enabled:
        return [text]
    if min_chars <= 0:
        raise TTSServiceError("chunk_min_charsは1以上にしてください。")
    return _split_text_for_speech(text, min_chars=min_chars)


def _split_text_for_speech(text: str, *, min_chars: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_chars = 0

    for char in text:
        current.append(char)
        if not char.isspace():
            current_chars += 1
        if char in CHUNK_BOUNDARIES and current_chars >= min_chars:
            chunk = "".join(current).strip()
            if chunk:
                chunks.append(chunk)
            current = []
            current_chars = 0

    tail = "".join(current).strip()
    if tail:
        chunks.append(tail)
    return chunks or [text]


def _concat_wav_bytes(audio_chunks: list[bytes]) -> bytes:
    if not audio_chunks:
        raise TTSServiceError("生成された音声が空です。")
    if len(audio_chunks) == 1:
        return audio_chunks[0]

    output = BytesIO()
    expected_params: tuple[int, int, int, str, str] | None = None
    with wave.open(output, "wb") as out_wav:
        for audio in audio_chunks:
            with wave.open(BytesIO(audio), "rb") as in_wav:
                params = (
                    in_wav.getnchannels(),
                    in_wav.getsampwidth(),
                    in_wav.getframerate(),
                    in_wav.getcomptype(),
                    in_wav.getcompname(),
                )
                if expected_params is None:
                    expected_params = params
                    out_wav.setnchannels(params[0])
                    out_wav.setsampwidth(params[1])
                    out_wav.setframerate(params[2])
                    out_wav.setcomptype(params[3], params[4])
                elif params != expected_params:
                    raise TTSServiceError("チャンク音声のWAV形式が一致しません。")
                out_wav.writeframes(in_wav.readframes(in_wav.getnframes()))
    return output.getvalue()


def _component_defaults(config: dict[str, Any]) -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    for component in config.get("components", []):
        props = component.get("props", {})
        label = props.get("label")
        if label:
            defaults[str(label)] = props.get("value")
    return defaults


def _generation_dependency(config: dict[str, Any]) -> dict[str, Any] | None:
    dependencies = config.get("dependencies", [])
    for dependency in dependencies:
        api_name = str(dependency.get("api_name") or "").strip("/")
        if api_name in {"run_generation", "_run_generation", "predict"}:
            return dependency
    for dependency in dependencies:
        if len(dependency.get("inputs", [])) == 28 and len(dependency.get("outputs", [])) >= 34:
            return dependency
    return None


def _first_uploaded_path(uploaded: Any) -> str | None:
    if isinstance(uploaded, str):
        return uploaded
    if isinstance(uploaded, dict):
        value = uploaded.get("path") or uploaded.get("name")
        return None if value is None else str(value)
    if isinstance(uploaded, list):
        for item in uploaded:
            path = _first_uploaded_path(item)
            if path:
                return path
    return None


def _first_audio_artifact_url(result: dict[str, Any]) -> str | None:
    artifacts = result.get("artifacts") if isinstance(result, dict) else None
    if not isinstance(artifacts, list):
        return None
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        mime_type = str(artifact.get("mime_type") or "")
        artifact_type = str(artifact.get("type") or "")
        url = str(artifact.get("url") or "")
        if url and (artifact_type == "audio" or mime_type.startswith("audio/")):
            return url
    return None


def _extract_audio_reference(value: Any) -> str | None:
    if isinstance(value, str) and _looks_like_audio_reference(value):
        return value
    if not isinstance(value, dict):
        return None
    if "value" in value:
        found = _extract_audio_reference(value["value"])
        if found:
            return found
    for key in ("url", "path", "name"):
        raw = value.get(key)
        if raw:
            return str(raw)
    return None


def _looks_like_audio_reference(value: str) -> bool:
    if not value:
        return False
    lowered = value.lower().split("?", 1)[0]
    if lowered.startswith(("http://", "https://", "/", "file=")):
        return True
    return lowered.endswith((".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"))


def _audio_download_candidates(base_url: str, audio_ref: str) -> list[str]:
    if audio_ref.startswith("http://") or audio_ref.startswith("https://"):
        return [audio_ref]
    if audio_ref.startswith("/"):
        return [audio_ref]
    encoded = quote(audio_ref, safe="/:")
    return [
        f"/gradio_api/file={encoded}",
        f"/file={encoded}",
        urljoin(base_url + "/", audio_ref),
    ]


def _raise_for_error(response: httpx.Response, provider_name: str) -> None:
    if response.is_success:
        return
    raise TTSServiceError(_response_error_message(response, provider_name))


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
