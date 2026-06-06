"""キャラクター選択 UI。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from inspect import isawaitable

from nicegui import ui

from ...core.character.schemas import CharacterSheet


async def open_character_picker(
    ctx,
    on_select: Callable[[CharacterSheet], Awaitable[None] | None],
    *,
    title: str = "ベースにするキャラクターを選択",
    empty_message: str = "保存済みキャラクターがありません",
) -> None:
    """作成済みキャラクターを選択するダイアログを開く。"""
    chars = await ctx.characters.list_all()
    if not chars:
        ui.notify(empty_message, type="warning")
        return

    with ui.dialog() as dlg, ui.card().classes("min-w-[400px]"):
        ui.label(title).classes("text-base font-semibold mb-2")
        with ui.scroll_area().style("height: 50vh; width: 100%"):
            with ui.list().props("dense separator").classes("w-full"):
                for char in chars:

                    def _make_handler(c: CharacterSheet):
                        async def _select() -> None:
                            result = on_select(c)
                            if isawaitable(result):
                                await result
                            dlg.close()

                        return _select

                    with ui.item(on_click=_make_handler(char)).classes("cursor-pointer"):
                        with ui.item_section():
                            ui.item_label(char.name).classes("font-medium")
                            desc = " / ".join(filter(None, [char.world, char.occupation]))
                            if desc:
                                ui.item_label(desc).props("caption")
    dlg.open()
