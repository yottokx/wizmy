"""/generation と /groups/{id}/generation のスモークテスト。"""

from __future__ import annotations

from datetime import datetime

from nicegui import app

from src.core.character.schemas import CharacterSheet
from src.core.character_generation.schemas import (
    GenerationMode,
    GenerationPreferences,
    GenerationRequest,
    GenerationResult,
)
from src.core.chat.schemas import UserPersona
from src.core.group_chat.schemas import GroupRelationship
from src.services.character_generation import GenerationJob, GenerationJobStatus
from src.ui2.generation_ui import GEN_CONFIRM_KEY


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
    await user.open("/generation")
    await user.should_see("LLMプロファイルが未設定です")


async def test_v2_generation_renders_modes_and_new_form(nicegui_smoke_app) -> None:
    _make_profile(nicegui_smoke_app.context)
    user = nicegui_smoke_app.user
    await user.open("/generation")
    await user.should_see("どんなキャラクターを作りますか。")
    await user.should_see("新規生成")
    await user.should_see("既存キャラを修正")
    await user.should_see("関連キャラを生成")
    await user.should_see("生成する")


async def test_v2_generation_modify_requires_base_character(nicegui_smoke_app) -> None:
    _make_profile(nicegui_smoke_app.context)
    user = nicegui_smoke_app.user
    await user.open("/generation")
    await user.should_see("どんなキャラクターを作りますか。")
    user.find(marker="ui2-gen-mode-modify").click()
    await user.should_see("ベースキャラクター")
    await user.should_see("未選択")
    user.find(marker="ui2-gen-start").click()
    await user.should_see("ベースにするキャラクターを選択してください")


async def test_v2_group_generation_not_found(nicegui_smoke_app) -> None:
    user = nicegui_smoke_app.user
    await user.open("/groups/no-such-group/generation")
    await user.should_see("指定されたグループは存在しません。")


