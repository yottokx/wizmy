"""グループチャットの世界観適応・関係性ダイアログ。"""

from __future__ import annotations

import difflib
import html as _html
from collections.abc import Callable
from typing import Any

from nicegui import ui

from ...core.character.markdown import (
    base_character_markdown as _base_character_markdown,
)
from ...core.character.markdown import (
    sheet_from_markdown_preserving as _sheet_from_markdown_preserving,
)
from ...core.character.schemas import CharacterSheet
from ...core.conversation.prompts.common import compact_character_summary
from ...core.conversation.prompts.group import group_participant_labels, group_user_persona_context
from ...core.conversation.relationship_drafts import (
    next_relationship_draft_id as _next_relationship_draft_id,
)
from ...core.conversation.relationship_drafts import (
    relationship_draft_participants as _relationship_draft_participants,
)
from ...core.conversation.relationship_drafts import (
    upsert_relationship_draft as _upsert_relationship_draft,
)
from ...core.group_chat.schemas import GroupChatRecord, GroupRelationship
from ...services.ai_jobs import AIJobStatus
from ...services.llm_runtime import LLMRuntimeError
from ..state import get_vault_password
from .common import notify_on_client, notify_setup_llm_runtime_error


async def adapt_character_to_world(
    ctx,
    profile_id: str,
    sheet: CharacterSheet,
    world: str,
    additional_instruction: str,
    apply_callback: Callable[[CharacterSheet], None],
    page_client=None,
    on_job_started: Callable[[str], None] | None = None,
) -> None:
    if not world.strip():
        ui.notify("先にワールドを確定してください", type="warning")
        return

    original_markdown = _base_character_markdown(sheet)
    try:
        result = await ctx.group_chat_assist.adapt_character_to_world(
            profile_id=profile_id,
            vault_password=get_vault_password(),
            sheet=sheet,
            world=world,
            additional_instruction=additional_instruction,
            on_job_started=on_job_started,
        )
    except LLMRuntimeError as err:
        notify_setup_llm_runtime_error(err)
        return
    except Exception as err:
        ui.notify(f"LLMの初期化に失敗しました: {err}", type="negative", timeout=10000)
        return
    if result.status == AIJobStatus.CANCELLED:
        notify_on_client(page_client, "キャラクターシート調整を停止しました", type="info")
        return
    if result.status != AIJobStatus.SUCCEEDED:
        notify_on_client(
            page_client,
            f"キャラクターシート調整に失敗しました: {result.error_message}",
            type="negative",
            timeout=10000,
        )
        return
    updated_markdown = str(result.value or "").strip()
    if not updated_markdown:
        notify_on_client(page_client, "キャラクターシートを調整できませんでした", type="warning")
        return
    await open_character_adaptation_preview_dialog(
        sheet,
        original_markdown,
        updated_markdown,
        apply_callback,
        page_client,
    )


async def open_character_adaptation_preview_dialog(
    sheet: CharacterSheet,
    original_markdown: str,
    updated_markdown: str,
    apply_callback: Callable[[CharacterSheet], None],
    page_client=None,
) -> None:
    diff_html = group_diff_html(original_markdown, updated_markdown)
    try:
        if page_client is not None and not getattr(page_client, "_deleted", False):
            with page_client:
                with ui.dialog() as dlg, ui.card().classes("w-full max-w-3xl"):
                    ui.label("キャラクターシート調整の確認").classes("text-base font-semibold")
                    ui.label(f"「{sheet.name}」をワールドに馴染む内容へ変更します。").classes("text-sm text-grey-6")
                    ui.html(diff_html).classes("w-full")

                    def _approve() -> None:
                        updated = _sheet_from_markdown_preserving(sheet, updated_markdown)
                        dlg.close()
                        apply_callback(updated)
                        notify_on_client(page_client, "キャラクターシート調整を反映しました", type="positive")

                    with ui.row().classes("justify-end gap-2 mt-4"):
                        ui.button("キャンセル", on_click=dlg.close).props("flat")
                        ui.button("反映", icon="check", on_click=_approve).props("color=primary unelevated")
                dlg.open()
        else:
            raise RuntimeError("client is not available")
    except RuntimeError:
        notify_on_client(page_client, "調整結果の確認画面を開けませんでした", type="warning")


