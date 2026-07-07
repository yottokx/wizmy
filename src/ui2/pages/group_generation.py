"""
/v2/groups/{group_id}/generation グループ内キャラクター生成(Phase 5)。

グローバル生成(pages/generation.py)と同じ状態A/B/C+ForgePanel を共有した箱庭版。

- ワールドはグループ固定(`group_world` + `omit_group_sections=True`)
- 新規/関連は自動保存しない(`auto_save=False`)。完成後に「グループに追加」=
  ハンドル+関係性ドラフト確認 → `add_generated_member`(旧 _open_group_save_dialog 踏襲)
- 修正は承認 diff → `update_member_character`
- メンバー詳細からの送出プロトコル `group_gen_mode` / `group_gen_member_ids` を
  旧UIと共有
- 復帰: `ui2_active_generation`(scope "group:{gid}")のジョブのみ拾う
"""

from __future__ import annotations

import asyncio
import html
from typing import Any

from nicegui import app, ui

from ...app_context import get_context
from ...core.character.markdown import (
    base_character_markdown,
    parse_markdown_to_sheet,
    sheet_from_markdown_preserving,
)
from ...core.character.schemas import CharacterSheet, GenerationMeta
from ...core.character_generation.prompts import AGE_OPTIONS, GENDER_OPTIONS
from ...core.character_generation.schemas import (
    GenerationBaseSheet,
    GenerationMode,
    GenerationPreferences,
    GenerationRequest,
    ProgressEventType,
)
from ...core.conversation.group_setup import (
    ascii_outside_parentheses,
    fallback_handle,
    sanitize_group_generated_markdown,
    sanitize_handle,
    unique_handle,
)
from ...core.group_chat.schemas import GroupChatRecord, GroupMember, GroupRelationship
from ...services.character_generation import GenerationJob
from ...ui.state import get_vault_password
from ..components.portrait import face_crop_style
from ..components.sparkle import sparkle_field
from ..generation_logic import build_generation_log, fact_chips
from ..generation_ui import (
    GENERATION_CSS,
    ForgePanel,
    open_modify_approve_dialog,
    open_sheet_dialog,
    recall_active_generation,
    remember_active_generation,
    render_born,
    render_sheet_sections,
)
from ..group_logic import HANDLE_RE
from ..group_setup import (
    chip_button,
    default_profile_id,
    p3_button,
    profile_options_for_context,
    run_assist,
)
from ..scaffold import p3_page
from ..sheet_logic import strip_outer_quotes

_DIALOG_CARD_STYLE = "background: var(--panel); color: var(--text);"

_PAGE_CSS = """
.ghead { display: flex; align-items: center; gap: 12px; margin-bottom: 18px; flex-wrap: wrap; }
.ghead .t { min-width: 0; }
.ghead h1 { margin: 0; font-size: 21px; letter-spacing: .12em; font-weight: 600; }
.ghead .g-sub { font-size: 12px; color: var(--muted); letter-spacing: .05em; }
.world-box {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 14px 18px;
  margin-bottom: 18px;
}
.world-box .lbl { font-size: 10.5px; letter-spacing: .3em; color: var(--muted); margin-bottom: 6px; }
.world-box .wtext {
  font-size: 13px; line-height: 1.9; color: var(--text);
  max-height: 96px; overflow-y: auto; white-space: pre-wrap;
}
.member-chips { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; justify-content: center; }
"""

_MODE_LABELS: list[tuple[str, str]] = [
    ("new", "新規生成"),
    ("modify", "住人を修正"),
    ("related", "知りあいを生成"),
]


def _member_label(member: GroupMember) -> str:
    return f"{member.character.name or '名称未設定'} (@{member.handle})"


def _member_base_markdown(member: GroupMember) -> str:
    return sanitize_group_generated_markdown(base_character_markdown(member.character))


def _clear_group_sheet_sections(sheet: CharacterSheet, markdown: str) -> CharacterSheet:
    sheet.world = ""
    sheet.relationships = []
    sheet.raw_markdown = sanitize_group_generated_markdown(markdown)
    return sheet


