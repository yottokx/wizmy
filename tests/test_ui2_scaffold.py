"""ui2 scaffold(/v2 仮ページ)のスモークテスト。"""

from __future__ import annotations

from src.ui2.theme import THEME_KEY


async def test_v2_page_renders_without_error(nicegui_smoke_app) -> None:
    await nicegui_smoke_app.user.open("/v2")
    await nicegui_smoke_app.user.should_see("PHASE 0")


async def test_v2_theme_toggle_persists_across_pages(nicegui_smoke_app) -> None:
    user = nicegui_smoke_app.user
    await user.open("/v2")
    await user.should_see("星あかり")

    user.find(marker="ui2-theme-toggle").click()
    await user.should_see("ひなた")

    # 再訪問しても保存済みテーマ(ui2_theme)が反映される
    await user.open("/v2")
    await user.should_see("ひなた")


async def test_v2_jobs_drawer_opens_with_empty_state(nicegui_smoke_app) -> None:
    user = nicegui_smoke_app.user
    await user.open("/v2")
    user.find(marker="ui2-open-jobs").click()
    await user.should_see("実行中または直近のAIジョブはありません。")


async def test_v2_theme_storage_key_is_independent(nicegui_smoke_app) -> None:
    """旧UIのテーマキー "theme" とは独立したキーで保存される。"""
    assert THEME_KEY == "ui2_theme"