async def adapt_user_persona_to_world(
    ctx,
    profile_id: str,
    display_name: str,
    description: str,
    world: str,
    additional_instruction: str,
    apply_callback: Callable[[str], None],
    page_client=None,
    on_job_started: Callable[[str], None] | None = None,
) -> None:
    if not world.strip():
        ui.notify("先にワールドを確定してください", type="warning")
        return

    current_description = (description or "").strip()
    try:
        result = await ctx.group_chat_assist.adapt_user_persona_to_world(
            profile_id=profile_id,
            vault_password=get_vault_password(),
            display_name=display_name,
            description=description,
            world=world,
            additional_instruction=additional_instruction,
            on_job_started=on_job_started,
        )
    except LLMRuntimeError as err:
        notify_setup_llm_runtime_error(err)
        return
    except Exception as err:
        ui.notify(f"LLMの初期化に失敗しました: {err}", type="negative", timeout=10000)
        return
    if result.status == AIJobStatus.CANCELLED:
        notify_on_client(page_client, "ユーザーペルソナ調整を停止しました", type="info")
        return
    if result.status != AIJobStatus.SUCCEEDED:
        notify_on_client(
            page_client,
            f"ユーザーペルソナ調整に失敗しました: {result.error_message}",
            type="negative",
            timeout=10000,
        )
        return
    updated_description = str(result.value or "").strip()
    if not updated_description:
        notify_on_client(page_client, "ユーザーペルソナを調整できませんでした", type="warning")
        return
    await open_user_persona_adaptation_preview_dialog(
        display_name,
        current_description,
        updated_description,
        apply_callback,
        page_client,
    )


async def open_user_persona_adaptation_preview_dialog(
    display_name: str,
    current_description: str,
    updated_description: str,
    apply_callback: Callable[[str], None],
    page_client=None,
) -> None:
    diff_html = group_diff_html(current_description, updated_description)
    try:
        if page_client is not None and not getattr(page_client, "_deleted", False):
            with page_client:
                with ui.dialog() as dlg, ui.card().classes("w-full max-w-3xl"):
                    ui.label("ユーザーペルソナ調整の確認").classes("text-base font-semibold")
                    ui.label(f"「{display_name}」をワールドに馴染む説明へ変更します。").classes("text-sm text-grey-6")
                    ui.html(diff_html).classes("w-full")

                    def _approve() -> None:
                        dlg.close()
                        apply_callback(updated_description)
                        notify_on_client(page_client, "ユーザーペルソナ調整を反映しました", type="positive")

                    with ui.row().classes("justify-end gap-2 mt-4"):
                        ui.button("キャンセル", on_click=dlg.close).props("flat")
                        ui.button("反映", icon="check", on_click=_approve).props("color=primary unelevated")
                dlg.open()
        else:
            raise RuntimeError("client is not available")
    except RuntimeError:
        notify_on_client(page_client, "調整結果の確認画面を開けませんでした", type="warning")


def group_diff_html(old_text: str, new_text: str) -> str:
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=2))
    if not diff:
        return "<p style='color:#6b7280;font-style:italic;padding:8px;'>変更なし</p>"
    parts = [
        "<div style='font-family:monospace;font-size:12px;line-height:1.6;white-space:pre-wrap;word-break:break-all;'>"
    ]
    for line in diff:
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("@@"):
            parts.append(
                "<div style='color:#6b7280;background:#f3f4f6;"
                f"padding:2px 6px;border-radius:3px;margin:4px 0;'>{_html.escape(line)}</div>"
            )
        elif line.startswith("+"):
            parts.append(
                f"<div style='background:#dcfce7;color:#166534;padding:1px 6px;'>+ {_html.escape(line[1:])}</div>"
            )
        elif line.startswith("-"):
            parts.append(
                f"<div style='background:#fee2e2;color:#991b1b;padding:1px 6px;'>- {_html.escape(line[1:])}</div>"
            )
        else:
            text = line[1:] if line.startswith(" ") else line
            parts.append(f"<div style='color:#9ca3af;padding:1px 6px;'>&nbsp; {_html.escape(text)}</div>")
    parts.append("</div>")
    return "".join(parts)


