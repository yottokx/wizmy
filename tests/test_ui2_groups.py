"""/groups(一覧・箱庭シェル・メンバー・ペルソナ)のスモークテスト。"""

from __future__ import annotations

import asyncio

from src.core.character.schemas import CharacterSheet
from src.core.chat.schemas import UserPersona


def _sheet(character_id: str, name: str, *, world: str = "星見図書館の世界。") -> CharacterSheet:
    return CharacterSheet(
        id=character_id,
        name=name,
        occupation="観測者",
        world=world,
        personality="穏やか。",
        self_intro="「こんばんは」",
    )


async def _make_group(context, *, name: str = "星見図書館の夜会"):
    return await context.group_chats.create_group(
        name=name,
        world="星が本の背表紙に宿る図書館。",
        completion_profile_id="profile-x",
        members=[(_sheet("char-a", "灯里"), "Akari"), (_sheet("char-b", "湊"), "Minato")],
        user_persona=UserPersona(
            id="persona-x",
            name="空野ソラ",
            display_name="ソラ",
            description="記録係として同行する旅人。",
        ),
        user_handle="Sora",
    )


async def test_v2_groups_list_renders_cards_and_create_flow(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    group = await _make_group(context)
    await context.group_chats.create_session(
        group_id=group.id,
        title="集いの夜",
        title_is_auto=False,
        settings={"participant_ids": [group.members[0].id]},
        messages=[],
    )

    user = nicegui_smoke_app.user
    await user.open("/groups")
    await user.should_see("グループ一覧")
    await user.should_see("星見図書館の夜会")
    await user.should_see("住人 2人 ・ セッション 1件")
    # 作成フロー(旧ウィザード順の4ステップ)
    await user.should_see("住人とあなたを決める")
    await user.should_see("世界と名前を決める")
    await user.should_see("世界に馴染ませる")
    await user.should_see("関係性を結ぶ")


async def test_v2_groups_create_requires_residents(nicegui_smoke_app) -> None:
    user = nicegui_smoke_app.user
    await user.open("/groups")
    await user.should_see("世界と名前を決める")  # 作成フローの非同期描画完了を待つ
    user.find(marker="ui2-group-create").click()
    # 補完用プロファイル未登録のため、最初の検証で止まる
    await user.should_see("補完用LLMプロファイルを選択してください")


async def test_v2_group_shell_renders_messages_and_cast(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    group = await _make_group(context)
    akari, minato = group.members
    await context.group_chats.create_session(
        group_id=group.id,
        title="閲覧室の夜",
        title_is_auto=False,
        settings={
            "profile_id": "profile-x",
            "participant_ids": [akari.id, minato.id],
            "situation": "星見図書館の夜更け。閲覧室に古い星図が広げられている。",
        },
        messages=[
            {"role": "narration", "text": "夜の鐘が鳴った。", "time_label": "21:00"},
            {
                "role": "user",
                "speaker_id": "persona",
                "speaker_name": "ソラ",
                "handle": "Sora",
                "text": "この星図、線が動いてない?",
                "time_label": "21:01",
            },
            {
                "role": "character",
                "speaker_id": akari.id,
                "speaker_name": "灯里",
                "handle": "Akari",
                "text": "星図は夜ごとに息をするんです。",
                "time_label": "21:02",
            },
            {
                "role": "guest",
                "speaker_id": "guest:巡回司書",
                "speaker_name": "巡回司書【ゲスト】",
                "guest_name": "巡回司書",
                "text": "閉館まであと少しですよ。",
                "time_label": "21:03",
            },
        ],
    )

    user = nicegui_smoke_app.user
    await user.open(f"/groups/{group.id}")
    await user.should_see("星見図書館の夜会")  # gband
    await user.should_see("閲覧室の夜")  # セッション+ヘッダー
    await user.should_see("星図は夜ごとに息をするんです。")
    await user.should_see("巡回司書【ゲスト】")
    await user.should_see("この世界の住人")
    await user.should_see("灯里")
    await user.should_see("湊")
    await user.should_see("星見図書館の夜更け。")  # シーンボックス

    # メモ入力は LLM 無しで保存される(/memo → 送信)
    input_box = list(user.find(marker="ui2-group-input").elements)[0]
    input_box.set_value("この鐘の音は伏線/memo")
    user.find(marker="ui2-group-send").click()
    await user.should_see("コメント入力モードにしました")
    input_box.set_value("この鐘の音は伏線")
    user.find(marker="ui2-group-send").click()
    saved = None
    for _ in range(100):
        sessions = await context.group_chats.list_sessions_for_group(group.id)
        if sessions and any(message.get("role") == "memo" for message in sessions[0].messages):
            saved = sessions[0]
            break
        await asyncio.sleep(0.05)
    assert saved is not None
    memo = [message for message in saved.messages if message.get("role") == "memo"]
    assert memo and memo[0]["text"] == "この鐘の音は伏線"


async def test_v2_group_user_turn_requires_llm_profile(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    group = await _make_group(context)
    await context.group_chats.create_session(
        group_id=group.id,
        title="ガード検証",
        title_is_auto=False,
        settings={"profile_id": "missing", "participant_ids": [group.members[0].id]},
        messages=[],
    )
    user = nicegui_smoke_app.user
    await user.open(f"/groups/{group.id}")
    input_box = list(user.find(marker="ui2-group-input").elements)[0]
    input_box.set_value("こんばんは")
    user.find(marker="ui2-group-send").click()
    await user.should_see("LLMプロファイルが見つかりません")


async def test_v2_group_member_page_renders_sheet_and_adaptation(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    group = await _make_group(context)
    member = group.members[1]  # 湊

    user = nicegui_smoke_app.user
    await user.open(f"/groups/{group.id}/members/{member.id}")
    await user.should_see("湊")
    await user.should_see("グループ内キャラ")
    await user.should_see("Markdown")


async def test_v2_group_persona_page_edit_saves(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    group = await _make_group(context)

    user = nicegui_smoke_app.user
    await user.open(f"/groups/{group.id}/persona")
    await user.should_see("ソラ")
    await user.should_see("専用のあなた")
    user.find(marker="ui2-persona-edit").click()
    name_input = list(user.find(marker="ui2-persona-name").elements)[0]
    name_input.set_value("空野ソラリス")
    user.find(marker="ui2-persona-save").click()
    await user.should_see("を保存しました")
    saved = await context.group_chats.get(group.id)
    assert saved is not None and saved.user_persona is not None
    assert saved.user_persona.name == "空野ソラリス"


async def test_v2_group_not_found_pages(nicegui_smoke_app) -> None:
    user = nicegui_smoke_app.user
    await user.open("/groups/no-such-group")
    await user.should_see("指定されたグループは存在しません。")
    await user.open("/groups/no-such-group/members/xxx")
    await user.should_see("指定されたグループは存在しません。")
