from __future__ import annotations

import unittest

from src.core.character.schemas import (
    CHARACTER_GEN_SERVER_TTS_MODE_CLONE,
    CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3,
    CHARACTER_TTS_API_DEFAULT,
    CHARACTER_TTS_API_GEN_SERVER,
    CHARACTER_TTS_API_TTS,
    CharacterTTSSettings,
)
from src.core.gen_server.schemas import (
    GEN_SERVER_MODE_IRODORI_VOICE_CLONE,
    GEN_SERVER_MODE_IRODORI_VOICE_DESIGN,
    GenServerConfig,
    GenServerEndpoint,
)
from src.core.tts.schemas import (
    TTS_PROVIDER_IRODORI_GRADIO,
    TTS_PROVIDER_IRODORI_SERVER,
    TTSEndpoint,
)
from src.ui.components.character_media_voice import (
    _GEN_SERVER_VOICE_CLONE_API,
    _assigned_gen_server_voice_endpoints,
    _gen_server_backend_mode,
    _is_gen_server_voice_api,
    _normalize_gen_server_tts_mode,
    _parse_voice_api_value,
    _selected_tts_endpoint,
    _selected_voice_api_value,
    _voice_api_options,
)
from src.ui.pages.settings.narrator import narrator_voice_api_options
from src.ui.pages.settings.user_personas import (
    PERSONA_GEN_SERVER_VOICE_API,
    persona_assigned_gen_server_voice_endpoints,
    persona_gen_server_backend_mode,
    persona_is_gen_server_voice_api,
    persona_normalize_gen_server_tts_mode,
    persona_parse_voice_api_value,
    persona_selected_tts_endpoint,
    persona_selected_voice_api_value,
    persona_voice_api_options,
)


class TTSOptionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.endpoints = [
            TTSEndpoint(id="tts-a", name="Alpha", provider=TTS_PROVIDER_IRODORI_GRADIO),
            TTSEndpoint(id="tts-b", name="Beta", provider=TTS_PROVIDER_IRODORI_SERVER),
        ]
        self.gen_server_config = GenServerConfig(
            endpoints=[
                GenServerEndpoint(id="gen-clone", name="Clone"),
                GenServerEndpoint(id="gen-design", name="Design"),
            ],
            mode_assignments={
                GEN_SERVER_MODE_IRODORI_VOICE_CLONE: "gen-clone",
                GEN_SERVER_MODE_IRODORI_VOICE_DESIGN: "gen-design",
            },
        )

    def test_voice_api_options_keep_current_values(self) -> None:
        self.assertEqual(
            _voice_api_options(self.endpoints, self.gen_server_config),
            {
                _GEN_SERVER_VOICE_CLONE_API: "Wizmy-Gen-Server (TTS: Clone, Design)",
                "tts:tts-a": "Alpha (Irodori-TTS Gradio / 07dfa74)",
                "tts:tts-b": "Beta (Irodori-TTS-Server)",
            },
        )
        expected_persona = {
            PERSONA_GEN_SERVER_VOICE_API: "Wizmy-Gen-Server (TTS: Clone, Design)",
            "tts:tts-a": "Alpha (Irodori-TTS Gradio / 07dfa74)",
            "tts:tts-b": "Beta (Irodori-TTS-Server)",
        }
        self.assertEqual(persona_voice_api_options(self.endpoints, self.gen_server_config), expected_persona)
        self.assertEqual(narrator_voice_api_options(self.endpoints, self.gen_server_config), expected_persona)

    def test_assigned_gen_server_voice_endpoints_are_deduplicated(self) -> None:
        config = GenServerConfig(
            endpoints=[GenServerEndpoint(id="shared", name="Shared")],
            mode_assignments={
                GEN_SERVER_MODE_IRODORI_VOICE_CLONE: "shared",
                GEN_SERVER_MODE_IRODORI_VOICE_DESIGN: "shared",
            },
        )

        self.assertEqual([endpoint.id for endpoint in _assigned_gen_server_voice_endpoints(config)], ["shared"])
        self.assertEqual([endpoint.id for endpoint in persona_assigned_gen_server_voice_endpoints(config)], ["shared"])

    def test_selected_voice_api_value_keeps_current_fallbacks(self) -> None:
        gen_server_settings = CharacterTTSSettings(api_type=CHARACTER_TTS_API_GEN_SERVER)
        tts_settings = CharacterTTSSettings(api_type=CHARACTER_TTS_API_TTS, endpoint_id="tts-b")
        missing_tts_settings = CharacterTTSSettings(api_type=CHARACTER_TTS_API_TTS, endpoint_id="missing")

        self.assertEqual(
            _selected_voice_api_value(gen_server_settings, self.endpoints, True), _GEN_SERVER_VOICE_CLONE_API
        )
        self.assertEqual(
            persona_selected_voice_api_value(gen_server_settings, self.endpoints, True), PERSONA_GEN_SERVER_VOICE_API
        )
        self.assertEqual(_selected_voice_api_value(tts_settings, self.endpoints, True), "tts:tts-b")
        self.assertEqual(persona_selected_voice_api_value(tts_settings, self.endpoints, True), "tts:tts-b")
        self.assertEqual(
            _selected_voice_api_value(missing_tts_settings, self.endpoints, True), _GEN_SERVER_VOICE_CLONE_API
        )
        self.assertEqual(
            persona_selected_voice_api_value(missing_tts_settings, self.endpoints, False),
            "tts:tts-a",
        )
        self.assertEqual(_selected_voice_api_value(CharacterTTSSettings(), [], False), "")

    def test_parse_and_selected_endpoint_keep_current_values(self) -> None:
        endpoint_by_id = {endpoint.id: endpoint for endpoint in self.endpoints}

        self.assertEqual(_parse_voice_api_value(_GEN_SERVER_VOICE_CLONE_API), (CHARACTER_TTS_API_GEN_SERVER, ""))
        self.assertEqual(
            persona_parse_voice_api_value(PERSONA_GEN_SERVER_VOICE_API), (CHARACTER_TTS_API_GEN_SERVER, "")
        )
        self.assertEqual(_parse_voice_api_value("tts:tts-b"), (CHARACTER_TTS_API_TTS, "tts-b"))
        self.assertEqual(persona_parse_voice_api_value("tts:tts-b"), (CHARACTER_TTS_API_TTS, "tts-b"))
        self.assertEqual(_parse_voice_api_value(""), (CHARACTER_TTS_API_DEFAULT, ""))
        self.assertEqual(persona_parse_voice_api_value("unknown"), (CHARACTER_TTS_API_DEFAULT, ""))
        self.assertIs(_selected_tts_endpoint("tts:tts-b", endpoint_by_id), self.endpoints[1])
        self.assertIs(persona_selected_tts_endpoint("tts:tts-b", endpoint_by_id), self.endpoints[1])
        self.assertIsNone(_selected_tts_endpoint(_GEN_SERVER_VOICE_CLONE_API, endpoint_by_id))
        self.assertTrue(_is_gen_server_voice_api(_GEN_SERVER_VOICE_CLONE_API))
        self.assertTrue(persona_is_gen_server_voice_api(PERSONA_GEN_SERVER_VOICE_API))
        self.assertFalse(_is_gen_server_voice_api("tts:tts-a"))

    def test_gen_server_tts_mode_helpers_keep_current_values(self) -> None:
        self.assertEqual(
            _normalize_gen_server_tts_mode(CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3),
            CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3,
        )
        self.assertEqual(persona_normalize_gen_server_tts_mode("unknown"), CHARACTER_GEN_SERVER_TTS_MODE_CLONE)
        self.assertEqual(
            _gen_server_backend_mode(CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3),
            GEN_SERVER_MODE_IRODORI_VOICE_DESIGN,
        )
        self.assertEqual(
            persona_gen_server_backend_mode(CHARACTER_GEN_SERVER_TTS_MODE_CLONE), GEN_SERVER_MODE_IRODORI_VOICE_CLONE
        )


if __name__ == "__main__":
    unittest.main()
