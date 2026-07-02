from __future__ import annotations

import unittest
from unittest.mock import patch

from src.core.character_generation.schemas import (
    GenerationMode,
    GenerationPreferences,
    GenerationRequest,
    GenerationResult,
)
from src.core.llm.schemas import Endpoint, LLMProfile
from src.services.character_generation import (
    CharacterGenerationService,
    GenerationJobStatus,
)


class _FakeCharacterService:
    def __init__(self) -> None:
        self.saved = []

    def new_id(self) -> str:
        return "character-saved"

    async def save(self, sheet):
        self.saved.append(sheet)
        return sheet


class CharacterGenerationServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_auto_save_false_does_not_save_global_character(self) -> None:
        characters = _FakeCharacterService()
        service = CharacterGenerationService(characters)
        request = GenerationRequest(
            preferences=GenerationPreferences(),
            mode=GenerationMode.NEW,
        )
        profile = LLMProfile(
            id="profile-1",
            name="テストプロファイル",
            endpoint_id="endpoint-1",
            model_id="test-model",
        )
        endpoint = Endpoint(
            id="endpoint-1",
            name="テストエンドポイント",
        )

        def fake_run_generation(_llm, req, _progress_callback=None, _stop_check=None):
            return GenerationResult(
                success=True,
                sheet_markdown="# テストキャラ\n\n## 基本情報\n| 項目 | 内容 |\n|------|------|\n| 名前 | テストキャラ |",
                mode=req.mode,
            )

        with patch("src.services.character_generation.create_llm", return_value=object()):
            with patch("src.services.character_generation.run_generation", fake_run_generation):
                job = service.start_job(
                    request,
                    profile,
                    endpoint,
                    auto_save=False,
                )
                await job._task

        self.assertEqual(GenerationJobStatus.COMPLETED, job.status)
        self.assertEqual([], characters.saved)
        self.assertEqual("", job.saved_character_id)


if __name__ == "__main__":
    unittest.main()
