"""グループチャット一覧とグループ作成 UI。"""

from __future__ import annotations

import asyncio
from typing import Any

from nicegui import app, ui

from ...app_context import get_context
from ...core.character.markdown import (
    base_character_markdown as _base_character_markdown,
)
from ...core.character.markdown import (
    parse_markdown_to_sheet,
)
from ...core.character.markdown import (
    sheet_from_markdown_preserving as _sheet_from_markdown_preserving,
)
from ...core.character.schemas import (
    CharacterSheet,
    GenerationMeta,
)
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
from ...core.group_chat.schemas import (
    GroupChatRecord,
    GroupMember,
    GroupRelationship,
)
from ...services.ai_jobs import AIJobStatus
from ...services.character_generation import (
    GenerationJob,
    GenerationJobStatus,
)
from ...services.llm_runtime import LLMRuntimeError
from ..chat.style import CHAT_CSS
from ..components.character_media import CharacterMediaActions, render_character_media_panel
from ..components.generation_result import (
    build_diff_html,
    build_generation_log,
    open_modify_approve_dialog,
    render_sheet_result,
    show_sheet_placeholder,
)
from ..components.progress_stream import ProgressPanel
from ..group_chat.common import (
    HANDLE_RE as _HANDLE_RE,
)
from ..group_chat.common import (
    default_profile_id as _default_profile_id,
)
from ..group_chat.common import (
    group_member_tts_id as _group_member_tts_id,
)
from ..group_chat.common import (
    notify_setup_llm_runtime_error as _notify_setup_llm_runtime_error,
)
from ..group_chat.common import (
    profile_options as _profile_options,
)
from ..group_chat.controller import GroupChatPageController
from ..group_chat.dialogs_group import open_new_group_dialog
from ..group_chat.rendering import (
    render_group_card as _render_group_card,
)
from ..group_chat.rendering import (
    render_recent_group as _render_recent_group,
)
from ..group_chat.rendering import (
    render_section_head as _render_section_head,
)
from ..group_chat.style import GROUP_CHAT_CSS
from ..layout import page_layout
from ..state import get_vault_password


@ui.page("/groups")
async def group_chat_page() -> None:
    ctx = get_context()

    with page_layout("グループチャット"):
        ui.add_head_html(GROUP_CHAT_CSS)
        with ui.element("div").classes("cs-group-page"):
            with ui.element("div").classes("cs-group-page-head"):
                with ui.element("div"):
                    ui.label("グループチャット").classes("cs-group-page-title")
                    ui.label("グループ一覧と最近のチャットを確認できます。").classes("cs-group-page-subtitle")
                ui.button(
                    "新しいグループ",
                    icon="group_add",
                    on_click=lambda: open_new_group_dialog(ctx, refresh_groups),
                ).props("color=primary unelevated").style("border-radius: 8px; font-weight: 700;")

            with ui.element("div").classes("cs-group-home-grid"):
                groups_container = ui.element("section")
                recent_container = ui.element("section")

            async def refresh_groups() -> None:
                groups = await ctx.group_chats.list_all()
                groups_container.clear()
                recent_container.clear()
                with groups_container:
                    _render_section_head("groups", "グループ一覧")
                    with ui.element("div").classes("cs-group-card-grid"):
                        if not groups:
                            with ui.element("div").classes("cs-group-empty"):
                                ui.label("グループはまだありません")
                        else:
                            for group in groups:
                                _render_group_card(ctx, group, refresh_groups)
                with recent_container:
                    _render_section_head("forum", "最近のチャット")
                    with ui.element("div").classes("grid gap-2"):
                        if not groups:
                            with ui.element("div").classes("cs-group-empty"):
                                ui.label("最近のチャットはまだありません")
                        else:
                            for group in groups[:5]:
                                _render_recent_group(group)

            await refresh_groups()


@ui.page("/groups/{group_id}")
async def group_chat_detail_page(group_id: str) -> None:
    ctx = get_context()
    group = await ctx.group_chats.get(group_id)
    if group is None:
        with page_layout("グループが見つかりません"):
            ui.label("指定されたグループは存在しません。").classes("text-grey-6")
            ui.button("一覧に戻る", on_click=lambda: ui.navigate.to("/groups")).props("flat color=primary")
        return

    with page_layout(group.name):
        ui.add_head_html(CHAT_CSS)
        ui.add_head_html(GROUP_CHAT_CSS)
        controller = GroupChatPageController(ctx, group, ui.context.client)
        await controller.initialize()
        controller.render_shell()


