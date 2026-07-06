"""TTS クライアントで共有する音声・HTTP 補助。"""

from __future__ import annotations

import wave
from io import BytesIO
from typing import Any
from urllib.parse import quote, urljoin

import httpx

CHUNK_BOUNDARIES = frozenset("。、，,．.!！?？\n\r")
DEFAULT_CHUNK_MIN_CHARS = 80


class TTSServiceError(RuntimeError):
    """Raised when a TTS provider request fails."""


def speech_chunks(
    text: str,
    *,
    enabled: bool,
    min_chars: int,
) -> list[str]:
    if not enabled:
        return [text]
    if min_chars <= 0:
        raise TTSServiceError("chunk_min_charsは1以上にしてください。")
    return split_text_for_speech(text, min_chars=min_chars)


def split_text_for_speech(text: str, *, min_chars: int) -> list[str]:
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


def concat_wav_bytes(audio_chunks: list[bytes]) -> bytes:
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


def component_defaults(config: dict[str, Any]) -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    for component in config.get("components", []):
        props = component.get("props", {})
        label = props.get("label")
        if label:
            defaults[str(label)] = props.get("value")
    return defaults


def generation_dependency(config: dict[str, Any]) -> dict[str, Any] | None:
    dependencies = config.get("dependencies", [])
    for dependency in dependencies:
        api_name = str(dependency.get("api_name") or "").strip("/")
        if api_name in {"run_generation", "_run_generation", "predict"}:
            return dependency
    for dependency in dependencies:
        if len(dependency.get("inputs", [])) == 28 and len(dependency.get("outputs", [])) >= 34:
            return dependency
    return None


def first_uploaded_path(uploaded: Any) -> str | None:
    if isinstance(uploaded, str):
        return uploaded
    if isinstance(uploaded, dict):
        value = uploaded.get("path") or uploaded.get("name")
        return None if value is None else str(value)
    if isinstance(uploaded, list):
        for item in uploaded:
            path = first_uploaded_path(item)
            if path:
                return path
    return None


def first_audio_artifact_url(result: dict[str, Any]) -> str | None:
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


def first_audio_reference(result: Any) -> str | None:
    if isinstance(result, dict):
        data = result.get("data")
        if isinstance(data, list):
            found = first_audio_reference(data)
            if found:
                return found
        for key in ["output", *(f"output_{index}" for index in range(1, 32))]:
            if key in result:
                found = extract_audio_reference(result[key])
                if found:
                    return found
        return extract_audio_reference(result)
    if not isinstance(result, list):
        return extract_audio_reference(result)
    for item in result[:32]:
        ref = extract_audio_reference(item)
        if ref:
            return ref
    return None


def extract_audio_reference(value: Any) -> str | None:
    if isinstance(value, str) and looks_like_audio_reference(value):
        return value
    if not isinstance(value, dict):
        return None
    if "value" in value:
        found = extract_audio_reference(value["value"])
        if found:
            return found
    for key in ("url", "path", "name"):
        raw = value.get(key)
        if raw:
            return str(raw)
    return None


def looks_like_audio_reference(value: str) -> bool:
    if not value:
        return False
    lowered = value.lower().split("?", 1)[0]
    if lowered.startswith(("http://", "https://", "/", "file=")):
        return True
    return lowered.endswith((".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"))


def audio_download_candidates(base_url: str, audio_ref: str) -> list[str]:
    if audio_ref.startswith("http://") or audio_ref.startswith("https://"):
        return [audio_ref]
    if audio_ref.startswith("/"):
        return [audio_ref]
    if audio_ref.startswith("file="):
        audio_ref = audio_ref.split("=", 1)[1]
    encoded = quote(audio_ref, safe="/:")
    return [
        f"/gradio_api/file={encoded}",
        f"/file={encoded}",
        urljoin(base_url + "/", audio_ref),
    ]


def raise_for_error(response: httpx.Response, provider_name: str) -> None:
    if response.is_success:
        return
    raise TTSServiceError(response_error_message(response, provider_name))


def response_error_message(response: httpx.Response, provider_name: str) -> str:
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
