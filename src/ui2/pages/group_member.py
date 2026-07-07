"""
/v2/groups/{id}/members/{mid} メンバー詳細(適応シート)+ /v2/groups/{id}/persona(Phase 4)。

- メンバー詳細はキャラクターシートページ(Phase 2)の箱庭版:
  章立て表示+章編集+Markdownモード(プレビュー無し)を `update_member_character` に接続。
  適応情報(参加区分・来訪理由・適応メモ)を左ペインに表示する。
- メディアは Phase 2 と同スコープ(一覧+アップロード+face/bust rect+メイン切替)。
  画像生成/ボイスデザイン等のダイアログ群は Phase 6(それまで旧メンバーページへ一時リンク)。
- 修正生成/関連キャラ生成はグループ内生成(旧 /groups/{id}/generation)へ送出
  (Phase 5 で /v2 版に差し替え)。
- ペルソナページは基本情報+編集(ハンドル/表示名/名前/説明)。
"""

from __future__ import annotations

import html
import json

from nicegui import app, ui

from ...app_context import get_context
from ...core.character.markdown import (
    base_character_markdown,
    replace_markdown_section,
    sheet_from_markdown_preserving,
)
from ...core.character.schemas import CharacterSheet
from ...core.conversation.group_setup import sanitize_handle
from ...core.group_chat.schemas import GroupMember
from ..components.portrait import image_object_position, media_url, raw_img
from ..components.rect_editor import open_rect_dialog
from ..group_logic import entry_type_label
from ..group_setup import chip_button, p3_button
from ..scaffold import p3_page
from ..sheet_logic import (
    classify_body,
    kanji_number,
    list_items,
    parse_sections,
    strip_outer_quotes,
    table_rows,
)

_MAX_THUMBS = 3

_DIALOG_CARD_STYLE = "background: var(--panel); color: var(--text);"