def _generated_sheet_from_result(markdown: str, sheet_id: str, job: GenerationJob, result) -> CharacterSheet:
    sanitized = sanitize_group_generated_markdown(markdown)
    sheet = parse_markdown_to_sheet(sanitized, sheet_id)
    _clear_group_sheet_sections(sheet, sanitized)
    sheet.generation_meta = _generation_meta(job, result)
    return sheet


def _generation_meta(job: GenerationJob, result) -> GenerationMeta:
    return GenerationMeta(
        llm_profile_name=job.profile.name,
        model_id=job.profile.model_id,
        temperature=job.profile.temperature if not job.profile.reasoning_enabled else None,
        reasoning_enabled=job.profile.reasoning_enabled,
        mode=result.mode.value,
        tool_count=result.tool_count,
        quality_status=result.quality_status,
        quality_score=result.quality_score,
    )


def _default_generated_handle(sheet: CharacterSheet, group: GroupChatRecord) -> str:
    used = {member.handle.lower() for member in group.members}
    if group.user_persona is not None and group.user_persona.handle:
        used.add(group.user_persona.handle.lower())
    fallback = fallback_handle(sheet, len(group.members) + 1)
    candidate = ascii_outside_parentheses(sheet.name) or fallback
    return unique_handle(sanitize_handle(candidate, fallback), used)


