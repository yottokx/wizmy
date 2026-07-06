"""/v2/characters(一覧)と /v2/characters/{id}(シート)のスモークテスト。"""

from __future__ import annotations

from src.core.character.schemas import CharacterImageAsset, CharacterMedia, CharacterSheet

SAMPLE_MD = """# トワ

## 基本情報
| 項目 | 内容 |
|------|------|
| 名前 | トワ |
| 年齢 | 17歳 |
| 職業・役割 | 星を数える観測者 |

## 世界観・舞台
星を観測する塔のある世界。

## 性格・内面
物静かだが星の話になると早口になる。

## 自己紹介台詞
「トワです。今日の星はよく瞬いていますよ」
"""


def _sheet(character_id: str, name: str, *, favorite: bool = False, image: bool = True) -> CharacterSheet:
    media = CharacterMedia()
    if image:
        media.images = [
            CharacterImageAsset(
                id=f"{character_id}-img",
                path=f"characters/{character_id}/images/portrait.png",
            )
        ]
    return CharacterSheet(
        id=character_id,
        name=name,
        occupation="星を数える観測者",
        self_intro="トワです。今日の星はよく瞬いていますよ。",
        is_favorite=favorite,
        media=media,
        tags=["観測者"],
        raw_markdown=SAMPLE_MD.replace("トワ", name),
    )


async def test_v2_characters_lists_gallery_and_pickup(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    await context.characters.save(_sheet("char-a", "アステル", favorite=True))
    await context.characters.save(_sheet("char-b", "ミラベル", image=False))

    user = nicegui_smoke_app.user
    await user.open("/v2/characters")
    await user.should_see("すべてのキャラクター")
    await user.should_see("アステル")  # 画像持ち → ピックアップ+ギャラリー
    await user.should_see("ミラベル")  # 画像なし → ギャラリーのみ(noimg カード)
    await user.should_see("新規生成")


async def test_v2_characters_favorites_filter(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    await context.characters.save(_sheet("char-a", "アステル", favorite=True, image=False))
    await context.characters.save(_sheet("char-b", "ミラベル", image=False))

    user = nicegui_smoke_app.user
    await user.open("/v2/characters")
    await user.should_see("ミラベル")
    user.find(marker="ui2-characters-fav-filter").click()
    await user.should_see("アステル")
    await user.should_not_see("ミラベル")


async def test_v2_character_sheet_renders_sections(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    await context.characters.save(_sheet("char-a", "アステル"))

    user = nicegui_smoke_app.user
    await user.open("/v2/characters/char-a")
    await user.should_see("基本情報")
    await user.should_see("星を観測する塔のある世界。")
    await user.should_see("物静かだが星の話になると早口になる。")
    # 左サイド: 名前・タグ・アクション
    await user.should_see("チャットする")
    await user.should_see("観測者 ×")


async def test_v2_character_sheet_markdown_save_reparses(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    await context.characters.save(_sheet("char-a", "アステル"))

    user = nicegui_smoke_app.user
    await user.open("/v2/characters/char-a")
    user.find(marker="ui2-sheet-vmode-md").click()  # Markdown モードに切替(既定は章立て表示)
    editor = list(user.find(marker="ui2-sheet-md").elements)[0]
    editor.set_value(SAMPLE_MD.replace("トワ", "ステラ"))
    user.find(marker="ui2-sheet-md-save").click()
    await user.should_see("シートを保存しました")

    saved = await context.characters.get("char-a")
    assert saved is not None
    assert saved.name == "ステラ"
    assert saved.tags == ["観測者"]  # タグ・メディア等は保存時に温存される
    assert saved.media.primary_image() is not None


async def test_v2_character_favorite_toggle_persists(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    await context.characters.save(_sheet("char-a", "アステル"))

    user = nicegui_smoke_app.user
    await user.open("/v2/characters/char-a")
    user.find(marker="ui2-sheet-fav").click()
    await user.should_see("お気に入りに追加しました")
    saved = await context.characters.get("char-a")
    assert saved is not None and saved.is_favorite is True


async def test_v2_character_not_found(nicegui_smoke_app) -> None:
    user = nicegui_smoke_app.user
    await user.open("/v2/characters/no-such-id")
    await user.should_see("指定されたキャラクターは存在しません。")
