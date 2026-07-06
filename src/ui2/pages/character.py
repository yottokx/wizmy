"""
/v2/characters/{id} キャラクターシート(Phase 2)。モック proposal3/character.html 準拠。

- 左: その子(立ち絵・お気に入り・アクション・画像サムネ・音声・タグ)
- 右: シート(章立て表示+章単位のその場編集 / Markdown 直接編集。プレビュー無し)
- 章編集は `replace_markdown_section` → `sheet_from_markdown_preserving` で
  raw_markdown とシート項目を常に双方向同期する
- メディアは Phase 2 スコープ(一覧+アップロード+face/bust rect 編集+管理ボタン)。
  画像生成/ボイスデザイン等のダイアログ群は Phase 6(それまで旧ページへ一時リンク)
- 「修正して生成/知りあいを生成」= gen_mode/gen_char_id を書いて旧 /(生成)へ
  (Phase 5 で /v2/generation に差し替え)
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
from ..components.portrait import image_object_position, media_url, raw_img
from ..components.rect_editor import open_rect_dialog
from ..components.sparkle import STAR_SVG
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

# モック character.html の <style> 移植(+ Quasar textarea の P3 スキン)
_PAGE_CSS = """
.shell {
  display: grid;
  grid-template-columns: 400px minmax(0, 1fr);
  min-height: calc(100vh - 55px);
  max-width: 1360px;
  margin: 0 auto;
}

/* ---------- 左:その子 ---------- */
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
  object-position: center 8%;
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
.side .fav {
  position: absolute; top: 14px; right: 14px; z-index: 3;
  width: 34px; height: 34px;
  display: grid; place-items: center;
  border-radius: 50%;
  background: color-mix(in srgb, var(--bg) 55%, transparent);
  border: 1px solid var(--line-2);
  cursor: pointer;
  backdrop-filter: blur(6px);
}
.side .fav svg { width: 15px; height: 15px; fill: var(--muted); transition: fill .2s; }
.side .fav.on svg { fill: var(--star); }
.side-body { padding: 0 26px; margin-top: -30px; position: relative; z-index: 2; }
.side-body h1 { margin: 0 0 2px; font-size: 27px; letter-spacing: .1em; font-weight: 600; }
.side-body .oc { color: var(--muted); font-size: 12.5px; letter-spacing: .05em; margin-bottom: 16px; }
.side-body .bubble { font-size: 13.5px; padding: 12px 16px; box-shadow: none; }
.side-actions { display: flex; gap: 8px; flex-wrap: wrap; margin: 18px 0 0; }

.side .blk { margin-top: 24px; }
.side .blk .lbl { font-size: 10.5px; letter-spacing: .3em; color: var(--muted); margin-bottom: 10px; }

