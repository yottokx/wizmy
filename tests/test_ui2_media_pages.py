"""メディア編集ページ(画像/音声・キャラ版+グループメンバー版)のスモークテスト。"""

from __future__ import annotations

from src.core.character.schemas import CharacterImageAsset, CharacterMedia, CharacterSheet
from src.core.chat.schemas import UserPersona


def _sheet(character_id: str, name: str, *, images: int = 1) -> CharacterSheet:
    media = CharacterMedia()
    media.images = [
        CharacterImageAsset(
            id=f"{character_id}-img-{index}",
            path=f"characters/{character_id}/images/portrait-{index}.png",
        )
        for index in range(images)
    ]
    if media.images:
        media.primary_image_id = media.images[0].id
    return CharacterSheet(
        id=character_id,
        name=name,
        occupation="観測者",
        self_intro="トワです。今日の星はよく瞬いていますよ。",
        media=media,
    )


async def _make_group(context):
    return await context.group_chats.create_group(
        name="星見図書館の夜会",
        world="星が本の背表紙に宿る図書館。",
        completion_profile_id="profile-x",
        members=[(_sheet("char-a", "灯里"), "Akari")],
        user_persona=UserPersona(
            id="persona-x",
            name="空野ソラ",
            display_name="ソラ",
            description="記録係として同行する旅人。",
        ),
        user_handle="Sora",
    )


async def test_v2_character_images_page_renders(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    await context.characters.save(_sheet("char-a", "アステル", images=2))

    user = nicegui_smoke_app.user
    await user.open("/characters/char-a/images")
    await user.should_see("メイン画像")
    await user.should_see("すべての画像")
    await user.should_see("顔範囲を編集")
    # テスト設定には画像生成プロファイルが無いのでワークスペースは案内表示
    await user.should_see("設定で画像生成プロファイルを追加すると、ここから画像を生成できます。")


async def test_v2_character_images_delete_non_primary(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    await context.characters.save(_sheet("char-a", "アステル", images=2))

    user = nicegui_smoke_app.user
    await user.open("/characters/char-a/images")
    user.find(marker="ui2-media-image-delete").click()
    await user.should_see("この画像を削除しますか?")
    user.find(marker="ui2-media-image-delete-confirm").click()
    await user.should_see("画像を削除しました")

    saved = await context.characters.get("char-a")
    assert saved is not None
    assert len(saved.media.images) == 1
    assert saved.media.primary_image() is not None  # メイン画像は残る


async def test_v2_character_voice_page_renders(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    await context.characters.save(_sheet("char-a", "アステル"))

    user = nicegui_smoke_app.user
    await user.open("/characters/char-a/voice")
    await user.should_see("ボイスデザイン")
    await user.should_see("声のキャプション")
    await user.should_see("まだ音声がありません。アップロードするか、下のボイスデザインで生成できます。")
    # テスト設定には TTS API も Gen-Server も無い
    await user.should_see("使用できるTTSがありません。設定でWizmy-Gen-ServerまたはTTS APIを追加してください。")


async def test_v2_group_member_media_pages_render(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    group = await _make_group(context)
    member = group.members[0]

    user = nicegui_smoke_app.user
    await user.open(f"/groups/{group.id}/members/{member.id}/images")
    await user.should_see("すべての画像")
    await user.open(f"/groups/{group.id}/members/{member.id}/voice")
    await user.should_see("ボイスデザイン")
    await user.should_see("TTS設定")


async def test_v2_media_pages_not_found(nicegui_smoke_app) -> None:
    user = nicegui_smoke_app.user
    await user.open("/characters/no-such-id/images")
    await user.should_see("指定されたキャラクターは存在しません。")
    await user.open("/characters/no-such-id/voice")
    await user.should_see("指定されたキャラクターは存在しません。")
