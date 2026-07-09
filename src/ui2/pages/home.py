"""
ホーム(/)(Phase 1)。モック proposal3/home.html 準拠。

- 相方切替: `app.storage.user["ui2_companion"]` に永続化
- 挨拶 v1: 時間帯定型+self_intro 流用(LLM呼び出し無し。home_logic 参照)
- 最近のセッション: ChatService.list_recent + GroupChatService.list_recent_sessions を
  updated_at 降順に統合して 3 件。1:1 は /characters/{id}/chat、
  グループは Phase 4 まで旧 /groups/{id} への暫定リンク
"""

from __future__ import annotations

import html
from datetime import datetime

from nicegui import app, ui

from ...app_context import get_context
from ...core.character.schemas import CharacterSheet
from ..components.portrait import image_object_position, media_url, portrait_img, raw_img
from ..components.sparkle import sparkle_field
from ..home_logic import (
    RecentSessionItem,
    companion_candidates,
    date_label,
    greeting_text,
    merge_recent_sessions,
    recent_character_ids,
    select_companion,
)
from ..scaffold import p3_page

COMPANION_KEY = "ui2_companion"

# モック home.html の <style> 移植(h1 は .name に、追加: プレースホルダ/空状態)
_PAGE_CSS = """
.entrance {
  position: relative;
  min-height: calc(100vh - 55px);
  overflow: hidden;
}
/* 立ち絵 — 画面の主役。UIより先に「その子がいる」 */
.stage {
  position: absolute;
  top: 0; right: 0; bottom: 0;
  width: 52%;
  pointer-events: none;
}
.stage img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center 12%;
  opacity: 0;
  transition: opacity .6s ease;
  -webkit-mask-image: linear-gradient(to right, transparent 0%, #000 32%),
                      linear-gradient(to top, transparent 0%, #000 26%);
  -webkit-mask-composite: source-in;
  mask-image: linear-gradient(to right, transparent 0%, #000 32%);
}
.stage img.on { opacity: 1; }
.stage::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(to top, var(--bg) 2%, transparent 34%);
}

.greet {
  position: relative;
  z-index: 2;
  max-width: 600px;
  padding: 9vh 0 0 6vw;
}
.greet .date { color: var(--muted); font-size: 13px; letter-spacing: .22em; }
.greet .name {
  margin: 18px 0 2px;
  font-size: 44px;
  line-height: 1.25;
  letter-spacing: .08em;
}
.greet .occ { color: var(--muted); font-size: 13.5px; letter-spacing: .1em; margin-bottom: 26px; min-height: 1em; }
.greet .bubble { max-width: 480px; font-size: 15.5px; }

.actions { display: flex; gap: 12px; margin-top: 30px; flex-wrap: wrap; }

/* 相方スイッチャ */
.companions {
  position: relative;
  z-index: 2;
  margin: 7vh 0 0 6vw;
}
.companions .lbl { font-size: 12px; letter-spacing: .28em; color: var(--muted); margin-bottom: 12px; }
.companions .row { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; }
.companions button {
  padding: 0; border: none; background: none; cursor: pointer;
  border-radius: 50%;
  transition: transform .18s;
}
.companions button:hover { transform: translateY(-4px); }
.companions img.avatar { width: 58px; height: 58px; }
.companions button.on img.avatar {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--glow), 0 6px 18px var(--glow);
}
.companions .more {
  width: 58px; height: 58px; border-radius: 50%;
  border: 1.5px dashed var(--line-2); color: var(--muted);
  font-size: 20px; display: grid; place-items: center;
  cursor: pointer;
}
.companions .more:hover { color: var(--accent); border-color: var(--accent); }

/* しおり(最近のセッション) */
.bookmarks { position: relative; z-index: 2; padding: 9vh 6vw 20px; }
.bookmarks h2 { font-size: 16px; letter-spacing: .3em; color: var(--muted); font-weight: 600; margin: 0 0 22px; }
.bm-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; max-width: 1080px; }
.bm {
  display: flex; gap: 16px; align-items: center;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 14px 18px 14px 14px;
  cursor: pointer;
  transition: transform .18s, border-color .18s, box-shadow .18s;
}
.bm:hover { transform: translateY(-3px); border-color: var(--line-2); box-shadow: var(--shadow); }
.bm img { width: 62px; height: 62px; border-radius: 14px; object-fit: cover; object-position: center 10%; flex: none; }
.bm .bm-ph {
  width: 62px; height: 62px; border-radius: 14px; flex: none;
  display: grid; place-items: center;
  background: var(--panel-2); color: var(--muted);
  font-size: 22px; font-weight: 600;
}
.bm .txt { min-width: 0; }
.bm .t { font-size: 14.5px; font-weight: 600; letter-spacing: .04em; }
.bm .last { font-size: 12.5px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 240px; }
.bm .when { margin-left: auto; font-size: 11.5px; color: var(--muted); flex: none; }

/* 空状態(キャラクター0件) */
.home-empty {
  position: relative;
  z-index: 2;
  max-width: 600px;
  padding: 12vh 0 0 6vw;
}

@media (max-width: 900px) {
  /* 縦画面: 立ち絵は下半分の背景に回し、文字は上に載せる */
  .stage {
    width: 100%;
    top: 24vh;
    opacity: .5;
  }
  .stage img {
    object-position: center 6%;
    -webkit-mask-image: linear-gradient(to bottom, transparent 0%, #000 24%);
    mask-image: linear-gradient(to bottom, transparent 0%, #000 24%);
  }
  .greet { padding: 5vh 6vw 0; max-width: none; }
  .greet .name { font-size: 32px; }
  .greet .bubble { font-size: 14.5px; }
  .companions { margin-top: 5vh; }
  .companions img.avatar, .companions .more { width: 50px; height: 50px; }
  .bookmarks { padding-top: 6vh; }
  .bm-row { grid-template-columns: 1fr; }
}
"""


