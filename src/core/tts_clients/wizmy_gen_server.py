"""Wizmy-Gen-Server 向け TTS HTTP クライアント。"""

from __future__ import annotations

import asyncio
import json
import mimetypes
from pathlib import Path
from typing import Any, Protocol

import httpx

from ..gen_server.schemas import GenServerEndpoint, gen_server_api_root
from .audio import (
    DEFAULT_CHUNK_MIN_CHARS,
    TTSServiceError,
    concat_wav_bytes,
    first_audio_artifact_url,
    raise_for_error,
    speech_chunks,
)


class AIJobServiceLike(Protocol):
    def update_progress(
        self,
        job_id: str,
        message: str,
        *,
        data: Any = None,
    ) -> None: ...

    def add_external_job(
        self,
        job_id: str,
        external: dict[str, Any],
    ) -> None: ...


class WizmyGenServerVoiceCloneClient:
    RESPONSE_FORMAT = "wav"
    POLL_LIMIT = 600

    def __init__(
        self,
        endpoint: GenServerEndpoint,
        ai_jobs: AIJobServiceLike | None = None,
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
        ai_job: Any = None,
    ) -> bytes:
        if voice_path is None:
            raise TTSServiceError("Wizmy-Gen-Serverで読み上げるには参照音声が必要です。")
        chunks = speech_chunks(text, enabled=chunking_enabled, min_chars=chunk_min_chars)
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
                return concat_wav_bytes(audio_chunks)
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
        ai_job: Any = None,
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
        raise_for_error(response, "Wizmy-Gen-Server")
        job_id = str(response.json().get("job_id") or "")
        if not job_id:
            raise TTSServiceError("Wizmy-Gen-ServerのジョブIDを取得できませんでした。")
        self._attach_external_job(ai_job, job_id, "tts.clone")
        result = await self._wait_job_result(client, job_id, ai_job=ai_job)
        audio_url = first_audio_artifact_url(result)
        if not audio_url:
            raise TTSServiceError("Wizmy-Gen-Serverの生成結果に音声が含まれていません。")
        audio_response = await client.get(audio_url)
        raise_for_error(audio_response, "Wizmy-Gen-Server")
        return audio_response.content

    async def _wait_job_result(
        self,
        client: httpx.AsyncClient,
        job_id: str,
        *,
        ai_job: Any = None,
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
            raise_for_error(response, "Wizmy-Gen-Server")
            return response.json()
        raise TTSServiceError("Wizmy-Gen-Serverの音声生成がタイムアウトしました。")

    def _attach_external_job(
        self,
        ai_job: Any,
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

        async def _cancel_external(_: Any) -> None:
            async with self._client(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
                await client.post(f"/v1/jobs/{job_id}/cancel")

        ai_job.add_cancel_callback(_cancel_external)

    def _client(self, *, timeout: float | httpx.Timeout = 30.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base_url, timeout=timeout)


class WizmyGenServerVoiceDesignClient(WizmyGenServerVoiceCloneClient):
    async def synthesize(  # type: ignore[override]  # 理由: VoiceDesign は共通HTTP処理を継承しつつ、API仕様上 caption 引数を追加するため。
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
        ai_job: Any = None,
    ) -> bytes:
        if voice_path is None:
            params = {**params, "no_ref": True}
        else:
            params = {**params, "no_ref": False}
        chunks = speech_chunks(text, enabled=chunking_enabled, min_chars=chunk_min_chars)
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
                return concat_wav_bytes(audio_chunks)
            except httpx.HTTPError as exc:
                raise TTSServiceError(f"Wizmy-Gen-Serverへの接続に失敗しました: {exc}") from exc

    async def _synthesize_once(  # type: ignore[override]  # 理由: VoiceDesign のAPI仕様に合わせ、共通処理の一部だけを差し替えるため。
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
        ai_job: Any = None,
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
        raise_for_error(response, "Wizmy-Gen-Server")
        job_id = str(response.json().get("job_id") or "")
        if not job_id:
            raise TTSServiceError("Wizmy-Gen-ServerのジョブIDを取得できませんでした。")
        self._attach_external_job(ai_job, job_id, "tts.design")
        result = await self._wait_job_result(client, job_id, ai_job=ai_job)
        audio_url = first_audio_artifact_url(result)
        if not audio_url:
            raise TTSServiceError("Wizmy-Gen-Serverの生成結果に音声が含まれていません。")
        audio_response = await client.get(audio_url)
        raise_for_error(audio_response, "Wizmy-Gen-Server")
        return audio_response.content