async def generate_arrival_reason(
    ctx,
    profile_id: str,
    display_name: str,
    world: str,
    summary: str,
    page_client=None,
    on_job_started: Callable[[str], None] | None = None,
) -> str:
    if not world.strip():
        ui.notify("先にワールドを確定してください", type="warning")
        return ""
    try:
        result = await ctx.group_chat_assist.generate_arrival_reason(
            profile_id=profile_id,
            vault_password=get_vault_password(),
            display_name=display_name,
            world=world,
            summary=summary,
            on_job_started=on_job_started,
        )
    except LLMRuntimeError as err:
        notify_setup_llm_runtime_error(err)
        return ""
    except Exception as err:
        ui.notify(f"LLMの初期化に失敗しました: {err}", type="negative", timeout=10000)
        return ""
    if result.status == AIJobStatus.CANCELLED:
        notify_on_client(page_client, "来訪理由補完を停止しました", type="info")
        return ""
    if result.status != AIJobStatus.SUCCEEDED:
        notify_on_client(
            page_client,
            f"来訪理由補完に失敗しました: {result.error_message}",
            type="negative",
            timeout=10000,
        )
        return ""
    reason = str(result.value or "").strip()
    if not reason:
        notify_on_client(page_client, "来訪理由を補完できませんでした", type="warning")
        return ""
    notify_on_client(page_client, "来訪理由を補完しました", type="positive")
    return reason


def open_relationship_draft_dialog(
    state: dict[str, Any],
    options: dict[str, str],
    relationship: dict[str, str] | None,
    render_step: Callable[[], None],
    *,
    ctx=None,
    profile_id: str = "",
    world: str = "",
    participants: list[dict[str, str]] | None = None,
    page_client=None,
    begin_busy: Callable[[str], None] | None = None,
    set_busy_job: Callable[[str], None] | None = None,
    end_busy: Callable[[], None] | None = None,
) -> None:
    if len(options) < 2:
        ui.notify("関係性を設定できる参加者が足りません", type="warning")
        return
    keys = list(options)
    first_value = relationship["participant_a_key"] if relationship else keys[0]
    second_value = relationship["participant_b_key"] if relationship else keys[1]

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg"):
        ui.label("関係性を編集" if relationship else "関係性を追加").classes("text-base font-semibold")
        first_select = (
            ui.select(
                options=options,
                value=first_value if first_value in options else keys[0],
                label="参加者1",
            )
            .props("outlined dense")
            .classes("w-full")
        )
        second_select = (
            ui.select(
                options=options,
                value=second_value if second_value in options else keys[1],
                label="参加者2",
            )
            .props("outlined dense")
            .classes("w-full")
        )
        with ui.element("div").classes("cs-group-world-field"):
            description_input = (
                ui.textarea(
                    label="関係性",
                    value=relationship["description"] if relationship else "",
                    placeholder="例: 幼なじみだが、現在は互いに距離を測っている。",
                )
                .props("outlined rows=5")
                .classes("w-full")
            )

            async def _enhance_relationship_click() -> None:
                if ctx is None:
                    return
                if begin_busy is not None:
                    begin_busy("関係性を補完しています...")
                try:
                    enhanced = await enhance_relationship_description(
                        ctx,
                        profile_id,
                        world,
                        participants or [],
                        str(first_select.value or ""),
                        str(second_select.value or ""),
                        str(description_input.value or ""),
                        page_client,
                        on_job_started=set_busy_job,
                    )
                    if enhanced:
                        description_input.set_value(enhanced)
                finally:
                    if end_busy is not None:
                        end_busy()

            ui.button(
                icon="auto_awesome",
                on_click=_enhance_relationship_click,
            ).props("flat round dense size=sm").classes("cs-group-world-enhance").tooltip("関係性を補完")

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
            item = {
                "id": relationship["id"] if relationship else _next_relationship_draft_id(state),
                "participant_a_key": first_key,
                "participant_b_key": second_key,
                "description": description,
            }
            _upsert_relationship_draft(state, item)
            dlg.close()
            render_step()

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", icon="save", on_click=_save).props("color=primary unelevated")
    dlg.open()


