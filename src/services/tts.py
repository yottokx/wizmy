"""TTS provider integration service."""

from __future__ import annotations

import mimetypes
import secrets
import wave
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import httpx

from ..core.tts.schemas import (
    TTS_PROVIDER_IRODORI_GRADIO,
    TTS_PROVIDER_IRODORI_SERVER,
    TTSEndpoint,
)
from .api_config import ApiConfigService


CHUNK_BOUNDARIES = frozenset("。、，,．.!！?？\n\r")
DEFAULT_CHUNK_MIN_CHARS = 80


class TTSServiceError(RuntimeError):
    """Raised when a TTS provider request fails."""


class TTSService:
    def __init__(self, api_config: ApiConfigService) -> None:
        self._api_config = api_config

    def get_endpoints(self) -> list[TTSEndpoint]:
        return self._api_config.get_tts_endpoints()

    def default_endpoint_id(self) -> str:
        config = self._api_config.get_tts_config()
        if config.default_endpoint_id and any(
            endpoint.id == config.default_endpoint_id for endpoint in config.endpoints
        ):
            return config.default_endpoint_id
        return config.endpoints[0].id if config.endpoints else ""

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
        chunking_enabled: bool = True,
        chunk_min_chars: int = DEFAULT_CHUNK_MIN_CHARS,
    ) -> bytes:
        endpoint = self.resolve_endpoint(endpoint_id)
        if endpoint.provider == TTS_PROVIDER_IRODORI_SERVER:
            return await IrodoriTTSServerClient(endpoint).synthesize(
                self.voice_id_for_character(character_id, voice_id),
                text,
                chunking_enabled=chunking_enabled,
                chunk_min_chars=chunk_min_chars,
            )
        return await IrodoriGradioClient(endpoint).synthesize(
            text,
            voice_path,
            filename=filename,
            content_type=content_type,
            chunking_enabled=chunking_enabled,
            chunk_min_chars=chunk_min_chars,
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