@ui.page("/groups/{group_id}/members/{member_id}")
async def group_member_detail_page(group_id: str, member_id: str) -> None:
    ctx = get_context()
    group = await ctx.group_chats.get(group_id)
    if group is None:
        with page_layout("グループが見つかりません"):
            ui.label("指定されたグループは存在しません。").classes("text-grey-6")
            ui.button("一覧に戻る", on_click=lambda: ui.navigate.to("/groups")).props("flat color=primary")
        return

    member = next((item for item in group.members if item.id == member_id), None)
    if member is None:
        with page_layout("メンバーが見つかりません"):
            ui.label("指定されたメンバーはこのグループに存在しません。").classes("text-grey-6")
            ui.button(
                "グループに戻る",
                on_click=lambda: ui.navigate.to(f"/groups/{group.id}"),
            ).props("flat color=primary")
        return

    sheet = member.character

    def _send_member_to_group_generation(mode: str) -> None:
        app.storage.user["group_gen_mode"] = mode
        app.storage.user["group_gen_member_ids"] = [member.id]
        ui.navigate.to(f"/groups/{group.id}/generation")

    with page_layout(sheet.name):
        ui.add_head_html(GROUP_CHAT_CSS)
        with ui.row().classes("items-center gap-2 mb-4 flex-wrap"):
            ui.button(
                icon="arrow_back",
                on_click=lambda: ui.navigate.to(f"/groups/{group.id}"),
            ).props("flat round")
            title_label = ui.label(sheet.name).classes("text-2xl font-bold flex-1")
            ui.badge("グループ内コピー").props("outline color=primary")
            ui.button(
                "修正生成",
                icon="edit",
                on_click=lambda: _send_member_to_group_generation("modify"),
            ).props("outline dense")
            ui.button(
                "関連キャラ生成",
                icon="person_add",
                on_click=lambda: _send_member_to_group_generation("related"),
            ).props("outline dense")
            ui.button(
                icon="download",
                on_click=lambda: ui.download(sheet.raw_markdown.encode("utf-8"), f"{sheet.name}.md"),
            ).props("flat round").tooltip("Markdownをダウンロード")
            ui.button(
                icon="content_copy",
                on_click=lambda: _copy_to_clipboard(),
            ).props("flat round").tooltip("Markdownをコピー")

        basic_container = ui.element("div").classes("w-full")
        edit_mode = {"active": False}
        view_mode = {"raw": False}
        edit_area: dict[str, Any] = {"ref": None}

        def _render_basic_info() -> None:
            basic_container.clear()
            with basic_container:
                with ui.card().classes("w-full mb-4"):
                    with ui.row().classes("gap-6 flex-wrap"):
                        for label, value in [
                            ("グループ", group.name),
                            ("ハンドル", f"@{member.handle}"),
                            *sheet.to_display_dict().items(),
                        ]:
                            if value:
                                with ui.column().classes("gap-0"):
                                    ui.label(label).classes("text-xs text-grey-6")
                                    ui.label(value).classes("text-sm font-medium")

                    if sheet.tags:
                        with ui.row().classes("gap-2 mt-3 flex-wrap"):
                            for tag in sheet.tags:
                                ui.badge(tag).props("outline color=primary")

        _render_basic_info()

        def _media_actions() -> CharacterMediaActions:
            def _apply_saved(saved_member: GroupMember | None) -> CharacterSheet:
                nonlocal member, sheet
                if saved_member is None:
                    raise ValueError("グループ内キャラクターが見つかりませんでした。")
                member = saved_member
                sheet = saved_member.character
                title_label.set_text(sheet.name)
                _render_basic_info()
                return sheet

            async def _save_image(upload: Any) -> CharacterSheet:
                return _apply_saved(await ctx.group_chats.save_member_image(group.id, member.id, upload))

            async def _save_image_bytes(image_bytes: bytes, **kwargs: Any) -> CharacterSheet:
                return _apply_saved(
                    await ctx.group_chats.save_member_image_bytes(
                        group.id,
                        member.id,
                        image_bytes,
                        **kwargs,
                    )
                )

            async def _save_voice(upload: Any) -> CharacterSheet:
                return _apply_saved(await ctx.group_chats.save_member_voice(group.id, member.id, upload))

            async def _save_voice_bytes(audio_bytes: bytes, **kwargs: Any) -> CharacterSheet:
                return _apply_saved(
                    await ctx.group_chats.save_member_voice_bytes(
                        group.id,
                        member.id,
                        audio_bytes,
                        **kwargs,
                    )
                )

            async def _update_tts_settings(settings) -> CharacterSheet:
                return _apply_saved(
                    await ctx.group_chats.update_member_tts_settings(
                        group.id,
                        member.id,
                        settings,
                    )
                )

            async def _update_face_rect(rect, **kwargs: Any) -> CharacterSheet:
                return _apply_saved(
                    await ctx.group_chats.update_member_face_rect(
                        group.id,
                        member.id,
                        rect,
                        **kwargs,
                    )
                )

            async def _update_bust_rect(rect, **kwargs: Any) -> CharacterSheet:
                return _apply_saved(
                    await ctx.group_chats.update_member_bust_rect(
                        group.id,
                        member.id,
                        rect,
                        **kwargs,
                    )
                )

            return CharacterMediaActions(
                target_id=_group_member_tts_id(group.id, member.id),
                result_url=f"/groups/{group.id}/members/{member.id}",
                scope_prefix=f"group_member:{group.id}:{member.id}",
                metadata={"group_id": group.id, "member_id": member.id},
                media_path=ctx.group_chats.media_path,
                save_image=_save_image,
                save_image_bytes=_save_image_bytes,
                save_voice=_save_voice,
                save_voice_bytes=_save_voice_bytes,
                update_tts_settings=_update_tts_settings,
                update_face_rect=_update_face_rect,
                update_bust_rect=_update_bust_rect,
                save_tts_preview=lambda audio_bytes, **kwargs: ctx.group_chats.save_member_tts_preview(
                    group.id,
                    member.id,
                    audio_bytes,
                    **kwargs,
                ),
                save_image_preview=lambda image_bytes, **kwargs: ctx.group_chats.save_member_image_preview(
                    group.id,
                    member.id,
                    image_bytes,
                    **kwargs,
                ),
                save_tts_playback=lambda audio_bytes: ctx.group_chats.save_member_tts_playback(
                    group.id,
                    member.id,
                    audio_bytes,
                ),
            )

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
                    with sheet_container:
                        ui.markdown(sheet.raw_markdown).classes("prose prose-sm max-w-none")

            media_panel = ui.column().classes("w-full lg:w-[360px] gap-4 shrink-0")

        def _refresh_media_panel() -> None:
            media_panel.clear()
            with media_panel:
                render_character_media_panel(
                    sheet,
                    ctx,
                    sheet.id,
                    _refresh_media_panel,
                    _media_actions(),
                )

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
            nonlocal member, sheet

            ta = edit_area["ref"]
            if ta is None:
                return
            new_md = str(ta.value or "").strip()
            if not new_md:
                ui.notify("シートが空です", type="warning")
                return

            updated = parse_markdown_to_sheet(new_md, sheet.id)
            updated.tags = sheet.tags
            updated.media = sheet.media
            updated.is_favorite = sheet.is_favorite
            updated.generation_meta = sheet.generation_meta
            updated.created_at = sheet.created_at
            saved_member = await ctx.group_chats.update_member_character(group.id, member.id, updated)
            if saved_member is None:
                ui.notify("グループ内キャラクターが見つかりませんでした", type="warning")
                return

            member = saved_member
            sheet = saved_member.character
            title_label.set_text(sheet.name)
            _render_basic_info()
            ui.notify(f"「{sheet.name}」を保存しました", type="positive")
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


