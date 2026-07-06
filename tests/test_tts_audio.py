from __future__ import annotations

from src.core.tts_clients.audio import audio_download_candidates, looks_like_audio_reference


def test_file_prefixed_audio_reference_is_downloaded_as_gradio_file_path() -> None:
    audio_ref = "file=/tmp/gradio/audio output.wav"

    assert looks_like_audio_reference(audio_ref) is True
    assert audio_download_candidates("http://127.0.0.1:7860", audio_ref)[:2] == [
        "/gradio_api/file=/tmp/gradio/audio%20output.wav",
        "/file=/tmp/gradio/audio%20output.wav",
    ]
