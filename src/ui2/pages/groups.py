"""
/v2/groups グループ一覧+作成フロー(Phase 4)。モック proposal3/groups.html 準拠。

- 一覧: 箱庭カード(三連の住人ポートレート+世界観+統計)。ひらく/削除。
- 作成フロー: モックの3ステップ(一 世界を決める / 二 住人を迎える / 三 あなたの姿)を
  ページ内セクションとして実装。パリティ項目(世界source・世界強化・名前生成・
  ハンドル生成・適応プレビューdiff・到着理由・ペルソナ適応)は各ステップ内の
  チップ/住人設定ダイアログ(group_setup.py)で提供する。
- 関係性の初期設定は作成後にグループページの「管理」で行う(旧ウィザードStep4相当)。
"""

from __future__ import annotations

import html
from typing import Any

from nicegui import ui

from ...app_context import get_context
from ...core.character.schemas import CharacterSheet
from ...core.conversation.group_setup import fallback_handle
from ...core.conversation.history import session_time_label
from ...core.conversation.prompts.common import compact_character_summary
from ...core.conversation.world_adaptation import (
    prepare_group_character_for_world,
    prepare_group_user_world_settings,
)
from ...core.group_chat.schemas import GroupChatRecord
from ..components.busy import BusyController
from ..components.portrait import image_object_position, media_url, raw_img
from ..group_logic import (
    entry_type_label,
    validate_handle_values,
    world_source_options,
)
from ..group_setup import (
    chip_button,
    default_profile_id,
    enhance_world_text,
    generate_group_name,
    generate_handles_values,
    open_character_pick_dialog,
    open_resident_settings_dialog,
    p3_button,
    profile_options_for_context,
)
from ..scaffold import p3_page

_DIALOG_CARD_STYLE = "background: var(--panel); color: var(--text);"

