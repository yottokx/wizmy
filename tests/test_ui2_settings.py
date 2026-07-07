"""/v2/settings(設定ページ)のスモークテスト。"""

from __future__ import annotations

from src.core.chat.schemas import UserPersona


async def test_v2_settings_renders_sections(nicegui_smoke_app) -> None:
    user = nicegui_smoke_app.user
    await user.open("/v2/settings")
    await user.should_see("LLMエンドポイント")
    await user.should_see("LLMプロファイル")
    await user.should_see("Wizmy-Gen-Server")
    await user.should_see("画像生成プロファイル")
    await user.should_see("APIキーボルト")
    await user.should_see("生成プリセット")
    await user.should_see("チャットモード")
    await user.should_see("ユーザーペルソナ")
    await user.should_see("ナレーター")
    await user.should_see("ピックアップの選び方")
    await user.should_see("テーマ")


async def test_v2_settings_add_endpoint_flow(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    user = nicegui_smoke_app.user
    await user.open("/v2/settings")
    user.find(marker="ui2-settings-endpoints").click()
    await user.should_see("エンドポイントが登録されていません")
    user.find(marker="ui2-settings-endpoint-add").click()
    await user.should_see("エンドポイントを追加")
    name_input = list(user.find(marker="ui2-settings-endpoint-name").elements)[0]
    name_input.set_value("ローカルOllama")
    user.find(marker="ui2-settings-endpoint-save").click()
    await user.should_see("保存しました")

    endpoints = context.api_config.get_endpoints()
    assert len(endpoints) == 1
    assert endpoints[0].name == "ローカルOllama"
    assert endpoints[0].base_url == "http://localhost:11434"


async def test_v2_settings_vault_setup_flow(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    user = nicegui_smoke_app.user
    await user.open("/v2/settings")
    user.find(marker="ui2-settings-vault").click()
    await user.should_see("APIキーボルトの設定")
    list(user.find(marker="ui2-settings-vault-pw1").elements)[0].set_value("pass-123")
    list(user.find(marker="ui2-settings-vault-pw2").elements)[0].set_value("pass-123")
    user.find(marker="ui2-settings-vault-setup").click()
    await user.should_see("ボルトを設定しました")
    await user.should_see("ボルトはロック解除されています")
    assert context.api_config.is_vault_setup() is True


async def test_v2_settings_pickup_policy_persists(nicegui_smoke_app) -> None:
    user = nicegui_smoke_app.user
    await user.open("/v2/settings")
    select = list(user.find(marker="ui2-settings-pickup-policy").elements)[0]
    select.set_value("daily")
    await user.should_see("ピックアップの選び方を保存しました")
    # 再訪しても選択値が保持されている(storage.user 永続)
    await user.open("/v2/settings")
    select = list(user.find(marker="ui2-settings-pickup-policy").elements)[0]
    assert select.value == "daily"


async def test_v2_settings_personas_dialog_lists_existing(nicegui_smoke_app) -> None:
    context = nicegui_smoke_app.context
    context.user_personas.create_user_persona(
        UserPersona(id="p1", name="空野ソラ", display_name="ソラ", description="記録係として同行する旅人。")
    )
    user = nicegui_smoke_app.user
    await user.open("/v2/settings")
    user.find(marker="ui2-settings-personas").click()
    await user.should_see("ソラ")
    await user.should_see("画像・音声")


async def test_v2_settings_chat_modes_dialog_opens(nicegui_smoke_app) -> None:
    user = nicegui_smoke_app.user
    await user.open("/v2/settings")
    user.find(marker="ui2-settings-chat-modes").click()
    await user.should_see("チャットモードを追加")
