"""
キャラクター一覧ページ。

作成済みキャラクターのグリッド表示・検索・タグ絞り込み・
Markdownファイルからのインポートを提供する。
"""

from __future__ import annotations

from nicegui import ui

from ...app_context import get_context
from ...services.character_generation import parse_markdown_to_sheet
from ..components.character_card import character_card
from ..layout import page_layout


@ui.page("/characters")
async def characters_page() -> None:
    ctx = get_context()

    search_query = {"value": ""}
    tag_filter = {"value": ""}
    favorite_filter = {"value": False}

    with page_layout("キャラクター一覧"):
        # 検索・フィルターバー
        with ui.row().classes("w-full items-center gap-3 mb-4 flex-wrap"):
            search_input = ui.input(
                placeholder="名前・世界観・職業で検索",
                on_change=lambda e: _refresh(
                    e.value,
                    tag_filter["value"],
                    favorite_filter["value"],
                ),
            ).props("clearable outlined dense").classes("flex-1 min-w-[200px]")
            search_input.props("prepend-icon=search")

            all_tags = await ctx.characters.get_all_tags()
            tag_opts: dict[str, str] = {"": "全タグ"} | {t: t for t in all_tags}
            tag_select = ui.select(
                options=tag_opts,
                value="",
                label="タグ絞り込み",
                on_change=lambda e: _refresh(search_query["value"], e.value, favorite_filter["value"]),
            ).props("outlined dense").classes("min-w-[160px]")

            ui.switch(
                "お気に入りのみ",
                value=False,
                on_change=lambda e: _refresh(
                    search_query["value"],
                    tag_filter["value"],
                    bool(e.value),
                ),
            ).props("dense color=amber")

            # Markdownインポートボタン
            ui.button(
                icon="upload_file",
                on_click=lambda: _open_import_dialog(),
            ).props("flat").style("color: #8A8880;").tooltip("Markdownファイルからインポート")

            ui.button(
                "新規生成", icon="add",
                on_click=lambda: ui.navigate.to("/"),
            ).props("color=primary unelevated").style(
                "border-radius: 8px; font-weight: 600;"
            ).tooltip("新しいキャラを生成")

        count_label = ui.label("").classes("text-xs mb-2").style("color: #8A8880;")

        # カードグリッドコンテナ
        grid_container = ui.element("div").classes(
            "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 w-full"
        )

        async def _confirm_delete(cid: str, cname: str) -> None:
            with ui.dialog() as dlg, ui.card():
                ui.label(f"「{cname}」を削除しますか？").classes("text-base font-medium mb-2")
                ui.label("この操作は取り消せません。").classes("text-sm text-grey-6")
                with ui.row().classes("justify-end gap-2 mt-4"):
                    ui.button("キャンセル", on_click=dlg.close).props("flat")

                    async def _do_delete():
                        await ctx.characters.delete(cid)
                        ui.notify(f"「{cname}」を削除しました", type="positive")
                        dlg.close()
                        await _refresh(
                            search_query["value"],
                            tag_filter["value"],
                            favorite_filter["value"],
                        )

                    ui.button("削除", icon="delete", on_click=_do_delete).props(
                        "color=negative unelevated"
                    )
            dlg.open()

        async def _refresh(search: str = "", tag: str = "", favorites_only: bool = False) -> None:
            search_query["value"] = search
            tag_filter["value"] = tag
            favorite_filter["value"] = favorites_only
            sheets = await ctx.characters.list_all(
                search=search,
                tag=tag,
                favorites_only=favorites_only,
            )
            count_label.set_text(f"{len(sheets)} 件")
            grid_container.clear()
            with grid_container:
                if not sheets:
                    with ui.column().classes("col-span-full items-center py-12"):
                        ui.icon("sentiment_neutral").classes("text-5xl mb-2").style("color: #CCC9C2;")
                        ui.label("キャラクターが見つかりません").style("color: #AAA8A0; font-size: 0.9rem;")
                        if not search and not tag and not favorites_only:
                            ui.button(
                                "最初のキャラを生成する",
                                on_click=lambda: ui.navigate.to("/"),
                            ).props("flat color=primary").style("margin-top: 8px;")
                else:
                    for sheet in sheets:
                        def _make_delete(s):
                            async def _handler():
                                await _confirm_delete(s.id, s.name)
                            return _handler

                        def _make_toggle_favorite(s):
                            async def _handler():
                                saved = await ctx.characters.set_favorite(s.id, not s.is_favorite)
                                ui.notify(
                                    f"「{saved.name}」をお気に入りに追加しました"
                                    if saved.is_favorite
                                    else f"「{saved.name}」のお気に入りを解除しました",
                                    type="positive",
                                )
                                await _refresh(
                                    search_query["value"],
                                    tag_filter["value"],
                                    favorite_filter["value"],
                                )
                            return _handler

                        character_card(
                            sheet,
                            on_click=lambda cid: ui.navigate.to(f"/characters/{cid}"),
                            on_chat=lambda cid: ui.navigate.to(f"/characters/{cid}/chat"),
                            on_delete=_make_delete(sheet),
                            on_toggle_favorite=_make_toggle_favorite(sheet),
                        )

        def _open_import_dialog() -> None:
            with ui.dialog() as dlg, ui.card().classes("min-w-[400px]"):
                ui.label("Markdownからインポート").classes("text-base font-semibold mb-2")
                ui.label(
                    "キャラクターシート形式の .md ファイルをアップロードしてください。"
                ).classes("text-sm text-grey-6 mb-3")

                upload_result: dict = {"text": None, "filename": ""}

                async def _on_upload(e) -> None:
                    try:
                        content = await e.file.read()
                        upload_result["text"] = content.decode("utf-8")
                        upload_result["filename"] = e.file.name
                        file_label.set_text(f"選択中: {e.file.name}")
                        file_label.classes(remove="text-grey-6")
                        file_label.classes("text-positive")
                    except Exception as err:
                        ui.notify(f"ファイルの読み込みに失敗しました: {err}", type="negative")

                ui.upload(
                    label="ファイルを選択",
                    on_upload=_on_upload,
                    auto_upload=True,
                ).props("accept=.md flat bordered").classes("w-full")

                file_label = ui.label("ファイル未選択").classes("text-sm text-grey-6 mt-1")

                async def _do_import() -> None:
                    md_text = upload_result["text"]
                    if not md_text:
                        ui.notify("ファイルを選択してください", type="warning")
                        return
                    try:
                        sheet = parse_markdown_to_sheet(md_text, ctx.characters.new_id())
                        await ctx.characters.save(sheet)
                        ui.notify(f"「{sheet.name}」をインポートしました", type="positive")
                        dlg.close()
                        await _refresh(
                            search_query["value"],
                            tag_filter["value"],
                            favorite_filter["value"],
                        )
                    except Exception as err:
                        ui.notify(f"インポートに失敗しました: {err}", type="negative")

                with ui.row().classes("justify-end gap-2 mt-4"):
                    ui.button("キャンセル", on_click=dlg.close).props("flat")
                    ui.button("インポート", icon="upload", on_click=_do_import).props(
                        "color=primary unelevated"
                    )
            dlg.open()

        await _refresh()
