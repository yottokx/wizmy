"""キャラクター選択 UI。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from inspect import isawaitable

from nicegui import ui

from ...core.character.schemas import CharacterSheet
from ..chat.media import cropped_background_style

_AVATAR_STYLE = "border: 1px solid var(--cs-border); box-shadow: 0 1px 2px rgba(42, 35, 24, 0.08);"
_EMPTY_AVATAR_STYLE = "background: var(--cs-surface-soft); border: 1px solid var(--cs-border); color: var(--cs-muted);"


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

    search_query = {"value": ""}
    favorite_filter = {"value": False}

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-2xl").style("min-width: min(560px, 92vw);"):
        ui.label(title).classes("text-base font-semibold mb-2")
        with ui.row().classes("w-full items-center gap-3 mb-2 flex-wrap"):
            search_input = (
                ui.input(placeholder="名前・世界観・職業で検索")
                .props("clearable outlined dense")
                .classes("flex-1 min-w-[220px]")
            )
            search_input.props("prepend-icon=search")
            favorite_switch = ui.switch("お気に入りのみ", value=False).props("dense color=amber")
        count_label = ui.label("").classes("text-xs mb-1").style("color: var(--cs-muted);")
        list_container = ui.element("div").classes("w-full")

        async def _refresh(
            search: str | None = None,
            favorites_only: bool | None = None,
        ) -> None:
            if search is not None:
                search_query["value"] = search
            if favorites_only is not None:
                favorite_filter["value"] = favorites_only

            sheets = await ctx.characters.list_all(
                search=search_query["value"],
                favorites_only=favorite_filter["value"],
            )
            count_label.set_text(f"{len(sheets)} 件")
            list_container.clear()
            with list_container:
                with ui.scroll_area().style("height: 50vh; width: 100%"):
                    if not sheets:
                        with ui.column().classes("items-center justify-center py-10 w-full"):
                            ui.icon("search_off").classes("text-4xl mb-2").style("color: var(--cs-muted);")
                            ui.label("キャラクターが見つかりません").classes("text-sm").style("color: var(--cs-muted);")
                        return

                    with ui.list().props("dense separator").classes("w-full"):
                        for char in sheets:

                            def _make_handler(c: CharacterSheet):
                                async def _select() -> None:
                                    result = on_select(c)
                                    if isawaitable(result):
                                        await result
                                    dlg.close()

                                return _select

                            with ui.item(on_click=_make_handler(char)).classes(
                                "cursor-pointer items-center gap-3 py-2 min-w-0"
                            ):
                                _character_avatar(ctx, char)
                                with ui.item_section().classes("min-w-0"):
                                    ui.item_label(char.name).classes("font-medium whitespace-normal break-words")
                                    desc = " / ".join(filter(None, [char.world, char.occupation]))
                                    if desc:
                                        ui.item_label(desc).props("caption").classes("whitespace-normal break-words")
                                if char.is_favorite:
                                    with ui.item_section().props("side"):
                                        ui.icon("star").style("color: #D9A441;")

        async def _on_search_change(e) -> None:
            await _refresh(search=str(e.value or ""))

        async def _on_favorite_change(e) -> None:
            await _refresh(favorites_only=bool(e.value))

        search_input.on_value_change(_on_search_change)
        favorite_switch.on_value_change(_on_favorite_change)
        await _refresh()
    dlg.open()


def _character_avatar(ctx, sheet: CharacterSheet) -> None:
    image = sheet.media.primary_image()
    image_path = ctx.characters.media_path(image.path) if image else None
    style = cropped_background_style(image, image_path, image.face_rect, 1.0) if image and image_path else ""
    if style:
        ui.element("div").classes("w-11 h-11 rounded-md shrink-0").style(f"{_AVATAR_STYLE} {style}")
        return

    with (
        ui.element("div")
        .classes("w-11 h-11 rounded-md shrink-0 flex items-center justify-center")
        .style(_EMPTY_AVATAR_STYLE)
    ):
        ui.icon("person").classes("text-lg")