# キャラクターシートページ(Phase 2)の <style> を箱庭版に流用
_PAGE_CSS = """
.shell {
  display: grid;
  grid-template-columns: 400px minmax(0, 1fr);
  min-height: calc(100vh - 55px);
  max-width: 1360px;
  margin: 0 auto;
}

/* ---------- 左:その住人 ---------- */
.side {
  position: sticky;
  top: 55px;
  height: calc(100vh - 55px);
  overflow-y: auto;
  padding: 0 0 26px;
  border-right: 1px solid var(--line);
}
.side .portrait { position: relative; height: 46vh; min-height: 320px; }
.side .portrait img {
  width: 100%; height: 100%;
  object-fit: cover;
  -webkit-mask-image: linear-gradient(to top, transparent 2%, #000 32%);
  mask-image: linear-gradient(to top, transparent 2%, #000 32%);
}
.side .portrait .portrait-ph {
  width: 100%; height: 100%;
  display: grid; place-items: center;
  background: var(--panel);
  color: var(--peri);
  font-size: 64px;
  font-family: "Yu Mincho", serif;
}
.side .back {
  position: absolute; top: 14px; left: 14px; z-index: 3;
  width: 34px; height: 34px;
  display: grid; place-items: center;
  border-radius: 50%;
  background: color-mix(in srgb, var(--bg) 55%, transparent);
  border: 1px solid var(--line-2);
  color: var(--text);
  backdrop-filter: blur(6px);
  cursor: pointer;
}
.side-body { padding: 0 26px; margin-top: -30px; position: relative; z-index: 2; }
.side-body h1 { margin: 0 0 2px; font-size: 27px; letter-spacing: .1em; font-weight: 600; }
.side-body .oc { color: var(--muted); font-size: 12.5px; letter-spacing: .05em; margin-bottom: 16px; }
.side-actions { display: flex; gap: 8px; flex-wrap: wrap; margin: 18px 0 0; }
.tag {
  display: inline-block;
  font-size: 10px;
  color: var(--peri);
  border: 1px solid color-mix(in srgb, var(--peri) 45%, transparent);
  border-radius: 6px;
  padding: 0 7px;
  margin-left: 8px;
  vertical-align: 3px;
  letter-spacing: .08em;
}

.side .blk { margin-top: 24px; }
.side .blk .lbl { font-size: 10.5px; letter-spacing: .3em; color: var(--muted); margin-bottom: 10px; }
.adapt-info { font-size: 12.5px; color: var(--muted); line-height: 1.8; }
.adapt-info b { color: var(--text); font-weight: 600; }

.thumbs { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.thumbs img, .thumbs .more-th {
  width: 56px; height: 72px;
  border-radius: 10px;
  object-fit: cover;
  border: 1px solid var(--line-2);
  cursor: pointer;
}
.thumbs img.main { border-color: var(--accent); box-shadow: 0 0 0 2px var(--glow); }
.thumbs .more-th {
  display: grid; place-items: center;
  color: var(--muted); font-size: 11.5px;
  background: var(--panel);
}
.voice-row {
  display: flex; align-items: center; gap: 10px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 9px 12px;
  font-size: 12px; color: var(--muted);
}
.voice-row audio { width: 100%; height: 34px; }
.media-links { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }

/* ---------- 右:シート ---------- */
.sheet-wrap { padding: 26px 34px 60px; min-width: 0; }
.sheet-head { display: flex; align-items: center; gap: 12px; margin-bottom: 22px; flex-wrap: wrap; }
.vmode { display: flex; border: 1px solid var(--line-2); border-radius: 999px; overflow: hidden; }
.vmode button { border: none; background: none; cursor: pointer; padding: 7px 20px; font-size: 13px; color: var(--muted); }
.vmode button.on { background: var(--panel-2); color: var(--text); }
.sheet-head .grow { flex: 1; }
.meta-note { font-size: 11px; color: var(--muted); }

.sec { position: relative; padding: 20px 0 20px 52px; border-top: 1px solid var(--line); }
.sec:first-of-type { border-top: none; }
.sec .no {
  position: absolute; left: 6px; top: 20px;
  color: var(--peri);
  font-family: "Yu Mincho", serif;
  font-size: 17px;
}
.sec h3 { margin: 0 0 10px; font-size: 14px; letter-spacing: .16em; font-weight: 600; }
.sec .bd { font-size: 14px; line-height: 2; color: var(--text); max-width: 680px; }
.sec .bd ul { margin: 0; padding-left: 20px; }
.sec .bd li { margin: 2px 0; }
.sec .kv { display: grid; grid-template-columns: 110px 1fr; gap: 4px 18px; max-width: 560px; margin: 0; }
.sec .kv dt { color: var(--muted); font-size: 12.5px; padding-top: 3px; }
.sec .kv dd { margin: 0; font-size: 14px; }
.sec .quote {
  font-family: "Yu Mincho", serif;
  border-left: 2px solid var(--peri);
  padding-left: 14px;
  color: var(--text);
}
.sec .edit-btn {
  position: absolute; right: 0; top: 18px;
  opacity: 0;
  transition: opacity .18s;
}
.sec:hover .edit-btn { opacity: 1; }
.sec .ed-ops { display: flex; gap: 8px; margin-top: 10px; }

.p3-ta { width: 100%; }
.p3-ta .q-field__control { background: var(--bg-2) !important; border-radius: 12px; }
.p3-ta .q-field__control:before { border-color: var(--line-2) !important; }
.p3-ta textarea, .p3-ta input { color: var(--text) !important; line-height: 1.9; }
.sec .p3-ta { max-width: 680px; }
.md-wrap { max-width: 860px; }
.md-bar { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
.md-bar .warn { font-size: 11.5px; color: var(--muted); }
.md-ed textarea {
  font-family: Consolas, "Courier New", monospace;
  font-size: 12.5px;
  line-height: 1.8;
  min-height: 65vh;
  white-space: pre;
  overflow-x: auto;
}

@media (max-width: 980px) {
  .shell { display: block; }
  .side {
    position: static;
    height: auto;
    border-right: none;
    border-bottom: 1px solid var(--line);
  }
  .side .portrait { height: 44vh; }
  .sheet-wrap { padding: 20px 16px 50px; }
  .sec { padding-left: 40px; }
  .sec .edit-btn { opacity: .7; }
  .md-ed textarea { min-height: 50vh; }
}
"""


def _open_upload_dialog(*, title: str, accept: str, max_file_size: int, on_upload) -> None:
    with ui.dialog() as dlg, ui.card().classes("min-w-[380px]").style(_DIALOG_CARD_STYLE):
        ui.label(title).classes("text-base font-semibold mb-2")

        async def _handle(e) -> None:
            if await on_upload(e):
                dlg.close()

        ui.upload(
            label="ファイルをドロップ / 選択",
            on_upload=_handle,
            auto_upload=True,
            max_file_size=max_file_size,
        ).props(f"accept={accept} flat bordered").classes("w-full")
        with ui.row().classes("justify-end mt-3 w-full"):
            p3_button("閉じる", dlg.close, classes="btn quiet")
    dlg.open()