# モック groups.html の <style> 移植+ピッカー(pcard)+P3フォームスキン
_PAGE_CSS = """
.wrap { max-width: 1120px; margin: 0 auto; padding: 34px 26px 30px; }
.page-head { display: flex; align-items: center; gap: 18px; margin-bottom: 24px; flex-wrap: wrap; }
.page-head h1 { font-size: 26px; letter-spacing: .3em; margin: 0; font-weight: 600; }
.page-head .mk { margin-left: auto; }

/* ---------- 箱庭カード ---------- */
.ggrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 18px; }
.gcard {
  position: relative;
  border-radius: 20px;
  overflow: hidden;
  background: var(--panel);
  border: 1px solid var(--line);
  cursor: pointer;
  transition: transform .18s, border-color .18s, box-shadow .18s;
}
.gcard:hover { transform: translateY(-4px); border-color: var(--line-2); box-shadow: var(--shadow); }
.gimgs { display: flex; height: 150px; gap: 2px; background: var(--bg-2); }
.gimgs img { flex: 1; min-width: 0; object-fit: cover; height: 100%; }
.gimgs .gimg-ph {
  flex: 1; min-width: 0; display: grid; place-items: center;
  color: var(--peri); font-size: 30px; font-family: "Yu Mincho", serif;
  background: var(--panel-2);
}
.gbody { padding: 16px 18px 14px; }
.gbody .nm { font-size: 17px; letter-spacing: .1em; }
.gbody .wd {
  font-size: 12px; color: var(--muted); line-height: 1.7; margin: 6px 0 12px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
  min-height: 2.6em;
}
.gbody .stats { display: flex; gap: 14px; font-size: 11.5px; color: var(--muted); letter-spacing: .04em; }
.gcard .ops {
  position: absolute; top: 12px; right: 12px;
  display: flex; gap: 6px;
  opacity: 0; transform: translateY(-4px);
  transition: opacity .2s, transform .2s;
}
.gcard:hover .ops { opacity: 1; transform: none; }
.gcard .ops .btn { padding: 4px 12px; font-size: 11.5px; background: rgba(10,12,32,.55); border-color: rgba(255,255,255,.28); color: #fff; backdrop-filter: blur(4px); }
.gcard .ops .btn.danger:hover { border-color: #e08a8a; color: #f0b0b0; }
.gcard.new {
  display: grid; place-items: center;
  min-height: 264px;
  background: transparent;
  border: 1.5px dashed var(--line-2);
}
.gcard.new:hover { border-color: var(--accent); box-shadow: none; }
.gcard.new .plus { font-size: 38px; color: var(--accent); line-height: 1; text-align: center; }
.gcard.new .t { color: var(--muted); font-size: 13px; letter-spacing: .14em; margin-top: 10px; text-align: center; }

/* ---------- 作成フロー ---------- */
.state-lbl {
  display: flex; align-items: center; gap: 14px;
  margin: 60px 0 20px;
  color: var(--muted); font-size: 12px; letter-spacing: .3em;
}
.state-lbl::after { content: ""; flex: 1; height: 1px; background: var(--line); }
.create {
  position: relative;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 26px;
  padding: 36px 44px 34px;
  overflow: hidden;
}
.step { display: flex; gap: 20px; padding: 20px 0; }
.step + .step { border-top: 1px solid var(--line); }
.step .no { width: 30px; flex: none; color: var(--peri); font-family: "Yu Mincho", serif; font-size: 20px; }
.step .body { flex: 1; min-width: 0; }
.step h3 { margin: 2px 0 4px; font-size: 15.5px; letter-spacing: .12em; font-weight: 600; }
.step .d { font-size: 12px; color: var(--muted); margin-bottom: 14px; line-height: 1.7; }
.opt-row { display: flex; gap: 12px; flex-wrap: wrap; }
.opt {
  flex: 1; min-width: 240px;
  border: 1px solid var(--line-2);
  border-radius: 16px;
  padding: 14px 18px;
  cursor: pointer;
  transition: border-color .18s, background .18s;
}
.opt:hover { border-color: var(--muted); }
.opt.on { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 8%, transparent); }
.opt .t { font-size: 13.5px; font-weight: 600; letter-spacing: .06em; }
.opt .s { font-size: 11.5px; color: var(--muted); margin-top: 3px; line-height: 1.6; }
.picks { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.pick {
  display: inline-flex; align-items: center; gap: 8px;
  border: 1px solid var(--line-2);
  border-radius: 999px;
  padding: 4px 14px 4px 5px;
  font-size: 12.5px;
  cursor: pointer;
  background: transparent;
  color: var(--text);
  transition: border-color .18s;
}
.pick:hover { border-color: var(--accent); }
.pick img { width: 28px; height: 28px; border-radius: 50%; object-fit: cover; }
.pick .pick-ph {
  width: 28px; height: 28px; border-radius: 50%;
  display: grid; place-items: center;
  background: var(--panel-2); color: var(--peri); font-size: 13px;
}
.pick .st { color: var(--peri); font-size: 10px; letter-spacing: .08em; }
.pick .x { color: var(--muted); cursor: pointer; margin-left: 2px; }
.pick .x:hover { color: var(--text); }
.go-row { display: flex; align-items: center; gap: 16px; margin-top: 26px; flex-wrap: wrap; }
.create .field-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 10px; }
.create .name-input { max-width: 340px; }

/* P3 スキン(Quasar 部品) */
.p3-ta { width: 100%; }
.p3-ta .q-field__control { background: var(--bg-2) !important; border-radius: 12px; }
.p3-ta .q-field__control:before { border-color: var(--line-2) !important; }
.p3-ta textarea, .p3-ta input { color: var(--text) !important; line-height: 1.8; }

/* ピッカー(pcard グリッド。chat.py の picker と同スキン) */
.pgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 14px; }
.pcard {
  position: relative;
  aspect-ratio: 3 / 4;
  border-radius: 16px;
  overflow: hidden;
  cursor: pointer;
  background: var(--panel);
  border: 1px solid var(--line);
  transition: transform .18s, border-color .18s, box-shadow .18s;
}
.pcard:hover { transform: translateY(-4px); border-color: var(--accent); box-shadow: var(--shadow); }
.pcard img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.pcard .p-ph {
  position: absolute; inset: 0;
  display: grid; place-items: center;
  color: var(--peri); font-size: 44px; font-family: "Yu Mincho", serif;
  background: var(--panel-2);
}
.pcard .veil { position: absolute; inset: 0; background: linear-gradient(to top, rgba(7,9,26,.9), transparent 52%); }
.pcard .info { position: absolute; left: 12px; right: 12px; bottom: 10px; color: #f4f5ff; }
.pcard .nm { font-size: 13.5px; letter-spacing: .06em; line-height: 1.4; }
.pcard .st { font-size: 10.5px; opacity: .8; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

@media (max-width: 860px) {
  .wrap { padding: 24px 16px; }
  .create { padding: 24px 20px; }
  .step { flex-direction: column; gap: 8px; }
}
"""


