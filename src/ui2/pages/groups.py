"""
/groups グループ一覧(Phase 4)。モック proposal3/groups.html 準拠。
作成フローは /groups/new(pages/create_group.py)に分離。

- 一覧: 箱庭カード(三連の住人ポートレート+世界観+統計)。ひらく/削除。
- 作成フロー: 旧ウィザードと同じ入力導線の4ステップ
  (一 住人とあなた / 二 世界と名前 / 三 世界に馴染ませる / 四 関係性)を
  ページ内セクションとして実装。パリティ項目(世界source・世界強化・名前生成・
  ハンドル生成・適応プレビューdiff・到着理由・ペルソナ適応・関係性ドラフト)は
  各ステップ内のチップ/住人設定ダイアログ(group_setup.py)で提供する。
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
from ...core.conversation.relationship_drafts import (
    merge_relationship_drafts,
    next_relationship_draft_id,
    relationship_draft_participants,
    upsert_relationship_draft,
)
from ...core.conversation.world_adaptation import (
    prepare_group_character_for_world,
    prepare_group_user_world_settings,
)
from ...core.group_chat.schemas import GroupChatRecord, GroupRelationship
from ..components.busy import BusyController
from ..components.portrait import face_avatar, image_object_position, media_url, raw_img
from ..group_logic import (
    entry_type_label,
    validate_handle_values,
    world_source_options,
)
from ..group_setup import (
    PICKER_CSS,
    chip_button,
    default_profile_id,
    enhance_relationship_text,
    enhance_world_text,
    generate_group_name,
    generate_handles_values,
    open_character_pick_dialog,
    open_resident_settings_dialog,
    p3_button,
    profile_options_for_context,
    run_assist,
)
from ..scaffold import p3_page
from ..state import get_vault_password

_DIALOG_CARD_STYLE = "background: var(--panel); color: var(--text);"

# モック groups.html の <style> 移植+P3フォームスキン(ピッカーは group_setup.PICKER_CSS)
_PAGE_CSS = """
.wrap { max-width: 1120px; margin: 0 auto; padding: 34px 26px 30px; }
.page-head { display: flex; align-items: center; gap: 18px; margin-bottom: 24px; flex-wrap: wrap; }
.page-head h1 { font-size: 26px; letter-spacing: .3em; margin: 0; font-weight: 600; }
.page-head .mk { margin-left: auto; }