async def test_v2_group_generation_renders_fixed_world_and_modes(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    _make_profile(context)
    group = await _make_group(context)
    user = nicegui_smoke_app.user
    await user.open(f"/groups/{group.id}/generation")
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
    await user.open(f"/groups/{group.id}/generation")
    await user.should_see("どんな住人を迎えますか。")
    user.find(marker="ui2-ggen-mode-modify").click()
    await user.should_see("この世界にはまだ住人がいません。")
    user.find(marker="ui2-ggen-start").click()
    await user.should_see("修正ベースにする住人を選択してください")


def _inject_completed_job(
    context,
    *,
    job_id: str = "gen-test",
    mode: GenerationMode = GenerationMode.NEW,
    saved_character_id: str = "",
    base_character_id: str = "",
    sheet_markdown: str = "",
) -> GenerationJob:
    """完了済みジョブをサービスへ直接差し込む(LLM実行なしの検証用)。"""
    profile_id = _make_profile(context)
    profile = context.api_config.get_llm_profile(profile_id)
    endpoint = context.api_config.get_endpoint(profile.endpoint_id)
    job = GenerationJob(
        id=job_id,
        request=GenerationRequest(preferences=GenerationPreferences(), mode=mode),
        profile=profile,
        endpoint=endpoint,
        base_character_id=base_character_id,
    )
    job.status = GenerationJobStatus.COMPLETED
    job.completed_at = datetime.now()
    job.saved_character_id = saved_character_id
    job.result = GenerationResult(success=True, sheet_markdown=sheet_markdown, mode=mode)
    context.generation._jobs[job.id] = job
    return job


async def test_find_job_for_character_reverse_lookup(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    _inject_completed_job(context, saved_character_id="char-42")
    found = context.generation.find_job_for_character("char-42")
    assert found is not None and found.id == "gen-test"
    assert context.generation.find_job_for_character("char-other") is None
    assert context.generation.find_job_for_character("") is None


async def test_v2_generation_review_missing_job_redirects(nicegui_smoke_app) -> None:
    user = nicegui_smoke_app.user
    await user.open("/generation/review/no-such-job")
    await user.should_see("LLMプロファイルが未設定です")


async def test_v2_generation_review_renders_diff_and_saves(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    base_sheet = _sheet("char-base", "灯里")
    base_sheet.raw_markdown = (
        "## 基本情報\n\n| 項目 | 内容 |\n|---|---|\n| 名前 | 灯里 |\n| 職業・役割 | 観測者 |\n\n"
        "## 性格・内面\n\n穏やか。\n"
    )
    base = await context.characters.save(base_sheet)
    new_md = base.raw_markdown.replace("観測者", "夜間観測員")
    _inject_completed_job(
        context,
        mode=GenerationMode.MODIFY,
        base_character_id=base.id,
        sheet_markdown=new_md,
    )
    user = nicegui_smoke_app.user
    await user.open("/generation/review/gen-test")
    await user.should_see("修正案の確認")
    await user.should_see("に適用しますか")
    user.find(marker="ui2-review-apply").click()
    await user.should_see("を上書き保存しました")
    saved = await context.characters.get(base.id)
    assert saved is not None and "夜間観測員" in saved.raw_markdown


async def test_v2_sheet_gen_confirm_bar_keep_and_drop(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    saved = await context.characters.save(_sheet("char-keep", "宵風"))
    user = nicegui_smoke_app.user
    # 受け渡しキーを積んでからシートを開くと、バーが一度だけ出る
    await user.open("/characters")
    app.storage.user[GEN_CONFIRM_KEY] = {"char_id": saved.id, "job_id": "gen-x"}
    await user.open(f"/characters/{saved.id}")
    await user.should_see("このキャラクターを保存しますか?")
    # 「いいえ(削除)」で削除して一覧へ
    user.find(marker="ui2-gen-drop").click()
    await user.should_see("を削除しました")
    assert await context.characters.get(saved.id) is None
    # キーは pop 済みなので、開き直してもバーは出ない
    other = await context.characters.save(_sheet("char-next", "朝霧"))
    await user.open(f"/characters/{other.id}")
    await user.should_see("朝霧")


_BASE_MD = (
    "## 基本情報\n\n| 項目 | 内容 |\n|---|---|\n| 名前 | 灯里 |\n| 職業・役割 | 観測者 |\n\n"
    "## 性格・内面\n\n穏やか。\n"
)


async def _make_group_with_md(context):
    sheet = _sheet("char-a", "灯里")
    sheet.raw_markdown = _BASE_MD
    return await _make_group(context, members=[(sheet, "Akari")])


async def test_group_remove_member_deletes_relationships(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    sheet_a = _sheet("char-a", "灯里")
    sheet_b = _sheet("char-b", "湊")
    group = await context.group_chats.create_group(
        name="星見図書館の夜会",
        world="星が本の背表紙に宿る図書館。",
        completion_profile_id="profile-x",
        members=[(sheet_a, "Akari"), (sheet_b, "Minato")],
        user_persona=UserPersona(id="persona-x", name="空野ソラ", display_name="ソラ", description="旅人。"),
        user_handle="Sora",
    )
    member_a, member_b = group.members
    await context.group_chats.save_relationship(
        group.id,
        GroupRelationship(
            id="",
            participant_a_key=f"member:{member_a.id}",
            participant_b_key=f"member:{member_b.id}",
            description="幼なじみ。",
        ),
    )
    removed = await context.group_chats.remove_member(group.id, member_b.id)
    assert removed is not None
    assert [member.id for member in removed.members] == [member_a.id]
    assert removed.relationships == []
    # 存在しないメンバーは None
    assert await context.group_chats.remove_member(group.id, "no-such-member") is None


async def test_v2_group_generation_review_renders_and_saves(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    group = await _make_group_with_md(context)
    member = group.members[0]
    new_md = _BASE_MD.replace("観測者", "夜間観測員")
    _inject_completed_job(
        context,
        mode=GenerationMode.MODIFY,
        base_character_id=member.id,
        sheet_markdown=new_md,
    )
    user = nicegui_smoke_app.user
    await user.open(f"/groups/{group.id}/generation/review/gen-test")
    await user.should_see("修正案の確認")
    user.find(marker="ui2-review-apply").click()
    await user.should_see("を上書き保存しました")
    saved = await context.group_chats.get(group.id)
    assert saved is not None
    assert "夜間観測員" in saved.members[0].character.raw_markdown


async def test_v2_member_sheet_gen_confirm_bar_drop_removes_member(nicegui_smoke_app) -> None:
    from nicegui import app as nicegui_app

    context = nicegui_smoke_app.context
    group = await _make_group_with_md(context)
    member = group.members[0]
    user = nicegui_smoke_app.user
    await user.open("/groups")
    nicegui_app.storage.user[GEN_CONFIRM_KEY] = {"char_id": member.id, "job_id": "gen-x"}
    await user.open(f"/groups/{group.id}/members/{member.id}")
    await user.should_see("この住人を保存しますか?")
    user.find(marker="ui2-gen-drop").click()
    await user.should_see("この世界から削除しました")
    saved = await context.group_chats.get(group.id)
    assert saved is not None and saved.members == []


async def test_v2_member_sheet_shows_relationships(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    sheet_a = _sheet("char-a", "灯里")
    sheet_b = _sheet("char-b", "湊")
    group = await context.group_chats.create_group(
        name="星見図書館の夜会",
        world="星が本の背表紙に宿る図書館。",
        completion_profile_id="profile-x",
        members=[(sheet_a, "Akari"), (sheet_b, "Minato")],
        user_persona=UserPersona(id="persona-x", name="空野ソラ", display_name="ソラ", description="旅人。"),
        user_handle="Sora",
    )
    member_a, member_b = group.members
    await context.group_chats.save_relationship(
        group.id,
        GroupRelationship(
            id="",
            participant_a_key=f"member:{member_a.id}",
            participant_b_key=f"member:{member_b.id}",
            description="同じ棚の常連同士。",
        ),
    )
    user = nicegui_smoke_app.user
    await user.open(f"/groups/{group.id}/members/{member_a.id}")
    await user.should_see("関係性")
    await user.should_see("湊")
    await user.should_see("同じ棚の常連同士。")