def _render_not_found(message: str, back_route: str, back_label: str) -> None:
    with ui.element("div").style("max-width: 640px; margin: 0 auto; padding: 60px 26px;"):
        ui.label(message).classes("note").style("font-size: 14px;")
        with ui.element("div").style("margin-top: 18px;"):
            p3_button(back_label, lambda route=back_route: ui.navigate.to(route))


@ui.page("/v2/groups/{group_id}/members/{member_id}")
async def ui2_group_member_page(group_id: str, member_id: str) -> None:
    ctx = get_context()
    group = await ctx.group_chats.get(group_id)
    if group is None:
        with p3_page("グループ"):
            _render_not_found("指定されたグループは存在しません。", "/v2/groups", "グループ一覧へ")
        return
    member = next((item for item in group.members if item.id == member_id), None)
    if member is None:
        with p3_page("グループ"):
            _render_not_found(
                "指定されたメンバーはこのグループに存在しません。",
                f"/v2/groups/{group.id}",
                "グループへ戻る",
            )
        return

    state: dict = {"member": member, "view": "sheet"}

    def _member() -> GroupMember:
        return state["member"]

    def _sheet() -> CharacterSheet:
        return _member().character

    def _apply_saved(saved: GroupMember | None) -> None:
        if saved is None:
            raise ValueError("グループ内キャラクターが見つかりませんでした。")
        state["member"] = saved

    def _send_to_group_generation(mode: str) -> None:
        app.storage.user["group_gen_mode"] = mode
        app.storage.user["group_gen_member_ids"] = [member_id]
        ui.navigate.to(f"/v2/groups/{group.id}/generation")

    with p3_page("グループ"):
        ui.add_css(_PAGE_CSS)
        with ui.element("div").classes("shell"):
            with ui.element("aside").classes("side"):
                portrait_box = ui.element("div").classes("portrait")
                side_body = ui.element("div").classes("side-body")

            with ui.element("main").classes("sheet-wrap"):
                with ui.element("div").classes("sheet-head"):
                    with ui.element("div").classes("vmode"):
                        sheet_mode_btn = ui.element("button").classes("on")
                        with sheet_mode_btn:
                            ui.html("シート")
                        md_mode_btn = ui.element("button").mark("ui2-member-vmode-md")
                        with md_mode_btn:
                            ui.html("Markdown")
                    ui.element("div").classes("grow")
                    meta_note = ui.element("span").classes("meta-note")
                    p3_button(
                        "書き出し(.md)",
                        lambda: ui.download(
                            base_character_markdown(_sheet()).encode("utf-8"),
                            f"{_sheet().name or 'member'}.md",
                        ),
                        classes="btn quiet",
                    )
                    p3_button("コピー", lambda: _copy_markdown(), classes="btn quiet")

                secs_container = ui.element("div").classes("sheet-secs").mark("ui2-member-secs")

                md_wrap = ui.element("div").classes("md-wrap")
                with md_wrap:
                    with ui.element("div").classes("md-bar"):
                        p3_button("保存", lambda: _save_markdown(), classes="btn primary").style(
                            "padding: 7px 22px;"
                        ).mark("ui2-member-md-save")
                        p3_button("破棄", lambda: _discard_markdown(), classes="btn quiet")
                        with ui.element("span").classes("warn"):
                            ui.html("保存時に Markdown からシート項目へ再パースされます（逆方向も常に同期）")
                    md_editor = (
                        ui.textarea(value=base_character_markdown(_sheet()))
                        .classes("p3-ta md-ed")
                        .props("outlined spellcheck=false")
                        .mark("ui2-member-md")
                    )
                md_wrap.set_visibility(False)

        # ---------------- 表示 ----------------

        def _render_portrait() -> None:
            portrait_box.clear()
            with portrait_box:
                back = ui.element("a").classes("back").props('title="グループへ戻る"')
                with back:
                    ui.html("←")
                back.on("click", lambda: ui.navigate.to(f"/v2/groups/{group.id}"))
                image = _sheet().media.primary_image()
                url = media_url(image.path) if image is not None else None
                if url is not None:
                    raw_img(url).style(f"object-position: {image_object_position(image)};")
                else:
                    with ui.element("div").classes("portrait-ph"):
                        ui.html(html.escape((_sheet().name or "?")[:1]))

        def _render_side_body() -> None:
            sheet = _sheet()
            current = _member()
            side_body.clear()
            with side_body:
                with ui.element("h1").classes("serif").mark("ui2-member-name"):
                    ui.html(html.escape(sheet.name))
                oc = sheet.occupation
                if sheet.age:
                    oc = f"{oc} ・ {sheet.age}" if oc else sheet.age
                with ui.element("div").classes("oc"):
                    ui.html(html.escape(f"@{current.handle}" + (f" ・ {oc}" if oc else "")))
                    with ui.element("span").classes("tag"):
                        ui.html("適応コピー")
                intro = strip_outer_quotes(sheet.self_intro)
                if intro:
                    with ui.element("div").classes("bubble tail-left"):
                        ui.html(html.escape(f"「{intro}」"))
                with ui.element("div").classes("side-actions"):
                    p3_button(
                        "チャットへ",
                        lambda: ui.navigate.to(f"/v2/groups/{group.id}"),
                        classes="btn primary",
                    )
                    p3_button("修正して生成", lambda: _send_to_group_generation("modify"))
                    p3_button("知りあいを生成", lambda: _send_to_group_generation("related"), classes="btn quiet")

                # ---- 適応情報 ----
                with ui.element("div").classes("blk"):
                    with ui.element("div").classes("lbl"):
                        ui.html("こ の 世 界 で は")
                    with ui.element("div").classes("adapt-info"):
                        parts = []
                        if current.world_entry_type:
                            parts.append(f"<b>{html.escape(entry_type_label(current.world_entry_type))}</b>")
                        else:
                            parts.append("<b>この世界に適応した住人</b>")
                        if current.arrival_reason:
                            parts.append(html.escape(current.arrival_reason))
                        if current.world_adaptation_note:
                            parts.append(html.escape(current.world_adaptation_note))
                        ui.html("<br>".join(parts))

                # ---- 画像 ----
                with ui.element("div").classes("blk"):
                    with ui.element("div").classes("lbl"):
                        ui.html("画 像")
                    with ui.element("div").classes("thumbs"):
                        primary = sheet.media.primary_image()
                        images = sheet.media.images[:_MAX_THUMBS]
                        if primary is not None and primary not in images:
                            images = [primary, *images][:_MAX_THUMBS]
                        for asset in images:
                            url = media_url(asset.path)
                            if url is None:
                                continue
                            thumb = raw_img(url).props(
                                'loading="lazy" title="クリックでメイン画像にする"'
                            ).style(f"object-position: {image_object_position(asset)};")
                            if primary is not None and asset.id == primary.id:
                                thumb.classes("main")
                            thumb.on("click", lambda asset_id=asset.id: _set_primary_image(asset_id))
                        rest = len(sheet.media.images) - len(images)
                        if rest > 0:
                            more = ui.element("span").classes("more-th").props(
                                'title="画像を管理(旧UI・Phase 6 で /v2 版に置き換え)"'
                            )
                            with more:
                                ui.html(f"+{rest}")
                            more.on(
                                "click",
                                lambda: ui.navigate.to(f"/groups/{group.id}/members/{member_id}"),
                            )
                        if not sheet.media.images:
                            with ui.element("span").classes("note"):
                                ui.html("まだ画像がありません")
                    with ui.element("div").classes("media-links"):
                        chip_button("アップロード", _open_image_upload)
                        if sheet.media.primary_image() is not None:
                            chip_button("顔範囲", lambda: _open_rect("face"))
                            chip_button("バスト範囲", lambda: _open_rect("bust"))
                        chip_button(
                            "画像を管理・生成",
                            lambda: ui.navigate.to(f"/groups/{group.id}/members/{member_id}"),
                            title="旧ページが開きます（画像生成などは Phase 6 で /v2 版に）",
                        )

                # ---- 音声 ----
                with ui.element("div").classes("blk"):
                    with ui.element("div").classes("lbl"):
                        ui.html("音 声")
                    voice = sheet.media.primary_voice()
                    voice_url = media_url(voice.path) if voice is not None else None
                    with ui.element("div").classes("voice-row"):
                        if voice_url is not None:
                            ui.audio(voice_url)
                        else:
                            text = "まだ設定されていません"
                            if sheet.voice_image:
                                text += f" — 声イメージ: {sheet.voice_image}"
                            ui.html(html.escape(text))
                    with ui.element("div").classes("media-links"):
                        chip_button("アップロード", _open_voice_upload)
                        chip_button(
                            "音声を管理・ボイスデザイン",
                            lambda: ui.navigate.to(f"/groups/{group.id}/members/{member_id}"),
                            title="旧ページが開きます（ボイスデザイン等は Phase 6 で /v2 版に）",
                        )

        def _render_meta_note() -> None:
            sheet = _sheet()
            meta_note.clear()
            parts: list[str] = [f"グループ: {group.name}"]
            meta = sheet.generation_meta
            if meta.model_id:
                parts.append(f"生成: {meta.model_id}")
            with meta_note:
                ui.html(html.escape(" ・ ".join(parts)))

        def _render_section_body(body: str) -> None:
            kind = classify_body(body)
            if kind == "table":
                with ui.element("dl").classes("kv"):
                    for key, value in table_rows(body):
                        with ui.element("dt"):
                            ui.html(html.escape(key))
                        with ui.element("dd"):
                            ui.html(html.escape(value))
            elif kind == "list":
                with ui.element("ul"):
                    for item in list_items(body):
                        with ui.element("li"):
                            ui.html(html.escape(item))
            elif kind == "quote":
                with ui.element("div").classes("quote"):
                    ui.html(html.escape(body.strip()))
            else:
                ui.html(html.escape(body).replace("\n", "<br>"))

        def _render_sections() -> None:
            secs_container.clear()
            sections = parse_sections(base_character_markdown(_sheet()))
            with secs_container:
                if not sections:
                    with ui.element("div").classes("note").style("padding: 30px 0;"):
                        ui.html("シートに章がありません。Markdown モードで追記できます。")
                for index, section in enumerate(sections):
                    sec = ui.element("section").classes("sec")
                    with sec:
                        with ui.element("span").classes("no"):
                            ui.html(kanji_number(index + 1))
                        with ui.element("h3"):
                            ui.html(html.escape(section.header))
                        bd = ui.element("div").classes("bd")
                        with bd:
                            _render_section_body(section.body)
                        p3_button(
                            "編集",
                            lambda s=section, target=bd: _edit_section(s, target),
                            classes="btn quiet edit-btn",
                        )

        def _edit_section(section, bd: ui.element) -> None:
            bd.clear()
            with bd:
                editor = (
                    ui.textarea(value=section.body)
                    .classes("p3-ta")
                    .props("outlined autogrow spellcheck=false")
                )
                with ui.element("div").classes("ed-ops"):

                    async def _save() -> None:
                        new_md = replace_markdown_section(
                            base_character_markdown(_sheet()), section.header, str(editor.value or "")
                        )
                        await _apply_markdown(new_md, f"「{section.header}」を保存しました")

                    p3_button("保存", _save, classes="btn primary").style(
                        "padding: 5px 18px; font-size: 12.5px;"
                    )
                    p3_button("取消", lambda: _render_sections(), classes="btn quiet")

        # ---------------- 操作 ----------------

        async def _apply_markdown(new_md: str, message: str) -> None:
            new_md = new_md.strip()
            if not new_md:
                ui.notify("シートが空です", type="warning")
                return
            updated = sheet_from_markdown_preserving(_sheet(), new_md)
            saved = await ctx.group_chats.update_member_character(group.id, member_id, updated)
            if saved is None:
                ui.notify("グループ内キャラクターが見つかりませんでした", type="warning")
                return
            state["member"] = saved
            md_editor.set_value(base_character_markdown(saved.character))
            _refresh_all()
            ui.notify(message, type="positive")

        async def _save_markdown() -> None:
            await _apply_markdown(str(md_editor.value or ""), "シートを保存しました")

        def _discard_markdown() -> None:
            md_editor.set_value(base_character_markdown(_sheet()))

        def _copy_markdown() -> None:
            ui.run_javascript(
                f"navigator.clipboard.writeText({json.dumps(base_character_markdown(_sheet()))})"
            )
            ui.notify("コピーしました", type="positive")

        async def _set_primary_image(asset_id: str) -> None:
            sheet = _sheet()
            if sheet.media.primary_image_id == asset_id:
                return
            updated = sheet.model_copy(deep=True)
            updated.media.primary_image_id = asset_id
            saved = await ctx.group_chats.update_member_character(group.id, member_id, updated)
            if saved is None:
                ui.notify("グループ内キャラクターが見つかりませんでした", type="warning")
                return
            state["member"] = saved
            _render_portrait()
            _render_side_body()
            ui.notify("メイン画像を変更しました", type="positive")

        def _open_image_upload() -> None:
            async def _on_upload(e) -> bool:
                try:
                    _apply_saved(await ctx.group_chats.save_member_image(group.id, member_id, e.file))
                    ui.notify("画像を保存しました", type="positive")
                    _render_portrait()
                    _render_side_body()
                    return True
                except Exception as err:  # noqa: BLE001 - UI通知のための包括捕捉
                    ui.notify(f"画像の保存に失敗しました: {err}", type="negative")
                    return False

            _open_upload_dialog(
                title="画像をアップロード",
                accept="image/*",
                max_file_size=20 * 1024 * 1024,
                on_upload=_on_upload,
            )

        def _open_voice_upload() -> None:
            async def _on_upload(e) -> bool:
                try:
                    _apply_saved(await ctx.group_chats.save_member_voice(group.id, member_id, e.file))
                    ui.notify("音声を保存しました", type="positive")
                    _render_side_body()
                    return True
                except Exception as err:  # noqa: BLE001 - UI通知のための包括捕捉
                    ui.notify(f"音声の保存に失敗しました: {err}", type="negative")
                    return False

            _open_upload_dialog(
                title="音声をアップロード",
                accept="audio/*",
                max_file_size=50 * 1024 * 1024,
                on_upload=_on_upload,
            )

        def _open_rect(kind: str) -> None:
            image = _sheet().media.primary_image()
            if image is None:
                ui.notify("範囲を設定する画像がありません", type="warning")
                return
            image_path = ctx.group_chats.media_path(image.path)
            if image_path is None:
                ui.notify("画像ファイルが見つかりません", type="warning")
                return

            async def _on_save(rect, width: int, height: int) -> None:
                if kind == "face":
                    saved = await ctx.group_chats.update_member_face_rect(
                        group.id, member_id, rect, image_width=width, image_height=height
                    )
                else:
                    saved = await ctx.group_chats.update_member_bust_rect(
                        group.id, member_id, rect, image_width=width, image_height=height
                    )
                _apply_saved(saved)
                _render_portrait()
                _render_side_body()

            open_rect_dialog(image=image, image_path=image_path, kind=kind, on_save=_on_save)

        def _set_view(view: str) -> None:
            state["view"] = view
            is_md = view == "md"
            secs_container.set_visibility(not is_md)
            md_wrap.set_visibility(is_md)
            if is_md:
                md_mode_btn.classes("on")
                sheet_mode_btn.classes(remove="on")
            else:
                sheet_mode_btn.classes("on")
                md_mode_btn.classes(remove="on")

        sheet_mode_btn.on("click", lambda: _set_view("sheet"))
        md_mode_btn.on("click", lambda: _set_view("md"))

        def _refresh_all() -> None:
            _render_portrait()
            _render_side_body()
            _render_meta_note()
            _render_sections()

        _refresh_all()


