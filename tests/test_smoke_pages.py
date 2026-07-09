"""旧UI(/legacy 退避中)の主要ページが初期表示で例外を出さないことを確認するスモークテスト。"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.core.character.schemas import CharacterSheet
from src.core.chat.schemas import UserPersona
from src.core.group_chat.schemas import GroupChatRecord
from src.services.api_config import ApiConfigService
from src.services.danbooru_prompt import DanbooruPromptService
from src.services.image_generation import ImageGenerationService
from src.services.tts import TTSService


@dataclass(frozen=True)
class SmokeRecords:
    """ページ表示に必要な最小データ。"""

    character: CharacterSheet
    group: GroupChatRecord


@pytest.fixture(autouse=True)
def external_call_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """ページ表示時に外部通信入口が呼ばれた場合は失敗させる。"""

    async def fail_async(*args, **kwargs):
        raise AssertionError("ページ表示で外部通信が発生しました。")

    def fail_sync(*args, **kwargs):
        raise AssertionError("ページ表示で外部通信が発生しました。")

    monkeypatch.setattr(ApiConfigService, "test_connection", fail_async)
    monkeypatch.setattr(ApiConfigService, "fetch_endpoint_models", fail_async)
    monkeypatch.setattr(ApiConfigService, "fetch_gen_server_capabilities", fail_async)
    monkeypatch.setattr(ApiConfigService, "fetch_gen_server_models", fail_async)
    monkeypatch.setattr(DanbooruPromptService, "start_generate_candidates_job", fail_sync)
    monkeypatch.setattr(ImageGenerationService, "start_sdxl_job", fail_sync)
    monkeypatch.setattr(TTSService, "start_synthesize_job", fail_sync)
    monkeypatch.setattr(TTSService, "start_design_voice_job", fail_sync)


@pytest.fixture
async def smoke_records(nicegui_smoke_app) -> SmokeRecords:
    """ページ表示に使うキャラクターとグループを作成する。"""
    context = nicegui_smoke_app.context
    character = CharacterSheet(
        id="smoke-character",
        name="スモーク用キャラクター",
        age="20",
        gender="未設定",
        occupation="テスト担当",
        world="スモークテスト用の世界",
        personality="初期表示の確認に使う短い説明。",
        raw_markdown=(
            "# スモーク用キャラクター\n\n"
            "## 基本情報\n"
            "- 年齢: 20\n"
            "- 性別: 未設定\n\n"
            "## 性格・内面\n"
            "初期表示の確認に使う短い説明。"
        ),
        tags=["smoke"],
    )
    saved_character = await context.characters.save(character)
    group = await context.group_chats.create_group(
        name="スモーク用グループ",
        world="スモークテスト用の世界",
        completion_profile_id="",
        members=[(saved_character, "Guide")],
        user_persona=UserPersona(
            id="smoke-user-persona",
            name="テストユーザー",
            description="ページ表示確認用のユーザー設定。",
        ),
        user_handle="User",
    )
    return SmokeRecords(character=saved_character, group=group)


@pytest.mark.parametrize(
    "path",
    [
        "/legacy",
        "/legacy/characters",
        "/legacy/groups",
        "/legacy/settings",
    ],
)
async def test_top_level_pages_render_without_error(nicegui_smoke_app, smoke_records: SmokeRecords, path: str) -> None:
    await nicegui_smoke_app.user.open(path)


async def test_group_detail_page_renders_without_error(nicegui_smoke_app, smoke_records: SmokeRecords) -> None:
    await nicegui_smoke_app.user.open(f"/legacy/groups/{smoke_records.group.id}")


async def test_character_chat_page_renders_without_error(nicegui_smoke_app, smoke_records: SmokeRecords) -> None:
    await nicegui_smoke_app.user.open(f"/legacy/characters/{smoke_records.character.id}/chat")


@pytest.mark.parametrize(
    "path",
    [
        "/legacy/characters/missing-character",
        "/legacy/characters/missing-character/chat",
        "/legacy/groups/missing-group",
    ],
)
async def test_missing_ids_render_existing_not_found_pages(nicegui_smoke_app, path: str) -> None:
    await nicegui_smoke_app.user.open(path)
    await nicegui_smoke_app.user.should_see("存在しません。")
