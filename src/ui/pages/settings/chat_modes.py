from __future__ import annotations

import uuid

from nicegui import ui

from ....core.chat.schemas import ChatMode
from ....core.chat.templates import TemplateError, validate_chat_mode_templates
from .common import enable_drag_sort, moved_order, notify_order_saved, short_text


async def build_chat_modes_tab(ctx) -> None:
    modes_container = ui.column().classes("w-full gap-3")

    async def reorder(e) -> None:
        args = e.args
        ordered = moved_order(
            [mode.id for mode in ctx.api_config.get_chat_modes()],
            args["old_index"],
            args["new_index"],
        )
        if ordered is None:
            return
        ctx.api_config.reorder_chat_modes(ordered)
        notify_order_saved()

    enable_drag_sort(modes_container, reorder)

    async def refresh() -> None:
        modes = ctx.api_config.get_chat_modes()
        modes_container.clear()
        with modes_container:
            if not modes:
                ui.label("チャットモードが登録されていません").classes("text-grey-6 py-4")
            for mode in modes:
                chat_mode_card(mode, ctx, refresh)

    await refresh()

    ui.button(
        "チャットモードを追加",
        icon="add",
        on_click=lambda: open_chat_mode_dialog(None, ctx, refresh),
    ).props("color=primary unelevated").classes("mt-2")


def chat_mode_card(mode: ChatMode, ctx, refresh_fn) -> None:
    with ui.card().classes("w-full cursor-grab"):
        with ui.card_section():
            with ui.row().classes("items-start gap-3"):
                with ui.column().classes("flex-1 gap-2"):
                    ui.label(mode.name).classes("text-base font-semibold")
                    ui.label("前提テンプレート").classes("text-xs font-semibold text-grey-6")
                    ui.label(short_text(mode.premise_template)).classes("text-sm").style(
                        "white-space: pre-wrap; overflow-wrap: anywhere;"
                    )
                    ui.label("シチュエーションテンプレート").classes("text-xs font-semibold text-grey-6")
                    ui.label(short_text(mode.situation_template)).classes("text-sm").style(
                        "white-space: pre-wrap; overflow-wrap: anywhere;"
                    )
                with ui.row().classes("gap-2"):
                    ui.button(
                        icon="edit",
                        on_click=lambda m=mode: open_chat_mode_dialog(m, ctx, refresh_fn),
                    ).props("flat round dense color=primary")
                    ui.button(
                        icon="delete",
                        on_click=lambda m=mode: confirm_delete_chat_mode(m, ctx, refresh_fn),
                    ).props("flat round dense color=negative")


def open_chat_mode_dialog(mode: ChatMode | None, ctx, refresh_fn) -> None:
    is_edit = mode is not None

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-2xl"):
        ui.label("チャットモードを編集" if is_edit else "チャットモードを追加").classes("text-lg font-semibold mb-3")
        name_input = (
            ui.input(
                label="モード名",
                value=mode.name if mode else "",
            )
            .props("outlined")
            .classes("w-full")
        )
        ui.label("使用できる変数: {{ character_name }}, {{ user_persona_name }}").classes("text-xs text-grey-6")
        premise_input = (
            ui.textarea(
                label="前提テンプレート",
                value=mode.premise_template if mode else "",
            )
            .props("outlined rows=4")
            .classes("w-full")
        )
        situation_input = (
            ui.textarea(
                label="シチュエーションテンプレート",
                value=mode.situation_template if mode else "",
            )
            .props("outlined rows=3")
            .classes("w-full")
        )

        async def _save_chat_mode() -> None:
            name = (name_input.value or "").strip()
            premise = (premise_input.value or "").strip()
            situation = (situation_input.value or "").strip()
            if not name or not premise or not situation:
                ui.notify("モード名、前提、シチュエーションを入力してください", type="negative")
                return

            updated = ChatMode(
                id=mode.id if mode else str(uuid.uuid4())[:8],
                name=name,
                premise_template=premise,
                situation_template=situation,
            )
            try:
                validate_chat_mode_templates(updated)
            except TemplateError as err:
                ui.notify(f"テンプレートを確認してください: {err}", type="negative", timeout=8000)
                return

            if is_edit:
                ctx.api_config.update_chat_mode(updated)
            else:
                ctx.api_config.create_chat_mode(updated)
            ui.notify("保存しました", type="positive")
            dlg.close()
            await refresh_fn()

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", icon="save", on_click=_save_chat_mode).props("color=primary unelevated")

    dlg.open()


def confirm_delete_chat_mode(mode: ChatMode, ctx, refresh_fn) -> None:
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm"):
        ui.label(f"「{mode.name}」を削除しますか？").classes("font-medium mb-2")
        ui.label("このチャットモードは新しいチャット開始時に選べなくなります。").classes("text-sm text-grey-6")
        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")

            async def _do() -> None:
                if len(ctx.api_config.get_chat_modes()) <= 1:
                    ui.notify("チャットモードは少なくとも1件必要です", type="warning")
                    return
                ctx.api_config.delete_chat_mode(mode.id)
                ui.notify("削除しました", type="positive")
                dlg.close()
                await refresh_fn()

            ui.button("削除", on_click=_do).props("color=negative unelevated")
    dlg.open()
