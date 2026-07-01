"""Danbooruタグプロンプト生成サービス。"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from pathlib import Path

from ..config import PROJECT_ROOT
from ..core.character.schemas import CharacterSheet
from ..core.danbooru_prompt import (
    DanbooruPromptCandidate,
    DanbooruPromptGenerator,
    DanbooruTagDictionary,
    LangChainDanbooruPromptLLM,
)
from ..core.llm.factory import create_llm
from .api_config import ApiConfigService
from .ai_jobs import AIJobKind, AIJobRecord, AIJobService


DEFAULT_TAG_CLASSIFICATION_CSV = PROJECT_ROOT / "assets" / "danbooru_tag_classification_flat.csv"


class DanbooruPromptServiceError(Exception):
    """Danbooruタグプロンプト生成に失敗したときの例外。"""


class DanbooruPromptService:
    """キャラクターシートから画像生成向けDanbooruタグプロンプト候補を作る。"""

    def __init__(
        self,
        api_config: ApiConfigService,
        ai_jobs: AIJobService | None = None,
        *,
        tag_csv_path: Path = DEFAULT_TAG_CLASSIFICATION_CSV,
    ) -> None:
        self._api_config = api_config
        self._ai_jobs = ai_jobs
        self._tag_csv_path = tag_csv_path
        self._tag_dictionary: DanbooruTagDictionary | None = None

    async def generate_candidates(
        self,
        sheet: CharacterSheet,
        *,
        llm_profile_id: str,
        vault_password: str | None = None,
        count: int = 3,
        seed: int | None = None,
    ) -> list[DanbooruPromptCandidate]:
        profile = self._api_config.get_llm_profile(llm_profile_id)
        if profile is None:
            raise DanbooruPromptServiceError("LLMプロファイルが見つかりません。")
        if not profile.model_id:
            raise DanbooruPromptServiceError("LLMプロファイルのモデルIDが未設定です。")

        endpoint = self._api_config.get_endpoint(profile.endpoint_id)
        if endpoint is None:
            raise DanbooruPromptServiceError("LLMプロファイルのエンドポイントが見つかりません。")

        api_key = self._api_config.get_api_key(profile.endpoint_id, vault_password)
        if self._api_config.is_api_key_locked(profile.endpoint_id, api_key):
            raise DanbooruPromptServiceError(
                "このエンドポイントにはAPIキーが設定されています。APIキーボルトをロック解除してください。"
            )

        llm = create_llm(profile, endpoint, api_key)
        generator = DanbooruPromptGenerator(
            self._dictionary(),
            LangChainDanbooruPromptLLM(llm),
        )
        return await generator.generate_danbooru_prompt_candidates(
            sheet,
            count=count,
            seed=seed,
        )

    def start_generate_candidates_job(
        self,
        sheet: CharacterSheet,
        *,
        llm_profile_id: str,
        vault_password: str | None = None,
        count: int = 3,
        seed: int | None = None,
        label: str = "プロンプト生成",
        scope: str = "",
        metadata: dict | None = None,
        result_handler: Callable[[list[DanbooruPromptCandidate], AIJobRecord], Awaitable[object] | object] | None = None,
    ) -> AIJobRecord:
        if self._ai_jobs is None:
            raise DanbooruPromptServiceError("AIジョブサービスが初期化されていません。")

        async def _runner(job: AIJobRecord) -> object:
            candidates = await self.generate_candidates(
                sheet,
                llm_profile_id=llm_profile_id,
                vault_password=vault_password,
                count=count,
                seed=seed,
            )
            if result_handler is None:
                return candidates
            handled = result_handler(candidates, job)
            if inspect.isawaitable(handled):
                handled = await handled
            if isinstance(handled, dict):
                self._ai_jobs.set_result_meta(job.id, handled)
            return handled if handled is not None else candidates

        return self._ai_jobs.start_job(
            kind=AIJobKind.LLM_PROMPT,
            label=label,
            scope=scope,
            metadata=metadata,
            runner=_runner,
        )

    def _dictionary(self) -> DanbooruTagDictionary:
        if self._tag_dictionary is None:
            if not self._tag_csv_path.exists():
                raise DanbooruPromptServiceError("Danbooruタグ分類CSVが見つかりません。")
            self._tag_dictionary = DanbooruTagDictionary.from_csv(self._tag_csv_path)
        return self._tag_dictionary
