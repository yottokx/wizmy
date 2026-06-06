import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.core.character.schemas import (
    CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3,
    CHARACTER_TTS_API_GEN_SERVER,
    CharacterTTSSettings,
)
from src.core.tts.schemas import TTSConfig
from src.services.api_config import ApiConfigService
from src.storage.api_config_store import ApiConfigStore


class NarratorTTSTest(unittest.TestCase):
    def test_tts_config_has_default_narrator_settings(self) -> None:
        config = TTSConfig()

        self.assertIsInstance(config.narrator, CharacterTTSSettings)
        self.assertEqual(config.narrator.api_type, "default")
        self.assertIsNone(config.narrator_voice)

    def test_narrator_tts_settings_are_saved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = ApiConfigService(ApiConfigStore(root / "config.json"), root)
            config = service.get_tts_config()
            config.narrator = CharacterTTSSettings(
                api_type=CHARACTER_TTS_API_GEN_SERVER,
                gen_server_tts_mode=CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3,
                voice_caption="calm narrator voice",
                gen_server_params={"cfg_scale_speaker": 4.0},
            )

            service.save_tts_config(config)
            loaded = service.get_tts_config()

            self.assertEqual(loaded.narrator.api_type, CHARACTER_TTS_API_GEN_SERVER)
            self.assertEqual(
                loaded.narrator.gen_server_tts_mode,
                CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3,
            )
            self.assertEqual(loaded.narrator.voice_caption, "calm narrator voice")
            self.assertEqual(loaded.narrator.gen_server_params["cfg_scale_speaker"], 4.0)

    def test_narrator_tts_playback_is_saved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = ApiConfigService(ApiConfigStore(root / "config.json"), root)

            path = service.save_narrator_tts_playback(b"audio-bytes")

            self.assertTrue(path.is_relative_to(root))
            self.assertEqual(path.read_bytes(), b"audio-bytes")
            self.assertTrue(path.name.startswith("playback-"))

    def test_narrator_preview_save_ignores_locked_old_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = ApiConfigService(ApiConfigStore(root / "config.json"), root)
            old_path = service.save_narrator_tts_preview(b"old-audio")
            original_unlink = Path.unlink

            def fake_unlink(path: Path, *args, **kwargs):
                if path == old_path:
                    raise PermissionError(32, "locked", str(path))
                return original_unlink(path, *args, **kwargs)

            with patch("pathlib.Path.unlink", fake_unlink):
                new_path = service.save_narrator_tts_preview(b"new-audio")

            self.assertEqual(new_path.read_bytes(), b"new-audio")
            self.assertTrue(old_path.exists())

    def test_narrator_voice_bytes_are_saved_and_reloaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = ApiConfigService(ApiConfigStore(root / "config.json"), root)

            voice = asyncio.run(
                service.save_narrator_voice_bytes(
                    b"voice-bytes",
                    filename="narrator.wav",
                    content_type="audio/wav",
                )
            )

            self.assertTrue(voice.path.startswith("narrator/voices/"))
            self.assertEqual(service.media_path(voice.path).read_bytes(), b"voice-bytes")

            reloaded = ApiConfigService(ApiConfigStore(root / "config.json"), root)
            loaded_config = reloaded.get_tts_config()
            self.assertIsNotNone(loaded_config.narrator_voice)
            self.assertEqual(loaded_config.narrator_voice.path, voice.path)


if __name__ == "__main__":
    unittest.main()
