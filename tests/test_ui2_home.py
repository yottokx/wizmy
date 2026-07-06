"""/v2 ホーム(Phase 1)のスモークテスト。"""

from __future__ import annotations

from src.core.character.schemas import CharacterImageAsset, CharacterMedia, CharacterSheet


def _sheet(character_id: str, name: str, *, favorite: bool = False) -> CharacterSheet:
    return CharacterSheet(
        id=character_id,
        name=name,
        occupation="星を数える観測者",
        self_intro="トワです。今日の星はよく瞬いていますよ。",
        is_favorite=favorite,
        media=CharacterMedia(
            images=[
                CharacterImageAsset(
                    id=f"{character_id}-img",
                    path=f"characters/{character_id}/images/portrait.png",
                )
            ]
        ),
    )


def _companion_name(user) -> str:
    elements = list(user.find(marker="ui2-companion-name").elements)
    assert elements, "相方名ラベルが見つかりません"
    return elements[0].text


async def test_v2_home_empty_state(nicegui_smoke_app) -> None:
    user = nicegui_smoke_app.user
    await user.open("/v2")
    await user.should_see("まだ画像付きのキャラクターがいません")
    await user.should_see("まだセッションがありません")


async def test_v2_home_shows_favorite_companion_and_recent_sessions(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    await context.characters.save(_sheet("char-a", "アステル"))
    await context.characters.save(_sheet("char-b", "ミラベル", favorite=True))
    await context.chats.create_session(
        character_id="char-a",
        title="地下書庫の夜話",
        title_is_auto=False,
        settings={},
        messages=[{"speaker": "character", "text": "銘文の三行目だけれど。", "time_label": "21:00"}],
    )

    user = nicegui_smoke_app.user
    await user.open("/v2")
    # 既定の相方はお気に入り
    assert _companion_name(user) == "ミラベル"
    await user.should_see("続きから話す")
    # 最近のセッション(タイトル+最終発言プレビュー)
    await user.should_see("地下書庫の夜話")
    await user.should_see("銘文の三行目だけれど。")


async def test_v2_home_companion_switch_persists(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    await context.characters.save(_sheet("char-a", "アステル"))
    await context.characters.save(_sheet("char-b", "ミラベル", favorite=True))

    user = nicegui_smoke_app.user
    await user.open("/v2")
    assert _companion_name(user) == "ミラベル"

    # 相方候補はお気に入り優先順: index 0 = ミラベル, index 1 = アステル
    user.find(marker="ui2-companion-1").click()
    assert _companion_name(user) == "アステル"

    # 再訪問しても storage.user["ui2_companion"] の保存値が反映される
    await user.open("/v2")
    assert _companion_name(user) == "アステル"
