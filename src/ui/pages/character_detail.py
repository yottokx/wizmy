"""
キャラクター詳細・編集ページ。

Markdown シートの表示・直接編集、タグ編集、メディア参照、
修正/関連キャラ生成への送信、削除機能を提供する。
"""

from __future__ import annotations

from typing import Any

from nicegui import app, ui

from ...app_context import get_context
from ...services.character_generation import parse_markdown_to_sheet
from ..components.character_media import render_character_media_panel
from ..layout import page_layout


@ui.page("/characters/{character_id}")
async def character_detail_page(character_id: str) -> None:
    ctx = get_context()
    sheet = await ctx.characters.get(character_id)

    if sheet is None:
        with page_layout("キャラクターが見つかりません"):
            ui.label("指定されたキャラクターは存在しません。").classes("text-grey-6")
            ui.button("一覧に戻る", on_click=lambda: ui.navigate.to("/characters")).props("flat color=primary")
        return

    with page_layout(sheet.name):
        with ui.row().classes("items-center gap-2 mb-4 flex-wrap"):
            ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/characters")).props("flat round")
            ui.label(sheet.name).classes("text-2xl font-bold flex-1")

            favorite_btn = (
                ui.button(
                    icon="star" if sheet.is_favorite else "star_border",
                    on_click=lambda: _toggle_favorite(),
                )
                .props("flat round")
                .style(f"color: {'#D9A441' if sheet.is_favorite else '#AAA8A0'};")
            )
            with favorite_btn:
                favorite_tooltip = ui.tooltip("お気に入りを解除" if sheet.is_favorite else "お気に入りに追加")

            with ui.button_group().props("flat"):
                ui.button(
                    "チャット",
                    icon="forum",
                    on_click=lambda: ui.navigate.to(f"/characters/{character_id}/chat"),
                ).props("flat color=primary size=sm").tooltip("このキャラクターとチャットする")
                ui.button(
                    "修正に送る",
                    icon="edit",
                    on_click=lambda: _send_to_generation("modify"),
                ).props("flat color=primary size=sm").tooltip("このシートをベースに修正生成する")
                ui.button(
                    "関連キャラ作成",
                    icon="person_add",
                    on_click=lambda: _send_to_generation("related"),
                ).props("flat color=secondary size=sm").tooltip("このシートをベースに関連キャラを生成する")

            ui.button(
                icon="download",
                on_click=lambda: ui.download(sheet.raw_markdown.encode("utf-8"), f"{sheet.name}.md"),
            ).props("flat round").tooltip("Markdownをダウンロード")
            ui.button(
                icon="content_copy",
                on_click=lambda: _copy_to_clipboard(),
            ).props("flat round").tooltip("Markdownをコピー")
            ui.button(
                icon="delete",
                on_click=lambda: _confirm_delete(),
            ).props("flat round color=negative").tooltip("削除")

        def _send_to_generation(mode: str) -> None:
            app.storage.user["gen_mode"] = mode
            app.storage.user["gen_char_id"] = character_id
            ui.navigate.to("/")

        async def _toggle_favorite() -> None:
            saved = await ctx.characters.set_favorite(character_id, not sheet.is_favorite)
            sheet.is_favorite = saved.is_favorite
            favorite_btn.set_icon("star" if sheet.is_favorite else "star_border")
            favorite_btn.style(f"color: {'#D9A441' if sheet.is_favorite else '#AAA8A0'};")
            favorite_tooltip.set_text("お気に入りを解除" if sheet.is_favorite else "お気に入りに追加")
            ui.notify(
                "お気に入りに追加しました" if sheet.is_favorite else "お気に入りを解除しました",
                type="positive",
            )

        with ui.card().classes("w-full mb-4"):
            with ui.row().classes("gap-6 flex-wrap"):
                for label, value in sheet.to_display_dict().items():
                    if value:
                        with ui.column().classes("gap-0"):
                            ui.label(label).classes("text-xs text-grey-6")
                            ui.label(value).classes("text-sm font-medium")

            if sheet.tags:
                with ui.row().classes("gap-2 mt-3 flex-wrap"):
                    for tag in sheet.tags:
                        ui.badge(tag).props("outline color=primary")

        with ui.row().classes("items-center gap-2 mb-4"):
            ui.label("タグ:").classes("text-sm font-medium")
            tags_row = ui.row().classes("gap-2 flex-wrap items-center")
            with tags_row:
                _render_tags(sheet, tags_row, ctx)

        if sheet.generation_meta.model_id:
            with ui.expansion("生成情報", icon="info").props("dense").classes("w-full mb-4"):
                meta = sheet.generation_meta
                with ui.grid(columns=2).classes("gap-x-4 gap-y-1 text-sm"):
                    ui.label("プロファイル:").classes("text-grey-6")
                    ui.label(meta.llm_profile_name or "-")
                    ui.label("モデル:").classes("text-grey-6")
                    ui.label(meta.model_id or "-")
                    ui.label("Temperature:").classes("text-grey-6")
                    ui.label(str(meta.temperature) if meta.temperature is not None else "N/A (reasoning)")
                    ui.label("品質:").classes("text-grey-6")
                    _quality_label(meta.quality_status)
                    ui.label("ツール呼び出し:").classes("text-grey-6")
                    ui.label(f"{meta.tool_count} 件")

        edit_mode = {"active": False}

        with ui.row().classes("w-full items-start gap-4 flex-col lg:flex-row"):
            with ui.column().classes("w-full lg:flex-1 min-w-0"):
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center justify-between mb-2"):
                        ui.label("キャラクターシート").classes("text-base font-semibold")
                        with ui.row().classes("gap-1"):
                            toggle_raw_btn = ui.button("Markdown表示", on_click=lambda: _toggle_raw()).props(
                                "flat size=sm"
                            )
                            edit_btn = ui.button("編集", icon="edit", on_click=lambda: _enter_edit()).props(
                                "flat size=sm color=primary"
                            )
                            save_edit_btn = (
                                ui.button("保存", icon="save", on_click=lambda: _save_edit())
                                .props("unelevated size=sm color=primary")
                                .classes("hidden")
                            )
                            cancel_edit_btn = (
                                ui.button("キャンセル", on_click=lambda: _cancel_edit())
                                .props("flat size=sm")
                                .classes("hidden")
                            )

                    sheet_container = ui.element("div").classes("w-full")
                    edit_area: dict[str, Any] = {"ref": None}
                    view_mode = {"raw": False}

                    with sheet_container:
                        ui.markdown(sheet.raw_markdown).classes("prose prose-sm max-w-none")

            media_panel = ui.column().classes("w-full lg:w-[360px] gap-4 shrink-0")

        def _refresh_media_panel() -> None:
            media_panel.clear()
            with media_panel:
                _render_media_panel(sheet, ctx, character_id, _refresh_media_panel)

        _refresh_media_panel()

        def _toggle_raw() -> None:
            if edit_mode["active"]:
                return
            view_mode["raw"] = not view_mode["raw"]
            sheet_container.clear()
            with sheet_container:
                if view_mode["raw"]:
                    ui.code(sheet.raw_markdown, language="markdown").classes("w-full text-xs")
                    toggle_raw_btn.set_text("レンダリング表示")
                else:
                    ui.markdown(sheet.raw_markdown).classes("prose prose-sm max-w-none")
                    toggle_raw_btn.set_text("Markdown表示")

        def _enter_edit() -> None:
            edit_mode["active"] = True
            sheet_container.clear()
            with sheet_container:
                ta = ui.textarea(value=sheet.raw_markdown).classes("w-full font-mono text-sm").props("rows=30 outlined")
                edit_area["ref"] = ta
                with ui.row().classes("justify-end gap-2 mt-2"):
                    ui.button("キャンセル", on_click=lambda: _cancel_edit()).props("flat size=sm")
                    ui.button("保存", icon="save", on_click=lambda: _save_edit()).props(
                        "unelevated size=sm color=primary"
                    )
            toggle_raw_btn.classes("hidden")
            edit_btn.classes("hidden")
            save_edit_btn.classes(remove="hidden")
            cancel_edit_btn.classes(remove="hidden")

        async def _save_edit() -> None:
            ta = edit_area["ref"]
            if ta is None:
                return
            new_md = ta.value.strip()
            if not new_md:
                ui.notify("シートが空です", type="warning")
                return
            updated = parse_markdown_to_sheet(new_md, sheet.id)
            updated.tags = sheet.tags
            updated.media = sheet.media
            updated.is_favorite = sheet.is_favorite
            updated.generation_meta = sheet.generation_meta
            updated.created_at = sheet.created_at
            saved = await ctx.characters.save(updated)
            sheet.raw_markdown = new_md
            sheet.name = saved.name
            sheet.tags = saved.tags
            sheet.media = saved.media
            ui.notify(f"「{saved.name}」を保存しました", type="positive")
            _cancel_edit()

        def _cancel_edit() -> None:
            edit_mode["active"] = False
            sheet_container.clear()
            with sheet_container:
                if view_mode["raw"]:
                    ui.code(sheet.raw_markdown, language="markdown").classes("w-full text-xs")
                else:
                    ui.markdown(sheet.raw_markdown).classes("prose prose-sm max-w-none")
            toggle_raw_btn.classes(remove="hidden")
            edit_btn.classes(remove="hidden")
            save_edit_btn.classes("hidden")
            cancel_edit_btn.classes("hidden")

        def _copy_to_clipboard() -> None:
            ui.run_javascript(f"navigator.clipboard.writeText({repr(sheet.raw_markdown)})")
            ui.notify("コピーしました", type="positive")

        def _confirm_delete() -> None:
            with ui.dialog() as dlg, ui.card():
                ui.label(f"「{sheet.name}」を削除しますか？").classes("text-base font-medium mb-2")
                ui.label("この操作は取り消せません。").classes("text-sm text-grey-6")
                with ui.row().classes("justify-end gap-2 mt-4"):
                    ui.button("キャンセル", on_click=dlg.close).props("flat")
                    ui.button("削除", on_click=lambda: _do_delete(dlg)).props("color=negative unelevated")
            dlg.open()

        async def _do_delete(dlg) -> None:
            await ctx.characters.delete(character_id)
            ui.notify(f"「{sheet.name}」を削除しました", type="positive")
            dlg.close()
            ui.navigate.to("/characters")