def _group_generation_member_label(member: GroupMember) -> str:
    return f"{member.character.name or '名称未設定'} (@{member.handle})"


def _generation_base_sheet_from_member(member: GroupMember) -> GenerationBaseSheet:
    return GenerationBaseSheet(
        id=member.id,
        name=member.character.name,
        handle=member.handle,
        sheet_markdown=_base_character_markdown(member.character),
    )


def _clear_group_generated_sheet_sections(sheet: CharacterSheet, markdown: str) -> CharacterSheet:
    sheet.world = ""
    sheet.relationships = []
    sheet.raw_markdown = sanitize_group_generated_markdown(markdown)
    return sheet


def _group_generated_sheet_from_result(
    markdown: str,
    sheet_id: str,
    job: GenerationJob,
    result,
) -> CharacterSheet:
    sanitized = sanitize_group_generated_markdown(markdown)
    sheet = parse_markdown_to_sheet(sanitized, sheet_id)
    _clear_group_generated_sheet_sections(sheet, sanitized)
    sheet.generation_meta = GenerationMeta(
        llm_profile_name=job.profile.name,
        model_id=job.profile.model_id,
        temperature=job.profile.temperature if not job.profile.reasoning_enabled else None,
        reasoning_enabled=job.profile.reasoning_enabled,
        mode=result.mode.value,
        tool_count=result.tool_count,
        quality_status=result.quality_status,
        quality_score=result.quality_score,
    )
    return sheet


def _default_generated_handle(sheet: CharacterSheet, group: GroupChatRecord) -> str:
    used = {member.handle.lower() for member in group.members}
    fallback = fallback_handle(sheet, len(group.members) + 1)
    candidate = ascii_outside_parentheses(sheet.name) or fallback
    return unique_handle(sanitize_handle(candidate, fallback), used)


async def _generate_group_generation_relationship_drafts(
    ctx,
    profile_id: str,
    group: GroupChatRecord,
    generated_sheet: CharacterSheet,
    base_members: list[GroupMember],
) -> dict[str, str]:
    fallback = {
        member.id: f"{generated_sheet.name or '新規キャラクター'}と{member.character.name}の関係性を入力してください。"
        for member in base_members
    }
    if not base_members:
        return {}
    try:
        result = await ctx.group_chat_assist.generate_group_generation_relationship_drafts(
            profile_id=profile_id,
            vault_password=get_vault_password(),
            group=group,
            generated_sheet=generated_sheet,
            base_members=base_members,
        )
    except LLMRuntimeError as err:
        _notify_setup_llm_runtime_error(err)
        return fallback
    except Exception as err:
        ui.notify(f"LLMの初期化に失敗しました: {err}", type="negative", timeout=10000)
        return fallback
    if result.status != AIJobStatus.SUCCEEDED:
        ui.notify("関係性の自動生成に失敗しました。手入力で保存できます。", type="warning")
        return fallback
    parsed = dict(result.value or {})
    return {member.id: parsed.get(member.id) or fallback[member.id] for member in base_members}


