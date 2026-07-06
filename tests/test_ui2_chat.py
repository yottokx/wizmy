"""/v2/characters/{id}/chat(1:1チャット)のスモークテスト。"""

from __future__ import annotations

import asyncio

from src.core.character.schemas import CharacterImageAsset, CharacterMedia, CharacterSheet


def _sheet(character_id: str, name: str, *, image: bool = True) -> CharacterSheet:
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
        world="星を観測する塔のある世界。",
        self_intro="「トワです。今日の星はよく瞬いていますよ」",
        media=media,
    )


def _settings_dict(situation: str = "砂に埋もれた地下図書館。ランプの灯りだけが頼り。") -> dict:
    return {
        "profile_id": "profile-x",
        "chat_mode_id": "mode-x",
        "chat_mode_name": "小さな会話",
        "chat_premise": "",
        "situation": situation,
        "user_persona_id": "persona-x",
        "user_persona_name": "旅の記録係",
        "user_persona_description": "港町に来たばかりの記録係。",
        "user_persona_source": "persona",
    }


async def test_v2_chat_fresh_state_without_sessions(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    await context.characters.save(_sheet("char-a", "アステル"))

    user = nicegui_smoke_app.user
    await user.open("/v2/characters/char-a/chat")
    # 初対面の空状態: 自己紹介+はじめかた+セッション0件の案内
    await user.should_see("トワです。今日の星はよく瞬いていますよ")
    await user.should_see("あいさつを返す")
    await user.should_see("まだセッションがありません")


async def test_v2_chat_renders_session_messages_and_scene(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    await context.characters.save(_sheet("char-a", "アステル"))
    await context.chats.create_session(
        character_id="char-a",
        title="地下書庫の夜話",
        title_is_auto=False,
        settings=_settings_dict(),
        messages=[
            {"speaker": "narration", "text": "ランプの灯が揺れている。", "time_label": "21:00"},
            {"speaker": "character", "text": "来たのね。ちょうどいいわ。", "time_label": "21:01"},
            {"speaker": "user", "text": "この銘文、読める?", "time_label": "21:02"},
        ],
    )

    user = nicegui_smoke_app.user
    await user.open("/v2/characters/char-a/chat")
    await user.should_see("地下書庫の夜話")  # 左のセッション+ヘッダー
    await user.should_see("来たのね。ちょうどいいわ。")
    await user.should_see("この銘文、読める?")
    await user.should_see("ランプの灯が揺れている。")
    await user.should_see("砂に埋もれた地下図書館。")  # シーンボックス
    await user.should_see("旅の記録係")  # user 発言の who ラベル


async def test_v2_chat_memo_command_posts_without_llm(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    await context.characters.save(_sheet("char-a", "アステル", image=False))
    session = await context.chats.create_session(
        character_id="char-a",
        title="メモ検証",
        title_is_auto=False,
        settings=_settings_dict(),
        messages=[],
    )

    user = nicegui_smoke_app.user
    await user.open("/v2/characters/char-a/chat")

    # 「本文/memo」送信 → コメント入力モード+本文が入力欄に残る
    input_box = list(user.find(marker="ui2-chat-input").elements)[0]
    input_box.set_value("ここは重要な伏線/memo")
    user.find(marker="ui2-chat-send").click()
    await user.should_see("コメント入力モードにしました")

    # そのまま送信 → LLM を呼ばずにコメントとして保存される
    input_box.set_value("ここは重要な伏線")
    user.find(marker="ui2-chat-send").click()

    saved = None
    for _ in range(100):  # 非同期保存の完了を待つ
        saved = await context.chats.get(session.id)
        if saved is not None and saved.messages:
            break
        await asyncio.sleep(0.05)
    assert saved is not None
    assert [message["speaker"] for message in saved.messages] == ["memo"]
    assert saved.messages[0]["text"] == "ここは重要な伏線"


async def test_v2_chat_user_turn_requires_llm_profile(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    await context.characters.save(_sheet("char-a", "アステル", image=False))
    await context.chats.create_session(
        character_id="char-a",
        title="ガード検証",
        title_is_auto=False,
        settings=_settings_dict(),
        messages=[],
    )

    user = nicegui_smoke_app.user
    await user.open("/v2/characters/char-a/chat")
    input_box = list(user.find(marker="ui2-chat-input").elements)[0]
    input_box.set_value("こんにちは")
    user.find(marker="ui2-chat-send").click()
    # 存在しないプロファイルのため LLM 構築が拒否され、ターンは実行されない
    await user.should_see("LLMプロファイルが見つかりません")


async def test_v2_chat_not_found(nicegui_smoke_app) -> None:
    user = nicegui_smoke_app.user
    await user.open("/v2/characters/no-such-id/chat")
    await user.should_see("指定されたキャラクターは存在しません。")
