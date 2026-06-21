from __future__ import annotations

import json
import tempfile
import unittest
import asyncio
from pathlib import Path
from unittest.mock import patch

import httpx

from src.core.character.schemas import (
    CHARACTER_GEN_SERVER_TTS_MODE_CLONE,
    CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3,
    CHARACTER_TTS_API_GEN_SERVER,
    CharacterTTSSettings,
)
from src.core.gen_server.schemas import (
    GEN_SERVER_MODE_IRODORI_VOICE_CLONE,
    GEN_SERVER_MODE_IRODORI_VOICE_DESIGN,
    GenServerEndpoint,
    clean_gen_server_mode_defaults,
    default_gen_server_mode_defaults,
)
from src.services.api_config import ApiConfigService
from src.services.ai_jobs import AIJobKind, AIJobService, AIJobStatus
from src.services.tts import (
    TTSService,
    TTSServiceError,
    WizmyGenServerVoiceDesignClient,
)
from src.storage.api_config_store import ApiConfigStore


class TTSVoiceDesignV3Test(unittest.IsolatedAsyncioTestCase):
    def test_tts_settings_keep_backward_compatibility(self) -> None:
        settings = CharacterTTSSettings.model_validate({
            "api_type": CHARACTER_TTS_API_GEN_SERVER,
            "gen_server_params": {"steps": 20},
        })

        self.assertEqual(settings.gen_server_tts_mode, CHARACTER_GEN_SERVER_TTS_MODE_CLONE)
        self.assertEqual(settings.voice_caption, "")
        self.assertEqual(settings.gen_server_params["steps"], 20)

    def test_voice_design_default_model_is_v3(self) -> None:
        defaults = default_gen_server_mode_defaults(GEN_SERVER_MODE_IRODORI_VOICE_DESIGN)

        self.assertEqual(
            defaults["model_id"],
            "Aratako/Irodori-TTS-600M-v3-VoiceDesign",
        )
        self.assertIn("cfg_scale_speaker", defaults)
        self.assertIn("speaker_kv_scale", defaults)

    def test_clean_defaults_drops_other_voice_mode_default_model_id(self) -> None:
        cleaned = clean_gen_server_mode_defaults(
            GEN_SERVER_MODE_IRODORI_VOICE_CLONE,
            {
                "model_id": "Aratako/Irodori-TTS-600M-v3-VoiceDesign",
                "steps": 20,
            },
        )

        self.assertNotIn("model_id", cleaned)
        self.assertEqual(cleaned["steps"], 20)

    async def test_service_uses_design_client_for_voice_design_v3_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = _tts_service(Path(tmp))
            voice_path = Path(tmp) / "voice.wav"
            voice_path.write_bytes(b"mock")
            calls: list[dict[str, object]] = []

            class FakeDesignClient:
                def __init__(self, endpoint: GenServerEndpoint) -> None:
                    self.endpoint = endpoint

                async def synthesize(
                    self,
                    text: str,
                    caption: str,
                    voice_path_arg: Path | None,
                    **kwargs,
                ) -> bytes:
                    calls.append({
                        "endpoint_id": self.endpoint.id,
                        "text": text,
                        "caption": caption,
                        "voice_path": voice_path_arg,
                        "kwargs": kwargs,
                    })
                    return b"audio"

            with patch("src.services.tts.WizmyGenServerVoiceDesignClient", FakeDesignClient):
                audio = await service.synthesize(
                    "char-1",
                    voice_path,
                    "こんにちは。",
                    api_type=CHARACTER_TTS_API_GEN_SERVER,
                    gen_server_tts_mode=CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3,
                    voice_caption="明るく柔らかい声",
                    gen_server_params={"cfg_scale_speaker": 4.0},
                )

            self.assertEqual(audio, b"audio")
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["endpoint_id"], "gen-1")
            self.assertEqual(calls[0]["caption"], "明るく柔らかい声")
            self.assertEqual(calls[0]["voice_path"], voice_path)
            kwargs = calls[0]["kwargs"]
            self.assertEqual(kwargs["model_id"], "Aratako/Irodori-TTS-600M-v3-VoiceDesign")
            self.assertEqual(kwargs["params"]["cfg_scale_speaker"], 4.0)
            self.assertIs(kwargs["params"]["no_ref"], False)

    async def test_service_clone_ignores_carried_voice_design_default_model_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = _tts_service(Path(tmp))
            voice_path = Path(tmp) / "voice.wav"
            voice_path.write_bytes(b"mock")
            calls: list[dict[str, object]] = []

            class FakeCloneClient:
                def __init__(self, endpoint: GenServerEndpoint) -> None:
                    self.endpoint = endpoint

                async def synthesize(
                    self,
                    text: str,
                    voice_path_arg: Path | None,
                    **kwargs,
                ) -> bytes:
                    calls.append({
                        "endpoint_id": self.endpoint.id,
                        "text": text,
                        "voice_path": voice_path_arg,
                        "kwargs": kwargs,
                    })
                    return b"audio"

            with patch("src.services.tts.WizmyGenServerVoiceCloneClient", FakeCloneClient):
                audio = await service.synthesize(
                    "char-1",
                    voice_path,
                    "hello",
                    api_type=CHARACTER_TTS_API_GEN_SERVER,
                    gen_server_tts_mode=CHARACTER_GEN_SERVER_TTS_MODE_CLONE,
                    gen_server_params={
                        "model_id": "Aratako/Irodori-TTS-600M-v3-VoiceDesign",
                        "steps": 20,
                    },
                )

            self.assertEqual(audio, b"audio")
            self.assertEqual(len(calls), 1)
            kwargs = calls[0]["kwargs"]
            self.assertEqual(kwargs["model_id"], "Aratako/Irodori-TTS-500M-v3")
            self.assertEqual(kwargs["params"]["steps"], 20)

    async def test_service_rejects_voice_design_v3_without_caption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = _tts_service(Path(tmp))
            voice_path = Path(tmp) / "voice.wav"
            voice_path.write_bytes(b"mock")

            with self.assertRaises(TTSServiceError):
                await service.synthesize(
                    "char-1",
                    voice_path,
                    "こんにちは。",
                    api_type=CHARACTER_TTS_API_GEN_SERVER,
                    gen_server_tts_mode=CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3,
                    voice_caption="",
                )

    async def test_design_client_posts_caption_and_reference_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            voice_path = Path(tmp) / "voice.wav"
            voice_path.write_bytes(b"mock wav")
            posts: list[tuple[str, bytes]] = []

            async def handler(request: httpx.Request) -> httpx.Response:
                if request.method == "POST" and request.url.path == "/v1/tts/design/jobs":
                    posts.append((request.headers.get("content-type", ""), await request.aread()))
                    return httpx.Response(200, json={"job_id": "job-1"})
                if request.method == "GET" and request.url.path == "/v1/jobs/job-1/result":
                    return httpx.Response(
                        200,
                        json={
                            "artifacts": [
                                {"type": "audio", "url": "/v1/artifacts/job-1/audio.wav"}
                            ]
                        },
                    )
                if request.method == "GET" and request.url.path == "/v1/artifacts/job-1/audio.wav":
                    return httpx.Response(200, content=b"audio")
                return httpx.Response(404)

            class MockedDesignClient(WizmyGenServerVoiceDesignClient):
                def _client(self, *, timeout: float | httpx.Timeout = 30.0) -> httpx.AsyncClient:
                    return httpx.AsyncClient(
                        base_url=self._base_url,
                        transport=httpx.MockTransport(handler),
                        timeout=timeout,
                    )

            client = MockedDesignClient(
                GenServerEndpoint(
                    id="gen-1",
                    name="Local Gen",
                    base_url="http://127.0.0.1:8008/v1",
                )
            )
            audio = await client.synthesize(
                "こんにちは。",
                "明るく柔らかい声",
                voice_path,
                model_id="Aratako/Irodori-TTS-600M-v3-VoiceDesign",
                params={"no_ref": False},
                chunking_enabled=False,
            )

            self.assertEqual(audio, b"audio")
            self.assertEqual(len(posts), 1)
            content_type, body = posts[0]
            self.assertIn("multipart/form-data", content_type)
            self.assertIn(b'name="caption"', body)
            self.assertIn("明るく柔らかい声".encode("utf-8"), body)
            self.assertIn(b'name="reference_audio"; filename="voice.wav"', body)

    async def test_design_client_records_external_job_and_calls_cancel(self) -> None:
        cancel_paths: list[str] = []
        service = AIJobService()

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/v1/tts/design/jobs":
                return httpx.Response(200, json={"job_id": "job-1"})
            if request.method == "GET" and request.url.path == "/v1/jobs/job-1/result":
                await asyncio.sleep(60)
                return httpx.Response(202, json={"retry_after_seconds": 1})
            if request.method == "POST" and request.url.path == "/v1/jobs/job-1/cancel":
                cancel_paths.append(request.url.path)
                return httpx.Response(200, json={"status": "cancelled"})
            return httpx.Response(404)

        class MockedDesignClient(WizmyGenServerVoiceDesignClient):
            def _client(self, *, timeout: float | httpx.Timeout = 30.0) -> httpx.AsyncClient:
                return httpx.AsyncClient(
                    base_url=self._base_url,
                    transport=httpx.MockTransport(handler),
                    timeout=timeout,
                )

        client = MockedDesignClient(
            GenServerEndpoint(
                id="gen-1",
                name="Local Gen",
                base_url="http://127.0.0.1:8008/v1",
            ),
            service,
        )

        job = service.start_job(
            kind=AIJobKind.TTS_DESIGN,
            label="外部ジョブ記録",
            runner=lambda ai_job: client.synthesize(
                "こんにちは。",
                "明るい声",
                None,
                model_id="design-model",
                params={},
                chunking_enabled=False,
                ai_job=ai_job,
            ),
        )

        for _ in range(50):
            if job.external_jobs:
                break
            await asyncio.sleep(0.01)

        self.assertEqual(job.external_jobs[0]["job_id"], "job-1")
        self.assertEqual(job.external_jobs[0]["kind"], "tts.design")

        await service.cancel_job(job.id)
        finished = await service.wait(job.id)

        self.assertEqual(finished.status, AIJobStatus.CANCELLED)
        self.assertEqual(cancel_paths, ["/v1/jobs/job-1/cancel"])


def _tts_service(tmp_path: Path) -> TTSService:
    config_path = tmp_path / "api-config.json"
    config_path.write_text(
        json.dumps({
            "llm_profiles": [],
            "gen_server_config": {
                "endpoints": [
                    {
                        "id": "gen-1",
                        "name": "Local Gen",
                        "base_url": "http://127.0.0.1:8008/v1",
                    }
                ],
                "mode_assignments": {
                    GEN_SERVER_MODE_IRODORI_VOICE_CLONE: "gen-1",
                    GEN_SERVER_MODE_IRODORI_VOICE_DESIGN: "gen-1",
                },
            },
        }),
        encoding="utf-8",
    )
    return TTSService(ApiConfigService(ApiConfigStore(config_path)))


if __name__ == "__main__":
    unittest.main()
