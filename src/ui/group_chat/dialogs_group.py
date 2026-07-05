"""グループチャットの作成・削除・メンバー追加ダイアログ。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from nicegui import ui

from ...core.character.schemas import CharacterSheet
from ...core.conversation.group_setup import (
    fallback_handle,
    fallback_persona_handle,
    sanitize_handle,
    unique_handle,
)
from ...core.conversation.prompts.common import compact_character_summary
from ...core.conversation.relationship_drafts import (
    merge_relationship_drafts as _merge_relationship_drafts,
)
from ...core.conversation.relationship_drafts import (
    relationship_draft_participants as _relationship_draft_participants,
)
from ...core.conversation.world_adaptation import (
    prepare_group_character_for_world as _prepare_group_character_for_world,
)
from ...core.conversation.world_adaptation import (
    prepare_group_user_world_settings as _prepare_group_user_world_settings,
)
from ...core.group_chat.schemas import GroupChatRecord, GroupRelationship, GroupUserPersona
from ...services.ai_jobs import AIJobStatus
from ...services.llm_runtime import LLMRuntimeError
from ..chat.media import cropped_background_style
from ..components.character_picker import open_character_picker
from ..state import get_vault_password
from .common import (
    HANDLE_RE,
    default_persona_id,
    notify_on_client,
    notify_setup_llm_runtime_error,
    selected_persona,
)
from .common import (
    default_profile_id as resolve_default_profile_id,
)
from .common import (
    profile_options as build_profile_options,
)
from .dialogs_adaptation import (
    adapt_character_to_world,
    adapt_user_persona_to_world,
    delete_relationship_draft,
    generate_arrival_reason,
    generate_relationship_drafts,
    open_relationship_draft_dialog,
)
from .rendering import render_group_user_menu_face


def open_new_group_dialog(
    ctx,
    refresh_groups: Callable[[], Awaitable[None]],
) -> None:
    profiles = ctx.api_config.get_llm_profiles()
    personas = ctx.user_personas.get_user_personas()
    profile_options = build_profile_options(ctx, profiles)
    persona_options = {persona.id: persona.display_name for persona in personas}
    page_client = ui.context.client
    selected = {"characters": []}
    handle_inputs: dict[str, Any] = {}
    controls: dict[str, Any] = {}
    state: dict[str, Any] = {
        "step": 0,
        "name": "",
        "profile_id": resolve_default_profile_id(ctx, profile_options),
        "persona_id": default_persona_id(persona_options),
        "user_handle": "User",
        "handle_values": {},
        "world_source": "new",
        "world_text": "",
        "entry_modes": {},
        "arrival_reasons": {},
        "adaptation_notes": {},
        "adaptation_instructions": {},
        "draft_sheets": {},
        "user_description_draft": "",
        "relationships": [],
        "relationship_sequence": 0,
    }

    with (
        ui.dialog() as dlg,
        ui.card()
        .classes("w-full max-w-3xl")
        .style("max-width: min(760px, 94vw); height: min(860px, 94vh); display: flex; flex-direction: column;"),
    ):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("新しいグループ").classes("text-lg font-semibold")
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")

        step_head = ui.element("div").classes("w-full")
        with ui.scroll_area().style("flex: 1; min-height: 0; width: 100%;"):
            body = ui.column().classes("w-full gap-3 pr-2")
        nav = ui.row().classes("justify-end gap-2 mt-4")
        busy_state: dict[str, Any] = {"active": False, "job_id": ""}
        with (
            ui.dialog().props("persistent") as busy_dialog,
            ui.card().classes("items-center gap-3 px-6 py-5").style("min-width: min(320px, 86vw);"),
        ):
            ui.spinner(size="lg")
            busy_label = ui.label("処理中です").classes("text-sm font-semibold text-center")
            busy_cancel_btn = ui.button(
                "キャンセル",
                icon="close",
                on_click=lambda: _cancel_busy_job(),
            ).props("outline color=negative")
            busy_cancel_btn.disable()

        def _begin_busy(label: str) -> None:
            busy_state["active"] = True
            busy_state["job_id"] = ""
            busy_label.set_text(label)
            busy_cancel_btn.disable()
            busy_dialog.open()

        def _set_busy_job(job_id: str) -> None:
            if not busy_state.get("active"):
                return
            busy_state["job_id"] = job_id
            busy_cancel_btn.enable()

        def _end_busy() -> None:
            busy_state["active"] = False
            busy_state["job_id"] = ""
            busy_cancel_btn.disable()
            busy_dialog.close()

        async def _cancel_busy_job() -> None:
            job_id = str(busy_state.get("job_id") or "")
            if not job_id:
                return
            busy_label.set_text("停止要求中...")
            busy_cancel_btn.disable()
            await ctx.ai_jobs.cancel_job(job_id)

        def _selected_persona_obj():
            return selected_persona(ctx, str(state.get("persona_id") or ""))

        def _current_world_source_character_id() -> str:
            source = str(state.get("world_source") or "new")
            return source.removeprefix("character:") if source.startswith("character:") else ""

        def _current_world_text() -> str:
            source_id = _current_world_source_character_id()
            if source_id:
                source_sheet = next((sheet for sheet in selected["characters"] if sheet.id == source_id), None)
                return (source_sheet.world if source_sheet else "").strip()
            return str(state.get("world_text") or "").strip()

        def _participant_key_for_sheet(sheet: CharacterSheet) -> str:
            return f"character:{sheet.id}"

        def _capture_step() -> None:
            if "name_input" in controls:
                state["name"] = str(controls["name_input"].value or "").strip()
            if "profile_select" in controls:
                state["profile_id"] = str(controls["profile_select"].value or "")
            if "persona_select" in controls:
                persona_id = str(controls["persona_select"].value or "")
                if persona_id != state["persona_id"]:
                    state["user_description_draft"] = ""
                    state["adaptation_notes"].pop("user", None)
                    state["adaptation_instructions"].pop("user", None)
                    state["arrival_reasons"].pop("user", None)
                    state["relationships"] = [
                        relationship
                        for relationship in state["relationships"]
                        if "user"
                        not in {
                            relationship["participant_a_key"],
                            relationship["participant_b_key"],
                        }
                    ]
                state["persona_id"] = persona_id
            if "user_handle_input" in controls:
                state["user_handle"] = str(controls["user_handle_input"].value or "").strip()
            if handle_inputs:
                handle_values = dict(state.get("handle_values", {}))
                for character_id, input_ in handle_inputs.items():
                    handle_values[character_id] = str(input_.value or "")
                state["handle_values"] = handle_values
            if "world_source_select" in controls:
                state["world_source"] = str(controls["world_source_select"].value or "new")
            if "world_input" in controls:
                state["world_text"] = str(controls["world_input"].value or "").strip()
            for key, select in controls.get("entry_selects", {}).items():
                state["entry_modes"][key] = str(select.value or "native")
            for key, input_ in controls.get("arrival_inputs", {}).items():
                state["arrival_reasons"][key] = str(input_.value or "").strip()

        def _validate_step(step: int) -> bool:
            _capture_step()
            if step == 0:
                if not state["profile_id"]:
                    ui.notify("補完用LLMプロファイルを選択してください", type="warning")
                    return False
                if not selected["characters"]:
                    ui.notify("キャラクターを選択してください", type="warning")
                    return False
                if _selected_persona_obj() is None:
                    ui.notify("ユーザーペルソナを選択してください", type="warning")
                    return False
                if (
                    validate_handles_from_values(selected["characters"], state["handle_values"], state["user_handle"])
                    is None
                ):
                    return False
            if step == 1:
                if not state["name"]:
                    ui.notify("グループ名を入力してください", type="warning")
                    return False
                if not _current_world_text():
                    ui.notify("ワールドを確定してください", type="warning")
                    return False
            if step == 2:
                source_id = _current_world_source_character_id()
                for sheet in selected["characters"]:
                    if sheet.id == source_id:
                        continue
                    key = _participant_key_for_sheet(sheet)
                    if (
                        state["entry_modes"].get(key, "native") == "visitor"
                        and not state["arrival_reasons"].get(key, "").strip()
                    ):
                        ui.notify(f"{sheet.name} の来訪理由を入力してください", type="warning")
                        return False
                if (
                    state["entry_modes"].get("user", "native") == "visitor"
                    and not state["arrival_reasons"].get("user", "").strip()
                ):
                    ui.notify("ユーザーペルソナの来訪理由を入力してください", type="warning")
                    return False
            return True

        def _render_step_head() -> None:
            labels = ["参加者", "ワールド", "適応", "関係性"]
            step_head.clear()
            with step_head:
                with ui.row().classes("items-center gap-2 flex-wrap"):
                    for index, label in enumerate(labels):
                        color = "primary" if index == state["step"] else "grey"
                        ui.badge(f"{index + 1}. {label}").props(f"outline color={color}")

        def _render_selected_list(container) -> None:
            previous_handles = {character_id: str(input_.value or "") for character_id, input_ in handle_inputs.items()}
            handle_values = dict(state.get("handle_values", {}))
            handle_values.update(previous_handles)
            state["handle_values"] = handle_values
            handle_inputs.clear()
            container.clear()
            with container:
                if not selected["characters"]:
                    ui.label("キャラクター未選択").classes("text-sm text-grey-6")
                    return
                for sheet in selected["characters"]:
                    render_selected_character_row(
                        ctx,
                        sheet,
                        handle_inputs,
                        value=handle_values.get(sheet.id),
                        remove=lambda character_id=sheet.id: _remove_character(character_id),
                    )

        def _remove_character(character_id: str) -> None:
            selected["characters"] = [sheet for sheet in selected["characters"] if sheet.id != character_id]
            handle_inputs.pop(character_id, None)
            state["handle_values"].pop(character_id, None)
            state["entry_modes"].pop(f"character:{character_id}", None)
            state["arrival_reasons"].pop(f"character:{character_id}", None)
            state["adaptation_instructions"].pop(f"character:{character_id}", None)
            state["draft_sheets"].pop(character_id, None)
            if state["world_source"] == f"character:{character_id}":
                state["world_source"] = "new"
            state["relationships"] = [
                relationship
                for relationship in state["relationships"]
                if f"character:{character_id}"
                not in {
                    relationship["participant_a_key"],
                    relationship["participant_b_key"],
                }
            ]
            render_step()

        async def _open_picker() -> None:
            async def _add_character(sheet: CharacterSheet) -> None:
                if any(current.id == sheet.id for current in selected["characters"]):
                    ui.notify("このキャラクターは選択済みです", type="warning")
                    return
                selected["characters"].append(sheet)
                state["entry_modes"].setdefault(f"character:{sheet.id}", "native")
                render_step()

            await open_character_picker(
                ctx,
                _add_character,
                title="グループに取り込むキャラクターを選択",
                empty_message="取り込めるキャラクターがありません",
            )

        def _render_setup_step() -> None:
            controls.clear()
            handle_inputs.clear()
            with body:
                controls["profile_select"] = (
                    ui.select(
                        options=profile_options,
                        value=state["profile_id"]
                        if state["profile_id"] in profile_options
                        else resolve_default_profile_id(ctx, profile_options),
                        label="補完用LLMプロファイル",
                    )
                    .props("outlined dense")
                    .classes("w-full")
                )
                with ui.element("div").classes("cs-group-modal-section"):
                    with ui.element("div").classes("cs-group-modal-actions"):
                        with ui.column().classes("gap-0"):
                            ui.label("グループに取り込むキャラクター").classes("text-sm font-semibold")
                            ui.label("選択したキャラクターはグループ内コピーとして保存します。").classes(
                                "cs-group-note"
                            )
                        ui.button(
                            "キャラクターを追加",
                            icon="person_search",
                            on_click=_open_picker,
                        ).props("color=primary unelevated").style("border-radius: 8px; font-weight: 700;")
                    selected_list = ui.element("div").classes("cs-group-selected-list")
                    _render_selected_list(selected_list)

                with ui.element("div").classes("cs-group-modal-section"):
                    ui.label("ユーザーペルソナ").classes("text-sm font-semibold")
                    with ui.element("div").classes("cs-group-persona-row"):
                        controls["persona_select"] = (
                            ui.select(
                                options=persona_options,
                                value=state["persona_id"]
                                if state["persona_id"] in persona_options
                                else default_persona_id(persona_options),
                                label="ユーザーペルソナ",
                            )
                            .props("outlined dense")
                            .classes("w-full")
                        )
                        controls["user_handle_input"] = (
                            ui.input(
                                label="ユーザーのハンドル",
                                value=state["user_handle"] or "User",
                            )
                            .props("outlined dense mask=\"NNNNNNNNNNNN\"")
                            .classes("w-full")
                        )

                async def _generate_handles_click() -> None:
                    _capture_step()
                    _begin_busy("ハンドルを生成しています...")
                    try:
                        await generate_handles(
                            ctx,
                            str(controls["profile_select"].value or ""),
                            selected["characters"],
                            selected_persona(ctx, str(controls["persona_select"].value or "")),
                            handle_inputs,
                            controls["user_handle_input"],
                            on_job_started=_set_busy_job,
                        )
                        _capture_step()
                    finally:
                        _end_busy()

                ui.button(
                    "一括でハンドル生成",
                    icon="auto_fix_high",
                    on_click=_generate_handles_click,
                ).props("flat color=primary").classes("w-fit")

        def _world_options() -> dict[str, str]:
            return world_source_options_for_characters(selected["characters"])

        def _render_world_step() -> None:
            controls.clear()
            options = _world_options()
            if state["world_source"] not in options:
                state["world_source"] = "new"
            with body:
                with ui.element("div").classes("cs-group-world-field"):
                    controls["name_input"] = (
                        ui.input(
                            label="グループ名",
                            value=state["name"],
                        )
                        .props("outlined clearable")
                        .classes("w-full")
                    )

                    async def _generate_group_name_click() -> None:
                        _capture_step()
                        _begin_busy("グループ名を補完しています...")
                        try:
                            name = await generate_group_name_from_world(
                                ctx,
                                str(state["profile_id"] or ""),
                                _current_world_text(),
                                selected["characters"],
                                _selected_persona_obj(),
                                page_client,
                                on_job_started=_set_busy_job,
                            )
                            if name:
                                controls["name_input"].set_value(name)
                                state["name"] = name
                        finally:
                            _end_busy()

                    ui.button(
                        icon="auto_awesome",
                        on_click=_generate_group_name_click,
                    ).props("flat round dense size=sm").classes("cs-group-world-enhance").tooltip("グループ名を補完")

                controls["world_source_select"] = (
                    ui.select(
                        options=options,
                        value=state["world_source"],
                        label="ワールドの決め方",
                    )
                    .props("outlined dense")
                    .classes("w-full")
                )

                def _refresh_world_preview() -> None:
                    _capture_step()
                    render_step()

                controls["world_source_select"].on_value_change(lambda _: _refresh_world_preview())
                if state["world_source"] == "new":
                    with ui.element("div").classes("cs-group-world-field"):
                        controls["world_input"] = (
                            ui.textarea(
                                label="新しいワールド",
                                value=state["world_text"],
                                placeholder="グループで共有する舞台、関係性、空気感など",
                            )
                            .props("outlined rows=6")
                            .classes("w-full")
                        )
                        ui.button(
                            icon="auto_awesome",
                            on_click=lambda: _enhance_world_click_busy(),
                        ).props("flat round dense size=sm").classes("cs-group-world-enhance").tooltip("ワールドを補完")
                else:
                    source_id = _current_world_source_character_id()
                    source_sheet = next((sheet for sheet in selected["characters"] if sheet.id == source_id), None)
                    ui.label(source_sheet.name if source_sheet else "引き継ぎ元").classes("text-sm font-semibold")
                    ui.label((source_sheet.world if source_sheet else "") or "未設定").classes(
                        "cs-group-profile-summary"
                    )

        async def _enhance_world_click_busy() -> None:
            _capture_step()
            world_input = controls.get("world_input")
            name_input = controls.get("name_input")
            if world_input is None or name_input is None:
                return
            _begin_busy("ワールドを補完しています...")
            try:
                await enhance_world_click(
                    ctx,
                    str(state["profile_id"] or ""),
                    selected["characters"],
                    _selected_persona_obj(),
                    world_input,
                    name_input,
                    on_job_started=_set_busy_job,
                )
                _capture_step()
            finally:
                _end_busy()

        def _render_entry_row(
            key: str, label: str, summary: str, *, is_character: bool, source_sheet: CharacterSheet | None = None
        ) -> None:
            source_id = _current_world_source_character_id()
            if source_sheet is not None and source_sheet.id == source_id:
                state["entry_modes"][key] = "world_source"
                with ui.element("div").classes("cs-group-selected-row"):
                    if source_sheet is not None:
                        render_character_face(ctx, source_sheet)
                    with ui.column().classes("gap-0 min-w-0 flex-1"):
                        ui.label(label).classes("text-sm font-semibold")
                        ui.label("ワールド引き継ぎ元").classes("text-xs text-grey-6")
                return

            mode = state["entry_modes"].get(key, "native")
            reason = state["arrival_reasons"].get(key, "")
            with ui.element("div").classes("cs-group-selected-row"):
                if source_sheet is not None:
                    render_character_face(ctx, source_sheet)
                else:
                    render_group_user_menu_face(
                        ctx, group_user_persona_from_selected(_selected_persona_obj(), state["user_handle"])
                    )
                with ui.column().classes("gap-2 min-w-0 flex-1"):
                    ui.label(label).classes("text-sm font-semibold")
                    if summary:
                        ui.label(summary).classes("text-xs text-grey-6")
                    entry_select = (
                        ui.select(
                            options={
                                "native": "元々この世界の住人だった",
                                "visitor": "何らかの理由でこの世界に来た",
                            },
                            value=mode if mode in {"native", "visitor"} else "native",
                            label="ワールド参加設定",
                        )
                        .props("outlined dense")
                        .classes("w-full")
                    )
                    controls.setdefault("entry_selects", {})[key] = entry_select

                    def _refresh_entry_mode() -> None:
                        _capture_step()
                        render_step()

                    entry_select.on_value_change(lambda _: _refresh_entry_mode())
                    if mode == "visitor":
                        controls.setdefault("arrival_inputs", {})[key] = (
                            ui.textarea(
                                label="この世界に来た理由",
                                value=reason,
                            )
                            .props("outlined rows=3")
                            .classes("w-full")
                        )
                        ui.button(
                            "理由を補完",
                            icon="auto_awesome",
                            on_click=lambda participant_key=key, display_name=label, text_summary=summary: (
                                _generate_arrival_reason_click(
                                    participant_key,
                                    display_name,
                                    text_summary,
                                )
                            ),
                        ).props("flat dense color=primary").classes("w-fit")
                    if mode != "visitor" and is_character and source_sheet is not None:
                        with ui.row().classes("gap-2 flex-wrap"):
                            ui.button(
                                "ワールドに馴染ませる",
                                icon="auto_fix_high",
                                on_click=lambda sheet=source_sheet, participant_key=key, display_name=label: (
                                    _open_world_adaptation_dialog(
                                        participant_key,
                                        display_name,
                                        lambda instruction, target_sheet=sheet, target_key=participant_key: (
                                            _adapt_character_click(
                                                target_sheet,
                                                target_key,
                                                instruction,
                                            )
                                        ),
                                    )
                                ),
                            ).props("outline dense color=primary")
                    elif mode != "visitor" and not is_character:
                        ui.button(
                            "ワールドに馴染ませる",
                            icon="auto_fix_high",
                            on_click=lambda participant_key=key, display_name=label, text_summary=summary: (
                                _adapt_user_persona_click(
                                    participant_key,
                                    display_name,
                                    text_summary,
                                )
                            ),
                        ).props("outline dense color=primary").classes("w-fit")
                    note = state["adaptation_notes"].get(key, "")
                    if note:
                        ui.label(note).classes("text-xs text-grey-6")

        async def _adapt_character_click(sheet: CharacterSheet, participant_key: str, instruction: str) -> None:
            _capture_step()
            if state["entry_modes"].get(participant_key, "native") != "native":
                ui.notify(
                    "ワールドに馴染ませる改変は「元々この世界の住人だった」設定で使用してください", type="warning"
                )
                return
            world = _current_world_text()
            _begin_busy("キャラクターシートを調整しています...")
            try:
                await adapt_character_to_world(
                    ctx,
                    str(state["profile_id"] or ""),
                    state["draft_sheets"].get(sheet.id, sheet),
                    world,
                    instruction,
                    lambda updated: _apply_adapted_sheet(sheet.id, participant_key, updated),
                    page_client,
                    on_job_started=_set_busy_job,
                )
            finally:
                _end_busy()

        def _apply_adapted_sheet(sheet_id: str, participant_key: str, updated: CharacterSheet) -> None:
            state["draft_sheets"][sheet_id] = updated
            state["adaptation_notes"][participant_key] = "LLM改変を承認済み"
            render_step()

        async def _adapt_user_persona_click(participant_key: str, display_name: str, summary: str) -> None:
            _open_world_adaptation_dialog(
                participant_key,
                display_name,
                lambda instruction: _adapt_user_persona_with_instruction(
                    participant_key,
                    display_name,
                    summary,
                    instruction,
                ),
            )

        async def _adapt_user_persona_with_instruction(
            participant_key: str,
            display_name: str,
            summary: str,
            instruction: str,
        ) -> None:
            _capture_step()
            if state["entry_modes"].get(participant_key, "native") != "native":
                ui.notify(
                    "ワールドに馴染ませる改変は「元々この世界の住人だった」設定で使用してください", type="warning"
                )
                return
            persona = _selected_persona_obj()
            if persona is None:
                ui.notify("ユーザーペルソナを選択してください", type="warning")
                return
            _begin_busy("ユーザーペルソナを調整しています...")
            try:
                await adapt_user_persona_to_world(
                    ctx,
                    str(state["profile_id"] or ""),
                    display_name,
                    str(state.get("user_description_draft") or summary or ""),
                    _current_world_text(),
                    instruction,
                    lambda updated: _apply_adapted_user_persona(participant_key, updated),
                    page_client,
                    on_job_started=_set_busy_job,
                )
            finally:
                _end_busy()

        def _apply_adapted_user_persona(participant_key: str, updated_description: str) -> None:
            state["user_description_draft"] = updated_description
            state["adaptation_notes"][participant_key] = "LLM改変を承認済み"
            render_step()

        def _open_world_adaptation_dialog(
            participant_key: str,
            display_name: str,
            run_adaptation: Callable[[str], Awaitable[None]],
        ) -> None:
            _capture_step()
            with ui.dialog() as adaptation_dialog, ui.card().classes("w-full max-w-lg"):
                ui.label("ワールドに馴染ませる").classes("text-base font-semibold")
                ui.label(display_name).classes("text-sm text-grey-6")
                instruction_input = (
                    ui.textarea(
                        label="追加指示（任意）",
                        value=state["adaptation_instructions"].get(participant_key, ""),
                        placeholder="例: 学園もの寄りにする、職業は変えない、口調は元のままにする",
                    )
                    .props("outlined rows=5")
                    .classes("w-full")
                )

                async def _run() -> None:
                    instruction = str(instruction_input.value or "").strip()
                    if instruction:
                        state["adaptation_instructions"][participant_key] = instruction
                    else:
                        state["adaptation_instructions"].pop(participant_key, None)
                    adaptation_dialog.close()
                    await run_adaptation(instruction)

                with ui.row().classes("justify-end gap-2 mt-4"):
                    ui.button("キャンセル", on_click=adaptation_dialog.close).props("flat")
                    ui.button("OK", icon="check", on_click=_run).props("color=primary unelevated")
            adaptation_dialog.open()

        async def _generate_arrival_reason_click(participant_key: str, display_name: str, summary: str) -> None:
            _capture_step()
            input_ = controls.get("arrival_inputs", {}).get(participant_key)
            if input_ is None:
                return
            _begin_busy("来訪理由を補完しています...")
            try:
                reason = await generate_arrival_reason(
                    ctx,
                    str(state["profile_id"] or ""),
                    display_name,
                    _current_world_text(),
                    summary,
                    page_client,
                    on_job_started=_set_busy_job,
                )
                if reason:
                    input_.set_value(reason)
                    state["arrival_reasons"][participant_key] = reason
            finally:
                _end_busy()

        def _render_entry_step() -> None:
            controls.clear()
            controls["entry_selects"] = {}
            controls["arrival_inputs"] = {}
            with body:
                ui.label("参加者ごとのワールド参加設定").classes("text-sm font-semibold")
                for sheet in selected["characters"]:
                    display_sheet = state["draft_sheets"].get(sheet.id, sheet)
                    _render_entry_row(
                        _participant_key_for_sheet(sheet),
                        display_sheet.name,
                        compact_character_summary(display_sheet),
                        is_character=True,
                        source_sheet=display_sheet,
                    )
                persona = _selected_persona_obj()
                if persona is not None:
                    _render_entry_row(
                        "user",
                        persona.display_name or persona.name or "ユーザー",
                        str(state.get("user_description_draft") or persona.description),
                        is_character=False,
                    )

        def _relationship_options() -> dict[str, str]:
            options = {
                _participant_key_for_sheet(sheet): (
                    f"{state['draft_sheets'].get(sheet.id, sheet).name} "
                    f"(@{state['handle_values'].get(sheet.id, fallback_handle(sheet, 1))})"
                )
                for sheet in selected["characters"]
            }
            persona = _selected_persona_obj()
            if persona is not None:
                options["user"] = (
                    f"{persona.display_name or persona.name or 'ユーザー'} (@{state.get('user_handle') or 'User'})"
                )
            return options

        def _relationship_participants() -> list[dict[str, str]]:
            display_characters = [state["draft_sheets"].get(sheet.id, sheet) for sheet in selected["characters"]]
            return _relationship_draft_participants(
                display_characters,
                _selected_persona_obj(),
                state,
            )

        def _render_relationship_step() -> None:
            controls.clear()
            with body:
                with ui.row().classes("items-center justify-between gap-2 w-full"):
                    ui.label("関係性").classes("text-sm font-semibold")
                    with ui.row().classes("gap-2"):
                        ui.button(
                            "追加",
                            icon="add",
                            on_click=lambda: open_relationship_draft_dialog(
                                state,
                                _relationship_options(),
                                None,
                                render_step,
                                ctx=ctx,
                                profile_id=str(state["profile_id"] or ""),
                                world=_current_world_text(),
                                participants=_relationship_participants(),
                                page_client=page_client,
                                begin_busy=_begin_busy,
                                set_busy_job=_set_busy_job,
                                end_busy=_end_busy,
                            ),
                        ).props("outline dense")
                        ui.button(
                            "LLMで自動設定",
                            icon="auto_awesome",
                            on_click=_generate_relationships_click,
                        ).props("flat dense color=primary")
                if not state["relationships"]:
                    ui.label("設定済みの関係性はありません").classes("text-sm text-grey-6")
                labels = _relationship_options()
                for relationship in state["relationships"]:
                    with ui.element("div").classes("cs-group-relationship-row"):
                        with ui.element("div").classes("cs-group-relationship-head"):
                            left = labels.get(relationship["participant_a_key"], "不明な参加者")
                            right = labels.get(relationship["participant_b_key"], "不明な参加者")
                            ui.label(f"{left} ↔ {right}").classes("cs-group-relationship-pair")
                            with ui.row().classes("gap-1"):
                                ui.button(
                                    icon="edit",
                                    on_click=lambda item=relationship: open_relationship_draft_dialog(
                                        state,
                                        labels,
                                        item,
                                        render_step,
                                        ctx=ctx,
                                        profile_id=str(state["profile_id"] or ""),
                                        world=_current_world_text(),
                                        participants=_relationship_participants(),
                                        page_client=page_client,
                                        begin_busy=_begin_busy,
                                        set_busy_job=_set_busy_job,
                                        end_busy=_end_busy,
                                    ),
                                ).props("flat round dense size=sm").tooltip("編集")
                                ui.button(
                                    icon="delete",
                                    on_click=lambda relationship_id=relationship["id"]: delete_relationship_draft(
                                        state,
                                        relationship_id,
                                        render_step,
                                    ),
                                ).props("flat round dense size=sm color=negative").tooltip("削除")
                        ui.label(relationship["description"]).classes("cs-group-relationship-text")

        async def _generate_relationships_click() -> None:
            _capture_step()
            _begin_busy("関係性を自動設定しています...")
            try:
                generated = await generate_relationship_drafts(
                    ctx,
                    str(state["profile_id"] or ""),
                    selected["characters"],
                    _selected_persona_obj(),
                    _current_world_text(),
                    state,
                    page_client,
                    on_job_started=_set_busy_job,
                )
                if generated:
                    _merge_relationship_drafts(state, generated)
                    render_step()
            finally:
                _end_busy()

        async def _create_group() -> None:
            _capture_step()
            for step in range(3):
                if not _validate_step(step):
                    state["step"] = step
                    render_step()
                    return
            validation = validate_handles_from_values(
                selected["characters"], state["handle_values"], state["user_handle"]
            )
            if validation is None:
                state["step"] = 0
                render_step()
                return
            member_handles, user_handle = validation
            persona = _selected_persona_obj()
            if persona is None:
                state["step"] = 0
                render_step()
                return
            world = _current_world_text()
            source_id = _current_world_source_character_id()
            members_for_create: list[tuple[CharacterSheet, str]] = []
            member_world_settings: dict[str, dict[str, str]] = {}
            for sheet, handle in zip(selected["characters"], member_handles, strict=True):
                prepared, settings = _prepare_group_character_for_world(
                    state["draft_sheets"].get(sheet.id, sheet),
                    world=world,
                    source_character_id=source_id,
                    entry_type=state["entry_modes"].get(_participant_key_for_sheet(sheet), "native"),
                    arrival_reason=state["arrival_reasons"].get(_participant_key_for_sheet(sheet), ""),
                    adaptation_note=state["adaptation_notes"].get(_participant_key_for_sheet(sheet), ""),
                )
                members_for_create.append((prepared, handle))
                member_world_settings[prepared.id] = settings

            user_world_settings = _prepare_group_user_world_settings(
                persona,
                world=world,
                entry_type=state["entry_modes"].get("user", "native"),
                arrival_reason=state["arrival_reasons"].get("user", ""),
                adaptation_note=state["adaptation_notes"].get("user", ""),
                description_override=str(state.get("user_description_draft") or ""),
            )
            relationships = [
                GroupRelationship(
                    id=str(relationship["id"]),
                    participant_a_key=str(relationship["participant_a_key"]),
                    participant_b_key=str(relationship["participant_b_key"]),
                    description=str(relationship["description"]),
                )
                for relationship in state["relationships"]
            ]
            await ctx.group_chats.create_group(
                name=state["name"],
                world=world,
                completion_profile_id=str(state["profile_id"] or ""),
                members=members_for_create,
                user_persona=persona,
                user_handle=user_handle,
                world_source_type="character" if source_id else "new",
                world_source_character_id=source_id,
                member_world_settings=member_world_settings,
                user_world_settings=user_world_settings,
                relationships=relationships,
            )
            dlg.close()
            ui.notify("グループを作成しました", type="positive")
            await refresh_groups()

        def _next_step() -> None:
            current = int(state["step"])
            if _validate_step(current):
                state["step"] = min(3, current + 1)
                render_step()

        def _prev_step() -> None:
            _capture_step()
            state["step"] = max(0, int(state["step"]) - 1)
            render_step()

        def _render_nav() -> None:
            nav.clear()
            with nav:
                ui.button("キャンセル", on_click=dlg.close).props("flat")
                if state["step"] > 0:
                    ui.button("戻る", icon="arrow_back", on_click=_prev_step).props("flat")
                if state["step"] < 3:
                    ui.button("次へ", icon="arrow_forward", on_click=_next_step).props("color=primary unelevated")
                else:
                    ui.button("作成", icon="save", on_click=_create_group).props("color=primary unelevated")

        def render_step() -> None:
            _render_step_head()
            body.clear()
            with body:
                if state["step"] == 0:
                    _render_setup_step()
                elif state["step"] == 1:
                    _render_world_step()
                elif state["step"] == 2:
                    _render_entry_step()
                else:
                    _render_relationship_step()
            _render_nav()

        render_step()

    dlg.open()


def validate_handles_from_values(
    characters: list[CharacterSheet],
    handle_values: dict[str, str],
    user_handle_value: str,
) -> tuple[list[str], str] | None:
    handles: list[str] = []
    seen: set[str] = set()
    for sheet in characters:
        handle = str(handle_values.get(sheet.id) or "").strip()
        if not HANDLE_RE.fullmatch(handle):
            ui.notify(f"{sheet.name} のハンドルは3〜12文字の英数字または_で入力してください", type="warning")
            return None
        if handle.lower() in seen:
            ui.notify("ハンドルが重複しています", type="warning")
            return None
        seen.add(handle.lower())
        handles.append(handle)

    user_handle = str(user_handle_value or "").strip()
    if not HANDLE_RE.fullmatch(user_handle):
        ui.notify("ユーザーのハンドルは3〜12文字の英数字または_で入力してください", type="warning")
        return None
    if user_handle.lower() in seen:
        ui.notify("ハンドルが重複しています", type="warning")
        return None
    return handles, user_handle


def group_user_persona_from_selected(persona, handle: str) -> GroupUserPersona | None:
    if persona is None:
        return None
    return GroupUserPersona(
        id=str(getattr(persona, "id", "") or "user"),
        source_persona_id=str(getattr(persona, "id", "") or ""),
        handle=sanitize_handle(handle or "User", "User"),
        name=str(getattr(persona, "name", "") or ""),
        display_name=str(getattr(persona, "display_name", "") or ""),
        description=str(getattr(persona, "description", "") or ""),
        media=getattr(persona, "media").model_copy(deep=True),
    )


def world_source_options_for_characters(characters: list[CharacterSheet]) -> dict[str, str]:
    options = {"new": "完全に新しいワールド"}
    for sheet in characters:
        if sheet.world.strip():
            options[f"character:{sheet.id}"] = f"{sheet.name} のワールドを引き継ぐ"
    return options


def open_delete_group_dialog(
    ctx,
    group: GroupChatRecord,
    refresh_groups: Callable[[], Awaitable[None]] | None = None,
    after_delete: Callable[[], None] | None = None,
) -> None:
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-md"):
        ui.label("グループを削除").classes("text-lg font-semibold")
        ui.label(f"「{group.name}」を削除します。").classes("text-sm text-grey-6")
        ui.label("この操作は元に戻せません。").classes("text-sm text-grey-6")

        async def _delete() -> None:
            deleted = await ctx.group_chats.delete_group(group.id)
            dlg.close()
            if deleted:
                ui.notify("グループを削除しました", type="positive")
                if refresh_groups is not None:
                    await refresh_groups()
                if after_delete is not None:
                    after_delete()
            else:
                ui.notify("グループが見つかりませんでした", type="warning")

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("削除", icon="delete", on_click=_delete).props("color=negative unelevated")
    dlg.open()


def open_add_group_character_dialog(ctx, group: GroupChatRecord) -> None:
    profiles = ctx.api_config.get_llm_profiles()
    profile_options = build_profile_options(ctx, profiles)
    default_profile_id = (
        group.completion_profile_id
        if group.completion_profile_id in profile_options
        else resolve_default_profile_id(ctx, profile_options)
    )
    page_client = ui.context.client
    selected = {"characters": []}
    handle_inputs: dict[str, Any] = {}
    controls: dict[str, Any] = {}
    state: dict[str, Any] = {
        "profile_id": default_profile_id,
        "handle_values": {},
        "entry_modes": {},
        "arrival_reasons": {},
        "adaptation_notes": {},
        "adaptation_instructions": {},
        "draft_sheets": {},
    }
    existing_source_ids = {
        member.source_character_id or member.character.id
        for member in group.members
        if member.source_character_id or member.character.id
    }
    existing_handles = {member.handle.lower() for member in group.members}
    if group.user_persona is not None:
        existing_handles.add(group.user_persona.handle.lower())

    with (
        ui.dialog() as dlg,
        ui.card()
        .classes("w-full max-w-2xl")
        .style("max-width: min(760px, 94vw); height: min(820px, 94vh); display: flex; flex-direction: column;"),
    ):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("キャラクター追加").classes("text-lg font-semibold")
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")

        ui.label("追加したキャラクターはグループ内コピーとして保存します。").classes("cs-group-note")

        with ui.scroll_area().style("flex: 1; min-height: 0; width: 100%;"):
            body = ui.column().classes("w-full gap-3 pr-2")
        nav = ui.row().classes("justify-end gap-2 mt-4")
        busy_state: dict[str, Any] = {"active": False, "job_id": ""}
        with (
            ui.dialog().props("persistent") as busy_dialog,
            ui.card().classes("items-center gap-3 px-6 py-5").style("min-width: min(320px, 86vw);"),
        ):
            ui.spinner(size="lg")
            busy_label = ui.label("処理中です").classes("text-sm font-semibold text-center")
            busy_cancel_btn = ui.button(
                "キャンセル",
                icon="close",
                on_click=lambda: _cancel_busy_job(),
            ).props("outline color=negative")
            busy_cancel_btn.disable()

        def _participant_key(sheet: CharacterSheet) -> str:
            return f"character:{sheet.id}"

        def _world_text() -> str:
            return (group.world or "").strip()

        def _capture_inputs() -> None:
            if "profile_select" in controls:
                state["profile_id"] = str(controls["profile_select"].value or "")
            previous_handles = {character_id: str(input_.value or "") for character_id, input_ in handle_inputs.items()}
            if previous_handles:
                handle_values = dict(state.get("handle_values", {}))
                handle_values.update(previous_handles)
                state["handle_values"] = handle_values
            for key, select in controls.get("entry_selects", {}).items():
                next_mode = str(select.value or "native")
                state["entry_modes"][key] = next_mode
                if next_mode == "visitor":
                    state["adaptation_notes"].pop(key, None)
            for key, input_ in controls.get("arrival_inputs", {}).items():
                state["arrival_reasons"][key] = str(input_.value or "").strip()

        def _begin_busy(label: str) -> None:
            busy_state["active"] = True
            busy_state["job_id"] = ""
            busy_label.set_text(label)
            busy_cancel_btn.disable()
            busy_dialog.open()

        def _set_busy_job(job_id: str) -> None:
            if not busy_state.get("active"):
                return
            busy_state["job_id"] = job_id
            busy_cancel_btn.enable()

        def _end_busy() -> None:
            busy_state["active"] = False
            busy_state["job_id"] = ""
            busy_cancel_btn.disable()
            busy_dialog.close()

        async def _cancel_busy_job() -> None:
            job_id = str(busy_state.get("job_id") or "")
            if not job_id:
                return
            busy_label.set_text("停止要求中...")
            busy_cancel_btn.disable()
            await ctx.ai_jobs.cancel_job(job_id)

        def _refresh_selected_list() -> None:
            _capture_inputs()
            handle_inputs.clear()
            controls["entry_selects"] = {}
            controls["arrival_inputs"] = {}
            selected_list.clear()
            with selected_list:
                if not selected["characters"]:
                    ui.label("追加するキャラクターを選択してください").classes("text-sm text-grey-6")
                    return
                for sheet in selected["characters"]:
                    _render_character_entry_row(sheet)

        def _render_character_entry_row(sheet: CharacterSheet) -> None:
            key = _participant_key(sheet)
            mode = state["entry_modes"].get(key, "native")
            display_sheet = state["draft_sheets"].get(sheet.id, sheet) if mode != "visitor" else sheet
            with (
                ui.element("div")
                .classes("cs-group-selected-row")
                .style("grid-template-columns: 48px minmax(0, 1fr) 32px; align-items: start;")
            ):
                render_character_face(ctx, display_sheet)
                with ui.column().classes("gap-2 min-w-0 w-full"):
                    with ui.column().classes("gap-0 min-w-0"):
                        ui.label(display_sheet.name).classes("cs-group-selected-name")
                        meta = " / ".join(filter(None, [sheet.world, display_sheet.occupation]))
                        ui.label(meta or "キャラクター").classes("cs-group-selected-meta")
                    handle_inputs[sheet.id] = (
                        ui.input(
                            label="ハンドル",
                            value=state["handle_values"].get(
                                sheet.id,
                                fallback_handle(sheet, len(handle_inputs) + 1),
                            ),
                        )
                        .props("outlined dense mask=\"NNNNNNNNNNNN\"")
                        .classes("w-full")
                    )
                    entry_select = (
                        ui.select(
                            options={
                                "native": "元々この世界の住人だった",
                                "visitor": "何らかの理由でこの世界に来た",
                            },
                            value=mode if mode in {"native", "visitor"} else "native",
                            label="ワールド参加設定",
                        )
                        .props("outlined dense")
                        .classes("w-full")
                    )
                    controls["entry_selects"][key] = entry_select

                    def _refresh_entry_mode() -> None:
                        _capture_inputs()
                        _refresh_selected_list()

                    entry_select.on_value_change(lambda _: _refresh_entry_mode())
                    if mode == "visitor":
                        reason_input = (
                            ui.textarea(
                                label="この世界に来た理由",
                                value=state["arrival_reasons"].get(key, ""),
                            )
                            .props("outlined rows=3")
                            .classes("w-full")
                        )
                        controls["arrival_inputs"][key] = reason_input
                        ui.button(
                            "理由を補完",
                            icon="auto_awesome",
                            on_click=lambda target_sheet=sheet: _generate_arrival_reason_click(target_sheet),
                        ).props("flat dense color=primary").classes("w-fit")
                    else:
                        ui.button(
                            "ワールドに馴染ませる",
                            icon="auto_fix_high",
                            on_click=lambda target_sheet=display_sheet, original_id=sheet.id: (
                                _open_world_adaptation_dialog(
                                    _participant_key(sheet),
                                    target_sheet.name,
                                    lambda instruction, target_sheet=target_sheet, original_id=original_id: (
                                        _adapt_character_click(
                                            target_sheet,
                                            original_id,
                                            instruction,
                                        )
                                    ),
                                )
                            ),
                        ).props("outline dense color=primary").classes("w-fit")
                        if state["adaptation_notes"].get(key):
                            ui.label("調整済み").classes("text-xs text-grey-6")
                ui.button(
                    icon="close",
                    on_click=lambda character_id=sheet.id: _remove_character(character_id),
                ).props("flat round dense").tooltip("リストから外す")

        def _remove_character(character_id: str) -> None:
            _capture_inputs()
            selected["characters"] = [sheet for sheet in selected["characters"] if sheet.id != character_id]
            handle_inputs.pop(character_id, None)
            state["handle_values"].pop(character_id, None)
            state["entry_modes"].pop(f"character:{character_id}", None)
            state["arrival_reasons"].pop(f"character:{character_id}", None)
            state["adaptation_notes"].pop(f"character:{character_id}", None)
            state["adaptation_instructions"].pop(f"character:{character_id}", None)
            state["draft_sheets"].pop(character_id, None)
            _refresh_selected_list()

        async def _open_picker() -> None:
            async def _add_character(sheet: CharacterSheet) -> None:
                if sheet.id in existing_source_ids:
                    ui.notify("このキャラクターは既にグループにいます", type="warning")
                    return
                if any(current.id == sheet.id for current in selected["characters"]):
                    ui.notify("このキャラクターは選択済みです", type="warning")
                    return
                selected["characters"].append(sheet)
                state["entry_modes"].setdefault(_participant_key(sheet), "native")
                _refresh_selected_list()

            await open_character_picker(
                ctx,
                _add_character,
                title="グループに追加するキャラクターを選択",
                empty_message="追加できるキャラクターがありません",
            )

        async def _generate_handles_click() -> None:
            _capture_inputs()
            _begin_busy("ハンドルを生成しています...")
            try:
                await generate_handles(
                    ctx,
                    str(state.get("profile_id") or ""),
                    [state["draft_sheets"].get(sheet.id, sheet) for sheet in selected["characters"]],
                    group.user_persona,
                    handle_inputs,
                    None,
                    on_job_started=_set_busy_job,
                    reserved_handles=existing_handles,
                )
                _capture_inputs()
            finally:
                _end_busy()

        def _open_world_adaptation_dialog(
            participant_key: str,
            display_name: str,
            run_adaptation: Callable[[str], Awaitable[None]],
        ) -> None:
            _capture_inputs()
            with ui.dialog() as adaptation_dialog, ui.card().classes("w-full max-w-lg"):
                ui.label("ワールドに馴染ませる").classes("text-base font-semibold")
                ui.label(display_name).classes("text-sm text-grey-6")
                instruction_input = (
                    ui.textarea(
                        label="追加指示（任意）",
                        value=state["adaptation_instructions"].get(participant_key, ""),
                        placeholder="例: 職業は変えない、口調は元のままにする",
                    )
                    .props("outlined rows=5")
                    .classes("w-full")
                )

                async def _run() -> None:
                    instruction = str(instruction_input.value or "").strip()
                    if instruction:
                        state["adaptation_instructions"][participant_key] = instruction
                    else:
                        state["adaptation_instructions"].pop(participant_key, None)
                    adaptation_dialog.close()
                    await run_adaptation(instruction)

                with ui.row().classes("justify-end gap-2 mt-4"):
                    ui.button("キャンセル", on_click=adaptation_dialog.close).props("flat")
                    ui.button("OK", icon="check", on_click=_run).props("color=primary unelevated")
            adaptation_dialog.open()

        async def _adapt_character_click(
            sheet: CharacterSheet,
            source_character_id: str,
            instruction: str,
        ) -> None:
            _capture_inputs()
            key = f"character:{source_character_id}"
            if state["entry_modes"].get(key, "native") != "native":
                ui.notify(
                    "ワールドに馴染ませる改変は「元々この世界の住人だった」設定で使用してください", type="warning"
                )
                return
            _begin_busy("キャラクターシートを調整しています...")
            try:
                await adapt_character_to_world(
                    ctx,
                    str(state.get("profile_id") or ""),
                    sheet,
                    _world_text(),
                    instruction,
                    lambda updated: _apply_adapted_sheet(source_character_id, key, updated),
                    page_client,
                    on_job_started=_set_busy_job,
                )
            finally:
                _end_busy()

        def _apply_adapted_sheet(
            source_character_id: str,
            participant_key: str,
            updated: CharacterSheet,
        ) -> None:
            state["draft_sheets"][source_character_id] = updated
            state["adaptation_notes"][participant_key] = "LLM改変を承認済み"
            _refresh_selected_list()

        async def _generate_arrival_reason_click(sheet: CharacterSheet) -> None:
            _capture_inputs()
            key = _participant_key(sheet)
            input_ = controls.get("arrival_inputs", {}).get(key)
            if input_ is None:
                return
            _begin_busy("来訪理由を補完しています...")
            try:
                reason = await generate_arrival_reason(
                    ctx,
                    str(state.get("profile_id") or ""),
                    sheet.name,
                    _world_text(),
                    compact_character_summary(sheet),
                    page_client,
                    on_job_started=_set_busy_job,
                )
                if reason:
                    input_.set_value(reason)
                    state["arrival_reasons"][key] = reason
            finally:
                _end_busy()

        async def _add_members() -> None:
            _capture_inputs()
            if not selected["characters"]:
                ui.notify("キャラクターを選択してください", type="warning")
                return
            handles = validate_member_handles(
                selected["characters"],
                handle_inputs,
                existing_handles,
            )
            if handles is None:
                return
            prepared_members: list[tuple[CharacterSheet, str]] = []
            member_world_settings: dict[str, dict[str, str]] = {}
            for sheet, handle in zip(selected["characters"], handles, strict=True):
                key = _participant_key(sheet)
                entry_type = state["entry_modes"].get(key, "native")
                if entry_type == "visitor" and not state["arrival_reasons"].get(key, "").strip():
                    ui.notify(f"{sheet.name} の来訪理由を入力してください", type="warning")
                    return
                source_sheet = state["draft_sheets"].get(sheet.id, sheet) if entry_type == "native" else sheet
                prepared_sheet, settings = _prepare_group_character_for_world(
                    source_sheet,
                    world=_world_text(),
                    source_character_id="",
                    entry_type=entry_type,
                    arrival_reason=state["arrival_reasons"].get(key, ""),
                    adaptation_note=state["adaptation_notes"].get(key, "") if entry_type == "native" else "",
                )
                prepared_members.append((prepared_sheet, handle))
                member_world_settings[prepared_sheet.id] = settings
            saved = await ctx.group_chats.add_members(
                group.id,
                prepared_members,
                member_world_settings=member_world_settings,
            )
            if saved is None:
                ui.notify("グループが見つかりませんでした", type="warning")
                return
            dlg.close()
            ui.notify("キャラクターを追加しました", type="positive")
            ui.navigate.to(f"/groups/{saved.id}")

        with body:
            controls["profile_select"] = (
                ui.select(
                    options=profile_options,
                    value=state["profile_id"]
                    if state["profile_id"] in profile_options
                    else resolve_default_profile_id(ctx, profile_options),
                    label="補完用LLMプロファイル",
                )
                .props("outlined dense")
                .classes("w-full")
            )
            with ui.element("div").classes("cs-group-modal-section"):
                with ui.element("div").classes("cs-group-modal-actions"):
                    with ui.column().classes("gap-0"):
                        ui.label("追加するキャラクター").classes("text-sm font-semibold")
                        ui.label(f"ワールド: {group.world or '未設定'}").classes("cs-group-note")
                    ui.button(
                        "キャラクターを選択",
                        icon="person_search",
                        on_click=_open_picker,
                    ).props("color=primary unelevated").style("border-radius: 8px; font-weight: 700;")
                selected_list = ui.element("div").classes("cs-group-selected-list").style("max-height: none;")
                _refresh_selected_list()
            ui.button(
                "一括でハンドル生成",
                icon="auto_fix_high",
                on_click=_generate_handles_click,
            ).props("flat color=primary").classes("w-fit")

        with nav:
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("追加", icon="person_add", on_click=_add_members).props("color=primary unelevated")

    dlg.open()


def render_selected_character_row(
    ctx,
    sheet: CharacterSheet,
    handle_inputs: dict[str, Any],
    *,
    value: str | None = None,
    remove,
) -> None:
    with ui.element("div").classes("cs-group-selected-row"):
        render_character_face(ctx, sheet)
        with ui.column().classes("gap-0 cs-group-selected-info"):
            ui.label(sheet.name).classes("cs-group-selected-name")
            meta = " / ".join(filter(None, [sheet.world, sheet.occupation]))
            ui.label(meta or "キャラクター").classes("cs-group-selected-meta")
        handle_inputs[sheet.id] = (
            ui.input(
                label="ハンドル",
                value=value or fallback_handle(sheet, len(handle_inputs) + 1),
            )
            .props("outlined dense mask=\"NNNNNNNNNNNN\"")
            .classes("w-full")
        )
        ui.button(icon="close", on_click=remove).props("flat round dense").tooltip("リストから外す")


def render_character_face(ctx, sheet: CharacterSheet) -> None:
    image = sheet.media.primary_image()
    image_path = ctx.characters.media_path(image.path) if image else None
    style = cropped_background_style(image, image_path, image.face_rect, 1.0) if image and image_path else ""
    with ui.element("div").classes("cs-group-selected-face").style(style):
        if not style:
            ui.icon("person")


async def generate_handles(
    ctx,
    profile_id: str,
    characters: list[CharacterSheet],
    persona,
    handle_inputs: dict[str, Any],
    user_handle_input=None,
    on_job_started: Callable[[str], None] | None = None,
    reserved_handles: set[str] | None = None,
) -> None:
    if not characters:
        ui.notify("キャラクターを選択してください", type="warning")
        return
    if persona is None:
        ui.notify("ユーザーペルソナを選択してください", type="warning")
        return
    try:
        finished = await ctx.group_chat_assist.generate_handles(
            profile_id=profile_id,
            vault_password=get_vault_password(),
            characters=characters,
            persona=persona,
            on_job_started=on_job_started,
        )
    except LLMRuntimeError as err:
        notify_setup_llm_runtime_error(err)
        return
    except Exception as err:
        ui.notify(f"LLMの初期化に失敗しました: {err}", type="negative", timeout=10000)
        return
    if finished.status == AIJobStatus.CANCELLED:
        ui.notify("ハンドル生成を停止しました", type="info")
        return
    if finished.status != AIJobStatus.SUCCEEDED:
        ui.notify(
            f"ハンドル生成に失敗しました: {finished.error_message}",
            type="negative",
            timeout=10000,
        )
        return
    suggested = finished.result or {}

    used: set[str] = {handle.lower() for handle in reserved_handles or set()}
    for index, sheet in enumerate(characters, start=1):
        candidate = suggested.get(sheet.id) or suggested.get(sheet.name) or fallback_handle(sheet, index)
        handle = unique_handle(sanitize_handle(candidate, fallback_handle(sheet, index)), used)
        used.add(handle.lower())
        handle_inputs[sheet.id].set_value(handle)
    user_fallback = fallback_persona_handle(persona)
    user_candidate = suggested.get("user") or suggested.get(persona.display_name) or user_fallback
    user_handle = unique_handle(sanitize_handle(user_candidate, user_fallback), used)
    if user_handle_input is not None:
        user_handle_input.set_value(user_handle)
    ui.notify("ハンドルを生成しました", type="positive")


async def enhance_world_click(
    ctx,
    profile_id: str,
    characters: list[CharacterSheet],
    persona,
    world_input,
    name_input,
    on_job_started: Callable[[str], None] | None = None,
) -> None:
    current_world = (world_input.value or "").strip()
    if not current_world:
        ui.notify("先に世界観を入力してください", type="warning")
        return
    try:
        finished = await ctx.group_chat_assist.enhance_world(
            profile_id=profile_id,
            vault_password=get_vault_password(),
            current_world=current_world,
            group_name=str(name_input.value or ""),
            characters=characters,
            persona=persona,
            on_job_started=on_job_started,
        )
    except LLMRuntimeError as err:
        notify_setup_llm_runtime_error(err)
        return
    except Exception as err:
        ui.notify(f"LLMの初期化に失敗しました: {err}", type="negative", timeout=10000)
        return
    if finished.status == AIJobStatus.CANCELLED:
        ui.notify("世界観補完を停止しました", type="info")
        return
    if finished.status != AIJobStatus.SUCCEEDED:
        ui.notify(
            f"世界観補完に失敗しました: {finished.error_message}",
            type="negative",
            timeout=10000,
        )
        return
    enhanced = str(finished.result or "")
    if not enhanced:
        ui.notify("世界観を補完できませんでした", type="warning")
        return
    world_input.set_value(enhanced)
    ui.notify("世界観を補完しました", type="positive")


async def generate_group_name_from_world(
    ctx,
    profile_id: str,
    world: str,
    characters: list[CharacterSheet],
    persona,
    page_client=None,
    on_job_started: Callable[[str], None] | None = None,
) -> str:
    current_world = (world or "").strip()
    if not current_world:
        ui.notify("先にワールドを入力してください", type="warning")
        return ""
    try:
        finished = await ctx.group_chat_assist.generate_group_name_from_world(
            profile_id=profile_id,
            vault_password=get_vault_password(),
            world=current_world,
            characters=characters,
            persona=persona,
            on_job_started=on_job_started,
        )
    except LLMRuntimeError as err:
        notify_setup_llm_runtime_error(err)
        return ""
    except Exception as err:
        notify_on_client(page_client, f"LLMの初期化に失敗しました: {err}", type="negative", timeout=10000)
        return ""
    if finished.status == AIJobStatus.CANCELLED:
        notify_on_client(page_client, "グループ名補完を停止しました", type="info")
        return ""
    if finished.status != AIJobStatus.SUCCEEDED:
        notify_on_client(
            page_client,
            f"グループ名補完に失敗しました: {finished.error_message}",
            type="negative",
            timeout=10000,
        )
        return ""
    name = str(finished.result or "")
    if not name:
        notify_on_client(page_client, "グループ名を補完できませんでした", type="warning")
        return ""
    notify_on_client(page_client, "グループ名を補完しました", type="positive")
    return name


def validate_member_handles(
    characters: list[CharacterSheet],
    handle_inputs: dict[str, Any],
    existing_handles: set[str] | None = None,
) -> list[str] | None:
    handles: list[str] = []
    seen: set[str] = set(existing_handles or set())
    for sheet in characters:
        handle = str(handle_inputs[sheet.id].value or "").strip()
        if not HANDLE_RE.fullmatch(handle):
            ui.notify(f"{sheet.name} のハンドルは3〜12文字の英数字または_で入力してください", type="warning")
            return None
        key = handle.lower()
        if key in seen:
            ui.notify("ハンドルが重複しています", type="warning")
            return None
        seen.add(key)
        handles.append(handle)
    return handles


def validate_handles(
    characters: list[CharacterSheet],
    handle_inputs: dict[str, Any],
    user_handle_input,
) -> tuple[list[str], str] | None:
    handles = validate_member_handles(characters, handle_inputs)
    if handles is None:
        return None
    seen = {handle.lower() for handle in handles}
    user_handle = str(user_handle_input.value or "").strip()
    if not HANDLE_RE.fullmatch(user_handle):
        ui.notify("ユーザーのハンドルは3〜12文字の英数字または_で入力してください", type="warning")
        return None
    if user_handle.lower() in seen:
        ui.notify("ハンドルが重複しています", type="warning")
        return None
    return handles, user_handle