async def enhance_relationship_description(
    ctx,
    profile_id: str,
    world: str,
    participants: list[dict[str, str]],
    first_key: str,
    second_key: str,
    current_description: str,
    page_client=None,
    on_job_started: Callable[[str], None] | None = None,
) -> str:
    current = current_description.strip()
    if not current:
        ui.notify("先に関係性を入力してください", type="warning")
        return ""
    if not first_key or not second_key:
        ui.notify("参加者を選択してください", type="warning")
        return ""
    if first_key == second_key:
        ui.notify("異なる2人を選択してください", type="warning")
        return ""
    try:
        result = await ctx.group_chat_assist.enhance_relationship_description(
            profile_id=profile_id,
            vault_password=get_vault_password(),
            world=world,
            participants=participants,
            first_key=first_key,
            second_key=second_key,
            current_description=current,
            on_job_started=on_job_started,
        )
    except LLMRuntimeError as err:
        notify_setup_llm_runtime_error(err)
        return ""
    except Exception as err:
        ui.notify(f"LLMの初期化に失敗しました: {err}", type="negative", timeout=10000)
        return ""
    if result.status == AIJobStatus.CANCELLED:
        notify_on_client(page_client, "関係性補完を停止しました", type="info")
        return ""
    if result.status != AIJobStatus.SUCCEEDED:
        notify_on_client(
            page_client,
            f"関係性補完に失敗しました: {result.error_message}",
            type="negative",
            timeout=10000,
        )
        return ""
    enhanced = str(result.value or "").strip()
    if not enhanced:
        notify_on_client(page_client, "関係性を補完できませんでした", type="warning")
        return ""
    notify_on_client(page_client, "関係性を補完しました", type="positive")
    return enhanced


def delete_relationship_draft(
    state: dict[str, Any],
    relationship_id: str,
    render_step: Callable[[], None],
) -> None:
    state["relationships"] = [item for item in state.get("relationships", []) if str(item.get("id")) != relationship_id]
    render_step()


async def generate_relationship_drafts(
    ctx,
    profile_id: str,
    characters: list[CharacterSheet],
    persona,
    world: str,
    state: dict[str, Any],
    page_client=None,
    on_job_started: Callable[[str], None] | None = None,
) -> list[dict[str, str]]:
    participants = _relationship_draft_participants(characters, persona, state)
    if len(participants) < 2:
        ui.notify("関係性を自動設定できる参加者が足りません", type="warning")
        return []
    try:
        result = await ctx.group_chat_assist.generate_relationship_drafts(
            profile_id=profile_id,
            vault_password=get_vault_password(),
            characters=characters,
            persona=persona,
            world=world,
            state=state,
            on_job_started=on_job_started,
        )
    except LLMRuntimeError as err:
        notify_setup_llm_runtime_error(err)
        return []
    except Exception as err:
        ui.notify(f"LLMの初期化に失敗しました: {err}", type="negative", timeout=10000)
        return []
    if result.status == AIJobStatus.CANCELLED:
        notify_on_client(page_client, "関係性自動設定を停止しました", type="info")
        return []
    if result.status != AIJobStatus.SUCCEEDED:
        notify_on_client(
            page_client,
            f"関係性自動設定に失敗しました: {result.error_message}",
            type="negative",
            timeout=10000,
        )
        return []
    generated = list(result.value or [])
    if not generated:
        notify_on_client(page_client, "関係性を自動設定できませんでした", type="warning")
        return []
    for item in generated:
        item["id"] = _next_relationship_draft_id(state)
    notify_on_client(page_client, "関係性を自動設定しました", type="positive")
    return generated