@ui.page("/v2/groups/{group_id}/generation")
async def ui2_group_generation_page(group_id: str) -> None:
    ctx = get_context()
    group = await ctx.group_chats.get(group_id)

    preset_mode = str(app.storage.user.pop("group_gen_mode", "") or "")
    raw_preset_ids = app.storage.user.pop("group_gen_member_ids", [])
    if isinstance(raw_preset_ids, str):
        preset_member_ids = [item for item in raw_preset_ids.split(",") if item]
    else:
        preset_member_ids = [str(item) for item in raw_preset_ids or []]

    if group is None:
        with p3_page("グループ"):
            with ui.element("div").style("max-width: 640px; margin: 0 auto; padding: 60px 26px;"):
                ui.label("指定されたグループは存在しません。").classes("note").style("font-size: 14px;")
                with ui.element("div").style("margin-top: 18px;"):
                    p3_button("グループ一覧へ", lambda: ui.navigate.to("/v2/groups"))
        return

    profile_options = profile_options_for_context(ctx)
    option_lists = ctx.api_config.get_option_lists()
    gender_opts = option_lists.get("gender", GENDER_OPTIONS)
    age_opts = option_lists.get("age", AGE_OPTIONS)
    member_by_id = {member.id: member for member in group.members}
    member_options = {member.id: _member_label(member) for member in group.members}
    if preset_mode not in {"modify", "related"}:
        preset_mode = ""

    with p3_page("グループ"):
        ui.add_css(GENERATION_CSS + _PAGE_CSS)
        with ui.element("div").classes("gen-wrap"):
            with ui.element("div").classes("ghead"):
                back = ui.element("button").classes("btn quiet")
                with back:
                    ui.html("← 箱庭へ")
                back.on("click", lambda: ui.navigate.to(f"/v2/groups/{group.id}"))
                with ui.element("div").classes("t"):
                    with ui.element("h1").classes("serif"):
                        ui.html("この世界で、あたらしい住人を")
                    with ui.element("div").classes("g-sub"):
                        ui.html(html.escape(group.name))

            if not group.world.strip():
                with ui.element("section").classes("ask"):
                    with ui.element("div").classes("sub"):
                        ui.html("グループのワールドが未設定です。先に箱庭の「管理」でワールドを設定してください。")
                    with ui.element("div").classes("go"):
                        p3_button("グループに戻る", lambda: ui.navigate.to(f"/v2/groups/{group.id}"))
                return

            if not profile_options:
                with ui.element("section").classes("ask"):
                    with ui.element("div").classes("sub"):
                        ui.html("LLMプロファイルが未設定です。先に設定を行ってください。")
                    with ui.element("div").classes("go"):
                        p3_button("設定ページへ", lambda: ui.navigate.to("/settings"))
                return

            with ui.element("div").classes("world-box"):
                with ui.element("div").classes("lbl"):
                    ui.html("固 定 ワ ー ル ド")
                with ui.element("div").classes("wtext"):
                    ui.html(html.escape(group.world))

            ask = ui.element("section").classes("ask")
            forge = ui.element("section").classes("forge")
            born = ui.element("section").classes("born")
            forge.set_visibility(False)
            born.set_visibility(False)

        # ---------------- 状態 ----------------
        view = {"mode": preset_mode or "new"}
        default_modify_id = (
            preset_member_ids[0]
            if preset_member_ids and preset_member_ids[0] in member_options
            else next(iter(member_options), "")
        )
        selection = {
            "modify_id": default_modify_id,
            "related_ids": {mid for mid in preset_member_ids if mid in member_options}
            or ({group.members[0].id} if group.members else set()),
        }
        fields: dict[str, Any] = {}
        current: dict = {
            "job_id": "",
            "request": None,
            "profile": None,
            "result": None,
            "sheet": "",
            "saved_name": "",
            "saved_member_id": "",
            "modify_member": None,
            "related_members": [],
        }
        watching = {"id": ""}
        starting = {"flag": False}
        prompted_review: set[str] = set()
        scope = f"group:{group.id}"

        # ---------------- 状態A: 入力 ----------------
        with ask:
            sparkle_field(16)
            with ui.element("h1").classes("serif"):
                ui.html("どんな住人を迎えますか。")
            with ui.element("div").classes("sub"):
                ui.html("ワールドはこの世界に固定されます。ひとことで構いません")
            modes_row = ui.element("div").classes("modes")
            form_box = ui.element("div").classes("form-box")
            with ui.element("div").classes("gen-quiet gen-profile-row"):
                ui.html("モデル").classes("note")
                profile_select = (
                    ui.select(
                        options=profile_options,
                        value=group.completion_profile_id
                        if group.completion_profile_id in profile_options
                        else default_profile_id(ctx, profile_options),
                    )
                    .props("outlined dense options-dense")
                    .classes("gen-select")
                    .mark("ui2-ggen-profile")
                )
            with ui.element("div").classes("go"):
                p3_button("生成する", lambda: _on_generate(), classes="btn primary").mark("ui2-ggen-start")

        mode_chips: dict[str, ui.element] = {}
        with modes_row:
            for mode_key, label in _MODE_LABELS:
                chip = chip_button(label, lambda k=mode_key: _set_mode(k))
                chip.mark(f"ui2-ggen-mode-{mode_key}")
                mode_chips[mode_key] = chip

        def _sync_mode_chips() -> None:
            for mode_key, chip in mode_chips.items():
                if mode_key == view["mode"]:
                    chip.classes("on")
                else:
                    chip.classes(remove="on")

        def _set_mode(mode_key: str) -> None:
            view["mode"] = mode_key
            _sync_mode_chips()
            _render_form()

        def _member_face(member: GroupMember) -> None:
            face = ui.element("div").classes("b-face")
            style = face_crop_style(member.character.media.primary_image())
            if style:
                face.style(style)
            else:
                with face:
                    ui.html(html.escape((member.character.name or "?")[:1]))

        def _render_form() -> None:
            form_box.clear()
            fields.clear()
            mode_key = view["mode"]
            with form_box:
                if mode_key == "new":
                    fields["name"] = (
                        ui.input(label="名前指定（任意）").classes("p3-ta").props("outlined dense")
                    )
                    with ui.element("div").classes("gen-quiet"):
                        fields["gender"] = (
                            ui.select(options=gender_opts, value=gender_opts[0] if gender_opts else "おまかせ", label="性別")
                            .props("outlined dense options-dense")
                            .classes("gen-select")
                        )
                        fields["age"] = (
                            ui.select(options=age_opts, value=age_opts[0] if age_opts else "おまかせ", label="年齢帯")
                            .props("outlined dense options-dense")
                            .classes("gen-select")
                        )
                    fields["extra"] = (
                        ui.textarea(
                            label="その他の要望（任意）",
                            placeholder="例）星図の修復を生業にしている、もの静かな職人。",
                        )
                        .classes("p3-ta")
                        .props("outlined rows=3 spellcheck=false")
                    )

                elif mode_key == "modify":
                    if not group.members:
                        with ui.element("div").classes("sub"):
                            ui.html("この世界にはまだ住人がいません。")
                        return
                    member = member_by_id.get(str(selection["modify_id"]) or "")
                    with ui.element("div").classes("base-box"):
                        if member is not None:
                            _member_face(member)
                        with ui.element("div").classes("b-name"):
                            ui.html(
                                html.escape(_member_label(member) if member else "未選択")
                                + '<span class="b-sub">修正ベース(この世界のコピー)</span>'
                            )
                        if member is not None:
                            chip_button(
                                "シートを確認",
                                lambda m=member: open_sheet_dialog(
                                    _member_base_markdown(m), title=m.character.name
                                ),
                            )
                    select = (
                        ui.select(
                            options=member_options,
                            value=selection["modify_id"] if selection["modify_id"] in member_options else None,
                            label="修正ベース",
                        )
                        .props("outlined dense options-dense")
                        .classes("p3-ta")
                        .mark("ui2-ggen-modify-base")
                    )

                    def _on_base_change(e) -> None:
                        selection["modify_id"] = str(e.value or "")
                        _render_form()

                    select.on_value_change(_on_base_change)
                    fields["modify_request"] = (
                        ui.textarea(label="修正の要望", placeholder="例: 口調をやわらかくしてほしい")
                        .classes("p3-ta")
                        .props("outlined rows=4 spellcheck=false")
                        .mark("ui2-ggen-modify-request")
                    )

                else:  # related
                    if not group.members:
                        with ui.element("div").classes("sub"):
                            ui.html("この世界にはまだ住人がいません。")
                        return
                    with ui.element("div").classes("sub"):
                        ui.html("ベースにする住人(複数可)")
                    with ui.element("div").classes("member-chips"):
                        for member in group.members:
                            chip = chip_button(
                                _member_label(member),
                                lambda mid=member.id: _toggle_related(mid),
                            )
                            if member.id in selection["related_ids"]:
                                chip.classes("on")
                    selected = [member_by_id[mid] for mid in selection["related_ids"] if mid in member_by_id]
                    if selected:
                        with ui.element("div").style("text-align: center; margin-bottom: 12px;"):
                            chip_button(
                                "ベースのシートを確認",
                                lambda: _open_base_sheets_dialog(selected),
                            )
                    fields["name"] = (
                        ui.input(label="新キャラクターの名前（任意）").classes("p3-ta").props("outlined dense")
                    )
                    with ui.element("div").classes("gen-quiet"):
                        fields["gender"] = (
                            ui.select(options=gender_opts, value=gender_opts[0] if gender_opts else "おまかせ", label="性別")
                            .props("outlined dense options-dense")
                            .classes("gen-select")
                        )
                        fields["age"] = (
                            ui.select(options=age_opts, value=age_opts[0] if age_opts else "おまかせ", label="年齢帯")
                            .props("outlined dense options-dense")
                            .classes("gen-select")
                        )
                    fields["extra"] = (
                        ui.textarea(label="その他の要望（任意）")
                        .classes("p3-ta")
                        .props("outlined rows=2 spellcheck=false")
                    )

        def _toggle_related(member_id: str) -> None:
            ids: set[str] = selection["related_ids"]
            if member_id in ids:
                ids.discard(member_id)
            else:
                ids.add(member_id)
            _render_form()

        def _open_base_sheets_dialog(members: list[GroupMember]) -> None:
            with ui.dialog() as dlg, ui.card().classes("w-full max-w-3xl").style(_DIALOG_CARD_STYLE):
                ui.label("ベースメンバーのシート").classes("text-base font-semibold mb-2")
                for member in members:
                    ui.label(_member_label(member)).classes("text-sm font-semibold mt-2")
                    render_sheet_sections(_member_base_markdown(member))
                with ui.row().classes("justify-end mt-3 w-full"):
                    p3_button("閉じる", dlg.close, classes="btn quiet")
            dlg.open()

        _sync_mode_chips()
        _render_form()

        # ---------------- 状態B: 生成中 ----------------

        async def _on_stop() -> None:
            if current["job_id"]:
                ctx.generation.stop(str(current["job_id"]))

        def _back_to_ask() -> None:
            forge.set_visibility(False)
            born.set_visibility(False)
            ask.set_visibility(True)

        forge_panel = ForgePanel(_on_stop, _back_to_ask)
        with forge:
            forge_panel.build()

        # ---------------- 保存(グループに追加) ----------------

        async def _relationship_drafts(
            draft_sheet: CharacterSheet, base_members: list[GroupMember]
        ) -> dict[str, str]:
            fallback = {
                member.id: (
                    f"{draft_sheet.name or '新規キャラクター'}と{member.character.name}の関係性を入力してください。"
                )
                for member in base_members
            }
            if not base_members:
                return {}
            value = await run_assist(
                ctx.group_chat_assist.generate_group_generation_relationship_drafts(
                    profile_id=str(profile_select.value or ""),
                    vault_password=get_vault_password(),
                    group=group,
                    generated_sheet=draft_sheet,
                    base_members=base_members,
                ),
                failure_message="関係性の自動生成に失敗しました。手入力で保存できます",
            )
            if value is None:
                return fallback
            parsed = dict(value or {})
            return {member.id: parsed.get(member.id) or fallback[member.id] for member in base_members}

        async def _open_group_save_dialog(job: GenerationJob, result) -> None:
            sanitized = sanitize_group_generated_markdown(str(current.get("sheet") or result.sheet_markdown))
            draft_sheet = _generated_sheet_from_result(sanitized, ctx.characters.new_id(), job, result)
            base_members: list[GroupMember] = list(current.get("related_members") or [])
            relationship_drafts: dict[str, str] = {}
            if job.request.mode == GenerationMode.RELATED and base_members:
                ui.notify("関係性説明を生成しています...", type="info")
                relationship_drafts = await _relationship_drafts(draft_sheet, base_members)

            with ui.dialog() as dlg, ui.card().classes("w-full max-w-3xl").style(_DIALOG_CARD_STYLE):
                ui.label("保存内容の確認").classes("text-base font-semibold")
                ui.label("ハンドルと関係性を確認してから、この世界の住人として保存します。").classes("note")
                handle_input = (
                    ui.input(
                        "ハンドル（メンション用・3〜12文字の英数字_）",
                        value=_default_generated_handle(draft_sheet, group),
                    )
                    .props("outlined dense")
                    .classes("w-full p3-ta")
                    .mark("ui2-ggen-handle")
                )

                relationship_inputs: dict[str, Any] = {}
                if job.request.mode == GenerationMode.RELATED and base_members:
                    ui.label("ベースメンバーとの関係性").classes("text-sm font-semibold mt-2")
                    for member in base_members:
                        relationship_inputs[member.id] = (
                            ui.textarea(
                                _member_label(member),
                                value=relationship_drafts.get(member.id, ""),
                            )
                            .props("outlined rows=3")
                            .classes("w-full p3-ta")
                        )

                chip_button("生成シートを確認", lambda: open_sheet_dialog(sanitized, title=draft_sheet.name))

                async def _save() -> None:
                    handle = str(handle_input.value or "").strip()
                    if not HANDLE_RE.fullmatch(handle):
                        ui.notify("ハンドルは3〜12文字の英数字または_で入力してください", type="warning")
                        return
                    used = {member.handle.lower() for member in group.members}
                    if group.user_persona is not None and group.user_persona.handle:
                        used.add(group.user_persona.handle.lower())
                    if handle.lower() in used:
                        ui.notify("ハンドルが重複しています", type="warning")
                        return
                    for member_id, textarea in relationship_inputs.items():
                        if not str(textarea.value or "").strip():
                            member = member_by_id.get(member_id)
                            ui.notify(
                                f"{member.character.name if member else 'ベースメンバー'}との関係性を入力してください",
                                type="warning",
                            )
                            return

                    sheet_to_save = _generated_sheet_from_result(sanitized, draft_sheet.id, job, result)
                    saved_member = await ctx.group_chats.add_generated_member(group.id, sheet_to_save, handle)
                    if saved_member is None:
                        ui.notify("この世界の住人として保存できませんでした", type="negative")
                        return
                    for base_member in base_members:
                        textarea = relationship_inputs.get(base_member.id)
                        description = str(textarea.value or "").strip() if textarea else ""
                        if description:
                            await ctx.group_chats.save_relationship(
                                group.id,
                                GroupRelationship(
                                    id="",
                                    participant_a_key=f"member:{saved_member.id}",
                                    participant_b_key=f"member:{base_member.id}",
                                    description=description,
                                ),
                            )
                    ctx.generation.mark_job_saved(job.id, saved_member.id, saved_member.character.name)
                    dlg.close()
                    ui.notify("この世界の住人として保存しました", type="positive")
                    ui.navigate.to(f"/v2/groups/{group.id}/members/{saved_member.id}")

                with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                    p3_button("キャンセル", dlg.close, classes="btn quiet")
                    p3_button("保存", _save, classes="btn primary").mark("ui2-ggen-save")
            dlg.open()

        # ---------------- 修正承認 diff ----------------

        async def _open_modify_review(job: GenerationJob, result, *, force: bool = False) -> None:
            if current.get("saved_member_id"):
                return
            if not force and job.id in prompted_review:
                return
            base_member = current.get("modify_member")
            if not isinstance(base_member, GroupMember):
                base_member = member_by_id.get(job.base_character_id)
            if not isinstance(base_member, GroupMember):
                ui.notify("修正元メンバーを復元できないため、承認ダイアログを開けません。", type="warning")
                return
            prompted_review.add(job.id)
            sanitized = sanitize_group_generated_markdown(result.sheet_markdown)

            async def _save_approved() -> None:
                updated = sheet_from_markdown_preserving(base_member.character, sanitized)
                _clear_group_sheet_sections(updated, sanitized)
                updated.generation_meta = _generation_meta(job, result)
                try:
                    saved = await ctx.group_chats.update_member_character(group.id, base_member.id, updated)
                except Exception as err:
                    ui.notify(f"保存に失敗しました: {err}", type="negative")
                    return
                if saved is None:
                    ui.notify("グループ内キャラクターが見つかりませんでした", type="negative")
                    return
                ctx.generation.mark_job_saved(job.id, saved.id, saved.character.name)
                current["saved_member_id"] = saved.id
                current["saved_name"] = saved.character.name
                ui.notify(f"「{saved.character.name}」を上書き保存しました", type="positive")
                _render_born_result(job, result)

            open_modify_approve_dialog(
                name=base_member.character.name,
                old_markdown=_member_base_markdown(base_member),
                new_markdown=sanitized,
                on_approve=_save_approved,
            )

        # ---------------- 状態C: 誕生 ----------------

        def _download_sheet() -> None:
            sheet_md = str(current.get("sheet") or "")
            if sheet_md:
                ui.download(sheet_md.encode("utf-8"), "group_character_sheet.md")

        def _download_log() -> None:
            result = current.get("result")
            if not result:
                return
            mode_value = getattr(getattr(current.get("request"), "mode", None), "value", "generate")
            ui.download(
                build_generation_log(
                    result,
                    mode_value,
                    str(current.get("sheet") or ""),
                    current.get("request"),
                    current.get("profile"),
                ).encode("utf-8"),
                "group_generation_log.txt",
            )

        async def _retake() -> None:
            request = current.get("request")
            if request is None:
                return
            base_member = current.get("modify_member")
            base_id = base_member.id if isinstance(base_member, GroupMember) else ""
            if not base_id:
                related = current.get("related_members") or []
                base_id = related[0].id if related else ""
            await _start_job(request, base_id)

        def _render_born_result(job: GenerationJob, result) -> None:
            sheet_md = sanitize_group_generated_markdown(str(current.get("sheet") or result.sheet_markdown))
            preview = parse_markdown_to_sheet(sheet_md, "preview")
            oc = preview.occupation
            if preview.age:
                oc = f"{oc} ・ {preview.age}" if oc else preview.age
            facts = fact_chips(
                world=group.world,
                occupation=preview.occupation,
                age=preview.age,
                voice_image=preview.voice_image,
                quality_status=result.quality_status,
            )
            is_modify = job.request.mode == GenerationMode.MODIFY
            saved_member_id = str(current.get("saved_member_id") or "")
            saved_name = str(current.get("saved_name") or "")
            if saved_member_id:
                save_note = f"{'更新済み' if is_modify else '保存済み'}: {saved_name}"
            elif is_modify:
                save_note = "まだ上書きしていません(差分を確認して上書きできます)"
            else:
                save_note = "まだ保存されていません(ハンドルと関係性を確認して保存します)"

            def _ops() -> None:
                saved_id = str(current.get("saved_member_id") or "")
                if not saved_id:
                    if is_modify:
                        p3_button(
                            "差分を確認して上書き",
                            lambda: _open_modify_review(job, result, force=True),
                            classes="btn primary",
                        ).mark("ui2-ggen-open-diff")
                    else:
                        p3_button(
                            "グループに追加",
                            lambda: _open_group_save_dialog(job, result),
                            classes="btn primary",
                        ).mark("ui2-ggen-add")
                else:
                    p3_button(
                        "住人シートを開く",
                        lambda: ui.navigate.to(f"/v2/groups/{group.id}/members/{saved_id}"),
                        classes="btn primary",
                    )
                    p3_button("箱庭へ戻る", lambda: ui.navigate.to(f"/v2/groups/{group.id}"))
                p3_button("リテイク", _retake, classes="btn quiet", title="同じ指示でもう一度生成する")
                p3_button("全文を表示", lambda: open_sheet_dialog(sheet_md), classes="btn quiet").mark(
                    "ui2-ggen-full-sheet"
                )
                p3_button("書き出し(.md)", _download_sheet, classes="btn quiet")
                p3_button("詳細ログ", _download_log, classes="btn quiet")
                p3_button("新しく作る", lambda: _back_to_ask(), classes="btn quiet")

            render_born(
                born,
                name=preview.name,
                oc=oc,
                intro=strip_outer_quotes(preview.self_intro),
                facts=facts,
                save_note=save_note,
                save_note_error=False,
                build_ops=_ops,
            )
            forge.set_visibility(False)
            born.set_visibility(True)

        # ---------------- ジョブ実行・復帰 ----------------

        def _prepare_job_view(job: GenerationJob) -> None:
            current.update(
                {
                    "job_id": job.id,
                    "request": job.request,
                    "profile": job.profile,
                    "result": None,
                    "sheet": "",
                    "saved_name": "",
                    "saved_member_id": "",
                }
            )
            base_member = member_by_id.get(job.base_character_id)
            if job.request.mode == GenerationMode.MODIFY and base_member is not None:
                current["modify_member"] = base_member
            if job.request.mode == GenerationMode.RELATED:
                # リロード復帰時もベースメンバーを request から再構成する(関係性ドラフト用)
                current["related_members"] = [
                    member_by_id[bs.id]
                    for bs in job.request.related_base_sheets
                    if bs.id in member_by_id
                ]
            if job.profile.id in profile_options:
                profile_select.set_value(job.profile.id)
            forge_panel.reset()
            ask.set_visibility(False)
            born.set_visibility(False)
            forge.set_visibility(True)

        async def _handle_event(job: GenerationJob, event) -> None:
            forge_panel.handle_event(event)
            if event.type == ProgressEventType.SHEET_READY:
                current["sheet"] = sanitize_group_generated_markdown(str(event.data or ""))
            elif event.type == ProgressEventType.DONE:
                result = event.data
                if result and result.success:
                    sanitized = sanitize_group_generated_markdown(result.sheet_markdown)
                    result.sheet_markdown = sanitized
                    job.sheet_markdown = sanitized
                    current["result"] = result
                    current["sheet"] = sanitized
                    if job.request.mode == GenerationMode.MODIFY:
                        if job.saved_character_id:
                            current["saved_member_id"] = job.saved_character_id
                            current["saved_name"] = job.saved_character_name
                        _render_born_result(job, result)
                        if not current.get("saved_member_id"):
                            await _open_modify_review(job, result)
                    else:
                        if job.saved_character_id:
                            current["saved_member_id"] = job.saved_character_id
                            current["saved_name"] = job.saved_character_name
                        _render_born_result(job, result)
                elif result:
                    ui.notify(result.error_message or "生成に失敗しました。", type="negative")
            elif event.type == ProgressEventType.ERROR:
                ui.notify(str(event.data), type="negative", timeout=8000)

        async def _attach_to_job(job_id: str) -> None:
            if watching["id"] == job_id:
                return
            job = ctx.generation.get_job(job_id)
            if not job:
                return
            watching["id"] = job_id
            remember_active_generation(job.id, scope)
            _prepare_job_view(job)
            try:
                async for event in ctx.generation.stream_events(job.id):
                    await _handle_event(job, event)
                    await asyncio.sleep(0)
            except RuntimeError:
                pass
            finally:
                if watching["id"] == job.id:
                    watching["id"] = ""

        async def _start_job(request: GenerationRequest, base_character_id: str) -> None:
            profile = ctx.api_config.get_llm_profile(str(profile_select.value or ""))
            if not profile:
                ui.notify("LLMプロファイルが見つかりません", type="negative")
                return
            if not profile.model_id:
                ui.notify(
                    "モデルIDが未設定です。設定画面でLLMプロファイルのモデルを設定してください。",
                    type="negative",
                    timeout=8000,
                )
                return
            endpoint = ctx.api_config.get_endpoint(profile.endpoint_id)
            if not endpoint:
                ui.notify("エンドポイントが見つかりません", type="negative")
                return
            api_key = ctx.api_config.get_api_key(profile.endpoint_id, get_vault_password())
            if ctx.api_config.is_api_key_locked(profile.endpoint_id, api_key):
                ui.notify(
                    "このエンドポイントにはAPIキーが設定されています。ボルトを解錠してください。",
                    type="warning",
                    timeout=8000,
                )
                return
            job = ctx.generation.start_job(
                request,
                profile,
                endpoint,
                api_key,
                base_character_id=base_character_id,
                auto_save=False,
            )
            await _attach_to_job(job.id)

        async def _start_generation() -> None:
            mode_key = view["mode"]
            if mode_key == "new":
                request = GenerationRequest(
                    preferences=GenerationPreferences(
                        gender=str(fields["gender"].value or "おまかせ"),
                        age=str(fields["age"].value or "おまかせ"),
                        extra=str(fields["extra"].value or ""),
                    ),
                    mode=GenerationMode.NEW,
                    new_char_name=str(fields["name"].value or "").strip(),
                    group_world=group.world,
                    omit_group_sections=True,
                )
                current["modify_member"] = None
                current["related_members"] = []
                base_id = ""
            elif mode_key == "modify":
                member = member_by_id.get(str(selection["modify_id"]) or "")
                if member is None:
                    ui.notify("修正ベースにする住人を選択してください", type="warning")
                    return
                request = GenerationRequest(
                    preferences=GenerationPreferences(),
                    mode=GenerationMode.MODIFY,
                    base_sheet=_member_base_markdown(member),
                    modify_request=str(fields["modify_request"].value or ""),
                    group_world=group.world,
                    omit_group_sections=True,
                )
                current["modify_member"] = member
                current["related_members"] = []
                base_id = member.id
            else:
                related_members = [member_by_id[mid] for mid in selection["related_ids"] if mid in member_by_id]
                if not related_members:
                    ui.notify("ベースにする住人を選択してください", type="warning")
                    return
                request = GenerationRequest(
                    preferences=GenerationPreferences(
                        gender=str(fields["gender"].value or "おまかせ"),
                        age=str(fields["age"].value or "おまかせ"),
                        extra=str(fields["extra"].value or ""),
                    ),
                    mode=GenerationMode.RELATED,
                    base_sheet=_member_base_markdown(related_members[0]),
                    new_char_name=str(fields["name"].value or "").strip(),
                    group_world=group.world,
                    related_base_sheets=[
                        GenerationBaseSheet(
                            id=member.id,
                            name=member.character.name,
                            handle=member.handle,
                            sheet_markdown=_member_base_markdown(member),
                        )
                        for member in related_members
                    ],
                    omit_group_sections=True,
                )
                current["modify_member"] = None
                current["related_members"] = related_members
                base_id = related_members[0].id
            await _start_job(request, base_id)

        async def _on_generate() -> None:
            if starting["flag"]:
                return
            starting["flag"] = True
            try:
                await _start_generation()
            finally:
                starting["flag"] = False

        async def _restore_active_job() -> None:
            job_id, stored_scope = recall_active_generation()
            if job_id and stored_scope == scope:
                job = ctx.generation.get_job(job_id)
                if job is not None:
                    await _attach_to_job(job.id)

        ui.timer(0.1, _restore_active_job, once=True)