def _member_image_assets(group: GroupChatRecord) -> list:
    return [member.character.media.primary_image() for member in group.members[:3]]


def _render_group_card(ctx, group: GroupChatRecord, session_count: int, on_delete) -> None:
    card = ui.element("div").classes("gcard").mark("ui2-group-card")
    card.on("click", lambda gid=group.id: ui.navigate.to(f"/v2/groups/{gid}"))
    with card:
        with ui.element("div").classes("gimgs"):
            images = _member_image_assets(group)
            if not images:
                with ui.element("div").classes("gimg-ph"):
                    ui.html(html.escape((group.name or "?")[:1]))
            for image in images:
                url = media_url(image.path) if image is not None else None
                if url is not None:
                    raw_img(url).props('loading="lazy"').style(
                        f"object-position: {image_object_position(image)};"
                    )
                else:
                    with ui.element("div").classes("gimg-ph"):
                        ui.html("？")
        with ui.element("div").classes("gbody"):
            with ui.element("div").classes("nm serif"):
                ui.html(html.escape(group.name))
            with ui.element("div").classes("wd"):
                ui.html(html.escape(group.world))
            with ui.element("div").classes("stats"):
                ui.html(
                    html.escape(
                        f"住人 {len(group.members)}人 ・ セッション {session_count}件"
                        f" ・ 更新: {session_time_label(group.updated_at)}"
                    )
                )
        with ui.element("div").classes("ops"):
            open_btn = ui.element("button").classes("btn")
            with open_btn:
                ui.html("ひらく")
            open_btn.on("click.stop", lambda gid=group.id: ui.navigate.to(f"/v2/groups/{gid}"))
            delete_btn = ui.element("button").classes("btn danger")
            with delete_btn:
                ui.html("削除")
            delete_btn.on("click.stop", lambda g=group: on_delete(g))


async def _load_groups_with_counts(ctx) -> list[tuple[GroupChatRecord, int]]:
    groups = await ctx.group_chats.list_all()
    result: list[tuple[GroupChatRecord, int]] = []
    for group in groups:
        sessions = await ctx.group_chats.list_sessions_for_group(group.id)
        result.append((group, len(sessions)))
    return result