/* ---------- 箱庭カード ---------- */
.ggrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 18px; }
.gcard {
  position: relative;
  border-radius: 8px;
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
.gcard.new {
  display: grid; place-items: center;
  min-height: 264px;
  background: transparent;
  border: 1.5px dashed var(--line-2);
}
.gcard.new:hover { border-color: var(--accent); box-shadow: none; }
.gcard.new .plus { font-size: 38px; color: var(--accent); line-height: 1; text-align: center; }
.gcard.new .t { color: var(--muted); font-size: 13px; letter-spacing: .14em; margin-top: 10px; text-align: center; }

/* ---------- 作成フロー(/groups/new) ---------- */
.create {
  position: relative;
  padding: 6px 0 30px;
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
  border-radius: 6px;
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
  border-radius: 4px;
  padding: 4px 12px 4px 5px;
  font-size: 12.5px;
  cursor: pointer;
  background: transparent;
  color: var(--text);
  transition: border-color .18s;
}
.pick:hover { border-color: var(--accent); }
.pick img, .pick .pick-av { width: 28px; height: 28px; border-radius: 50%; object-fit: cover; flex: none; }
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

/* 関係性(Step 四) */
.rels { display: flex; flex-direction: column; gap: 10px; margin-top: 12px; }
.rel-row { border: 1px solid var(--line); border-radius: 6px; padding: 10px 14px; }
.rel-row .rel-head { display: flex; align-items: center; gap: 6px; }
.rel-row .pair { font-size: 12.5px; font-weight: 600; letter-spacing: .04em; }
.rel-row .sp { flex: 1; }
.rel-row .tx { font-size: 12.5px; color: var(--muted); line-height: 1.7; margin-top: 4px; white-space: pre-wrap; }

/* P3 スキン(Quasar 部品) */
.p3-ta { width: 100%; }
.p3-ta .q-field__control { background: var(--bg-2) !important; border-radius: 6px; }
.p3-ta .q-field__control:before { border-color: var(--line-2) !important; }
.p3-ta textarea, .p3-ta input { color: var(--text) !important; line-height: 1.8; }

@media (max-width: 860px) {
  .wrap { padding: 24px 16px; }
  .create { padding: 6px 0 24px; }
  .step { flex-direction: column; gap: 8px; }
}
"""


def _member_image_assets(group: GroupChatRecord) -> list:
    return [member.character.media.primary_image() for member in group.members[:3]]


def _render_group_card(ctx, group: GroupChatRecord, session_count: int) -> None:
    card = ui.element("div").classes("gcard").mark("ui2-group-card")
    card.on("click", lambda gid=group.id: ui.navigate.to(f"/groups/{gid}"))
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


async def _load_groups_with_counts(ctx) -> list[tuple[GroupChatRecord, int]]:
    groups = await ctx.group_chats.list_all()
    result: list[tuple[GroupChatRecord, int]] = []
    for group in groups:
        sessions = await ctx.group_chats.list_sessions_for_group(group.id)
        result.append((group, len(sessions)))
    return result


@ui.page("/groups")
async def ui2_groups_page() -> None:
    ctx = get_context()
    # 描画前にデータを読み切る(p3_page 内で await すると初期レスポンスに載らず、
    # WS未接続の headless 検証で白く写る。先行Phaseと同じ「先読み→同期描画」)
    initial_groups = await _load_groups_with_counts(ctx)

    with p3_page("グループ"):
        ui.add_css(_PAGE_CSS + PICKER_CSS)
        with ui.element("div").classes("wrap"):
            with ui.element("div").classes("page-head"):
                with ui.element("h1").classes("serif"):
                    ui.html("グループ一覧")
                with ui.element("span").classes("note"):
                    ui.html("それぞれが独立した箱庭。住人はその世界に合わせた適応コピー")
                mk = ui.element("button").classes("btn primary mk")
                with mk:
                    ui.html("+ 新しいグループ")
                mk.on("click", lambda: ui.navigate.to("/groups/new"))

            grid = ui.element("div").classes("ggrid").mark("ui2-groups-grid")

            def _render_grid(groups_with_counts: list[tuple[GroupChatRecord, int]]) -> None:
                grid.clear()
                with grid:
                    for group, session_count in groups_with_counts:
                        _render_group_card(ctx, group, session_count)
                    new_card = ui.element("div").classes("gcard new")
                    with new_card:
                        with ui.element("div"):
                            with ui.element("div").classes("plus"):
                                ui.html("+")
                            with ui.element("div").classes("t"):
                                ui.html("新しいグループ")
                    new_card.on("click", lambda: ui.navigate.to("/groups/new"))

            _render_grid(initial_groups)


def _render_create_flow(ctx) -> None:
    """作成フロー本体(モックの3ステップ+パリティ機能)。"""
    personas = ctx.user_personas.get_user_personas()
    persona_options = {persona.id: persona.display_name for persona in personas}
    profile_options = profile_options_for_context(ctx)

    selected: dict[str, list[CharacterSheet]] = {"characters": []}
    initial_persona_id = next(iter(persona_options), "")
    initial_persona = ctx.user_personas.get_user_persona(initial_persona_id) if initial_persona_id else None
    state: dict[str, Any] = {
        "profile_id": default_profile_id(ctx, profile_options),
        "name": "",
        "world_source": "new",
        "world_text": "",
        "persona_id": initial_persona_id,
        "user_handle": (initial_persona.fixed_handle if initial_persona else "") or "User",
        "handle_values": {},
        "entry_modes": {},
        "arrival_reasons": {},
        "adaptation_notes": {},
        "adaptation_instructions": {},
        "draft_sheets": {},
        "user_description_draft": "",
        "relationships": [],
        "relationship_sequence": 0,
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

    # ---- Step 一: 住人とあなたを決める ----
    with ui.element("div").classes("step"):
        with ui.element("div").classes("no"):
            ui.html("一")
        with ui.element("div").classes("body"):
            with ui.element("h3"):
                ui.html("住人とあなたを決める")
            with ui.element("div").classes("d"):
                ui.html(
                    "この世界の住人になるキャラクターと、あなたの姿（ユーザーペルソナ）を選びます。"
                    "選んだキャラクターは、この世界に合わせた<b>適応コピー</b>として保存されます"
                    "（元のキャラクターは変わりません）。"
                )
            picks_box = ui.element("div").classes("picks").mark("ui2-group-picks")
            with ui.element("div").classes("d").style("margin-top: 16px;"):
                ui.html("この世界でのあなた（グループ専用ペルソナ）")
            persona_box = ui.element("div").classes("picks").mark("ui2-group-persona-row")

    # ---- Step 二: 世界と名前を決める ----
    with ui.element("div").classes("step"):
        with ui.element("div").classes("no"):
            ui.html("二")
        with ui.element("div").classes("body"):
            with ui.element("h3"):
                ui.html("世界と名前を決める")
            with ui.element("div").classes("d"):
                ui.html("グループの土台になる世界観と、その世界にふさわしい名前。ここが箱庭の「外枠」になります。")
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
                    ui.html("選んだ住人の世界観をそのまま引き継ぎます（一で迎えた住人から選択）")
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
                _refresh_adaptation()

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

    # ---- Step 三: 世界に馴染ませる ----
    with ui.element("div").classes("step"):
        with ui.element("div").classes("no"):
            ui.html("三")
        with ui.element("div").classes("body"):
            with ui.element("h3"):
                ui.html("世界に馴染ませる")
            with ui.element("div").classes("d"):
                ui.html(
                    "それぞれが「元々この世界の住人」なのか「何らかの理由でこの世界に来た」のかを決め、"
                    "必要ならシートをこの世界に合わせて適応します。チップをクリックすると"
                    "参加設定・来訪理由・適応を編集できます。"
                )
            adapt_box = ui.element("div").classes("picks").mark("ui2-group-adapt")

    # ---- Step 四: 関係性を結ぶ ----
    with ui.element("div").classes("step"):
        with ui.element("div").classes("no"):
            ui.html("四")
        with ui.element("div").classes("body"):
            with ui.element("h3"):
                ui.html("関係性を結ぶ")
            with ui.element("div").classes("d"):
                ui.html(
                    "住人どうし・あなたとの初期関係。空のままでも作成でき、"
                    "作成後にグループの「管理」からも編集できます。"
                )
            with ui.element("div").classes("field-row"):
                chip_button("+ 関係性を追加", lambda: _open_relationship_draft_dialog(None)).mark(
                    "ui2-group-rel-add"
                )
                chip_button(
                    "LLMで自動設定",
                    lambda: _generate_relationships(),
                    title="会話が動きやすい重要な関係だけをLLMが提案",
                )
            rel_box = ui.element("div").classes("rels").mark("ui2-group-rels")

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
        """Step 三: 参加設定・来訪理由・適応の編集(ハンドルは Step 一で変更)。"""
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
            handle_editable=False,
            is_world_source=sheet.id == _world_source_character_id(),
        )

    def _open_handle_dialog(sheet: CharacterSheet) -> None:
        """Step 一: ハンドルだけを変更する。"""
        display = _display_sheet(sheet)
        state["handle_values"].setdefault(
            sheet.id, fallback_handle(sheet, len(selected["characters"]))
        )
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm").style(_DIALOG_CARD_STYLE):
            ui.label(f"{display.name} のハンドル").classes("text-base font-semibold")
            handle_input = (
                ui.input(
                    label="ハンドル（メンション用・3〜12文字の英数字_）",
                    value=str(state["handle_values"].get(sheet.id) or ""),
                )
                .props("outlined dense")
                .classes("w-full p3-ta")
                .mark("ui2-group-handle-input")
            )

            def _save() -> None:
                state["handle_values"][sheet.id] = str(handle_input.value or "").strip()
                dlg.close()
                _refresh_picks()

            with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                p3_button("キャンセル", dlg.close, classes="btn quiet")
                p3_button("保存", _save, classes="btn primary").mark("ui2-group-handle-save")
        dlg.open()

    def _remove_character(character_id: str) -> None:
        selected["characters"] = [sheet for sheet in selected["characters"] if sheet.id != character_id]
        key = f"character:{character_id}"
        for bucket in ("entry_modes", "arrival_reasons", "adaptation_notes", "adaptation_instructions"):
            state[bucket].pop(key, None)
        state["handle_values"].pop(character_id, None)
        state["draft_sheets"].pop(character_id, None)
        if state["world_source"] == f"character:{character_id}":
            state["world_source"] = "new"
        state["relationships"] = [
            item
            for item in state["relationships"]
            if f"character:{character_id}"
            not in {str(item.get("participant_a_key")), str(item.get("participant_b_key"))}
        ]
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
                reserved_handles={str(state["user_handle"] or "")},
                include_user=False,
                on_job_started=busy.set_job,
            )
            if generated is None:
                return
            values, _ = generated
            # 生成キー(draft sheet の id は元と同じ)を元 sheet id に対応づける
            state["handle_values"].update(values)
            _refresh_picks()
        finally:
            busy.end()

    def _refresh_picks() -> None:
        picks_box.clear()
        with picks_box:
            for sheet in selected["characters"]:
                display = _display_sheet(sheet)
                pick = ui.element("button").classes("pick").props('title="クリックでハンドルを変更"')
                pick.on("click", lambda s=sheet: _open_handle_dialog(s))
                with pick:
                    image = sheet.media.primary_image()
                    path = ctx.characters.media_path(image.path) if image is not None else None
                    if face_avatar(image, "pick-av", image_path=path) is None:
                        with ui.element("span").classes("pick-ph"):
                            ui.html(html.escape((display.name or "?")[:1]))
                    ui.html(html.escape(display.name))
                    with ui.element("span").classes("st"):
                        ui.html(html.escape(f"@{state['handle_values'].get(sheet.id) or ''}"))
                    x = ui.element("span").classes("x").props('title="はずす"')
                    with x:
                        ui.html("×")
                    x.on("click.stop", lambda cid=sheet.id: _remove_character(cid))
            chip_button("+ キャラクターを追加", _open_picker).mark("ui2-group-add-resident")
            if selected["characters"]:
                chip_button("ハンドルを一括生成", _generate_all_handles, title="メンション用ハンドルをLLMで一括生成")
        _refresh_adaptation()
        _refresh_relationships()

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

            def _sync_fixed_handle(_) -> None:
                persona_obj = ctx.user_personas.get_user_persona(str(persona_select.value or ""))
                fixed = (persona_obj.fixed_handle if persona_obj else "").strip()
                if fixed:
                    handle_input.set_value(fixed)

            persona_select.on_value_change(_sync_fixed_handle)

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
                    path = ctx.user_personas.media_path(image.path) if image is not None else None
                    if face_avatar(image, "pick-av", image_path=path) is None:
                        with ui.element("span").classes("pick-ph"):
                            ui.html(html.escape(display[:1]))
                    ui.html(html.escape(f"{display}（@{state['user_handle']}）"))
                    if state["adaptation_notes"].get("user"):
                        with ui.element("span").classes("st"):
                            ui.html("適応済")
            chip_button("ペルソナを変更", _change_persona).mark("ui2-group-change-persona")
        _refresh_adaptation()
        _refresh_relationships()

    # ------------------------------------------------------------------
    # Step 三: 世界に馴染ませる / Step 四: 関係性
    # ------------------------------------------------------------------

    def _user_status() -> str:
        parts = [entry_type_label(state["entry_modes"].get("user", "native"))]
        if state["adaptation_notes"].get("user"):
            parts.append("適応済")
        return "・".join(parts)

    def _refresh_adaptation() -> None:
        adapt_box.clear()
        with adapt_box:
            persona = _selected_persona()
            if not selected["characters"] and persona is None:
                with ui.element("span").classes("note"):
                    ui.html("一で住人とあなたを選ぶと、ここに並びます")
                return
            for sheet in selected["characters"]:
                display = _display_sheet(sheet)
                pick = ui.element("button").classes("pick").props('title="クリックで参加設定を編集"')
                pick.on("click", lambda s=sheet: _open_resident_dialog(s))
                with pick:
                    image = sheet.media.primary_image()
                    path = ctx.characters.media_path(image.path) if image is not None else None
                    if face_avatar(image, "pick-av", image_path=path) is None:
                        with ui.element("span").classes("pick-ph"):
                            ui.html(html.escape((display.name or "?")[:1]))
                    ui.html(html.escape(display.name))
                    with ui.element("span").classes("st"):
                        ui.html(html.escape(_resident_status(sheet)))
            if persona is not None:
                display_name = persona.display_name or persona.name or "ユーザー"
                pick = ui.element("button").classes("pick").props('title="クリックで参加設定を編集"')
                pick.on("click", lambda: _open_user_settings())
                with pick:
                    image = persona.media.primary_image()
                    path = ctx.user_personas.media_path(image.path) if image is not None else None
                    if face_avatar(image, "pick-av", image_path=path) is None:
                        with ui.element("span").classes("pick-ph"):
                            ui.html(html.escape(display_name[:1]))
                    ui.html(html.escape(display_name))
                    with ui.element("span").classes("st"):
                        ui.html(html.escape(_user_status()))

    def _relationship_participants() -> list[dict[str, str]]:
        display_characters = [_display_sheet(sheet) for sheet in selected["characters"]]
        return relationship_draft_participants(display_characters, _selected_persona(), state)

    def _relationship_labels() -> dict[str, str]:
        return {item["key"]: item["name"] for item in _relationship_participants()}

    def _delete_relationship(relationship_id: str) -> None:
        state["relationships"] = [
            item for item in state["relationships"] if str(item.get("id")) != relationship_id
        ]
        _refresh_relationships()

    def _refresh_relationships() -> None:
        rel_box.clear()
        labels = _relationship_labels()
        with rel_box:
            if not state["relationships"]:
                with ui.element("span").classes("note"):
                    ui.html("設定済みの関係性はありません")
                return
            for relationship in list(state["relationships"]):
                with ui.element("div").classes("rel-row"):
                    with ui.element("div").classes("rel-head"):
                        with ui.element("div").classes("pair"):
                            left = labels.get(str(relationship["participant_a_key"]), "不明な参加者")
                            right = labels.get(str(relationship["participant_b_key"]), "不明な参加者")
                            ui.html(html.escape(f"{left} ↔ {right}"))
                        ui.element("div").classes("sp")
                        chip_button("編集", lambda item=relationship: _open_relationship_draft_dialog(item))
                        chip_button("削除", lambda rid=str(relationship["id"]): _delete_relationship(rid))
                    with ui.element("div").classes("tx"):
                        ui.html(html.escape(str(relationship["description"])))

    def _open_relationship_draft_dialog(item: dict[str, str] | None) -> None:
        options = _relationship_labels()
        if len(options) < 2:
            ui.notify("関係性を設定できる参加者が足りません（一で住人とあなたを選んでください）", type="warning")
            return
        keys = list(options)
        first_value = str(item["participant_a_key"]) if item else keys[0]
        second_value = str(item["participant_b_key"]) if item else keys[1]
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg").style(_DIALOG_CARD_STYLE):
            ui.label("関係性を編集" if item else "関係性を追加").classes("text-base font-semibold")
            first_select = (
                ui.select(options=options, value=first_value if first_value in options else keys[0], label="参加者1")
                .props("outlined dense")
                .classes("w-full")
            )
            second_select = (
                ui.select(options=options, value=second_value if second_value in options else keys[1], label="参加者2")
                .props("outlined dense")
                .classes("w-full")
            )
            description_input = (
                ui.textarea(
                    label="関係性",
                    value=str(item["description"]) if item else "",
                    placeholder="例: 幼なじみだが、現在は互いに距離を測っている。",
                )
                .props("outlined rows=5")
                .classes("w-full p3-ta")
                .mark("ui2-group-rel-description")
            )

            async def _enhance() -> None:
                busy.begin("関係性を補完しています...")
                try:
                    enhanced = await enhance_relationship_text(
                        ctx,
                        _profile_id(),
                        world=_current_world_text(),
                        participants=_relationship_participants(),
                        first_key=str(first_select.value or ""),
                        second_key=str(second_select.value or ""),
                        current_description=str(description_input.value or ""),
                        on_job_started=busy.set_job,
                    )
                    if enhanced:
                        description_input.set_value(enhanced)
                finally:
                    busy.end()

            chip_button("関係性を補完", _enhance, title="入力内容を核に具体性だけ補う")

            def _save() -> None:
                first_key = str(first_select.value or "")
                second_key = str(second_select.value or "")
                description = str(description_input.value or "").strip()
                if not first_key or not second_key:
                    ui.notify("参加者を選択してください", type="warning")
                    return
                if first_key == second_key:
                    ui.notify("異なる2人を選択してください", type="warning")
                    return
                if not description:
                    ui.notify("関係性を入力してください", type="warning")
                    return
                upsert_relationship_draft(
                    state,
                    {
                        "id": str(item["id"]) if item else next_relationship_draft_id(state),
                        "participant_a_key": first_key,
                        "participant_b_key": second_key,
                        "description": description,
                    },
                )
                dlg.close()
                _refresh_relationships()

            with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                p3_button("キャンセル", dlg.close, classes="btn quiet")
                p3_button("保存", _save, classes="btn primary").mark("ui2-group-rel-save")
        dlg.open()

    async def _generate_relationships() -> None:
        if len(_relationship_participants()) < 2:
            ui.notify("関係性を自動設定できる参加者が足りません", type="warning")
            return
        if not _profile_id():
            ui.notify("補完用LLMプロファイルを選択してください", type="warning")
            return
        busy.begin("関係性を自動設定しています...")
        try:
            generated = await run_assist(
                ctx.group_chat_assist.generate_relationship_drafts(
                    profile_id=_profile_id(),
                    vault_password=get_vault_password(),
                    characters=[_display_sheet(sheet) for sheet in selected["characters"]],
                    persona=_selected_persona(),
                    world=_current_world_text(),
                    state=state,
                    on_job_started=busy.set_job,
                ),
                failure_message="関係性自動設定に失敗しました",
            )
        finally:
            busy.end()
        if generated is None:
            return
        generated = list(generated or [])
        if not generated:
            ui.notify("関係性を自動設定できませんでした", type="warning")
            return
        for draft in generated:
            draft["id"] = next_relationship_draft_id(state)
        merge_relationship_drafts(state, generated)
        _refresh_relationships()

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

        relationships = [
            GroupRelationship(
                id=str(item["id"]),
                participant_a_key=str(item["participant_a_key"]),
                participant_b_key=str(item["participant_b_key"]),
                description=str(item["description"]),
            )
            for item in state["relationships"]
        ]
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
            relationships=relationships,
        )
        ui.notify(f"グループ「{group.name}」を作成しました", type="positive")
        ui.navigate.to(f"/groups/{group.id}")

    _refresh_picks()
    _refresh_persona_row()
    _sync_world_option()