def group_relationship_options(group: GroupChatRecord) -> dict[str, str]:
    return group_participant_labels(group)


def group_relationship_enhancement_participants(group: GroupChatRecord) -> list[dict[str, str]]:
    participants = [
        {
            "key": f"member:{member.id}",
            "id": member.id,
            "name": member.character.name,
            "summary": compact_character_summary(member.character),
            "kind": "character",
            "world_entry_type": member.world_entry_type,
            "arrival_reason": member.arrival_reason,
            "adaptation_note": member.world_adaptation_note,
        }
        for member in group.members
    ]
    if group.user_persona is not None:
        user = group.user_persona
        participants.append(
            {
                "key": f"user:{user.id}",
                "id": user.id,
                "name": user.display_name or user.name or "ユーザー",
                "summary": group_user_persona_context(user),
                "kind": "user_persona",
                "world_entry_type": user.world_entry_type,
                "arrival_reason": user.arrival_reason,
                "adaptation_note": user.world_adaptation_note,
            }
        )
    return participants


def open_group_relationship_dialog(
    ctx,
    group: GroupChatRecord,
    relationship: GroupRelationship | None,
    on_group_updated: Callable[[GroupChatRecord], None] | None,
) -> None:
    options = group_relationship_options(group)
    if len(options) < 2:
        ui.notify("関係性を設定できる参加者が足りません", type="warning")
        return
    default_keys = list(options)
    first_value = relationship.participant_a_key if relationship else default_keys[0]
    second_value = relationship.participant_b_key if relationship else default_keys[1]

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg"):
        ui.label("関係性を編集" if relationship else "関係性を追加").classes("text-base font-semibold")
        first_select = (
            ui.select(
                options=options,
                value=first_value if first_value in options else default_keys[0],
                label="参加者1",
            )
            .props("outlined dense")
            .classes("w-full")
        )
        second_select = (
            ui.select(
                options=options,
                value=second_value if second_value in options else default_keys[1],
                label="参加者2",
            )
            .props("outlined dense")
            .classes("w-full")
        )
        with ui.element("div").classes("cs-group-world-field"):
            description_input = (
                ui.textarea(
                    label="関係性",
                    value=relationship.description if relationship else "",
                    placeholder="例: 幼なじみだが、現在は互いに距離を測っている。",
                )
                .props("outlined rows=5")
                .classes("w-full")
            )

            async def _enhance_relationship_click() -> None:
                enhanced = await enhance_relationship_description(
                    ctx,
                    group.completion_profile_id,
                    group.world,
                    group_relationship_enhancement_participants(group),
                    str(first_select.value or ""),
                    str(second_select.value or ""),
                    str(description_input.value or ""),
                )
                if enhanced:
                    description_input.set_value(enhanced)

            ui.button(
                icon="auto_awesome",
                on_click=_enhance_relationship_click,
            ).props("flat round dense size=sm").classes("cs-group-world-enhance").tooltip("関係性を補完")

        async def _save() -> None:
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
            saved = await ctx.group_chats.save_relationship(
                group.id,
                GroupRelationship(
                    id=relationship.id if relationship else "",
                    participant_a_key=first_key,
                    participant_b_key=second_key,
                    description=description,
                ),
            )
            if saved is None:
                ui.notify("グループが見つかりませんでした", type="warning")
                return
            dlg.close()
            ui.notify("関係性を保存しました", type="positive")
            if on_group_updated is not None:
                on_group_updated(saved)

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", icon="save", on_click=_save).props("color=primary unelevated")
    dlg.open()


async def delete_group_relationship(
    ctx,
    group: GroupChatRecord,
    relationship_id: str,
    on_group_updated: Callable[[GroupChatRecord], None] | None,
) -> None:
    saved = await ctx.group_chats.delete_relationship(group.id, relationship_id)
    if saved is None:
        ui.notify("グループが見つかりませんでした", type="warning")
        return
    ui.notify("関係性を削除しました", type="positive")
    if on_group_updated is not None:
        on_group_updated(saved)
