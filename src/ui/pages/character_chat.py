"""Character chat page entrypoint."""

from __future__ import annotations

from nicegui import ui

from ...app_context import get_context
from ..chat.controller import ChatPageController
from ..chat.style import CHAT_CSS
from ..layout import page_layout


@ui.page("/legacy/characters/{character_id}/chat")
async def character_chat_page(character_id: str) -> None:
    ctx = get_context()
    sheet = await ctx.characters.get(character_id)

    if sheet is None:
        with page_layout("キャラクターが見つかりません"):
            ui.label("指定されたキャラクターは存在しません。").classes("text-grey-6")
            ui.button("一覧に戻る", on_click=lambda: ui.navigate.to("/legacy/characters")).props("flat color=primary")
        return

    with page_layout(f"{sheet.name} とチャット"):
        ui.add_head_html(CHAT_CSS)
        controller = ChatPageController(ctx, sheet, ui.context.client)
        await controller.initialize()
        controller.render_shell()
