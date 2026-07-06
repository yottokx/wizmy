"""
/v2/characters キャラクター一覧(Phase 2)。モック proposal3/characters.html 準拠。

- 上段: 劇場ストリップ(ピックアップ)。選出は components/pickup.py の純関数
  (ポリシー選択値 `app.storage.user["ui2_pickup_policy"]`、既定 mixed)
- 下段: ギャラリー(検索・タグ・お気に入り絞り込み+Markdownインポート+新規生成カード)
- チャットボタンは /v2/characters/{id}/chat へ。
  新規生成カードは Phase 5 まで旧 /(生成)へ暫定リンク
"""

from __future__ import annotations

import html

from nicegui import app, ui

from ...app_context import get_context
from ...core.character.markdown import parse_markdown_to_sheet
from ...core.character.schemas import CharacterSheet
from ..components.pickup import (
    DEFAULT_POLICY,
    PICKUP_POLICY_KEY,
    build_pickup_candidates,
    select_pickup,
)
from ..components.portrait import image_object_position, media_url, raw_img
from ..components.sparkle import STAR_SVG
from ..scaffold import p3_page

# モック characters.html の <style> 移植(+ noimg カードの hover-ops 追加)
_PAGE_CSS = """
.wrap { max-width: 1280px; margin: 0 auto; padding: 34px 26px 10px; }
.page-head { display: flex; align-items: baseline; gap: 18px; margin-bottom: 22px; }
.page-head h1 { font-size: 26px; letter-spacing: .3em; margin: 0; font-weight: 600; }
.page-head .note { letter-spacing: .06em; }

/* ============ 劇場ストリップ ============ */
.theater {
  display: flex;
  gap: 8px;
  height: 470px;
  border-radius: 24px;
  overflow: hidden;
}
.strip {
  position: relative;
  flex: 1;
  min-width: 0;
  border-radius: 18px;
  overflow: hidden;
  cursor: pointer;
  transition: flex .45s cubic-bezier(.2, .8, .2, 1);
  background: var(--panel);
}
.theater:not(:hover) .strip.default,
.strip:hover { flex: 4.2; }
.strip img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: var(--pos, center 12%);
  filter: saturate(.82) brightness(.86);
  transition: filter .45s;
}
.theater:not(:hover) .strip.default img,
.strip:hover img { filter: none; }
.strip::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(to top, rgba(6, 8, 24, .82) 0%, transparent 45%);
}
.strip .spine {
  position: absolute;
  top: 18px;
  left: 50%;
  transform: translateX(-50%);
  writing-mode: vertical-rl;
  font-size: 14px;
  letter-spacing: .3em;
  color: #f2f3ff;
  text-shadow: 0 1px 10px rgba(0, 0, 0, .7);
  z-index: 2;
  white-space: nowrap;
  opacity: .95;
  transition: opacity .3s;
}
.theater:not(:hover) .strip.default .spine,
.strip:hover .spine { opacity: 0; }
.strip .meet {
  position: absolute;
  left: 0; right: 0; bottom: 0;
  padding: 18px 22px 18px;
  z-index: 2;
  opacity: 0;
  transform: translateY(12px);
  transition: opacity .35s .12s, transform .35s .12s;
  color: #f4f5ff;
}
.theater:not(:hover) .strip.default .meet,
.strip:hover .meet { opacity: 1; transform: none; }
.meet .nm { font-size: 21px; letter-spacing: .12em; }
.meet .oc { font-size: 12px; opacity: .8; letter-spacing: .06em; margin: 2px 0 10px; }
.meet .say {
  font-size: 13px;
  line-height: 1.7;
  background: rgba(10, 12, 32, .55);
  border: 1px solid rgba(255, 255, 255, .14);
  border-radius: 14px;
  padding: 10px 14px;
  backdrop-filter: blur(6px);
  max-width: 340px;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.meet .ops { display: flex; gap: 8px; margin-top: 12px; }
.meet .ops .btn { padding: 6px 16px; font-size: 12.5px; background: rgba(10, 12, 32, .4); border-color: rgba(255,255,255,.3); color: #fff; }
.meet .ops .btn.primary { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); }

/* ============ ぜんいん(ギャラリー) ============ */
.all-head { display: flex; align-items: center; gap: 16px; margin: 46px 0 18px; flex-wrap: wrap; }
.all-head h2 { font-size: 16px; letter-spacing: .3em; font-weight: 600; margin: 0; }
.filters { display: flex; gap: 8px; flex-wrap: wrap; }
.search {
  margin-left: auto;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 7px 18px;
  color: var(--text);
  font-size: 13px;
  width: 200px;
  outline: none;
}
.search::placeholder { color: var(--muted); }
.search:focus { border-color: var(--peri); }

.gallery {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 16px;
  padding-bottom: 30px;
}
.gcard {
  position: relative;
  aspect-ratio: 3 / 4.1;
  border-radius: 18px;
  overflow: hidden;
  background: var(--panel);
  border: 1px solid var(--line);
  cursor: pointer;
  transition: transform .2s, box-shadow .2s, border-color .2s;
}
.gcard:hover { transform: translateY(-5px); box-shadow: var(--shadow); border-color: var(--line-2); }
.gcard img {
  position: absolute; inset: 0;
  width: 100%; height: 100%;
  object-fit: cover;
  object-position: var(--pos, center 10%);
  transition: transform .35s;
}
.gcard:hover img { transform: scale(1.04); }
.gcard .veil {
  position: absolute; inset: 0;
  background: linear-gradient(to top, rgba(7, 9, 26, .88) 0%, rgba(7, 9, 26, .1) 38%, transparent 55%);
}
.gcard .info { position: absolute; left: 14px; right: 14px; bottom: 12px; color: #f4f5ff; }
.gcard .nm { font-size: 15.5px; letter-spacing: .08em; line-height: 1.4; }
.gcard .oc { font-size: 11px; opacity: .78; letter-spacing: .04em; display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden; }
.gcard .fav {
  position: absolute; top: 10px; right: 12px;
  width: 16px; height: 16px; color: var(--star);
  filter: drop-shadow(0 1px 6px rgba(0,0,0,.6));
}
.gcard .fav svg { fill: currentColor; }
.gcard .hover-ops {
  position: absolute; left: 14px; right: 14px; bottom: 58px;
  display: flex; gap: 8px;
  opacity: 0; transform: translateY(8px);
  transition: opacity .22s, transform .22s;
}
.gcard:hover .hover-ops { opacity: 1; transform: none; }
.hover-ops .btn { padding: 5px 14px; font-size: 12px; background: rgba(10,12,32,.5); border-color: rgba(255,255,255,.3); color: #fff; backdrop-filter: blur(4px); }
.hover-ops .btn.primary { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); }

/* 絵姿がまだない子 */
.gcard.noimg { display: grid; place-items: center; background: var(--panel-2); }
.gcard.noimg .ph { text-align: center; padding: 0 18px; color: var(--muted); }
.gcard.noimg .initial {
  width: 74px; height: 74px; margin: 0 auto 14px;
  border-radius: 50%;
  display: grid; place-items: center;
  font-size: 30px;
  color: var(--peri);
  border: 1.5px dashed var(--line-2);
  font-family: "Yu Mincho", serif;
}
.gcard.noimg .nm2 { color: var(--text); font-size: 15px; letter-spacing: .08em; }
.gcard.noimg .cta { margin-top: 12px; font-size: 12px; color: var(--accent); }

/* 迎えるカード */
.gcard.newcard {
  display: grid; place-items: center;
  background: transparent;
  border: 1.5px dashed var(--line-2);
}
.gcard.newcard:hover { border-color: var(--accent); box-shadow: none; }
.gcard.newcard .plus { font-size: 40px; color: var(--accent); line-height: 1; }
.gcard.newcard .t { color: var(--muted); font-size: 13px; letter-spacing: .14em; margin-top: 10px; }

.list-empty { padding: 40px 0 60px; }

/* ============ 縦画面・スマホ ============ */
@media (max-width: 860px) {
  .wrap { padding: 24px 16px 10px; }
  .page-head { flex-direction: column; gap: 4px; margin-bottom: 16px; }
  .theater {
    height: 400px;
    overflow-x: auto;
    scroll-snap-type: x mandatory;
    -webkit-overflow-scrolling: touch;
  }
  .strip,
  .theater:not(:hover) .strip.default,
  .strip:hover {
    flex: 0 0 76vw;
    max-width: 330px;
    scroll-snap-align: center;
  }
  .strip img { filter: none !important; }
  .strip .spine { opacity: 0 !important; }
  .strip .meet { opacity: 1 !important; transform: none !important; }
  .all-head { margin-top: 32px; }
  .search { width: 100%; margin-left: 0; }
  .gallery { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; }
  .gcard .nm { font-size: 13.5px; }
  .gcard .hover-ops { opacity: 1; transform: none; bottom: 52px; }
  .hover-ops .btn { padding: 4px 10px; font-size: 11px; }
}
"""