@ui.page("/groups/{group_id}/generation")
async def group_generation_page(group_id: str) -> None:
    ctx = get_context()
    group = await ctx.group_chats.get(group_id)
    if group is None:
        with page_layout("グループが見つかりません"):
            ui.label("指定されたグループは存在しません。").classes("text-grey-6")
            ui.button("一覧に戻る", on_click=lambda: ui.navigate.to("/groups")).props("flat color=primary")
        return

    preset_mode = str(app.storage.user.pop("group_gen_mode", "") or "")
    raw_preset_ids = app.storage.user.pop("group_gen_member_ids", [])
    if isinstance(raw_preset_ids, str):
        preset_member_ids = [item for item in raw_preset_ids.split(",") if item]
    else:
        preset_member_ids = [str(item) for item in raw_preset_ids or []]

    member_options = {member.id: _group_generation_member_label(member) for member in group.members}
    member_by_id = {member.id: member for member in group.members}
    profile_options = _profile_options(ctx, ctx.api_config.get_llm_profiles())
    progress_panel = ProgressPanel()
    watching_job_id: dict[str, str] = {"value": ""}
    prompted_modify_review: set[str] = set()
    current_result: dict[str, Any] = {
        "gen_id": "",
        "sheet": "",
        "mode": GenerationMode.NEW,
        "request": None,
        "profile": None,
        "gen_result": None,
        "modify_member": None,
        "related_members": [],
    }

    def _member_by_id(member_id: str) -> GroupMember | None:
        return member_by_id.get(member_id)

    with page_layout(f"{group.name} - キャラクター生成"):
        ui.add_head_html(GROUP_CHAT_CSS)

        if not group.world.strip():
            with ui.element("div").classes("cs-group-empty"):
                ui.label("グループのワールドが未設定です。先にグループのワールドを設定してください。")
                ui.button(
                    "グループに戻る",
                    icon="arrow_back",
                    on_click=lambda: ui.navigate.to(f"/groups/{group.id}"),
                ).props("flat color=primary")
            return

        if not profile_options:
            with ui.element("div").classes("cs-group-empty"):
                ui.label("LLMプロファイルが未設定です。先に設定を行ってください。")
                ui.button("設定ページへ", icon="settings", on_click=lambda: ui.navigate.to("/settings")).props(
                    "flat color=primary"
                )
            return

        with ui.row().classes("w-full items-center gap-3 mb-4 flex-wrap"):
            ui.button(
                icon="arrow_back",
                on_click=lambda: ui.navigate.to(f"/groups/{group.id}"),
            ).props("flat round")
            with ui.column().classes("gap-0 flex-1 min-w-0"):
                ui.label("グループ内キャラクター生成").classes("text-2xl font-bold")
                ui.label(group.name).classes("text-sm text-grey-6")
            profile_select = (
                ui.select(
                    options=profile_options,
                    value=group.completion_profile_id
                    if group.completion_profile_id in profile_options
                    else _default_profile_id(ctx, profile_options),
                    label="LLMプロファイル",
                )
                .props("outlined dense")
                .classes("min-w-[260px]")
            )
            job_status_badge = ui.badge("").classes("hidden")
            stop_btn = ui.button("停止", icon="stop").props("outline color=negative").classes("hidden")
            generate_btn = ui.button("生成する", icon="auto_awesome").props("color=primary unelevated")

        with ui.element("div").classes("cs-group-profile-card mb-4"):
            ui.label("固定ワールド").classes("cs-group-profile-card-title")
            ui.label(group.world).classes("cs-group-profile-summary")

        age_options = ctx.api_config.get_option_lists().get("age", AGE_OPTIONS)
        gender_options = ctx.api_config.get_option_lists().get("gender", GENDER_OPTIONS)

        with ui.row().classes("w-full gap-4 flex-col lg:flex-row"):
            with ui.column().classes("w-full lg:w-80 gap-3"):
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-2 mb-3"):
                        ui.icon("tune").classes("text-primary")
                        ui.label("生成設定").classes("text-sm font-semibold")

                    TAB_NEW = "新規生成"
                    TAB_MODIFY = "修正"
                    TAB_RELATED = "関連キャラ"

                    mode_tabs = ui.tabs().classes("w-full")
                    with mode_tabs:
                        tab_new = ui.tab(TAB_NEW, icon="add_circle")
                        tab_modify = ui.tab(TAB_MODIFY, icon="edit")
                        tab_related = ui.tab(TAB_RELATED, icon="person_add")

                    def _active_tab_is(tab_obj, name: str) -> bool:
                        value = mode_tabs.value
                        return value is tab_obj or value == name

                    related_checks: dict[str, Any] = {}

                    with ui.tab_panels(mode_tabs, value=tab_new).classes("w-full"):
                        with ui.tab_panel(tab_new):
                            new_name_input = ui.input(label="名前指定（任意）").classes("w-full")
                            new_gender_select = ui.select(
                                options=gender_options,
                                value=gender_options[0] if gender_options else "おまかせ",
                                label="性別",
                            ).classes("w-full")
                            new_age_select = ui.select(
                                options=age_options,
                                value=age_options[0] if age_options else "おまかせ",
                                label="年齢帯",
                            ).classes("w-full")
                            new_extra_input = ui.textarea(label="その他の要望").classes("w-full").props("rows=4")

                        with ui.tab_panel(tab_modify):
                            if member_options:
                                default_modify_id = (
                                    preset_member_ids[0]
                                    if preset_member_ids and preset_member_ids[0] in member_options
                                    else next(iter(member_options), "")
                                )
                                modify_member_select = ui.select(
                                    options=member_options,
                                    value=default_modify_id,
                                    label="修正ベース",
                                ).classes("w-full")
                            else:
                                modify_member_select = ui.select(options={}, label="修正ベース").classes("w-full")
                                ui.label("グループ内メンバーがいません。").classes("text-sm text-grey-6")
                            modify_request_input = ui.textarea(label="修正の要望").classes("w-full").props("rows=5")

                        with ui.tab_panel(tab_related):
                            if not group.members:
                                ui.label("グループ内メンバーがいません。").classes("text-sm text-grey-6")
                            else:
                                ui.label("ベースメンバー").classes("text-sm font-semibold")
                                for member in group.members:
                                    checked = member.id in preset_member_ids
                                    if not preset_member_ids and member is group.members[0]:
                                        checked = True
                                    related_checks[member.id] = ui.checkbox(
                                        _group_generation_member_label(member),
                                        value=checked,
                                    ).classes("w-full")
                            related_name_input = ui.input(label="新キャラクターの名前（任意）").classes("w-full")
                            related_gender_select = ui.select(
                                options=gender_options,
                                value=gender_options[0] if gender_options else "おまかせ",
                                label="性別",
                            ).classes("w-full")
                            related_age_select = ui.select(
                                options=age_options,
                                value=age_options[0] if age_options else "おまかせ",
                                label="年齢帯",
                            ).classes("w-full")
                            related_extra_input = ui.textarea(label="その他の要望").classes("w-full").props("rows=3")

            with ui.column().classes("flex-1 gap-3 min-w-0"):
                base_expansion = ui.expansion("ベースメンバー確認", icon="groups", value=False).classes("w-full hidden")
                with base_expansion:
                    base_content = ui.element("div").classes("w-full max-h-[480px] overflow-y-auto")

                progress_panel.build()

                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center justify-between mb-3 flex-wrap gap-y-1"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("description").classes("text-primary")
                            ui.label("生成結果").classes("text-sm font-semibold")
                        with ui.row().classes("gap-1 items-center flex-wrap"):
                            quality_badge = ui.badge("").classes("hidden")
                            save_result_btn = (
                                ui.button(
                                    "グループに追加",
                                    icon="person_add",
                                )
                                .props("flat size=sm color=primary")
                                .classes("hidden")
                            )
                            log_download_btn = (
                                ui.button(
                                    icon="assignment_late",
                                )
                                .props("flat round dense")
                                .classes("hidden")
                                .tooltip("詳細ログをダウンロード")
                            )
                            download_btn = (
                                ui.button(
                                    icon="download",
                                )
                                .props("flat round dense")
                                .classes("hidden")
                                .tooltip("シートをダウンロード")
                            )
                    save_status_label = ui.label("").classes("text-xs hidden text-primary")
                    result_area = ui.element("div").classes("w-full max-h-[640px] overflow-y-auto")
                    show_sheet_placeholder(result_area)

        def _selected_related_members() -> list[GroupMember]:
            return [
                member
                for member in group.members
                if bool(related_checks.get(member.id) and related_checks[member.id].value)
            ]

        def _refresh_base_preview(members: list[GroupMember]) -> None:
            base_content.clear()
            if not members:
                base_expansion.set_value(False)
                base_expansion.classes("hidden")
                return
            base_expansion.classes(remove="hidden")
            base_expansion.set_value(True)
            with base_content:
                for member in members:
                    with ui.expansion(_group_generation_member_label(member), value=len(members) == 1).classes(
                        "w-full"
                    ):
                        render_sheet_result(ui.element("div"), _base_character_markdown(member.character))

        def _on_tab_change(e) -> None:
            tab_name = str(e.args) if e.args else ""
            if tab_name == TAB_MODIFY:
                member = _member_by_id(str(modify_member_select.value or ""))
                _refresh_base_preview([member] if member else [])
            elif tab_name == TAB_RELATED:
                _refresh_base_preview(_selected_related_members())
            else:
                _refresh_base_preview([])

        mode_tabs.on("update:model-value", _on_tab_change)
        if member_options:
            modify_member_select.on_value_change(
                lambda e: _refresh_base_preview([member] if (member := _member_by_id(str(e.value or ""))) else [])
            )
        for checkbox in related_checks.values():
            checkbox.on_value_change(lambda _: _refresh_base_preview(_selected_related_members()))

        if preset_mode == "modify":
            mode_tabs.set_value(TAB_MODIFY)
            member = _member_by_id(str(modify_member_select.value or ""))
            _refresh_base_preview([member] if member else [])
        elif preset_mode == "related":
            mode_tabs.set_value(TAB_RELATED)
            _refresh_base_preview(_selected_related_members())

        def _sync_job_badge(job: GenerationJob) -> None:
            labels = {
                GenerationJobStatus.QUEUED: "生成待機中",
                GenerationJobStatus.RUNNING: "生成中",
                GenerationJobStatus.COMPLETED: "完了",
                GenerationJobStatus.FAILED: "失敗",
                GenerationJobStatus.CANCELLED: "停止済み",
            }
            colors = {
                GenerationJobStatus.QUEUED: "warning",
                GenerationJobStatus.RUNNING: "primary",
                GenerationJobStatus.COMPLETED: "positive",
                GenerationJobStatus.FAILED: "negative",
                GenerationJobStatus.CANCELLED: "grey",
            }
            job_status_badge.set_text(labels.get(job.status, job.status.value))
            job_status_badge.props(remove="color")
            job_status_badge.props(f"color={colors.get(job.status, 'grey')}")
            job_status_badge.classes(remove="hidden")

        def _sync_job_controls(job: GenerationJob) -> None:
            generate_btn.set_enabled(not job.is_active)
            if job.is_active:
                stop_btn.classes(remove="hidden")
            else:
                stop_btn.classes("hidden")
            _sync_job_badge(job)

        def _prepare_job_view(job: GenerationJob) -> None:
            current_result.update(
                {
                    "gen_id": job.id,
                    "sheet": "",
                    "mode": job.request.mode,
                    "request": job.request,
                    "profile": job.profile,
                    "gen_result": None,
                }
            )
            quality_badge.classes("hidden")
            save_result_btn.classes("hidden")
            log_download_btn.classes("hidden")
            download_btn.classes("hidden")
            save_status_label.classes("hidden")
            progress_panel.reset()
            show_sheet_placeholder(result_area)
            _sync_job_controls(job)

        async def _open_group_modify_review_if_needed(job: GenerationJob, result) -> None:
            if job.id in prompted_modify_review:
                return
            base_member = current_result.get("modify_member")
            if not isinstance(base_member, GroupMember):
                base_member = _member_by_id(job.base_character_id)
            if not isinstance(base_member, GroupMember):
                ui.notify("修正元メンバーを復元できないため、承認ダイアログを開けません。", type="warning")
                return

            prompted_modify_review.add(job.id)
            sanitized = sanitize_group_generated_markdown(result.sheet_markdown)
            diff_html = build_diff_html(_base_character_markdown(base_member.character), sanitized)

            async def _save_approved() -> None:
                updated = _sheet_from_markdown_preserving(base_member.character, sanitized)
                _clear_group_generated_sheet_sections(updated, sanitized)
                updated.generation_meta = GenerationMeta(
                    llm_profile_name=job.profile.name,
                    model_id=job.profile.model_id,
                    temperature=job.profile.temperature if not job.profile.reasoning_enabled else None,
                    reasoning_enabled=job.profile.reasoning_enabled,
                    mode=result.mode.value,
                    tool_count=result.tool_count,
                    quality_status=result.quality_status,
                    quality_score=result.quality_score,
                )
                saved = await ctx.group_chats.update_member_character(group.id, base_member.id, updated)
                if saved is None:
                    raise ValueError("グループ内キャラクターが見つかりませんでした。")
                ctx.generation.mark_job_saved(job.id, saved.id, saved.character.name)
                save_status_label.set_text(f"更新済み: {saved.character.name}")
                save_status_label.classes(remove="hidden")

            await open_modify_approve_dialog(
                base_member.character.name,
                diff_html,
                _save_approved,
                save_status_label,
            )

        async def _open_group_save_dialog(job: GenerationJob, result) -> None:
            sanitized = sanitize_group_generated_markdown(current_result.get("sheet") or result.sheet_markdown)
            draft_sheet = _group_generated_sheet_from_result(
                sanitized,
                ctx.characters.new_id(),
                job,
                result,
            )
            base_members: list[GroupMember] = list(current_result.get("related_members") or [])
            relationship_drafts: dict[str, str] = {}
            if job.request.mode == GenerationMode.RELATED and base_members:
                ui.notify("関係性説明を生成しています...", type="info")
                relationship_drafts = await _generate_group_generation_relationship_drafts(
                    ctx,
                    str(profile_select.value or ""),
                    group,
                    draft_sheet,
                    base_members,
                )

            with ui.dialog() as dlg, ui.card().classes("w-full max-w-3xl"):
                ui.label("保存内容の確認").classes("text-base font-semibold")
                ui.label("ハンドルと関係性を確認してから、グループ内メンバーとして保存します。").classes(
                    "text-sm text-grey-6"
                )
                handle_input = (
                    ui.input(
                        "ハンドル",
                        value=_default_generated_handle(draft_sheet, group),
                    )
                    .props("outlined dense mask=\"NNNNNNNNNNNN\"")
                    .classes("w-full")
                )

                relationship_inputs: dict[str, Any] = {}
                if job.request.mode == GenerationMode.RELATED and base_members:
                    ui.label("ベースメンバーとの関係性").classes("text-sm font-semibold mt-2")
                    for member in base_members:
                        relationship_inputs[member.id] = (
                            ui.textarea(
                                _group_generation_member_label(member),
                                value=relationship_drafts.get(member.id, ""),
                            )
                            .props("outlined rows=3")
                            .classes("w-full")
                        )

                with ui.expansion("生成シートを確認", icon="description", value=False).classes("w-full"):
                    render_sheet_result(ui.element("div"), sanitized)

                async def _save() -> None:
                    handle = str(handle_input.value or "").strip()
                    if not _HANDLE_RE.fullmatch(handle):
                        ui.notify("ハンドルは3〜12文字の英数字または_で入力してください", type="warning")
                        return
                    if handle.lower() in {member.handle.lower() for member in group.members}:
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

                    sheet_to_save = _group_generated_sheet_from_result(
                        sanitized,
                        draft_sheet.id,
                        job,
                        result,
                    )
                    saved_member = await ctx.group_chats.add_generated_member(
                        group.id,
                        sheet_to_save,
                        handle,
                    )
                    if saved_member is None:
                        ui.notify("グループ内メンバーとして保存できませんでした", type="negative")
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
                    ui.notify("グループ内キャラクターを保存しました", type="positive")
                    ui.navigate.to(f"/groups/{group.id}/members/{saved_member.id}")

                with ui.row().classes("justify-end gap-2 mt-4"):
                    ui.button("キャンセル", on_click=dlg.close).props("flat")
                    ui.button("保存", icon="check", on_click=_save).props("color=primary unelevated")
            dlg.open()

        async def _handle_job_event(job: GenerationJob, event) -> None:
            progress_panel.handle_event(event)
            _sync_job_controls(job)

            if event.type == ProgressEventType.SHEET_READY:
                sanitized = sanitize_group_generated_markdown(str(event.data or ""))
                current_result["sheet"] = sanitized
                render_sheet_result(result_area, sanitized)
            elif event.type == ProgressEventType.DONE:
                result = event.data
                if result and result.success:
                    sanitized = sanitize_group_generated_markdown(result.sheet_markdown)
                    result.sheet_markdown = sanitized
                    job.sheet_markdown = sanitized
                    current_result["gen_result"] = result
                    current_result["sheet"] = sanitized
                    render_sheet_result(result_area, sanitized)
                    color = {"complete": "positive", "partial": "warning", "failed": "negative"}.get(
                        result.quality_status, "grey"
                    )
                    label = {"complete": "品質: 良好", "partial": "品質: 部分的", "failed": "品質: 低"}.get(
                        result.quality_status, ""
                    )
                    quality_badge.props(f"color={color}")
                    quality_badge.set_text(label)
                    quality_badge.classes(remove="hidden")
                    download_btn.classes(remove="hidden")
                    log_download_btn.classes(remove="hidden")
                    if job.request.mode == GenerationMode.MODIFY:
                        await _open_group_modify_review_if_needed(job, result)
                    else:
                        save_result_btn.classes(remove="hidden")
                elif result:
                    ui.notify(result.error_message or "生成に失敗しました。", type="negative")
            elif event.type == ProgressEventType.ERROR:
                ui.notify(str(event.data), type="negative", timeout=8000)

        async def _attach_to_job(job_id: str) -> None:
            if watching_job_id["value"] == job_id:
                return
            job = ctx.generation.get_job(job_id)
            if not job:
                return
            watching_job_id["value"] = job_id
            _prepare_job_view(job)
            try:
                async for event in ctx.generation.stream_events(job.id):
                    await _handle_job_event(job, event)
                    await asyncio.sleep(0)
            except RuntimeError:
                pass
            finally:
                latest = ctx.generation.get_job(job.id)
                if latest:
                    _sync_job_controls(latest)
                if watching_job_id["value"] == job.id:
                    watching_job_id["value"] = ""

        async def on_generate() -> None:
            if _active_tab_is(tab_new, TAB_NEW):
                mode = GenerationMode.NEW
                prefs = GenerationPreferences(
                    gender=str(new_gender_select.value or "おまかせ"),
                    age=str(new_age_select.value or "おまかせ"),
                    extra=str(new_extra_input.value or ""),
                )
                request = GenerationRequest(
                    preferences=prefs,
                    mode=mode,
                    new_char_name=str(new_name_input.value or "").strip(),
                    group_world=group.world,
                    omit_group_sections=True,
                )
                base_member = None
                current_result["related_members"] = []
            elif _active_tab_is(tab_modify, TAB_MODIFY):
                member = _member_by_id(str(modify_member_select.value or ""))
                if member is None:
                    ui.notify("修正ベースにするグループ内キャラクターを選択してください", type="warning")
                    return
                mode = GenerationMode.MODIFY
                request = GenerationRequest(
                    preferences=GenerationPreferences(),
                    mode=mode,
                    base_sheet=sanitize_group_generated_markdown(_base_character_markdown(member.character)),
                    modify_request=str(modify_request_input.value or ""),
                    group_world=group.world,
                    omit_group_sections=True,
                )
                base_member = member
                current_result["modify_member"] = member
                current_result["related_members"] = []
            else:
                related_members = _selected_related_members()
                if not related_members:
                    ui.notify("関連キャラ生成のベースメンバーを選択してください", type="warning")
                    return
                mode = GenerationMode.RELATED
                prefs = GenerationPreferences(
                    gender=str(related_gender_select.value or "おまかせ"),
                    age=str(related_age_select.value or "おまかせ"),
                    extra=str(related_extra_input.value or ""),
                )
                request = GenerationRequest(
                    preferences=prefs,
                    mode=mode,
                    base_sheet=_base_character_markdown(related_members[0].character),
                    new_char_name=str(related_name_input.value or "").strip(),
                    group_world=group.world,
                    related_base_sheets=[_generation_base_sheet_from_member(member) for member in related_members],
                    omit_group_sections=True,
                )
                base_member = related_members[0]
                current_result["related_members"] = related_members

            profile_id = str(profile_select.value or "")
            profile = ctx.api_config.get_llm_profile(profile_id)
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
                    "このエンドポイントにはAPIキーが設定されています。APIキーボルトをロック解除してください。",
                    type="warning",
                    timeout=8000,
                )
                return

            job = ctx.generation.start_job(
                request,
                profile,
                endpoint,
                api_key,
                base_character_id=base_member.id if base_member else "",
                auto_save=False,
            )
            await _attach_to_job(job.id)

        async def on_stop() -> None:
            if current_result.get("gen_id"):
                ctx.generation.stop(str(current_result["gen_id"]))

        def _download_sheet() -> None:
            sheet_md = str(current_result.get("sheet") or "")
            if sheet_md:
                ui.download(sheet_md.encode("utf-8"), "group_character_sheet.md")

        def _download_log() -> None:
            result = current_result.get("gen_result")
            if not result:
                return
            mode_value = getattr(current_result.get("mode"), "value", "generate")
            log_text = build_generation_log(
                result,
                mode_value,
                str(current_result.get("sheet") or ""),
                current_result.get("request"),
                current_result.get("profile"),
            )
            ui.download(log_text.encode("utf-8"), "group_generation_log.txt")

        async def _open_current_save_dialog() -> None:
            job = ctx.generation.get_job(str(current_result.get("gen_id") or ""))
            result = current_result.get("gen_result")
            if not job or not result:
                ui.notify("保存できる生成結果がありません", type="warning")
                return
            await _open_group_save_dialog(job, result)

        generate_btn.on("click", on_generate)
        stop_btn.on("click", on_stop)
        download_btn.on("click", _download_sheet)
        log_download_btn.on("click", _download_log)
        save_result_btn.on("click", _open_current_save_dialog)


