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
from src.core.tts.options import (
    CHARACTER_GEN_SERVER_VOICE_API_VALUE,
    PERSONA_GEN_SERVER_VOICE_API_VALUE,
    assigned_gen_server_voice_endpoints,
    gen_server_backend_mode,
    is_gen_server_voice_api,
    normalize_gen_server_tts_mode,
    parse_voice_api_value,
    selected_tts_endpoint,
    selected_voice_api_value,
    voice_api_options,
)
from src.core.tts.schemas import (
    TTS_PROVIDER_IRODORI_GRADIO,
    TTS_PROVIDER_IRODORI_SERVER,
    TTSEndpoint,
)

GEN_SERVER_API_VALUES = (
    CHARACTER_GEN_SERVER_VOICE_API_VALUE,
    PERSONA_GEN_SERVER_VOICE_API_VALUE,
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
        for api_value in GEN_SERVER_API_VALUES:
            self.assertEqual(
                voice_api_options(
                    self.endpoints,
                    self.gen_server_config,
                    gen_server_api_value=api_value,
                ),
                {
                    api_value: "Wizmy-Gen-Server (TTS: Clone, Design)",
                    "tts:tts-a": "Alpha (Irodori-TTS Gradio / 07dfa74)",
                    "tts:tts-b": "Beta (Irodori-TTS-Server)",
                },
            )

    def test_assigned_gen_server_voice_endpoints_are_deduplicated(self) -> None:
        config = GenServerConfig(
            endpoints=[GenServerEndpoint(id="shared", name="Shared")],
            mode_assignments={
                GEN_SERVER_MODE_IRODORI_VOICE_CLONE: "shared",
                GEN_SERVER_MODE_IRODORI_VOICE_DESIGN: "shared",
            },
        )

        self.assertEqual([endpoint.id for endpoint in assigned_gen_server_voice_endpoints(config)], ["shared"])

    def test_selected_voice_api_value_keeps_current_fallbacks(self) -> None:
        gen_server_settings = CharacterTTSSettings(api_type=CHARACTER_TTS_API_GEN_SERVER)
        tts_settings = CharacterTTSSettings(api_type=CHARACTER_TTS_API_TTS, endpoint_id="tts-b")
        missing_tts_settings = CharacterTTSSettings(api_type=CHARACTER_TTS_API_TTS, endpoint_id="missing")

        for api_value in GEN_SERVER_API_VALUES:
            self.assertEqual(
                selected_voice_api_value(
                    gen_server_settings, self.endpoints, True, gen_server_api_value=api_value
                ),
                api_value,
            )
            self.assertEqual(
                selected_voice_api_value(tts_settings, self.endpoints, True, gen_server_api_value=api_value),
                "tts:tts-b",
            )
            self.assertEqual(
                selected_voice_api_value(
                    missing_tts_settings, self.endpoints, True, gen_server_api_value=api_value
                ),
                api_value,
            )
            self.assertEqual(
                selected_voice_api_value(
                    missing_tts_settings, self.endpoints, False, gen_server_api_value=api_value
                ),
                "tts:tts-a",
            )
            self.assertEqual(
                selected_voice_api_value(CharacterTTSSettings(), [], False, gen_server_api_value=api_value),
                "",
            )

    def test_parse_and_selected_endpoint_keep_current_values(self) -> None:
        endpoint_by_id = {endpoint.id: endpoint for endpoint in self.endpoints}

        for api_value in GEN_SERVER_API_VALUES:
            self.assertEqual(
                parse_voice_api_value(api_value, gen_server_api_value=api_value),
                (CHARACTER_TTS_API_GEN_SERVER, ""),
            )
            self.assertEqual(
                parse_voice_api_value("tts:tts-b", gen_server_api_value=api_value),
                (CHARACTER_TTS_API_TTS, "tts-b"),
            )
            self.assertEqual(
                parse_voice_api_value("", gen_server_api_value=api_value),
                (CHARACTER_TTS_API_DEFAULT, ""),
            )
            self.assertEqual(
                parse_voice_api_value("unknown", gen_server_api_value=api_value),
                (CHARACTER_TTS_API_DEFAULT, ""),
            )
            self.assertIs(
                selected_tts_endpoint("tts:tts-b", endpoint_by_id, gen_server_api_value=api_value),
                self.endpoints[1],
            )
            self.assertIsNone(selected_tts_endpoint(api_value, endpoint_by_id, gen_server_api_value=api_value))
            self.assertTrue(is_gen_server_voice_api(api_value, gen_server_api_value=api_value))
            self.assertFalse(is_gen_server_voice_api("tts:tts-a", gen_server_api_value=api_value))

    def test_gen_server_tts_mode_helpers_keep_current_values(self) -> None:
        self.assertEqual(
            normalize_gen_server_tts_mode(CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3),
            CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3,
        )
        self.assertEqual(normalize_gen_server_tts_mode("unknown"), CHARACTER_GEN_SERVER_TTS_MODE_CLONE)
        self.assertEqual(
            gen_server_backend_mode(CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3),
            GEN_SERVER_MODE_IRODORI_VOICE_DESIGN,
        )
        self.assertEqual(
            gen_server_backend_mode(CHARACTER_GEN_SERVER_TTS_MODE_CLONE),
            GEN_SERVER_MODE_IRODORI_VOICE_CLONE,
        )


if __name__ == "__main__":
    unittest.main()