def _say_text(sheet: CharacterSheet) -> str:
    """ストリップの台詞: self_intro を 1 行に(外側カギ括弧は表示側で付ける)。"""
    intro = " ".join(sheet.self_intro.split())
    while intro.startswith("「") and intro.endswith("」"):
        intro = intro[1:-1].strip()
    return intro


def _chat_route(character_id: str) -> str:
    return f"/v2/characters/{character_id}/chat"


def _detail_route(character_id: str) -> str:
    return f"/v2/characters/{character_id}"


def _op_button(label: str, route: str, *, primary: bool = False) -> None:
    btn = ui.element("a").classes("btn primary" if primary else "btn")
    with btn:
        ui.html(html.escape(label))
    btn.on("click.stop", lambda r=route: ui.navigate.to(r))


def _render_strip(sheet: CharacterSheet, *, default: bool) -> None:
    image = sheet.media.primary_image()
    url = media_url(image.path) if image is not None else None
    if url is None:
        return
    strip = ui.element("div").classes("strip default" if default else "strip")
    strip.on("click", lambda cid=sheet.id: ui.navigate.to(_detail_route(cid)))
    with strip:
        raw_img(url).style(f"object-position: {image_object_position(image)};")
        with ui.element("span").classes("spine serif"):
            ui.html(html.escape(sheet.name))
        with ui.element("div").classes("meet"):
            with ui.element("div").classes("nm serif"):
                ui.html(html.escape(sheet.name))
            with ui.element("div").classes("oc"):
                ui.html(html.escape(sheet.occupation))
            say = _say_text(sheet)
            if say:
                with ui.element("div").classes("say"):
                    ui.html(html.escape(f"「{say}」"))
            with ui.element("div").classes("ops"):
                _op_button("チャット", _chat_route(sheet.id), primary=True)
                _op_button("詳細", _detail_route(sheet.id))


