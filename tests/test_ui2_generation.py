"""/v2/generation と /v2/groups/{id}/generation のスモークテスト。"""

from __future__ import annotations

from src.core.character.schemas import CharacterSheet
from src.core.chat.schemas import UserPersona


def _make_profile(context) -> str:
    endpoint = context.api_config.create_endpoint("ローカル", "openai_compat", "http://127.0.0.1:9")
    profile = context.api_config.create_llm_profile("生成用", endpoint.id, "model-x")
    return profile.id


def _sheet(character_id: str, name: str) -> CharacterSheet:
    return CharacterSheet(
        id=character_id,
        name=name,
        occupation="観測者",
        world="星見図書館の世界。",
        personality="穏やか。",
        self_intro="「こんばんは」",
    )


async def _make_group(context, *, members=None):
    return await context.group_chats.create_group(
        name="星見図書館の夜会",
        world="星が本の背表紙に宿る図書館。",
        completion_profile_id="profile-x",
        members=members if members is not None else [(_sheet("char-a", "灯里"), "Akari")],
        user_persona=UserPersona(
            id="persona-x",
            name="空野ソラ",
            display_name="ソラ",
            description="記録係として同行する旅人。",
        ),
        user_handle="Sora",
    )


async def test_v2_generation_without_profiles_shows_setup_guide(nicegui_smoke_app) -> None:
    user = nicegui_smoke_app.user
    await user.open("/v2/generation")
    await user.should_see("LLMプロファイルが未設定です")


async def test_v2_generation_renders_modes_and_new_form(nicegui_smoke_app) -> None:
    _make_profile(nicegui_smoke_app.context)
    user = nicegui_smoke_app.user
    await user.open("/v2/generation")
    await user.should_see("どんなキャラクターを作りますか。")
    await user.should_see("新規生成")
    await user.should_see("既存キャラを修正")
    await user.should_see("関連キャラを生成")
    await user.should_see("生成する")


async def test_v2_generation_modify_requires_base_character(nicegui_smoke_app) -> None:
    _make_profile(nicegui_smoke_app.context)
    user = nicegui_smoke_app.user
    await user.open("/v2/generation")
    await user.should_see("どんなキャラクターを作りますか。")
    user.find(marker="ui2-gen-mode-modify").click()
    await user.should_see("ベースキャラクター")
    await user.should_see("未選択")
    user.find(marker="ui2-gen-start").click()
    await user.should_see("ベースにするキャラクターを選択してください")


async def test_v2_group_generation_not_found(nicegui_smoke_app) -> None:
    user = nicegui_smoke_app.user
    await user.open("/v2/groups/no-such-group/generation")
    await user.should_see("指定されたグループは存在しません。")


async def test_v2_group_generation_renders_fixed_world_and_modes(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    _make_profile(context)
    group = await _make_group(context)
    user = nicegui_smoke_app.user
    await user.open(f"/v2/groups/{group.id}/generation")
    await user.should_see("どんな住人を迎えますか。")
    await user.should_see("固定ワールド")
    await user.should_see("星が本の背表紙に宿る図書館。")
    await user.should_see("住人を修正")
    await user.should_see("知りあいを生成")


async def test_v2_group_generation_modify_requires_member(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    _make_profile(context)
    group = await _make_group(context, members=[])
    user = nicegui_smoke_app.user
    await user.open(f"/v2/groups/{group.id}/generation")
    await user.should_see("どんな住人を迎えますか。")
    user.find(marker="ui2-ggen-mode-modify").click()
    await user.should_see("この世界にはまだ住人がいません。")
    user.find(marker="ui2-ggen-start").click()
    await user.should_see("修正ベースにする住人を選択してください")