def _render_media_panel(sheet, ctx, character_id: str, refresh_fn) -> None:
    render_character_media_panel(sheet, ctx, character_id, refresh_fn)


def _render_tags(sheet, container, ctx) -> None:
    container.clear()
    with container:
        for tag in list(sheet.tags):

            def _make_remove(t: str):
                async def _remove() -> None:
                    if t in sheet.tags:
                        sheet.tags.remove(t)
                        await ctx.characters.save(sheet)
                        _render_tags(sheet, container, ctx)

                return _remove

            with ui.row().classes("items-center gap-0"):
                ui.badge(tag).props("outline color=primary").classes("text-xs px-2 py-1")
                ui.button(icon="close", on_click=_make_remove(tag)).props("flat round dense size=xs").classes(
                    "text-grey-5"
                )

        def _open_tag_dialog() -> None:
            with ui.dialog() as dlg, ui.card().classes("min-w-[300px]"):
                ui.label("タグを追加").classes("text-base font-semibold mb-2")
                new_tag = ui.input(label="タグ名").classes("w-full")

                async def _add() -> None:
                    tag = new_tag.value.strip()
                    if tag and tag not in sheet.tags:
                        sheet.tags.append(tag)
                        await ctx.characters.save(sheet)
                        _render_tags(sheet, container, ctx)
                        ui.notify(f"タグ「{tag}」を追加しました", type="positive")
                    dlg.close()

                with ui.row().classes("justify-end gap-2 mt-3"):
                    ui.button("キャンセル", on_click=dlg.close).props("flat")
                    ui.button("追加", on_click=_add).props("color=primary unelevated")
            dlg.open()

        ui.button(icon="add", on_click=_open_tag_dialog).props("flat round dense color=primary").tooltip("タグを追加")


def _quality_label(status: str) -> None:
    labels = {"complete": ("良好", "positive"), "partial": ("部分的", "warning"), "failed": ("低い", "negative")}
    label, color = labels.get(status, ("不明", "grey"))
    ui.badge(label).props(f"color={color}")