def _render_gcard(sheet: CharacterSheet) -> None:
    image = sheet.media.primary_image()
    url = media_url(image.path) if image is not None else None
    if url is None:
        card = ui.element("div").classes("gcard noimg")
        card.on("click", lambda cid=sheet.id: ui.navigate.to(_detail_route(cid)))
        with card:
            with ui.element("div").classes("ph"):
                with ui.element("div").classes("initial"):
                    ui.html(html.escape((sheet.name or "?")[:1]))
                with ui.element("div").classes("nm2 serif"):
                    ui.html(html.escape(sheet.name))
                with ui.element("div").classes("oc").style("font-size: 11px;"):
                    ui.html(html.escape(sheet.occupation))
                with ui.element("div").classes("cta"):
                    ui.html("+ 画像を設定")
        return

    card = ui.element("div").classes("gcard")
    card.on("click", lambda cid=sheet.id: ui.navigate.to(_detail_route(cid)))
    with card:
        raw_img(url).props('loading="lazy"').style(
            f"object-position: {image_object_position(image)};"
        )
        ui.element("div").classes("veil")
        if sheet.is_favorite:
            with ui.element("span").classes("fav").props('title="お気に入り"'):
                ui.html(STAR_SVG)
        with ui.element("div").classes("hover-ops"):
            _op_button("チャット", _chat_route(sheet.id), primary=True)
            _op_button("詳細", _detail_route(sheet.id))
        with ui.element("div").classes("info"):
            with ui.element("div").classes("nm serif"):
                ui.html(html.escape(sheet.name))
            with ui.element("div").classes("oc"):
                ui.html(html.escape(sheet.occupation))


def _open_import_dialog(on_imported) -> None:
    ctx = get_context()
    with ui.dialog() as dlg, ui.card().classes("min-w-[380px]").style(
        "background: var(--panel); color: var(--text);"
    ):
        ui.label("Markdownからインポート").classes("text-base font-semibold mb-2")
        ui.label("キャラクターシート形式の .md ファイルをアップロードしてください。").classes("note mb-3")

        upload_result: dict = {"text": None}

        async def _on_upload(e) -> None:
            try:
                content = await e.file.read()
                upload_result["text"] = content.decode("utf-8")
                file_label.set_text(f"選択中: {e.file.name}")
            except Exception as err:
                ui.notify(f"ファイルの読み込みに失敗しました: {err}", type="negative")

        ui.upload(label="ファイルを選択", on_upload=_on_upload, auto_upload=True).props(
            "accept=.md flat bordered"
        ).classes("w-full")
        file_label = ui.label("ファイル未選択").classes("note mt-1")

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
                await on_imported()
            except Exception as err:
                ui.notify(f"インポートに失敗しました: {err}", type="negative")

        with ui.row().classes("justify-end gap-2 mt-4 w-full"):
            cancel = ui.element("button").classes("btn quiet")
            with cancel:
                ui.html("キャンセル")
            cancel.on("click", dlg.close)
            submit = ui.element("button").classes("btn primary")
            with submit:
                ui.html("インポート")
            submit.on("click", _do_import)
    dlg.open()