@ui.page("/v2/groups/{group_id}/persona")
async def ui2_group_persona_page(group_id: str) -> None:
    ctx = get_context()
    group = await ctx.group_chats.get(group_id)
    if group is None:
        with p3_page("グループ"):
            _render_not_found("指定されたグループは存在しません。", "/v2/groups", "グループ一覧へ")
        return
    if group.user_persona is None:
        with p3_page("グループ"):
            _render_not_found(
                "このグループにはユーザーペルソナが設定されていません。",
                f"/v2/groups/{group.id}",
                "グループへ戻る",
            )
        return

    state: dict = {"persona": group.user_persona}

    def _persona():
        return state["persona"]

    def _title() -> str:
        persona = _persona()
        return persona.display_name or persona.name or "ユーザー"

    with p3_page("グループ"):
        with ui.element("div").style("max-width: 760px; margin: 0 auto; padding: 34px 26px 60px;"):
            with ui.row().classes("items-center gap-3 w-full"):
                back = ui.element("button").classes("btn quiet")
                with back:
                    ui.html("← グループへ")
                back.on("click", lambda: ui.navigate.to(f"/v2/groups/{group.id}"))
            title_el = ui.element("h1").classes("serif").style(
                "font-size: 26px; letter-spacing: .12em; margin: 18px 0 4px; font-weight: 600;"
            )
            with title_el:
                ui.html(html.escape(_title()))
            with ui.element("div").classes("note"):
                ui.html(html.escape(f"グループ「{group.name}」専用のあなた（グループ内コピー）"))

            info_box = ui.element("div").style(
                "margin-top: 22px; background: var(--panel); border: 1px solid var(--line);"
                " border-radius: 16px; padding: 20px 24px;"
            )

            def _render_view() -> None:
                info_box.clear()
                persona = _persona()
                with info_box:
                    with ui.row().classes("items-center justify-between w-full"):
                        ui.label("ユーザーペルソナ").classes("text-sm font-semibold")
                        chip_button("編集", _enter_edit).mark("ui2-persona-edit")
                    with ui.element("dl").style(
                        "display: grid; grid-template-columns: 110px 1fr; gap: 4px 18px; margin: 12px 0 0;"
                    ):
                        for label, value in (
                            ("ハンドル", f"@{persona.handle}"),
                            ("表示名", persona.display_name),
                            ("名前", persona.name),
                            (
                                "この世界では",
                                entry_type_label(persona.world_entry_type) if persona.world_entry_type else "",
                            ),
                            ("来訪理由", persona.arrival_reason),
                        ):
                            if not value:
                                continue
                            with ui.element("dt").style("color: var(--muted); font-size: 12.5px; padding-top: 3px;"):
                                ui.html(html.escape(label))
                            with ui.element("dd").style("margin: 0; font-size: 14px;"):
                                ui.html(html.escape(value))
                    ui.label("説明").classes("text-sm font-semibold mt-4")
                    ui.label(persona.description or "未設定").classes("text-sm").style(
                        "white-space: pre-wrap; line-height: 1.9; color: var(--muted);"
                    )

            def _enter_edit() -> None:
                info_box.clear()
                persona = _persona()
                with info_box:
                    ui.label("ユーザーペルソナを編集").classes("text-sm font-semibold")
                    handle_input = (
                        ui.input(label="ハンドル", value=persona.handle)
                        .props("outlined dense")
                        .classes("w-full p3-ta")
                        .mark("ui2-persona-handle")
                    )
                    display_name_input = (
                        ui.input(label="表示名", value=persona.display_name)
                        .props("outlined dense")
                        .classes("w-full p3-ta")
                    )
                    name_input = (
                        ui.input(label="名前", value=persona.name)
                        .props("outlined dense")
                        .classes("w-full p3-ta")
                        .mark("ui2-persona-name")
                    )
                    description_input = (
                        ui.textarea(label="説明", value=persona.description)
                        .props("outlined rows=8 autogrow")
                        .classes("w-full p3-ta")
                        .mark("ui2-persona-description")
                    )

                    async def _save() -> None:
                        current = _persona()
                        handle = str(handle_input.value or "").strip()
                        name = str(name_input.value or "").strip()
                        display_name = str(display_name_input.value or "").strip()
                        description = str(description_input.value or "").strip()
                        sanitized_handle = sanitize_handle(handle, current.handle or "User")
                        used_handles = {member.handle.lower() for member in group.members}
                        if sanitized_handle.lower() in used_handles:
                            ui.notify("同じハンドルの住人が既にいます", type="warning")
                            return
                        if not name:
                            ui.notify("名前を入力してください", type="warning")
                            return
                        updated = current.model_copy(
                            update={
                                "handle": sanitized_handle,
                                "name": name,
                                "display_name": display_name or name,
                                "description": description,
                            },
                            deep=True,
                        )
                        saved = await ctx.group_chats.update_user_persona(group.id, updated)
                        if saved is None:
                            ui.notify("ユーザーペルソナが見つかりませんでした", type="warning")
                            return
                        state["persona"] = saved
                        title_el.clear()
                        with title_el:
                            ui.html(html.escape(_title()))
                        ui.notify(f"「{_title()}」を保存しました", type="positive")
                        _render_view()

                    with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                        p3_button("キャンセル", lambda: _render_view(), classes="btn quiet")
                        p3_button("保存", _save, classes="btn primary").mark("ui2-persona-save")

            _render_view()