/* メディア(コンパクト+専用エディタへの導線) */
.thumbs { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.thumbs img, .thumbs .more-th {
  width: 56px; height: 72px;
  border-radius: 10px;
  object-fit: cover;
  object-position: center 12%;
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

.tag-row { display: flex; gap: 8px; flex-wrap: wrap; }

/* ---------- 右:シート ---------- */
.sheet-wrap { padding: 26px 34px 60px; min-width: 0; }
.sheet-head { display: flex; align-items: center; gap: 12px; margin-bottom: 22px; flex-wrap: wrap; }
.vmode { display: flex; border: 1px solid var(--line-2); border-radius: 999px; overflow: hidden; }
.vmode button { border: none; background: none; cursor: pointer; padding: 7px 20px; font-size: 13px; color: var(--muted); }
.vmode button.on { background: var(--panel-2); color: var(--text); }
.sheet-head .grow { flex: 1; }
.meta-note { font-size: 11px; color: var(--muted); }

/* シート表示:章立て */
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

/* 章編集/Markdown 編集(Quasar textarea を P3 スキンに) */
.p3-ta { width: 100%; }
.p3-ta .q-field__control { background: var(--bg-2) !important; border-radius: 12px; }
.p3-ta .q-field__control:before { border-color: var(--line-2) !important; }
.p3-ta textarea { color: var(--text) !important; line-height: 1.9; }
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

/* ---------- 縦画面 ---------- */
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


def _p3_button(label: str, on_click, *, classes: str = "btn", title: str = "") -> ui.element:
    btn = ui.element("button").classes(classes)
    if title:
        btn.props(f'title="{html.escape(title)}"')
    with btn:
        ui.html(html.escape(label))
    btn.on("click", on_click)
    return btn


def _chip_button(label: str, on_click, *, title: str = "") -> ui.element:
    btn = ui.element("button").classes("chip")
    if title:
        btn.props(f'title="{html.escape(title)}"')
    with btn:
        ui.html(html.escape(label))
    btn.on("click", on_click)
    return btn


def _open_upload_dialog(*, title: str, accept: str, max_file_size: int, on_upload) -> None:
    with ui.dialog() as dlg, ui.card().classes("min-w-[380px]").style(
        "background: var(--panel); color: var(--text);"
    ):
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
            _p3_button("閉じる", dlg.close, classes="btn quiet")
    dlg.open()


@ui.page("/v2/characters/{character_id}")
async def ui2_character_page(character_id: str) -> None:
    ctx = get_context()
    sheet = await ctx.characters.get(character_id)

    if sheet is None:
        with p3_page("キャラクター"):
            with ui.element("div").style("max-width: 640px; margin: 0 auto; padding: 60px 26px;"):
                ui.label("指定されたキャラクターは存在しません。").classes("note").style("font-size: 14px;")
                with ui.element("div").style("margin-top: 18px;"):
                    _p3_button("一覧に戻る", lambda: ui.navigate.to("/v2/characters"))
        return

    state: dict = {"sheet": sheet, "view": "sheet"}

    def _sheet() -> CharacterSheet:
        return state["sheet"]

    def _send_to_generation(mode: str) -> None:
        app.storage.user["gen_mode"] = mode
        app.storage.user["gen_char_id"] = character_id
        ui.navigate.to("/")  # Phase 5 で /v2/generation に差し替え

    with p3_page("キャラクター"):
        ui.add_css(_PAGE_CSS)
        with ui.element("div").classes("shell"):
            # ================= 左:その子 =================
            with ui.element("aside").classes("side"):
                portrait_box = ui.element("div").classes("portrait")
                side_body = ui.element("div").classes("side-body")

            # ================= 右:シート =================
            with ui.element("main").classes("sheet-wrap"):
                with ui.element("div").classes("sheet-head"):
                    with ui.element("div").classes("vmode"):
                        sheet_mode_btn = ui.element("button").classes("on")
                        with sheet_mode_btn:
                            ui.html("シート")
                        md_mode_btn = ui.element("button").mark("ui2-sheet-vmode-md")
                        with md_mode_btn:
                            ui.html("Markdown")
                    ui.element("div").classes("grow")
                    meta_note = ui.element("span").classes("meta-note")
                    _p3_button(
                        "書き出し(.md)",
                        lambda: ui.download(
                            base_character_markdown(_sheet()).encode("utf-8"),
                            f"{_sheet().name or 'character'}.md",
                        ),
                        classes="btn quiet",
                    )
                    _p3_button("コピー", lambda: _copy_markdown(), classes="btn quiet")
                    _p3_button("削除", lambda: _confirm_delete(), classes="btn quiet").style("color: #c98;")

                secs_container = ui.element("div").classes("sheet-secs").mark("ui2-sheet-secs")

                md_wrap = ui.element("div").classes("md-wrap")
                with md_wrap:
                    with ui.element("div").classes("md-bar"):
                        _p3_button("保存", lambda: _save_markdown(), classes="btn primary").style(
                            "padding: 7px 22px;"
                        ).mark("ui2-sheet-md-save")
                        _p3_button("破棄", lambda: _discard_markdown(), classes="btn quiet")
                        with ui.element("span").classes("warn"):
                            ui.html("保存時に Markdown からシート項目へ再パースされます(逆方向も常に同期)")
                    md_editor = (
                        ui.textarea(value=base_character_markdown(sheet))
                        .classes("p3-ta md-ed")
                        .props("outlined spellcheck=false")
                        .mark("ui2-sheet-md")
                    )
                md_wrap.set_visibility(False)

        # ---------------- 表示の組み立て ----------------

        def _render_portrait() -> None:
            portrait_box.clear()
            with portrait_box:
                back = ui.element("a").classes("back").props('title="キャラクター一覧へ"')
                with back:
                    ui.html("←")
                back.on("click", lambda: ui.navigate.to("/v2/characters"))
                fav = ui.element("span").classes("fav on" if _sheet().is_favorite else "fav").props(
                    'title="お気に入り"'
                )
                fav.mark("ui2-sheet-fav")
                with fav:
                    ui.html(STAR_SVG)
                fav.on("click", _toggle_favorite)
                image = _sheet().media.primary_image()
                url = media_url(image.path) if image is not None else None
                if url is not None:
                    raw_img(url).style(f"object-position: {image_object_position(image)};")
                else:
                    with ui.element("div").classes("portrait-ph"):
                        ui.html(html.escape((_sheet().name or "?")[:1]))

        def _render_side_body() -> None:
            sheet = _sheet()
            side_body.clear()
            with side_body:
                with ui.element("h1").classes("serif").mark("ui2-sheet-name"):
                    ui.html(html.escape(sheet.name))
                oc = sheet.occupation
                if sheet.age:
                    oc = f"{oc} ・ {sheet.age}" if oc else sheet.age
                with ui.element("div").classes("oc"):
                    ui.html(html.escape(oc))
                intro = strip_outer_quotes(sheet.self_intro)
                if intro:
                    with ui.element("div").classes("bubble tail-left"):
                        ui.html(html.escape(f"「{intro}」"))
                with ui.element("div").classes("side-actions"):
                    _p3_button(
                        "チャットする",
                        lambda: ui.navigate.to(f"/characters/{character_id}/chat"),
                        classes="btn primary",
                        title="旧チャット画面が開きます(Phase 3 で /v2 版に置き換え)",
                    )
                    _p3_button("修正して生成", lambda: _send_to_generation("modify"))
                    _p3_button("知りあいを生成", lambda: _send_to_generation("related"), classes="btn quiet")

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
                            more.on("click", lambda: ui.navigate.to(f"/characters/{character_id}"))
                        if not sheet.media.images:
                            with ui.element("span").classes("note"):
                                ui.html("まだ画像がありません")
                    with ui.element("div").classes("media-links"):
                        _chip_button("アップロード", _open_image_upload)
                        if sheet.media.primary_image() is not None:
                            _chip_button("顔範囲", lambda: _open_rect("face"))
                            _chip_button("バスト範囲", lambda: _open_rect("bust"))
                        _chip_button(
                            "画像を管理・生成",
                            lambda: ui.navigate.to(f"/characters/{character_id}"),
                            title="旧ページが開きます(画像生成などは Phase 6 で /v2 版に)",
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
                        _chip_button("アップロード", _open_voice_upload)
                        _chip_button(
                            "音声を管理・ボイスデザイン",
                            lambda: ui.navigate.to(f"/characters/{character_id}"),
                            title="旧ページが開きます(ボイスデザイン等は Phase 6 で /v2 版に)",
                        )

                # ---- タグ ----
                with ui.element("div").classes("blk"):
                    with ui.element("div").classes("lbl"):
                        ui.html("タ グ")
                    with ui.element("div").classes("tag-row"):
                        for tag in list(sheet.tags):
                            _chip_button(f"{tag} ×", lambda t=tag: _remove_tag(t), title="クリックで削除")
                        _chip_button("+ 追加", _open_tag_dialog)

        def _render_meta_note() -> None:
            sheet = _sheet()
            meta_note.clear()
            parts: list[str] = []
            meta = sheet.generation_meta
            if meta.model_id:
                parts.append(f"生成: {meta.model_id}")
            if meta.quality_score:
                parts.append(f"品質 {meta.quality_score:g}")
            parts.append(f"更新 {sheet.updated_at:%Y-%m-%d}")
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
                        _p3_button(
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

                    _p3_button("保存", _save, classes="btn primary").style(
                        "padding: 5px 18px; font-size: 12.5px;"
                    )
                    _p3_button("取消", lambda: _render_sections(), classes="btn quiet")

        # ---------------- 操作 ----------------

        async def _apply_markdown(new_md: str, message: str) -> None:
            new_md = new_md.strip()
            if not new_md:
                ui.notify("シートが空です", type="warning")
                return
            updated = sheet_from_markdown_preserving(_sheet(), new_md)
            saved = await ctx.characters.save(updated)
            state["sheet"] = saved
            md_editor.set_value(base_character_markdown(saved))
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

        async def _toggle_favorite() -> None:
            saved = await ctx.characters.set_favorite(character_id, not _sheet().is_favorite)
            state["sheet"] = saved
            _render_portrait()
            ui.notify(
                "お気に入りに追加しました" if saved.is_favorite else "お気に入りを解除しました",
                type="positive",
            )

        async def _set_primary_image(asset_id: str) -> None:
            sheet = _sheet()
            if sheet.media.primary_image_id == asset_id:
                return
            sheet.media.primary_image_id = asset_id
            state["sheet"] = await ctx.characters.save(sheet)
            _render_portrait()
            _render_side_body()
            ui.notify("メイン画像を変更しました", type="positive")

        def _open_image_upload() -> None:
            async def _on_upload(e) -> bool:
                try:
                    state["sheet"] = await ctx.characters.save_image(character_id, e.file)
                    ui.notify("画像を保存しました", type="positive")
                    _render_portrait()
                    _render_side_body()
                    return True
                except Exception as err:
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
                    state["sheet"] = await ctx.characters.save_voice(character_id, e.file)
                    ui.notify("音声を保存しました", type="positive")
                    _render_side_body()
                    return True
                except Exception as err:
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
            image_path = ctx.characters.media_path(image.path)
            if image_path is None:
                ui.notify("画像ファイルが見つかりません", type="warning")
                return

            async def _on_save(rect, width: int, height: int) -> None:
                if kind == "face":
                    saved = await ctx.characters.update_face_rect(
                        character_id, rect, image_width=width, image_height=height
                    )
                else:
                    saved = await ctx.characters.update_bust_rect(
                        character_id, rect, image_width=width, image_height=height
                    )
                state["sheet"] = saved
                _render_portrait()
                _render_side_body()

            open_rect_dialog(image=image, image_path=image_path, kind=kind, on_save=_on_save)

        async def _remove_tag(tag: str) -> None:
            sheet = _sheet()
            if tag in sheet.tags:
                sheet.tags.remove(tag)
                state["sheet"] = await ctx.characters.save(sheet)
                _render_side_body()
                ui.notify(f"タグ「{tag}」を削除しました", type="positive")

        def _open_tag_dialog() -> None:
            with ui.dialog() as dlg, ui.card().classes("min-w-[300px]").style(
                "background: var(--panel); color: var(--text);"
            ):
                ui.label("タグを追加").classes("text-base font-semibold mb-2")
                new_tag = ui.input(label="タグ名").classes("w-full")

                async def _add() -> None:
                    tag = str(new_tag.value or "").strip()
                    sheet = _sheet()
                    if tag and tag not in sheet.tags:
                        sheet.tags.append(tag)
                        state["sheet"] = await ctx.characters.save(sheet)
                        _render_side_body()
                        ui.notify(f"タグ「{tag}」を追加しました", type="positive")
                    dlg.close()

                with ui.row().classes("justify-end gap-2 mt-3 w-full"):
                    _p3_button("キャンセル", dlg.close, classes="btn quiet")
                    _p3_button("追加", _add, classes="btn primary")
            dlg.open()

        def _confirm_delete() -> None:
            with ui.dialog() as dlg, ui.card().style("background: var(--panel); color: var(--text);"):
                ui.label(f"「{_sheet().name}」を削除しますか?").classes("text-base font-medium mb-2")
                ui.label("この操作は取り消せません。").classes("note")

                async def _do_delete() -> None:
                    await ctx.characters.delete(character_id)
                    ui.notify(f"「{_sheet().name}」を削除しました", type="positive")
                    dlg.close()
                    ui.navigate.to("/v2/characters")

                with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                    _p3_button("キャンセル", dlg.close, classes="btn quiet")
                    _p3_button("削除", _do_delete, classes="btn primary").mark("ui2-sheet-delete")
            dlg.open()

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
