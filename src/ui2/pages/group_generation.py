"""
/groups/{group_id}/generation グループ内キャラクター生成(Phase 5)。

グローバル生成(pages/generation.py)と同じフロー構成の箱庭版。

- ワールドはグループ固定(`group_world` + `omit_group_sections=True`)
- フォーム下にフェーズ進捗(ForgeStrip)。完成したら:
  新規/関連 → ハンドル自動生成+`add_generated_member`(関連は関係性も
  自動生成・確認なし)→ 住人シートへ直行(確認バーを一度だけ表示)、
  修正 → 暫定住人シート(/groups/{gid}/generation/review/{job_id})で差分確認
- メンバー詳細からの送出プロトコル `group_gen_mode` / `group_gen_member_ids` を
  旧UIと共有
- 復帰: `ui2_active_generation`(scope "group:{gid}")の実行中ジョブのみ拾う
"""

from __future__ import annotations

import asyncio
import html
from typing import Any

from nicegui import app, ui

from ...app_context import get_context
from ...core.character.markdown import base_character_markdown, parse_markdown_to_sheet
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
from ..generation_ui import (
    GEN_CONFIRM_KEY,
    GENERATION_CSS,
    ForgeStrip,
    open_sheet_dialog,
    recall_active_generation,
    remember_active_generation,
    render_sheet_sections,
)
from ..group_setup import (
    chip_button,
    default_profile_id,
    p3_button,
    profile_options_for_context,
    run_assist,
)
from ..scaffold import p3_page

_DIALOG_CARD_STYLE = "background: var(--panel); color: var(--text);"