@ui.page("/v2/groups")
async def ui2_groups_page() -> None:
    ctx = get_context()
    # 描画前にデータを読み切る(p3_page 内で await すると初期レスポンスに載らず、
    # WS未接続の headless 検証で白く写る。先行Phaseと同じ「先読み→同期描画」)
    initial_groups = await _load_groups_with_counts(ctx)

    with p3_page("グループ"):
        ui.add_css(_PAGE_CSS)
        with ui.element("div").classes("wrap"):
            with ui.element("div").classes("page-head"):
                with ui.element("h1").classes("serif"):
                    ui.html("グループ一覧")
                with ui.element("span").classes("note"):
                    ui.html("それぞれが独立した箱庭。住人はその世界に合わせた適応コピー")
                mk = ui.element("button").classes("btn primary mk")
                with mk:
                    ui.html("+ 新しいグループ")
                mk.on(
                    "click",
                    js_handler="() => document.getElementById('createLbl')"
                    "?.scrollIntoView({behavior:'smooth'})",
                )

            grid = ui.element("div").classes("ggrid").mark("ui2-groups-grid")

            def _confirm_delete(group: GroupChatRecord) -> None:
                with ui.dialog() as dlg, ui.card().classes("w-full max-w-md").style(_DIALOG_CARD_STYLE):
                    ui.label(f"「{group.name}」を削除しますか？").classes("text-base font-semibold")
                    ui.label("この箱庭のセッション・住人・メディアも削除されます。元に戻せません。").classes("note")

                    async def _delete() -> None:
                        dlg.close()
                        deleted = await ctx.group_chats.delete_group(group.id)
                        if deleted:
                            ui.notify("グループを削除しました", type="positive")
                            await _refresh_groups()
                        else:
                            ui.notify("グループが見つかりませんでした", type="warning")

                    with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                        p3_button("キャンセル", dlg.close, classes="btn quiet")
                        p3_button("削除", _delete, classes="btn primary").mark("ui2-group-delete-confirm")
                dlg.open()

            def _render_grid(groups_with_counts: list[tuple[GroupChatRecord, int]]) -> None:
                grid.clear()
                with grid:
                    for group, session_count in groups_with_counts:
                        _render_group_card(ctx, group, session_count, _confirm_delete)
                    new_card = ui.element("div").classes("gcard new")
                    with new_card:
                        with ui.element("div"):
                            with ui.element("div").classes("plus"):
                                ui.html("+")
                            with ui.element("div").classes("t"):
                                ui.html("新しいグループ")
                    new_card.on(
                        "click",
                        js_handler="() => document.getElementById('createLbl')"
                        "?.scrollIntoView({behavior:'smooth'})",
                    )

            async def _refresh_groups() -> None:
                _render_grid(await _load_groups_with_counts(ctx))

            _render_grid(initial_groups)

            with ui.element("div").classes("state-lbl").props('id="createLbl"'):
                ui.html("新しいグループを作る（作成フロー）")
            with ui.element("section").classes("create"):
                ui.element("div").classes("sparkle-field").props('data-count="12"')
                _render_create_flow(ctx)


