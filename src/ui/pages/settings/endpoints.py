from __future__ import annotations

from nicegui import ui

from ....core.llm.schemas import Endpoint
from ...state import get_vault_password, is_vault_unlocked
from .common import enable_drag_sort, moved_order, notify_order_saved


async def build_endpoints_tab(ctx) -> None:
    endpoints_container = ui.column().classes("w-full gap-3")

    async def reorder(e) -> None:
        args = e.args
        ordered = moved_order(
            [ep.id for ep in ctx.api_config.get_endpoints()],
            args["old_index"],
            args["new_index"],
        )
        if ordered is None:
            return
        ctx.api_config.reorder_endpoints(ordered)
        notify_order_saved()

    enable_drag_sort(endpoints_container, reorder)

    async def refresh() -> None:
        endpoints = ctx.api_config.get_endpoints()
        endpoints_container.clear()
        with endpoints_container:
            if not endpoints:
                ui.label("エンドポイントが登録されていません").classes("text-grey-6 py-4")
            for ep in endpoints:
                endpoint_card(ep, ctx, refresh)

    await refresh()

    ui.button(
        "エンドポイントを追加",
        icon="add",
        on_click=lambda: open_endpoint_dialog(None, ctx, refresh),
    ).props("color=primary unelevated").classes("mt-2")


def endpoint_card(ep: Endpoint, ctx, refresh_fn) -> None:
    type_labels = {"ollama": "Ollama", "openai_compat": "OpenAI互換"}
    type_colors = {"ollama": "green", "openai_compat": "blue"}
    key_set = ctx.api_config.is_api_key_configured(ep.id) if ep.type == "openai_compat" else False

    with ui.card().classes("w-full cursor-grab"):
        with ui.card_section():
            with ui.row().classes("items-center gap-3 flex-wrap"):
                with ui.column().classes("flex-1 gap-1"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(ep.name).classes("text-base font-semibold")
                        color = type_colors.get(ep.type, "grey")
                        ui.badge(type_labels.get(ep.type, ep.type)).props(f"color={color}")
                    ui.label(ep.base_url).classes("text-sm text-grey-6 font-mono")
                    if ep.type == "openai_compat":
                        with ui.row().classes("items-center gap-2 mt-1"):
                            ui.icon("key").classes("text-positive text-sm" if key_set else "text-grey-4 text-sm")
                            ui.label("APIキー設定済" if key_set else "APIキー未設定").classes(
                                "text-xs " + ("text-positive" if key_set else "text-grey-5")
                            )
                            if not is_vault_unlocked():
                                ui.label("（ボルトをロック解除してください）").classes("text-xs text-warning")
                            else:
                                ui.button(
                                    "削除" if key_set else "設定",
                                    icon="delete" if key_set else "add",
                                    on_click=lambda e=ep, ks=key_set: (
                                        delete_endpoint_key(e, ctx, refresh_fn)
                                        if ks
                                        else open_key_dialog(e, ctx, refresh_fn)
                                    ),
                                ).props(f"flat size=xs color={'negative' if key_set else 'primary'}")

                with ui.row().classes("gap-2"):
                    status_icon = ui.icon("circle").classes("text-grey-4 text-base")
                    ui.button(
                        icon="wifi_tethering",
                        on_click=lambda e=ep: test_connection(e, status_icon, ctx),
                    ).props("flat round dense").tooltip("接続テスト")
                    ui.button(
                        icon="edit",
                        on_click=lambda e=ep: open_endpoint_dialog(e, ctx, refresh_fn),
                    ).props("flat round dense color=primary")
                    ui.button(
                        icon="delete",
                        on_click=lambda e=ep: confirm_delete_endpoint(e, ctx, refresh_fn),
                    ).props("flat round dense color=negative")


async def delete_endpoint_key(ep: Endpoint, ctx, refresh_fn) -> None:
    ctx.api_config.delete_api_key(ep.id)
    ui.notify(f"「{ep.name}」のAPIキーを削除しました", type="positive")
    await refresh_fn()


async def test_connection(ep: Endpoint, status_icon: ui.icon, ctx) -> None:
    status_icon.classes("text-grey-4")
    vault_pw = get_vault_password()
    ok = await ctx.api_config.test_connection(ep.id, vault_pw)
    if ok:
        status_icon.classes(remove="text-grey-4 text-negative").classes("text-positive")
        ui.notify(f"「{ep.name}」に接続できました", type="positive")
    else:
        status_icon.classes(remove="text-grey-4 text-positive").classes("text-negative")
        ui.notify(f"「{ep.name}」に接続できませんでした", type="negative")


def open_endpoint_dialog(ep: Endpoint | None, ctx, refresh_fn) -> None:
    is_edit = ep is not None

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg"):
        ui.label("エンドポイントを編集" if is_edit else "エンドポイントを追加").classes("text-lg font-semibold mb-3")
        name_input = ui.input(label="表示名", value=ep.name if ep else "").classes("w-full")
        type_select = ui.select(
            options={"ollama": "Ollama", "openai_compat": "OpenAI互換"},
            value=ep.type if ep else "ollama",
            label="プロバイダー種別",
        ).classes("w-full")
        url_input = ui.input(
            label="ベースURL",
            value=ep.base_url if ep else "http://localhost:11434",
            placeholder="http://localhost:11434",
        ).classes("w-full")

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", on_click=lambda: _save_endpoint(dlg)).props("color=primary unelevated")

    async def _save_endpoint(dlg) -> None:
        name = name_input.value.strip()
        url = url_input.value.strip()
        if not name or not url:
            ui.notify("表示名とURLを入力してください", type="negative")
            return
        if is_edit:
            updated = ep.model_copy(
                update={
                    "name": name,
                    "type": type_select.value,
                    "base_url": url,
                }
            )
            ctx.api_config.update_endpoint(updated)
        else:
            ctx.api_config.create_endpoint(name, type_select.value, url)
        ui.notify("保存しました", type="positive")
        dlg.close()
        await refresh_fn()

    dlg.open()


def confirm_delete_endpoint(ep: Endpoint, ctx, refresh_fn) -> None:
    with ui.dialog() as dlg, ui.card():
        ui.label(f"「{ep.name}」を削除しますか？").classes("font-medium mb-2")
        ui.label("このエンドポイントを使用するLLMプロファイルも影響を受けます。").classes("text-sm text-grey-6")
        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")

            async def _do_delete() -> None:
                ctx.api_config.delete_endpoint(ep.id)
                ui.notify(f"「{ep.name}」を削除しました", type="positive")
                dlg.close()
                await refresh_fn()

            ui.button("削除", on_click=_do_delete).props("color=negative unelevated")
    dlg.open()


def open_key_dialog(ep: Endpoint, ctx, refresh_fn) -> None:
    with ui.dialog() as dlg, ui.card().classes("min-w-[360px]"):
        ui.label(f"「{ep.name}」のAPIキー").classes("text-lg font-semibold mb-3")
        key_input = (
            ui.input(
                label="APIキー",
                placeholder="sk-...",
            )
            .props("type=password clearable")
            .classes("w-full")
        )

        async def _save() -> None:
            key = key_input.value.strip()
            if not key:
                ui.notify("APIキーを入力してください", type="negative")
                return
            vault_pw = get_vault_password()
            if not vault_pw:
                ui.notify("ボルトがロックされています", type="negative")
                return
            ctx.api_config.save_api_key(ep.id, key, vault_pw)
            ui.notify("APIキーを保存しました", type="positive")
            dlg.close()
            await refresh_fn()

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", on_click=_save).props("color=primary unelevated")

    dlg.open()