_PAGE_CSS = """
.ghead { display: flex; align-items: center; gap: 12px; margin-bottom: 18px; flex-wrap: wrap; }
.ghead .t { min-width: 0; }
.ghead h1 { margin: 0; font-size: 21px; letter-spacing: .12em; font-weight: 600; }
.ghead .g-sub { font-size: 12px; color: var(--muted); letter-spacing: .05em; }
.world-box {
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  padding: 12px 4px 14px;
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


@ui.page("/groups/{group_id}/generation")
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
                    p3_button("グループ一覧へ", lambda: ui.navigate.to("/groups"))
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
                back.on("click", lambda: ui.navigate.to(f"/groups/{group.id}"))
                with ui.element("div").classes("t"):
                    with ui.element("h1").classes("serif"):
                        ui.html("グループ内キャラクター生成")
                    with ui.element("div").classes("g-sub"):
                        ui.html(html.escape(group.name))

            if not group.world.strip():
                with ui.element("section").classes("ask"):
                    with ui.element("div").classes("sub"):
                        ui.html("グループのワールドが未設定です。先に箱庭の「管理」でワールドを設定してください。")
                    with ui.element("div").classes("go"):
                        p3_button("グループに戻る", lambda: ui.navigate.to(f"/groups/{group.id}"))
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
                    ui.html("固定ワールド")
                with ui.element("div").classes("wtext"):
                    ui.html(html.escape(group.world))

            ask = ui.element("section").classes("ask")

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
            "modify_member": None,
            "related_members": [],
        }
        watching = {"id": ""}
        starting = {"flag": False}
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
                start_btn = p3_button("生成する", lambda: _on_generate(), classes="btn primary").mark(
                    "ui2-ggen-start"
                )
            strip_box = ui.element("div").classes("gen-strip")
            strip_box.set_visibility(False)

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

        # ---------------- 生成進捗(フォーム下) ----------------

        async def _on_stop() -> None:
            if watching["id"]:
                ctx.generation.stop(str(watching["id"]))

        def _hide_strip() -> None:
            strip_box.set_visibility(False)

        forge_strip = ForgeStrip(_on_stop, _hide_strip)
        with strip_box:
            forge_strip.build()

        def _set_running(running: bool) -> None:
            if running:
                start_btn.props("disabled")
            else:
                start_btn.props(remove="disabled")

        # ---------------- 完成時の自動追加(新規/関連) ----------------

        def _go_member_sheet(member_id: str, job_id: str) -> None:
            app.storage.user[GEN_CONFIRM_KEY] = {"char_id": member_id, "job_id": job_id}
            ui.navigate.to(f"/groups/{group.id}/members/{member_id}")

        async def _auto_handle(draft_sheet: CharacterSheet) -> str:
            """ハンドルをLLMで自動生成する(作成フローの一括生成と同じ)。失敗時は名前由来。"""
            fallback = _default_generated_handle(draft_sheet, group)
            persona = group.user_persona
            if persona is None:
                return fallback
            suggested = await run_assist(
                ctx.group_chat_assist.generate_handles(
                    profile_id=str(profile_select.value or ""),
                    vault_password=get_vault_password(),
                    characters=[draft_sheet],
                    persona=persona,
                ),
                failure_message="ハンドルの自動生成に失敗したため、名前から自動設定しました",
            )
            candidate = str(dict(suggested or {}).get(draft_sheet.id) or "")
            if not candidate:
                return fallback
            used = {member.handle.lower() for member in group.members}
            if persona.handle:
                used.add(persona.handle.lower())
            return unique_handle(sanitize_handle(candidate, fallback), used)

        async def _auto_add_member(job: GenerationJob, result) -> None:
            """ハンドル自動生成+住人追加。関連生成は関係性も自動生成する(確認なし)。"""
            sanitized = sanitize_group_generated_markdown(result.sheet_markdown)
            draft_sheet = _generated_sheet_from_result(sanitized, ctx.characters.new_id(), job, result)
            handle = await _auto_handle(draft_sheet)
            saved_member = await ctx.group_chats.add_generated_member(group.id, draft_sheet, handle)
            if saved_member is None:
                ui.notify("この世界の住人として保存できませんでした", type="negative")
                return
            base_members: list[GroupMember] = list(current.get("related_members") or [])
            if job.request.mode == GenerationMode.RELATED and base_members:
                ui.notify("関係性を設定しています...", type="info")
                drafts = await run_assist(
                    ctx.group_chat_assist.generate_group_generation_relationship_drafts(
                        profile_id=str(profile_select.value or ""),
                        vault_password=get_vault_password(),
                        group=group,
                        generated_sheet=draft_sheet,
                        base_members=base_members,
                    ),
                    failure_message="関係性の自動生成に失敗しました。箱庭の「管理」から追加できます",
                )
                parsed = dict(drafts or {})
                for base_member in base_members:
                    description = str(parsed.get(base_member.id) or "").strip()
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
            _go_member_sheet(saved_member.id, job.id)

        # ---------------- ジョブ実行・復帰 ----------------

        def _prepare_job_view(job: GenerationJob) -> None:
            current.update({"modify_member": None, "related_members": []})
            base_member = member_by_id.get(job.base_character_id)
            if job.request.mode == GenerationMode.MODIFY and base_member is not None:
                current["modify_member"] = base_member
            if job.request.mode == GenerationMode.RELATED:
                # リロード復帰時もベースメンバーを request から再構成する(関係性の自動生成用)
                current["related_members"] = [
                    member_by_id[bs.id]
                    for bs in job.request.related_base_sheets
                    if bs.id in member_by_id
                ]
            if job.profile.id in profile_options:
                profile_select.set_value(job.profile.id)
            forge_strip.reset()
            strip_box.set_visibility(True)
            _set_running(True)

        async def _handle_event(job: GenerationJob, event) -> None:
            forge_strip.handle_event(event)
            if event.type == ProgressEventType.DONE:
                result = event.data
                if result and result.success:
                    if job.request.mode == GenerationMode.MODIFY:
                        ui.navigate.to(f"/groups/{group.id}/generation/review/{job.id}")
                    elif job.saved_character_id:
                        # 復帰中の再生などで既に追加済みならそのまま住人シートへ
                        _go_member_sheet(job.saved_character_id, job.id)
                    else:
                        await _auto_add_member(job, result)
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
                    try:
                        _set_running(False)
                    except RuntimeError:
                        pass

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
                if job is not None and job.is_active:
                    await _attach_to_job(job.id)

        ui.timer(0.1, _restore_active_job, once=True)
