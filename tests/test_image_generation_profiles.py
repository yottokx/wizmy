from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.core.gen_server.schemas import GEN_SERVER_MODE_SDXL_IMAGE
from src.core.image_generation.schemas import (
    IMAGE_PROVIDER_WIZMY_GEN_SERVER,
    ImageGenerationProfile,
)
from src.services.api_config import ApiConfigService
from src.services.image_generation import ImageGenerationService
from src.storage.api_config_store import ApiConfigStore


class ImageGenerationProfileTest(unittest.TestCase):
    def test_old_sdxl_defaults_are_migrated_to_image_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "api-config.json"
            path.write_text(
                json.dumps(
                    {
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
                                GEN_SERVER_MODE_SDXL_IMAGE: "gen-1",
                            },
                            "mode_defaults": {
                                GEN_SERVER_MODE_SDXL_IMAGE: {
                                    "model_id": "sdxl-test",
                                    "prompt": "1girl, solo",
                                    "negative_prompt": "lowres",
                                    "width": 768,
                                    "height": 1024,
                                    "steps": 24,
                                }
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            store = ApiConfigStore(path)
            config = store.get_image_generation_config()
            gen_config = store.get_gen_server_config()

            self.assertEqual(len(config.profiles), 1)
            profile = config.profiles[0]
            self.assertEqual(profile.provider, IMAGE_PROVIDER_WIZMY_GEN_SERVER)
            self.assertEqual(profile.endpoint_id, "gen-1")
            self.assertEqual(profile.model_id, "sdxl-test")
            self.assertEqual(profile.prompt, "1girl, solo")
            self.assertEqual(profile.negative_prompt, "lowres")
            self.assertEqual(profile.params["width"], 768)
            self.assertNotIn(GEN_SERVER_MODE_SDXL_IMAGE, gen_config.mode_defaults)
            self.assertNotIn(GEN_SERVER_MODE_SDXL_IMAGE, gen_config.mode_assignments)

    def test_profile_payload_merges_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = ImageGenerationService(ApiConfigService(ApiConfigStore(Path(tmp) / "api-config.json")))
            profile = ImageGenerationProfile(
                id="profile-1",
                name="Test",
                endpoint_id="gen-1",
                model_id="base-model",
                prompt="base prompt",
                negative_prompt="base negative",
                params={"width": 832, "height": 1216, "steps": 30},
            )

            payload = service._sdxl_payload(
                profile,
                {
                    "prompt": "override prompt",
                    "width": 1024,
                    "seed": None,
                    "unknown": "ignored",
                },
            )

            self.assertEqual(payload["model_id"], "base-model")
            self.assertEqual(payload["prompt"], "override prompt")
            self.assertEqual(payload["negative_prompt"], "base negative")
            self.assertEqual(payload["width"], 1024)
            self.assertEqual(payload["height"], 1216)
            self.assertNotIn("seed", payload)
            self.assertNotIn("unknown", payload)


if __name__ == "__main__":
    unittest.main()