def _bubble_text(sheet: CharacterSheet) -> str:
    return f"「{greeting_text(datetime.now().hour, sheet.self_intro)}」"


def _render_bookmark(item: RecentSessionItem, image_html: tuple[str, str] | None) -> None:
    """しおり1件。image_html は (url, object-position) or None。"""
    card = ui.element("div").classes("bm")
    card.on("click", lambda route=item.route: ui.navigate.to(route))
    with card:
        if image_html is not None:
            url, position = image_html
            raw_img(url).style(f"object-position: {position};")
        else:
            with ui.element("div").classes("bm-ph"):
                ui.label((item.title or "?")[:1])
        with ui.element("div").classes("txt"):
            ui.label(item.title).classes("t")
            ui.label(item.preview).classes("last")
        ui.label(item.time_label).classes("when")


@ui.page("/")
async def ui2_home_page() -> None:
    ctx = get_context()
    sheets = await ctx.characters.list_all()
    recent_chats = await ctx.chats.list_recent(10)
    recent_groups = await ctx.group_chats.list_recent_sessions(10)
    groups_by_id = {group.id: group for group in await ctx.group_chats.list_all()}

    candidates = companion_candidates(sheets)
    stored_id = str(app.storage.user.get(COMPANION_KEY, "") or "")
    selected = select_companion(candidates, stored_id, recent_character_ids(recent_chats))
    sheets_by_id = {sheet.id: sheet for sheet in sheets}
    bookmarks = merge_recent_sessions(
        recent_chats, recent_groups, groups_by_id, valid_character_ids=set(sheets_by_id)
    )

    with p3_page("ホーム"):
        ui.add_css(_PAGE_CSS)

        with ui.element("section").classes("entrance"):
            sparkle_field(22)

            # ---- 立ち絵ステージ(候補全員を重ねて置き、選択中だけ表示) ----
            stage_imgs: dict[str, ui.element] = {}
            with ui.element("div").classes("stage"):
                for sheet in candidates:
                    img = portrait_img(sheet.media.primary_image())
                    if img is not None:
                        stage_imgs[sheet.id] = img

            if selected is None:
                with ui.element("div").classes("home-empty"):
                    ui.label(date_label(datetime.now())).classes("date").style(
                        "color: var(--muted); font-size: 13px; letter-spacing: .22em;"
                    )
                    ui.label("ようこそ、Wizmy へ。").classes("serif name").style(
                        "font-size: 36px; display: block; margin: 18px 0 10px;"
                    )
                    ui.label(
                        "まだ画像付きのキャラクターがいません。"
                        "キャラクターを生成すると、この場所で出迎えてくれます。"
                    ).classes("note").style("font-size: 14px;")
                    with ui.element("div").classes("actions"):
                        gen_btn = ui.element("button").classes("btn primary")
                        with gen_btn:
                            ui.label("キャラクターを生成する")
                        gen_btn.on("click", lambda: ui.navigate.to("/generation"))
                        list_btn = ui.element("button").classes("btn")
                        with list_btn:
                            ui.label("キャラクター一覧へ")
                        list_btn.on("click", lambda: ui.navigate.to("/characters"))
            else:
                current = {"id": selected.id}

                # ---- 挨拶 ----
                with ui.element("div").classes("greet"):
                    ui.label(date_label(datetime.now())).classes("date")
                    name_label = ui.label(selected.name).classes("serif name").mark("ui2-companion-name")
                    occ_label = ui.label(selected.occupation).classes("occ")
                    with ui.element("div").classes("bubble tail-left"):
                        bubble_label = ui.label(_bubble_text(selected))
                    with ui.element("div").classes("actions"):
                        cont_btn = ui.element("button").classes("btn primary").mark("ui2-continue")
                        with cont_btn:
                            ui.label("続きから話す")
                        cont_btn.on("click", lambda: ui.navigate.to(f"/characters/{current['id']}/chat"))
                        new_btn = ui.element("button").classes("btn")
                        with new_btn:
                            ui.label("新しいセッション")
                        new_btn.on("click", lambda: ui.navigate.to(f"/characters/{current['id']}/chat"))

                # ---- 相方スイッチャ ----
                avatar_buttons: dict[str, ui.element] = {}

                def _apply_selection() -> None:
                    sheet = sheets_by_id[current["id"]]
                    name_label.set_text(sheet.name)
                    occ_label.set_text(sheet.occupation)
                    bubble_label.set_text(_bubble_text(sheet))
                    for character_id, img in stage_imgs.items():
                        if character_id == sheet.id:
                            img.classes("on")
                        else:
                            img.classes(remove="on")
                    for character_id, button in avatar_buttons.items():
                        if character_id == sheet.id:
                            button.classes("on")
                        else:
                            button.classes(remove="on")

                def _select(character_id: str) -> None:
                    current["id"] = character_id
                    app.storage.user[COMPANION_KEY] = character_id
                    _apply_selection()

                with ui.element("div").classes("companions"):
                    ui.label("キャラクター切り替え").classes("lbl")
                    with ui.element("div").classes("row"):
                        for index, sheet in enumerate(candidates):
                            image = sheet.media.primary_image()
                            url = media_url(image.path) if image is not None else None
                            if url is None:
                                continue
                            button = (
                                ui.element("button")
                                .props(f'title="{html.escape(sheet.name)}"')
                                .mark(f"ui2-companion-{index}")
                            )
                            with button:
                                raw_img(url, "avatar").style(
                                    f"object-position: {image_object_position(image)};"
                                )
                            button.on("click", lambda character_id=sheet.id: _select(character_id))
                            avatar_buttons[sheet.id] = button
                        more = ui.element("button").classes("more").props('title="キャラクター一覧へ"')
                        with more:
                            ui.html("+")
                        more.on("click", lambda: ui.navigate.to("/characters"))

                _apply_selection()

        # ---- 最近のセッション ----
        with ui.element("section").classes("bookmarks"):
            with ui.element("h2"):
                ui.html("最近のセッション")
            if not bookmarks:
                ui.label("まだセッションがありません。相方に話しかけると、ここに続きが並びます。").classes("note")
            else:
                with ui.element("div").classes("bm-row"):
                    for item in bookmarks:
                        image_ref: tuple[str, str] | None = None
                        image = None
                        if item.kind == "chat":
                            sheet = sheets_by_id.get(item.target_id)
                            image = sheet.media.primary_image() if sheet is not None else None
                        else:
                            group = groups_by_id.get(item.target_id)
                            if group is not None and group.members:
                                image = group.members[0].character.media.primary_image()
                        if image is not None:
                            url = media_url(image.path)
                            if url is not None:
                                image_ref = (url, image_object_position(image))
                        _render_bookmark(item, image_ref)