def _render_create_flow(ctx) -> None:
    """作成フロー本体(モックの3ステップ+パリティ機能)。"""
    personas = ctx.user_personas.get_user_personas()
    persona_options = {persona.id: persona.display_name for persona in personas}
    profile_options = profile_options_for_context(ctx)

    selected: dict[str, list[CharacterSheet]] = {"characters": []}
    state: dict[str, Any] = {
        "profile_id": default_profile_id(ctx, profile_options),
        "name": "",
        "world_source": "new",
        "world_text": "",
        "persona_id": next(iter(persona_options), ""),
        "user_handle": "User",
        "handle_values": {},
        "entry_modes": {},
        "arrival_reasons": {},
        "adaptation_notes": {},
        "adaptation_instructions": {},
        "draft_sheets": {},
        "user_description_draft": "",
    }
    busy = BusyController()

    def _selected_persona():
        persona_id = str(state.get("persona_id") or "")
        return ctx.user_personas.get_user_persona(persona_id) if persona_id else None

    def _world_source_character_id() -> str:
        source = str(state.get("world_source") or "new")
        return source.removeprefix("character:") if source.startswith("character:") else ""

    def _current_world_text() -> str:
        source_id = _world_source_character_id()
        if source_id:
            source_sheet = next((sheet for sheet in selected["characters"] if sheet.id == source_id), None)
            return (source_sheet.world if source_sheet else "").strip()
        return str(state.get("world_text") or "").strip()

    def _display_sheet(sheet: CharacterSheet) -> CharacterSheet:
        return state["draft_sheets"].get(sheet.id, sheet)

    # ---- 上段: 補完用プロファイル ----
    if not profile_options:
        ui.label("LLMプロファイルが未登録です。補完・適応機能を使うには設定画面で追加してください。").classes(
            "note"
        ).style("color: #e08a8a;")
    profile_select = (
        ui.select(
            options=profile_options,
            value=state["profile_id"] if state["profile_id"] in profile_options else None,
            label="補完用LLMプロファイル（世界観補完・適応・ハンドル生成に使用）",
        )
        .props("outlined dense")
        .classes("w-full p3-ta")
        .style("max-width: 480px;")
    )
    profile_select.on_value_change(lambda e: state.update(profile_id=str(e.value or "")))

    def _profile_id() -> str:
        return str(profile_select.value or "")

    # ---- Step 一: 世界を決める ----
    with ui.element("div").classes("step"):
        with ui.element("div").classes("no"):
            ui.html("一")
        with ui.element("div").classes("body"):
            with ui.element("h3"):
                ui.html("世界を決める")
            with ui.element("div").classes("d"):
                ui.html("グループの土台になる世界観。ここが箱庭の「外枠」になります。")
            with ui.element("div").classes("opt-row"):
                opt_new = ui.element("div").classes("opt on").mark("ui2-group-world-new")
                opt_char = ui.element("div").classes("opt").mark("ui2-group-world-char")
            with opt_new:
                with ui.element("div").classes("t"):
                    ui.html("新しく生成する")
                with ui.element("div").classes("s"):
                    ui.html("世界観を書き、必要なら「世界観を補完」でAIが具体化します")
                world_input = (
                    ui.textarea(
                        placeholder="例）あらゆる次元が交差する中立地帯。異世界の住人たちが共存している。",
                        value=state["world_text"],
                    )
                    .props("outlined rows=3 autogrow")
                    .classes("w-full p3-ta")
                    .mark("ui2-group-world-input")
                )
                world_input.on_value_change(lambda e: state.update(world_text=str(e.value or "")))
                with ui.element("div").classes("field-row"):

                    async def _enhance_world() -> None:
                        busy.begin("世界観を補完しています...")
                        try:
                            enhanced = await enhance_world_text(
                                ctx,
                                _profile_id(),
                                current_world=str(world_input.value or ""),
                                group_name=str(state.get("name") or ""),
                                characters=[_display_sheet(sheet) for sheet in selected["characters"]],
                                persona=_selected_persona(),
                                on_job_started=busy.set_job,
                            )
                            if enhanced:
                                world_input.set_value(enhanced)
                                state["world_text"] = enhanced
                        finally:
                            busy.end()

                    chip_button("世界観を補完", _enhance_world, title="核を変えずにLLMで具体化")
            with opt_char:
                with ui.element("div").classes("t"):
                    ui.html("既存キャラクターの世界を土台にする")
                with ui.element("div").classes("s"):
                    ui.html("選んだ住人の世界観をそのまま引き継ぎます（住人を迎えてから選択）")
                world_char_box = ui.element("div").classes("field-row")

            world_preview = ui.element("div").classes("note").style("margin-top: 12px; white-space: pre-wrap;")

            def _sync_world_option() -> None:
                is_new = str(state.get("world_source") or "new") == "new"
                if is_new:
                    opt_new.classes("on")
                    opt_char.classes(remove="on")
                else:
                    opt_char.classes("on")
                    opt_new.classes(remove="on")
                world_char_box.clear()
                with world_char_box:
                    options = world_source_options(selected["characters"])
                    source_id = _world_source_character_id()
                    for key, label in options.items():
                        if key == "new":
                            continue
                        chip = ui.element("button").classes(
                            "chip on" if key == f"character:{source_id}" else "chip"
                        )
                        with chip:
                            ui.html(html.escape(label))
                        chip.on("click.stop", lambda k=key: _pick_world_source(k))
                    if len(options) <= 1:
                        with ui.element("span").classes("note"):
                            ui.html("世界観を持つ住人がまだ選ばれていません")
                world_preview.clear()
                if not is_new:
                    with world_preview:
                        ui.html(html.escape(_current_world_text() or "（引き継ぎ元が未選択です）"))

            def _pick_world_source(key: str) -> None:
                state["world_source"] = key
                _sync_world_option()

            def _select_char_option() -> None:
                options = world_source_options(selected["characters"])
                character_keys = [key for key in options if key != "new"]
                if not character_keys:
                    ui.notify("先に世界観を持つ住人を迎えてください", type="warning")
                    return
                if str(state.get("world_source") or "new") == "new":
                    state["world_source"] = character_keys[0]
                _sync_world_option()

            opt_new.on("click", lambda: _pick_world_source("new"))
            opt_char.on("click", lambda: _select_char_option())

            with ui.element("div").classes("field-row"):
                name_input = (
                    ui.input(label="グループ名", value=state["name"])
                    .props("outlined dense")
                    .classes("p3-ta name-input")
                    .mark("ui2-group-name-input")
                )
                name_input.on_value_change(lambda e: state.update(name=str(e.value or "").strip()))

                async def _generate_name() -> None:
                    busy.begin("グループ名を補完しています...")
                    try:
                        name = await generate_group_name(
                            ctx,
                            _profile_id(),
                            world=_current_world_text(),
                            characters=[_display_sheet(sheet) for sheet in selected["characters"]],
                            persona=_selected_persona(),
                            on_job_started=busy.set_job,
                        )
                        if name:
                            name_input.set_value(name)
                            state["name"] = name
                    finally:
                        busy.end()

                chip_button("名前を補完", _generate_name, title="ワールドからグループ名を1つ提案")

    # ---- Step 二: 住人を迎える ----
    with ui.element("div").classes("step"):
        with ui.element("div").classes("no"):
            ui.html("二")
        with ui.element("div").classes("body"):
            with ui.element("h3"):
                ui.html("住人を迎える")
            with ui.element("div").classes("d"):
                ui.html(
                    "選んだキャラクターは、この世界に合わせた<b>適応コピー</b>として保存されます"
                    "（元のキャラクターは変わりません）。チップをクリックすると"
                    "ハンドル・参加設定・来訪理由・適応を編集できます。"
                )
            picks_box = ui.element("div").classes("picks").mark("ui2-group-picks")

    # ---- Step 三: あなたの姿 ----
    with ui.element("div").classes("step"):
        with ui.element("div").classes("no"):
            ui.html("三")
        with ui.element("div").classes("body"):
            with ui.element("h3"):
                ui.html("あなたの姿")
            with ui.element("div").classes("d"):
                ui.html("この世界でのあなた（グループ専用ペルソナ）。来歴は世界に合わせて適応できます。")
            persona_box = ui.element("div").classes("picks").mark("ui2-group-persona-row")

    # ---- 作成 ----
    with ui.element("div").classes("go-row"):
        p3_button("グループを作成", lambda: _create_group(), classes="btn primary").style(
            "padding: 12px 36px;"
        ).mark("ui2-group-create")
        with ui.element("span").classes("note"):
            ui.html("世界観の補完・住人の適応・来訪理由は、各ステップで確認しながら反映できます")

    # ------------------------------------------------------------------
    # 描画リフレッシュ
    # ------------------------------------------------------------------

    def _resident_status(sheet: CharacterSheet) -> str:
        key = f"character:{sheet.id}"
        if sheet.id == _world_source_character_id():
            return entry_type_label("world_source")
        parts = [entry_type_label(state["entry_modes"].get(key, "native"))]
        if state["adaptation_notes"].get(key):
            parts.append("適応済")
        return "・".join(parts)

    def _open_resident_dialog(sheet: CharacterSheet) -> None:
        display = _display_sheet(sheet)
        state["handle_values"].setdefault(
            sheet.id, fallback_handle(sheet, len(selected["characters"]))
        )
        open_resident_settings_dialog(
            ctx,
            state=state,
            key=f"character:{sheet.id}",
            display_name=display.name,
            summary=compact_character_summary(display),
            sheet=sheet,
            world_getter=_current_world_text,
            profile_getter=_profile_id,
            busy=busy,
            on_change=_refresh_picks,
            is_world_source=sheet.id == _world_source_character_id(),
        )

    def _remove_character(character_id: str) -> None:
        selected["characters"] = [sheet for sheet in selected["characters"] if sheet.id != character_id]
        key = f"character:{character_id}"
        for bucket in ("entry_modes", "arrival_reasons", "adaptation_notes", "adaptation_instructions"):
            state[bucket].pop(key, None)
        state["handle_values"].pop(character_id, None)
        state["draft_sheets"].pop(character_id, None)
        if state["world_source"] == f"character:{character_id}":
            state["world_source"] = "new"
        _refresh_picks()
        _sync_world_option()

    async def _open_picker() -> None:
        async def _add(sheet: CharacterSheet) -> None:
            selected["characters"].append(sheet)
            state["entry_modes"].setdefault(f"character:{sheet.id}", "native")
            state["handle_values"].setdefault(sheet.id, fallback_handle(sheet, len(selected["characters"])))
            _refresh_picks()
            _sync_world_option()

        await open_character_pick_dialog(
            ctx,
            title="グループに迎えるキャラクターを選択",
            exclude_ids={sheet.id for sheet in selected["characters"]},
            on_select=_add,
        )

    async def _generate_all_handles() -> None:
        persona = _selected_persona()
        busy.begin("ハンドルを生成しています...")
        try:
            generated = await generate_handles_values(
                ctx,
                _profile_id(),
                [_display_sheet(sheet) for sheet in selected["characters"]],
                persona,
                on_job_started=busy.set_job,
            )
            if generated is None:
                return
            values, user_handle = generated
            # 生成キー(draft sheet の id は元と同じ)を元 sheet id に対応づける
            state["handle_values"].update(values)
            if user_handle:
                state["user_handle"] = user_handle
            _refresh_picks()
            _refresh_persona_row()
        finally:
            busy.end()

    def _refresh_picks() -> None:
        picks_box.clear()
        with picks_box:
            for sheet in selected["characters"]:
                display = _display_sheet(sheet)
                pick = ui.element("button").classes("pick").props(
                    f'title="クリックで参加設定を編集: @{html.escape(str(state["handle_values"].get(sheet.id) or ""))}"'
                )
                pick.on("click", lambda s=sheet: _open_resident_dialog(s))
                with pick:
                    image = sheet.media.primary_image()
                    url = media_url(image.path) if image is not None else None
                    if url is not None:
                        raw_img(url).style(f"object-position: {image_object_position(image)};")
                    else:
                        with ui.element("span").classes("pick-ph"):
                            ui.html(html.escape((display.name or "?")[:1]))
                    ui.html(html.escape(display.name))
                    with ui.element("span").classes("st"):
                        ui.html(html.escape(_resident_status(sheet)))
                    x = ui.element("span").classes("x").props('title="はずす"')
                    with x:
                        ui.html("×")
                    x.on("click.stop", lambda cid=sheet.id: _remove_character(cid))
            chip_button("+ キャラクターを追加", _open_picker).mark("ui2-group-add-resident")
            if selected["characters"]:
                chip_button("ハンドルを一括生成", _generate_all_handles, title="メンション用ハンドルをLLMで一括生成")

    def _open_user_settings() -> None:
        persona = _selected_persona()
        if persona is None:
            ui.notify("先にペルソナを選択してください", type="warning")
            return
        open_resident_settings_dialog(
            ctx,
            state=state,
            key="user",
            display_name=persona.display_name or persona.name or "ユーザー",
            summary=str(state.get("user_description_draft") or persona.description),
            sheet=None,
            world_getter=_current_world_text,
            profile_getter=_profile_id,
            busy=busy,
            on_change=_refresh_persona_row,
        )

    def _change_persona() -> None:
        if not persona_options:
            ui.notify("ユーザーペルソナが未登録です。設定画面で追加してください。", type="warning")
            return
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-md").style(_DIALOG_CARD_STYLE):
            ui.label("ペルソナを変更").classes("text-base font-semibold")
            persona_select = (
                ui.select(options=persona_options, value=state["persona_id"] or None, label="ユーザーペルソナ")
                .props("outlined dense")
                .classes("w-full")
            )
            handle_input = (
                ui.input(label="あなたのハンドル", value=state["user_handle"])
                .props("outlined dense")
                .classes("w-full p3-ta")
            )

            def _apply() -> None:
                persona_id = str(persona_select.value or "")
                if persona_id != state["persona_id"]:
                    state["user_description_draft"] = ""
                    for bucket in ("adaptation_notes", "adaptation_instructions", "arrival_reasons"):
                        state[bucket].pop("user", None)
                state["persona_id"] = persona_id
                state["user_handle"] = str(handle_input.value or "").strip() or "User"
                dlg.close()
                _refresh_persona_row()

            with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                p3_button("キャンセル", dlg.close, classes="btn quiet")
                p3_button("決定", _apply, classes="btn primary")
        dlg.open()

    def _refresh_persona_row() -> None:
        persona_box.clear()
        with persona_box:
            persona = _selected_persona()
            if persona is None:
                with ui.element("span").classes("note"):
                    ui.html("ユーザーペルソナが未選択です")
            else:
                display = persona.display_name or persona.name or "ユーザー"
                pick = ui.element("button").classes("pick").props('title="クリックで参加設定を編集"')
                pick.on("click", lambda: _open_user_settings())
                with pick:
                    image = persona.media.primary_image()
                    url = media_url(image.path) if image is not None else None
                    if url is not None:
                        raw_img(url).style(f"object-position: {image_object_position(image)};")
                    else:
                        with ui.element("span").classes("pick-ph"):
                            ui.html(html.escape(display[:1]))
                    ui.html(html.escape(f"{display}（@{state['user_handle']}）"))
                    if state["adaptation_notes"].get("user"):
                        with ui.element("span").classes("st"):
                            ui.html("適応済")
            chip_button("ペルソナを変更", _change_persona).mark("ui2-group-change-persona")

    # ------------------------------------------------------------------
    # 作成
    # ------------------------------------------------------------------

    async def _create_group() -> None:
        persona = _selected_persona()
        if not _profile_id():
            ui.notify("補完用LLMプロファイルを選択してください", type="warning")
            return
        if not selected["characters"]:
            ui.notify("住人になるキャラクターを選択してください", type="warning")
            return
        if persona is None:
            ui.notify("ユーザーペルソナを選択してください", type="warning")
            return
        if not str(state.get("name") or "").strip():
            ui.notify("グループ名を入力してください", type="warning")
            return
        world = _current_world_text()
        if not world:
            ui.notify("世界観を入力（または引き継ぎ元を選択）してください", type="warning")
            return
        validation = validate_handle_values(
            selected["characters"], state["handle_values"], state["user_handle"]
        )
        if not validation.ok:
            ui.notify(validation.error, type="warning")
            return
        source_id = _world_source_character_id()
        for sheet in selected["characters"]:
            key = f"character:{sheet.id}"
            if sheet.id == source_id:
                continue
            if state["entry_modes"].get(key, "native") == "visitor" and not state["arrival_reasons"].get(key, "").strip():
                ui.notify(f"{sheet.name} の来訪理由を入力してください", type="warning")
                return
        if state["entry_modes"].get("user", "native") == "visitor" and not state["arrival_reasons"].get("user", "").strip():
            ui.notify("あなたの来訪理由を入力してください", type="warning")
            return

        members_for_create: list[tuple[CharacterSheet, str]] = []
        member_world_settings: dict[str, dict[str, str]] = {}
        for sheet, handle in zip(selected["characters"], validation.handles, strict=True):
            key = f"character:{sheet.id}"
            prepared, settings = prepare_group_character_for_world(
                _display_sheet(sheet),
                world=world,
                source_character_id=source_id,
                entry_type=state["entry_modes"].get(key, "native"),
                arrival_reason=state["arrival_reasons"].get(key, ""),
                adaptation_note=state["adaptation_notes"].get(key, ""),
            )
            members_for_create.append((prepared, handle))
            member_world_settings[prepared.id] = settings

        user_world_settings = prepare_group_user_world_settings(
            persona,
            world=world,
            entry_type=state["entry_modes"].get("user", "native"),
            arrival_reason=state["arrival_reasons"].get("user", ""),
            adaptation_note=state["adaptation_notes"].get("user", ""),
            description_override=str(state.get("user_description_draft") or ""),
        )

        group = await ctx.group_chats.create_group(
            name=str(state["name"]).strip(),
            world=world,
            completion_profile_id=_profile_id(),
            members=members_for_create,
            user_persona=persona,
            user_handle=validation.user_handle,
            world_source_type="character" if source_id else "new",
            world_source_character_id=source_id,
            member_world_settings=member_world_settings,
            user_world_settings=user_world_settings,
        )
        ui.notify(f"グループ「{group.name}」を作成しました", type="positive")
        ui.navigate.to(f"/v2/groups/{group.id}")

    _refresh_picks()
    _refresh_persona_row()
    _sync_world_option()