@ui.page("/v2/characters")
async def ui2_characters_page() -> None:
    ctx = get_context()
    all_sheets = await ctx.characters.list_all()
    all_tags = await ctx.characters.get_all_tags()
    recent_chats = await ctx.chats.list_recent(500)

    policy = str(app.storage.user.get(PICKUP_POLICY_KEY, DEFAULT_POLICY) or DEFAULT_POLICY)
    picked = select_pickup(build_pickup_candidates(all_sheets, recent_chats), policy)

    state = {"search": "", "tag": "", "favorites": False}

    with p3_page("キャラクター"):
        ui.add_css(_PAGE_CSS)
        with ui.element("div").classes("wrap"):
            with ui.element("div").classes("page-head"):
                with ui.element("h1").classes("serif"):
                    ui.html("キャラクター一覧")
                with ui.element("span").classes("note"):
                    ui.html("上段はピックアップ。触れたキャラクターが広がります")

            # ---- 劇場ストリップ(候補0ならストリップ自体を非表示) ----
            if picked:
                with ui.element("div").classes("theater"):
                    for index, candidate in enumerate(picked):
                        _render_strip(candidate.sheet, default=index == 0)

            # ---- ぜんいん ----
            with ui.element("div").classes("all-head"):
                with ui.element("h2"):
                    ui.html("すべてのキャラクター")
                count_label = ui.label("").classes("note")
                filters = ui.element("div").classes("filters")
                import_btn = ui.element("button").classes("chip").props(
                    'title="キャラクターシート形式の .md をインポート"'
                )
                with import_btn:
                    ui.html("Markdownインポート")
                search_input = (
                    ui.element("input")
                    .classes("search")
                    .props('placeholder="名前・世界観で検索" type="search"')
                    .mark("ui2-characters-search")
                )

            gallery = ui.element("div").classes("gallery").mark("ui2-characters-gallery")

            tag_chips: dict[str, ui.element] = {}
            fav_chip: ui.element | None = None

            def _sync_chips() -> None:
                for tag, chip in tag_chips.items():
                    if state["tag"] == tag:
                        chip.classes("on")
                    else:
                        chip.classes(remove="on")
                if fav_chip is not None:
                    if state["favorites"]:
                        fav_chip.classes("on")
                    else:
                        fav_chip.classes(remove="on")

            async def _refresh() -> None:
                sheets = await ctx.characters.list_all(
                    search=state["search"],
                    tag=state["tag"],
                    favorites_only=state["favorites"],
                )
                count_label.set_text(f"{len(sheets)} 件")
                gallery.clear()
                with gallery:
                    for sheet in sheets:
                        _render_gcard(sheet)
                    if not sheets:
                        with ui.element("div").classes("list-empty note"):
                            ui.html("キャラクターが見つかりません")
                    newcard = (
                        ui.element("a")
                        .classes("gcard newcard")
                        .props('title="生成ページへ(旧UI・Phase 5 で /v2 版に置き換え)"')
                    )
                    newcard.on("click", lambda: ui.navigate.to("/"))
                    with newcard, ui.element("div").style("text-align: center;"):
                        with ui.element("div").classes("plus"):
                            ui.html("+")
                        with ui.element("div").classes("t"):
                            ui.html("新規生成")

            async def _set_tag(tag: str) -> None:
                state["tag"] = tag
                _sync_chips()
                await _refresh()

            async def _toggle_favorites() -> None:
                state["favorites"] = not state["favorites"]
                _sync_chips()
                await _refresh()

            async def _on_search(e) -> None:
                state["search"] = str(e.args or "")
                await _refresh()

            with filters:
                for tag in ["", *all_tags]:
                    chip = ui.element("button").classes("chip")
                    with chip:
                        ui.html(html.escape(tag) if tag else "すべて")
                    chip.on("click", lambda t=tag: _set_tag(t))
                    tag_chips[tag] = chip
                fav_chip = ui.element("button").classes("chip").mark("ui2-characters-fav-filter")
                with fav_chip:
                    ui.html("★ お気に入り")
                fav_chip.on("click", _toggle_favorites)

            import_btn.on("click", lambda: _open_import_dialog(_refresh))
            # input イベントで即時絞り込み(throttle 0.3s)
            search_input.on(
                "input",
                _on_search,
                js_handler="(e) => emit(e.target.value)",
                throttle=0.3,
                trailing_events=True,
            )

            _sync_chips()
            await _refresh()