@ui.page("/groups/{group_id}/persona")
async def group_persona_detail_page(group_id: str) -> None:
    ctx = get_context()
    group = await ctx.group_chats.get(group_id)
    if group is None:
        with page_layout("グループが見つかりません"):
            ui.label("指定されたグループは存在しません。").classes("text-grey-6")
            ui.button("一覧に戻る", on_click=lambda: ui.navigate.to("/groups")).props("flat color=primary")
        return

    persona = group.user_persona
    if persona is None:
        with page_layout("ユーザーペルソナが見つかりません"):
            ui.label("このグループにはユーザーペルソナが設定されていません。").classes("text-grey-6")
            ui.button(
                "グループに戻る",
                on_click=lambda: ui.navigate.to(f"/groups/{group.id}"),
            ).props("flat color=primary")
        return

    def _persona_title() -> str:
        return persona.display_name or persona.name or "ユーザー"

    with page_layout(_persona_title()):
        ui.add_head_html(GROUP_CHAT_CSS)
        with ui.row().classes("items-center gap-2 mb-4 flex-wrap"):
            ui.button(
                icon="arrow_back",
                on_click=lambda: ui.navigate.to(f"/groups/{group.id}"),
            ).props("flat round")
            title_label = ui.label(_persona_title()).classes("text-2xl font-bold flex-1")
            ui.badge("グループ内コピー").props("outline color=primary")

        edit_mode = {"active": False}
        basic_container = ui.element("div").classes("w-full")

        def _render_basic_info() -> None:
            basic_container.clear()
            with basic_container:
                with ui.card().classes("w-full mb-4"):
                    with ui.row().classes("gap-6 flex-wrap"):
                        for label, value in [
                            ("グループ", group.name),
                            ("ハンドル", f"@{persona.handle}"),
                            ("表示名", persona.display_name),
                            ("名前", persona.name),
                        ]:
                            if value:
                                with ui.column().classes("gap-0"):
                                    ui.label(label).classes("text-xs text-grey-6")
                                    ui.label(value).classes("text-sm font-medium")

        _render_basic_info()

        with ui.card().classes("w-full"):
            with ui.row().classes("items-center justify-between mb-2"):
                ui.label("ユーザーペルソナ").classes("text-base font-semibold")
                with ui.row().classes("gap-1"):
                    edit_btn = ui.button("編集", icon="edit", on_click=lambda: _enter_edit()).props(
                        "flat size=sm color=primary"
                    )
                    save_btn = (
                        ui.button("保存", icon="save", on_click=lambda: _save_edit())
                        .props("unelevated size=sm color=primary")
                        .classes("hidden")
                    )
                    cancel_btn = (
                        ui.button("キャンセル", on_click=lambda: _cancel_edit()).props("flat size=sm").classes("hidden")
                    )

            handle_input = {"ref": None}
            name_input = {"ref": None}
            display_name_input = {"ref": None}
            description_input = {"ref": None}
            detail_container = ui.element("div").classes("w-full")

            def _render_view() -> None:
                detail_container.clear()
                with detail_container:
                    with ui.element("div").classes("cs-group-profile-grid"):
                        for label, value in [
                            ("ハンドル", f"@{persona.handle}"),
                            ("表示名", persona.display_name),
                            ("名前", persona.name),
                        ]:
                            ui.label(label).classes("cs-group-profile-label")
                            ui.label(value or "未設定").classes("cs-group-profile-value")
                    ui.label("説明").classes("cs-group-profile-card-title mt-4")
                    ui.label(persona.description or "未設定").classes("cs-group-profile-summary")

            _render_view()

        def _enter_edit() -> None:
            edit_mode["active"] = True
            detail_container.clear()
            with detail_container:
                handle_input["ref"] = (
                    ui.input(
                        label="ハンドル",
                        value=persona.handle,
                    )
                    .props("outlined dense mask=\"NNNNNNNNNNNN\"")
                    .classes("w-full")
                )
                display_name_input["ref"] = (
                    ui.input(
                        label="表示名",
                        value=persona.display_name,
                    )
                    .props("outlined dense")
                    .classes("w-full")
                )
                name_input["ref"] = (
                    ui.input(
                        label="名前",
                        value=persona.name,
                    )
                    .props("outlined dense")
                    .classes("w-full")
                )
                description_input["ref"] = (
                    ui.textarea(
                        label="説明",
                        value=persona.description,
                    )
                    .props("outlined rows=8")
                    .classes("w-full")
                )
            edit_btn.classes("hidden")
            save_btn.classes(remove="hidden")
            cancel_btn.classes(remove="hidden")

        async def _save_edit() -> None:
            nonlocal persona

            handle = str(handle_input["ref"].value if handle_input["ref"] is not None else "").strip()
            display_name = str(display_name_input["ref"].value if display_name_input["ref"] is not None else "").strip()
            name = str(name_input["ref"].value if name_input["ref"] is not None else "").strip()
            description = str(description_input["ref"].value if description_input["ref"] is not None else "").strip()

            sanitized_handle = sanitize_handle(handle, persona.handle or "User")
            used_handles = {member.handle.lower() for member in group.members}
            if sanitized_handle.lower() in used_handles:
                ui.notify("同じハンドルのメンバーが既にいます", type="warning")
                return
            if not name:
                ui.notify("名前を入力してください", type="warning")
                return

            updated = persona.model_copy(
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

            persona = saved
            title_label.set_text(_persona_title())
            _render_basic_info()
            ui.notify(f"「{_persona_title()}」を保存しました", type="positive")
            _cancel_edit()

        def _cancel_edit() -> None:
            edit_mode["active"] = False
            _render_view()
            edit_btn.classes(remove="hidden")
            save_btn.classes("hidden")
            cancel_btn.classes("hidden")
