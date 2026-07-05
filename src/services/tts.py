"""TTS クライアントを選択して音声合成を実行するサービス。"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal, overload

from ..core.character.schemas import (
    CHARACTER_GEN_SERVER_TTS_MODE_CLONE,
    CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3,
    CHARACTER_TTS_API_GEN_SERVER,
    CHARACTER_TTS_API_TTS,
)
from ..core.gen_server.schemas import (
    GEN_SERVER_MODE_IRODORI_VOICE_CLONE,
    GEN_SERVER_MODE_IRODORI_VOICE_DESIGN,
    GenServerEndpoint,
    clean_gen_server_mode_defaults,
)
from ..core.tts.schemas import (
    TTS_PROVIDER_IRODORI_SERVER,
    TTSEndpoint,
)
from ..core.tts_clients import irodori as _irodori_clients
from ..core.tts_clients import wizmy_gen_server as _wizmy_gen_server_clients
from ..core.tts_clients.audio import DEFAULT_CHUNK_MIN_CHARS as _DEFAULT_CHUNK_MIN_CHARS
from ..core.tts_clients.audio import TTSServiceError
from .ai_jobs import AIJobKind, AIJobRecord, AIJobService
from .api_config import ApiConfigService


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
        if (
            api_type == CHARACTER_TTS_API_TTS
            and endpoint_id
            and any(endpoint.id == endpoint_id for endpoint in endpoints)
        ):
            return True
        return gen_server_available or bool(endpoints)

    def _voice_clone_client(self, endpoint: GenServerEndpoint):
        try:
            return _wizmy_gen_server_clients.WizmyGenServerVoiceCloneClient(
                endpoint,
                self._ai_jobs,
            )
        except TypeError:
            return _wizmy_gen_server_clients.WizmyGenServerVoiceCloneClient(endpoint)

    def _voice_design_client(self, endpoint: GenServerEndpoint):
        try:
            return _wizmy_gen_server_clients.WizmyGenServerVoiceDesignClient(
                endpoint,
                self._ai_jobs,
            )
        except TypeError:
            return _wizmy_gen_server_clients.WizmyGenServerVoiceDesignClient(endpoint)

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
            max(1, int(config.voice_chunk_min_chars or _DEFAULT_CHUNK_MIN_CHARS)),
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
        return voice_id.strip() or f"charagen-{character_id}"

    @overload
    def resolve_gen_server_voice_clone_endpoint(
        self,
        *,
        raise_on_missing: Literal[True] = True,
    ) -> GenServerEndpoint: ...

    @overload
    def resolve_gen_server_voice_clone_endpoint(
        self,
        *,
        raise_on_missing: Literal[False],
    ) -> GenServerEndpoint | None: ...

    @overload
    def resolve_gen_server_voice_clone_endpoint(
        self,
        *,
        raise_on_missing: bool,
    ) -> GenServerEndpoint | None: ...

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

    @overload
    def resolve_gen_server_voice_design_endpoint(
        self,
        *,
        raise_on_missing: Literal[True] = True,
    ) -> GenServerEndpoint: ...

    @overload
    def resolve_gen_server_voice_design_endpoint(
        self,
        *,
        raise_on_missing: Literal[False],
    ) -> GenServerEndpoint | None: ...

    @overload
    def resolve_gen_server_voice_design_endpoint(
        self,
        *,
        raise_on_missing: bool,
    ) -> GenServerEndpoint | None: ...

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

    @overload
    def _resolve_gen_server_endpoint(
        self,
        mode: str,
        label: str,
        *,
        raise_on_missing: Literal[True] = True,
    ) -> GenServerEndpoint: ...

    @overload
    def _resolve_gen_server_endpoint(
        self,
        mode: str,
        label: str,
        *,
        raise_on_missing: Literal[False],
    ) -> GenServerEndpoint | None: ...

    @overload
    def _resolve_gen_server_endpoint(
        self,
        mode: str,
        label: str,
        *,
        raise_on_missing: bool,
    ) -> GenServerEndpoint | None: ...

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
        return await _irodori_clients.IrodoriTTSServerClient(endpoint).register_voice(
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
        return await _irodori_clients.IrodoriTTSServerClient(endpoint).delete_voice(
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
                gen_server_endpoint = self.resolve_gen_server_voice_design_endpoint()
                model_id, params = self._gen_server_voice_design_options(gen_server_params or {})
                return await self._voice_design_client(gen_server_endpoint).synthesize(
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

            gen_server_endpoint = self.resolve_gen_server_voice_clone_endpoint()
            model_id, params = self._gen_server_voice_clone_options(gen_server_params or {})
            return await self._voice_clone_client(gen_server_endpoint).synthesize(
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

        tts_endpoint = self.resolve_endpoint(self._resolve_tts_endpoint_id(endpoint_id))
        if tts_endpoint.provider == TTS_PROVIDER_IRODORI_SERVER:
            return await _irodori_clients.IrodoriTTSServerClient(tts_endpoint).synthesize(
                self.voice_id_for_character(character_id, voice_id),
                text,
                chunking_enabled=resolved_chunking_enabled,
                chunk_min_chars=resolved_chunk_min_chars,
            )
        return await _irodori_clients.IrodoriGradioClient(tts_endpoint).synthesize(
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
        ai_jobs = self._ai_jobs
        if ai_jobs is None:
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
                ai_jobs.set_result_meta(job.id, handled)
            return handled if handled is not None else audio

        return ai_jobs.start_job(
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
        ai_jobs = self._ai_jobs
        if ai_jobs is None:
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
                ai_jobs.set_result_meta(job.id, handled)
            return handled if handled is not None else audio

        return ai_jobs.start_job(
            kind=AIJobKind.TTS_DESIGN,
            label=label,
            scope=scope,
            metadata=metadata,
            runner=_runner,
        )

    def _resolve_api_type(self, api_type: str, endpoint_id: str = "") -> str:
        gen_server_available = self._has_gen_server_voice_endpoint()
        endpoint_exists = bool(endpoint_id) and any(endpoint.id == endpoint_id for endpoint in self.get_endpoints())
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
            key: value for key, value in clean_gen_server_mode_defaults(mode, merged).items() if value is not None
        }
        return model_id, params
