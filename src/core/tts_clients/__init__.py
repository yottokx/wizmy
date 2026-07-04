"""TTS HTTP クライアント群。"""

from .audio import (
    DEFAULT_CHUNK_MIN_CHARS,
    TTSServiceError,
    audio_download_candidates,
    concat_wav_bytes,
    extract_audio_reference,
    first_audio_artifact_url,
    first_audio_reference,
    raise_for_error,
    response_error_message,
    speech_chunks,
    split_text_for_speech,
)
from .irodori import IrodoriGradioClient, IrodoriTTSServerClient
from .wizmy_gen_server import WizmyGenServerVoiceCloneClient, WizmyGenServerVoiceDesignClient

__all__ = [
    "DEFAULT_CHUNK_MIN_CHARS",
    "IrodoriGradioClient",
    "IrodoriTTSServerClient",
    "TTSServiceError",
    "WizmyGenServerVoiceCloneClient",
    "WizmyGenServerVoiceDesignClient",
    "audio_download_candidates",
    "concat_wav_bytes",
    "extract_audio_reference",
    "first_audio_artifact_url",
    "first_audio_reference",
    "raise_for_error",
    "response_error_message",
    "speech_chunks",
    "split_text_for_speech",
]
