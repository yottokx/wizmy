"""グループチャット詳細コントローラ用ダイアログ。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from nicegui import ui

from ...core.conversation.history import (
    group_participant_ids,
    group_system_event_message,
    settings_with_participant,
)
from ...core.conversation.prompts.group import build_group_system_prompt
from ...core.conversation.sanitize import (
    clean_guest_name,
    guest_display_name,
    guest_name_from_actor_text,
)
from ...core.group_chat.schemas import GroupMember
from ...core.group_chat.sessions import DEFAULT_GROUP_CHAT_TITLE
from .common import (
    default_profile_id as _default_profile_id,
    profile_options as _profile_options,
)
from .rendering import (
    group_message_target_label as _group_message_target_label,
    render_face as _render_face,
    render_group_member_menu_face as _render_group_member_menu_face,
    render_group_role_icon as _render_group_role_icon,
    render_group_user_menu_face as _render_group_user_menu_face,
)

if TYPE_CHECKING:
    from .controller import GroupChatPageController


def _guest_prefix_completion(value: str) -> dict[str, Any] | None:
    query = (value or "").strip().lower()
    if not query or query.startswith("@"):
        return None
    if query == "guest:" or not "guest:".startswith(query):
        return None
    return {
        "value": "guest:",
        "label": "guest:",
        "state": "ゲスト",
        "kind": "guest",
        "icon": "person_add",
        "member": None,
    }


def _position_group_actor_suggestions() -> None:
    ui.run_javascript(
        """
requestAnimationFrame(() => {
  document.querySelectorAll('.cs-group-guide-actor-wrap').forEach(root => {
    const box = root.querySelector('.cs-group-guide-suggestions:not(.hidden)');
    const field = root.querySelector('.q-field');
    if (!box || !field) return;
    const rect = field.getBoundingClientRect();
    const margin = 8;
    const width = Math.max(220, Math.min(rect.width, window.innerWidth - margin * 2));
    const left = Math.max(margin, Math.min(rect.left, window.innerWidth - width - margin));
    const top = Math.min(rect.bottom + 4, window.innerHeight - margin);
    box.style.setProperty('--cs-guide-suggestion-left', `${left}px`);
    box.style.setProperty('--cs-guide-suggestion-top', `${top}px`);
    box.style.setProperty('--cs-guide-suggestion-width', `${width}px`);
  });
});
"""
    )


def open_guest_input_mode_dialog(controller: "GroupChatPageController", left_text: str = "") -> None:
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm"):
        ui.label("ゲスト入力").classes("text-base font-semibold")
        name_input = (
            ui.input(
                label="ゲスト名",
                value=controller.guest_input_name,
                placeholder="例: 酒場のマスター",
            )
            .props("outlined dense clearable")
            .classes("w-full")
        )

        def _apply() -> None:
            name = clean_guest_name(str(name_input.value or ""))
            if not name:
                ui.notify("ゲスト名を入力してください", type="warning")
                return
            controller.set_guest_input_mode(name)
            if left_text:
                controller.set_input_value(left_text.rstrip())
            controller.focus_chat_input_at_end()
            dlg.close()
            ui.notify(f"{guest_display_name(name)}入力モードにしました", type="info")

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("選択", icon="person_add", on_click=_apply).props("color=primary unelevated")
    dlg.open()
    ui.timer(0.1, lambda: name_input.run_method("focus"), once=True)


def confirm_rewind_to_message(controller: "GroupChatPageController", index: int) -> None:
    if controller.sending:
        ui.notify("生成中は戻れません", type="warning")
        return
    if index < 0 or index >= len(controller.messages):
        return
    message = controller.messages[index]
    role = str(message.get("role", ""))
    if role not in {"character", "guest", "user", "narration", "memo"}:
        return

    target_label = _group_message_target_label(role)
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm"):
        ui.label(f"この{target_label}まで戻りますか？").classes("text-base font-semibold")
        ui.label(f"この{target_label}以降の会話を削除し、本文を入力欄に戻します。").classes("text-sm text-grey-6")
        ui.label(str(message.get("text", ""))).classes("text-sm").style(
            "white-space: pre-wrap; overflow-wrap: anywhere;"
        )

        async def _do_rewind() -> None:
            dlg.close()
            await controller.rewind_to_message(index)

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("OK", icon="undo", on_click=_do_rewind).props("color=primary unelevated")
    dlg.open()


def open_rewrite_message_dialog(controller: "GroupChatPageController", index: int) -> None:
    if controller.sending:
        ui.notify("生成中は書き換えできません", type="warning")
        return
    if index < 0 or index >= len(controller.messages):
        return
    message = controller.messages[index]
    role = str(message.get("role", ""))
    if role not in {"character", "guest", "user", "narration", "memo"}:
        return
    speaker_label = _group_message_target_label(role)

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-xl"):
        ui.label(f"{speaker_label}を書き換え").classes("text-base font-semibold")
        ui.label("保存しても、この後の会話は削除されません。").classes("text-sm text-grey-6")
        rewrite_input = (
            ui.textarea(
                value=str(message.get("text", "")),
                placeholder="書き換え後の本文",
            )
            .props("outlined rows=5 autogrow")
            .classes("w-full")
        )

        async def _save_rewrite() -> None:
            next_text = (rewrite_input.value or "").strip()
            if not next_text:
                ui.notify("本文を入力してください", type="warning")
                return
            if index >= len(controller.messages):
                dlg.close()
                return
            controller.messages[index]["text"] = next_text
            dlg.close()
            controller.refresh_messages()
            await controller.save_current_session()

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", icon="save", on_click=_save_rewrite).props("color=primary unelevated")
    dlg.open()


async def confirm_or_regenerate_character_message(controller: "GroupChatPageController", index: int) -> None:
    if controller.sending:
        ui.notify("生成中は再生成できません", type="warning")
        return
    if index < 0 or index >= len(controller.messages):
        return
    if controller.messages[index].get("role") != "character":
        return
    if index == len(controller.messages) - 1:
        await controller.regenerate_character_message(index)
        return

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm"):
        ui.label("この台詞から再生成しますか？").classes("text-base font-semibold")
        ui.label("この台詞以降の会話を削除してから、新しい台詞を生成します。").classes("text-sm text-grey-6")
        ui.label(str(controller.messages[index].get("text", ""))).classes("text-sm").style(
            "white-space: pre-wrap; overflow-wrap: anywhere;"
        )

        async def _do_regenerate() -> None:
            dlg.close()
            await controller.regenerate_character_message(index)

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("再生成", icon="refresh", on_click=_do_regenerate).props("color=primary unelevated")
    dlg.open()


async def open_guide_next_turn_dialog(controller: "GroupChatPageController", left_text: str = "") -> None:
    if left_text.strip():
        controller.set_input_value(left_text)
    else:
        controller.clear_input()

    active = controller.active_members()
    active_ids = {member.id for member in active}
    inactive = [member for member in controller.group.members if member.id not in active_ids]
    departure_state = {"value": False}
    departure_checkbox: dict[str, Any] = {"ref": None}
    actor_value_syncing = {"active": False}
    guide_targets = {
        "character": ("キャラクター（自動）", "character", "theater_comedy"),
        "narrative": ("地の文", "narration", "auto_stories"),
        "user": ("ユーザー", "user", "person"),
    }

    def _resolve_actor_input(value: str) -> dict[str, Any] | None:
        raw = (value or "").strip()
        lowered = raw.lower()
        guest_name = guest_name_from_actor_text(raw)
        if guest_name:
            return {
                "kind": "guest",
                "active": False,
                "member": None,
                "guest_name": guest_name,
                "label": guest_display_name(guest_name),
            }
        if lowered in {"character", "char", "キャラ", "キャラクター", "キャラクター（自動）"}:
            return {"kind": "auto", "active": False, "member": None, "label": "キャラクター（自動）"}
        if lowered in {"narrative", "narration", "地の文", "ナラティブ"}:
            return {"kind": "narration", "active": False, "member": None, "label": "地の文"}
        if lowered in {"user", "ユーザー"}:
            return {"kind": "user", "active": False, "member": None, "label": "ユーザー"}
        identifier = lowered.removeprefix("@")
        for member in controller.group.members:
            if member.handle.lower() == identifier:
                return {
                    "kind": "member",
                    "active": member.id in active_ids,
                    "member": member,
                    "label": f"{member.character.name} / @{member.handle}",
                }
            if raw and member.character.name == raw:
                return {
                    "kind": "member",
                    "active": member.id in active_ids,
                    "member": member,
                    "label": f"{member.character.name} / @{member.handle}",
                }
        return None

    def _actor_display_value(resolved: dict[str, Any]) -> str:
        member = resolved.get("member")
        if isinstance(member, GroupMember):
            return member.character.name
        if resolved.get("kind") == "guest":
            return guest_display_name(str(resolved.get("guest_name") or ""))
        return str(resolved.get("label") or "")

    def _actor_suggestions(value: str) -> list[dict[str, Any]]:
        raw = (value or "").strip()
        if not raw:
            return []
        resolved = _resolve_actor_input(raw)
        if resolved is not None:
            return []
        query = raw.lower().removeprefix("@")
        suggestions: list[dict[str, Any]] = []
        if not raw.startswith("@"):
            guest_suggestion = _guest_prefix_completion(raw)
            if guest_suggestion is not None:
                suggestions.append(guest_suggestion)
            for token, (label, kind, icon) in guide_targets.items():
                if token.startswith(query):
                    suggestions.append(
                        {
                            "value": token,
                            "label": label,
                            "state": "ロール",
                            "kind": kind,
                            "icon": icon,
                            "member": None,
                        }
                    )
        if raw.startswith("@"):
            for member in controller.group.members:
                if (
                    not query
                    or member.handle.lower().startswith(query)
                    or member.character.name.lower().startswith(query)
                ):
                    suggestions.append(
                        {
                            "value": f"@{member.handle}",
                            "label": f"{member.character.name} / @{member.handle}",
                            "state": "参加済み" if member.id in active_ids else "未参加",
                            "kind": "member",
                            "icon": "",
                            "member": member,
                        }
                    )
        return suggestions[:8]

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-2xl"):
        ui.label("次の行動").classes("text-base font-semibold")
        ui.label("行動者").classes("text-xs font-semibold text-grey-6")
        with ui.element("div").classes("cs-group-guide-actor-row"):
            with (
                ui.button().props("flat dense unelevated aria-label=行動者を選択").classes("cs-group-guide-actor-icon")
            ):
                actor_icon = ui.element("div").classes("cs-group-guide-actor-icon-content")
                with ui.menu().classes("cs-chat-mode-menu") as target_menu:
                    with ui.element("button").props("type=button").classes("cs-group-menu-parent"):
                        _render_group_role_icon("character")
                        ui.label("キャラ").classes("cs-group-menu-option-label")
                        ui.icon("chevron_right").classes("text-grey-6")
                        with (
                            ui.menu()
                            .props('anchor="top end" self="top start"')
                            .classes("cs-chat-mode-menu cs-group-character-submenu") as active_menu
                        ):
                            with (
                                ui.element("button")
                                .props("type=button")
                                .classes("cs-group-menu-option")
                                .on("click", lambda _: _choose_actor("character", active_menu))
                            ):
                                _render_group_role_icon("character")
                                ui.label("自動").classes("cs-group-menu-option-label")
                                ui.element("span")
                            if not active:
                                ui.label("参加済みキャラクターはいません").classes("text-xs text-grey-6 px-3 py-2")
                            for member in active:
                                with (
                                    ui.element("button")
                                    .props("type=button")
                                    .classes("cs-group-menu-option")
                                    .on(
                                        "click",
                                        lambda _, member=member: _choose_actor(
                                            f"@{member.handle}",
                                            active_menu,
                                        ),
                                    )
                                ):
                                    _render_group_member_menu_face(controller.ctx, member)
                                    ui.label(f"{member.character.name} / @{member.handle}").classes(
                                        "cs-group-menu-option-label"
                                    )
                                    ui.element("span")
                            with (
                                ui.element("button")
                                .props("type=button")
                                .classes("cs-group-menu-option")
                                .on("click", lambda _: _open_guest_actor_dialog(active_menu))
                            ):
                                _render_group_role_icon("guest")
                                ui.label("ゲスト").classes("cs-group-menu-option-label")
                                ui.element("span")
                    with ui.element("button").props("type=button").classes("cs-group-menu-parent"):
                        _render_group_role_icon("character")
                        ui.label("未参加キャラ").classes("cs-group-menu-option-label")
                        ui.icon("chevron_right").classes("text-grey-6")
                        with (
                            ui.menu()
                            .props('anchor="top end" self="top start"')
                            .classes("cs-chat-mode-menu cs-group-character-submenu") as inactive_menu
                        ):
                            if not inactive:
                                ui.label("未参加キャラクターはいません").classes("text-xs text-grey-6 px-3 py-2")
                            for member in inactive:
                                with (
                                    ui.element("button")
                                    .props("type=button")
                                    .classes("cs-group-menu-option")
                                    .on(
                                        "click",
                                        lambda _, member=member: _choose_actor(
                                            f"@{member.handle}",
                                            inactive_menu,
                                        ),
                                    )
                                ):
                                    _render_group_member_menu_face(controller.ctx, member)
                                    ui.label(f"{member.character.name} / @{member.handle}").classes(
                                        "cs-group-menu-option-label"
                                    )
                                    ui.element("span")
                    with (
                        ui.element("button")
                        .props("type=button")
                        .classes("cs-group-menu-option")
                        .on("click", lambda _: _choose_actor("narrative"))
                    ):
                        _render_group_role_icon("narration")
                        ui.label("地の文").classes("cs-group-menu-option-label")
                        ui.element("span")
                    with (
                        ui.element("button")
                        .props("type=button")
                        .classes("cs-group-menu-option")
                        .on("click", lambda _: _choose_actor("user"))
                    ):
                        _render_group_user_menu_face(controller.ctx, controller.group.user_persona)
                        ui.label("ユーザー").classes("cs-group-menu-option-label")
                        ui.element("span")
            with ui.element("div").classes("cs-group-guide-actor-wrap"):
                actor_input = (
                    ui.input(
                        value="",
                        placeholder="@handle / character / narrative / user / guest:",
                    )
                    .props("outlined dense clearable")
                    .classes("w-full")
                )
                suggestion_box = ui.element("div").classes("cs-group-guide-suggestions hidden")
        direction_input = (
            ui.textarea(
                label="指示",
                placeholder="キャラまたは地の文にだけ反映する任意の指示",
            )
            .props("outlined rows=4 autogrow")
            .classes("w-full")
        )
        departure_container = ui.element("div").classes("w-full")

        def _choose_actor(value: str, menu_to_close=None) -> None:
            resolved = _resolve_actor_input(value)
            actor_input.set_value(_actor_display_value(resolved) if resolved is not None else value)
            suggestion_box.classes("hidden")
            if menu_to_close is not None:
                menu_to_close.close()
            target_menu.close()
            _sync_actor_controls()

        def _open_guest_actor_dialog(menu_to_close=None) -> None:
            with ui.dialog() as guest_dialog, ui.card().classes("w-full max-w-sm"):
                ui.label("ゲストを指定").classes("text-base font-semibold")
                guest_name_input = (
                    ui.input(
                        label="ゲスト名",
                        placeholder="例: 酒場のマスター",
                    )
                    .props("outlined dense clearable")
                    .classes("w-full")
                )

                def _apply_guest() -> None:
                    name = clean_guest_name(str(guest_name_input.value or ""))
                    if not name:
                        ui.notify("ゲスト名を入力してください", type="warning")
                        return
                    guest_dialog.close()
                    _choose_actor(guest_display_name(name), menu_to_close)

                with ui.row().classes("justify-end gap-2 mt-4"):
                    ui.button("キャンセル", on_click=guest_dialog.close).props("flat")
                    ui.button("選択", icon="person_add", on_click=_apply_guest).props("color=primary unelevated")
            guest_dialog.open()
            ui.timer(0.1, lambda: guest_name_input.run_method("focus"), once=True)

        def _render_suggestions() -> None:
            suggestions = _actor_suggestions(str(actor_input.value or ""))
            suggestion_box.clear()
            if not suggestions:
                suggestion_box.classes("hidden")
                return
            suggestion_box.classes(remove="hidden")
            with suggestion_box:
                for index, suggestion in enumerate(suggestions):
                    classes = "cs-group-guide-suggestion"
                    if index == 0:
                        classes += " cs-group-guide-suggestion-active"
                    with (
                        ui.element("button")
                        .props("type=button")
                        .classes(classes)
                        .on(
                            "click",
                            lambda _, value=suggestion["value"]: _choose_actor(value),
                        )
                    ):
                        member = suggestion.get("member")
                        if isinstance(member, GroupMember):
                            _render_group_member_menu_face(controller.ctx, member)
                        else:
                            _render_group_role_icon(str(suggestion.get("kind") or "user"))
                        ui.label(str(suggestion["label"])).classes("cs-group-guide-suggestion-label")
                        ui.label(str(suggestion["state"])).classes("cs-group-guide-suggestion-state")
            _position_group_actor_suggestions()

        def _render_actor_icon(resolved: dict[str, Any] | None) -> None:
            actor_icon.clear()
            with actor_icon:
                if resolved is None:
                    ui.icon("help_outline").classes("text-sm")
                    return
                member = resolved.get("member")
                if isinstance(member, GroupMember):
                    _render_group_member_menu_face(controller.ctx, member)
                    return
                kind = str(resolved.get("kind") or "")
                if kind == "auto":
                    _render_group_role_icon("character")
                elif kind == "guest":
                    _render_group_role_icon("guest")
                elif kind == "narration":
                    _render_group_role_icon("narration")
                elif kind == "user":
                    _render_group_user_menu_face(controller.ctx, controller.group.user_persona)
                else:
                    ui.icon("help_outline").classes("text-sm")

        def _sync_actor_controls() -> None:
            if actor_value_syncing["active"]:
                return
            raw_actor_value = str(actor_input.value or "")
            resolved = _resolve_actor_input(raw_actor_value)
            if resolved is not None:
                display_value = _actor_display_value(resolved)
                is_typing_guest_prefix = (
                    resolved.get("kind") == "guest"
                    and re.match(r"^\s*guest\s*[:：]", raw_actor_value, flags=re.IGNORECASE) is not None
                )
                if not is_typing_guest_prefix and raw_actor_value.strip() != display_value:
                    actor_value_syncing["active"] = True
                    actor_input.set_value(display_value)
                    actor_value_syncing["active"] = False
            _render_actor_icon(resolved)
            departure_container.clear()
            if resolved is None:
                departure_state["value"] = False
                direction_input.enable()
                _render_suggestions()
                return
            if resolved["kind"] == "user":
                departure_state["value"] = False
                direction_input.set_value("")
                direction_input.disable()
            else:
                direction_input.enable()
            if resolved["kind"] == "member" and resolved["active"]:
                with departure_container:
                    checkbox = ui.checkbox(
                        "退場させる",
                        value=departure_state["value"],
                    )
                    departure_checkbox["ref"] = checkbox
                    checkbox.on_value_change(lambda e: departure_state.update({"value": bool(e.value)}))
            else:
                departure_state["value"] = False
                departure_checkbox["ref"] = None
            _render_suggestions()

        actor_input.on_value_change(lambda _: _sync_actor_controls())
        actor_input.on(
            "keydown",
            js_handler="""
event => {
  const root = event.target.closest('.cs-group-guide-actor-wrap');
  const box = root ? root.querySelector('.cs-group-guide-suggestions:not(.hidden)') : null;
  const options = box ? Array.from(box.querySelectorAll('.cs-group-guide-suggestion')) : [];
  if (!options.length) return;
  const activeIndex = () => Math.max(0, options.findIndex(option => option.classList.contains('cs-group-guide-suggestion-active')));
  const setActive = index => {
options.forEach((option, current) => {
  const active = current === index;
  option.classList.toggle('cs-group-guide-suggestion-active', active);
  option.setAttribute('aria-selected', active ? 'true' : 'false');
  if (active) option.scrollIntoView({ block: 'nearest' });
});
  };
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
event.preventDefault();
const delta = event.key === 'ArrowDown' ? 1 : -1;
setActive((activeIndex() + delta + options.length) % options.length);
return;
  }
  if (event.key === 'Enter') {
event.preventDefault();
(options[activeIndex()] || options[0]).click();
return;
  }
  if (event.key === 'Escape') {
box.classList.add('hidden');
  }
}
""",
        )

        async def _run_directed_turn() -> None:
            direction = (direction_input.value or "").strip()
            resolved = _resolve_actor_input(str(actor_input.value or ""))
            if resolved is None:
                ui.notify("行動者を指定してください", type="warning")
                return
            dlg.close()
            if resolved["kind"] == "user":
                if left_text.strip():
                    controller.clear_input()
                    await controller.post_hold_user_text(left_text.strip())
                else:
                    controller.clear_input()
                    controller.set_input_mode("user")
                return
            if resolved["kind"] == "narration":
                await controller.run_describe_action(left_text, instruction=direction)
                return
            if left_text.strip():
                await controller.post_command_left_text(left_text)
            else:
                controller.clear_input()
            if resolved["kind"] == "auto":
                await controller.append_character_turn(turn_instruction=direction)
                return
            if resolved["kind"] == "guest":
                await controller.append_guest_turn(
                    str(resolved.get("guest_name") or ""),
                    turn_instruction=direction,
                )
                return
            member = resolved.get("member")
            if not isinstance(member, GroupMember):
                ui.notify("行動者を指定してください", type="warning")
                return
            if not resolved["active"]:
                await controller.append_guided_member_turn(
                    member,
                    turn_instruction=direction,
                    membership_action="join",
                )
                return
            if departure_state["value"]:
                await controller.append_guided_member_turn(
                    member,
                    turn_instruction=direction,
                    membership_action="leave",
                )
                return
            await controller.append_character_turn(
                speaker=member,
                turn_instruction=direction,
            )

        _sync_actor_controls()
        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("実行", icon="play_arrow", on_click=_run_directed_turn).props("color=primary unelevated")
    dlg.open()
    ui.timer(0.1, lambda: actor_input.run_method("focus"), once=True)


def open_imitate_character_dialog(controller: "GroupChatPageController", left_text: str = "") -> None:
    active = controller.active_members()
    active_ids = {member.id for member in active}
    inactive = [member for member in controller.group.members if member.id not in active_ids]
    actor_value_syncing = {"active": False}

    def _resolve_actor_input(value: str) -> dict[str, Any] | None:
        raw = (value or "").strip()
        guest_name = guest_name_from_actor_text(raw)
        if guest_name:
            return {
                "kind": "guest",
                "member": None,
                "active": False,
                "guest_name": guest_name,
                "label": guest_display_name(guest_name),
            }
        identifier = raw.lower().removeprefix("@")
        for member in controller.group.members:
            if member.handle.lower() == identifier or member.character.name == raw:
                return {
                    "kind": "member",
                    "member": member,
                    "active": member.id in active_ids,
                    "label": f"{member.character.name} / @{member.handle}",
                }
        return None

    def _actor_display_value(resolved: dict[str, Any]) -> str:
        member = resolved.get("member")
        if isinstance(member, GroupMember):
            return member.character.name
        if resolved.get("kind") == "guest":
            return guest_display_name(str(resolved.get("guest_name") or ""))
        return str(resolved.get("label") or "")

    def _actor_suggestions(value: str) -> list[dict[str, Any]]:
        raw = (value or "").strip()
        if not raw or _resolve_actor_input(raw) is not None:
            return []
        query = raw.lower().removeprefix("@")
        suggestions: list[dict[str, Any]] = []
        if not raw.startswith("@"):
            guest_suggestion = _guest_prefix_completion(raw)
            if guest_suggestion is not None:
                suggestions.append(guest_suggestion)
        if raw.startswith("@"):
            for member in controller.group.members:
                if (
                    not query
                    or member.handle.lower().startswith(query)
                    or member.character.name.lower().startswith(query)
                ):
                    suggestions.append(
                        {
                            "value": f"@{member.handle}",
                            "label": f"{member.character.name} / @{member.handle}",
                            "state": "参加済み" if member.id in active_ids else "未参加",
                            "kind": "member",
                            "member": member,
                        }
                    )
        return suggestions[:8]

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-2xl"):
        ui.label("キャラクター入力").classes("text-base font-semibold")
        ui.label("発言者").classes("text-xs font-semibold text-grey-6")
        with ui.element("div").classes("cs-group-guide-actor-row"):
            with (
                ui.button().props("flat dense unelevated aria-label=発言者を選択").classes("cs-group-guide-actor-icon")
            ):
                actor_icon = ui.element("div").classes("cs-group-guide-actor-icon-content")
                with ui.menu().classes("cs-chat-mode-menu") as actor_menu:
                    with ui.element("button").props("type=button").classes("cs-group-menu-parent"):
                        _render_group_role_icon("character")
                        ui.label("キャラ").classes("cs-group-menu-option-label")
                        ui.icon("chevron_right").classes("text-grey-6")
                        with (
                            ui.menu()
                            .props('anchor="top end" self="top start"')
                            .classes("cs-chat-mode-menu cs-group-character-submenu") as character_menu
                        ):
                            if not active:
                                ui.label("参加済みキャラクターはいません").classes("text-xs text-grey-6 px-3 py-2")
                            for member in active:
                                with (
                                    ui.element("button")
                                    .props("type=button")
                                    .classes("cs-group-menu-option")
                                    .on(
                                        "click",
                                        lambda _, member=member: _choose_actor(
                                            f"@{member.handle}",
                                            character_menu,
                                        ),
                                    )
                                ):
                                    _render_group_member_menu_face(controller.ctx, member)
                                    ui.label(f"{member.character.name} / @{member.handle}").classes(
                                        "cs-group-menu-option-label"
                                    )
                                    ui.element("span")
                            if inactive:
                                for member in inactive:
                                    with (
                                        ui.element("button")
                                        .props("type=button")
                                        .classes("cs-group-menu-option")
                                        .on(
                                            "click",
                                            lambda _, member=member: _choose_actor(
                                                f"@{member.handle}",
                                                character_menu,
                                            ),
                                        )
                                    ):
                                        _render_group_member_menu_face(controller.ctx, member)
                                        ui.label(f"{member.character.name} / @{member.handle}").classes(
                                            "cs-group-menu-option-label"
                                        )
                                        ui.label("未参加").classes("text-xs text-grey-6")
                            with (
                                ui.element("button")
                                .props("type=button")
                                .classes("cs-group-menu-option")
                                .on("click", lambda _: _open_guest_actor_dialog(character_menu))
                            ):
                                _render_group_role_icon("guest")
                                ui.label("ゲスト").classes("cs-group-menu-option-label")
                                ui.element("span")
            with ui.element("div").classes("cs-group-guide-actor-wrap"):
                actor_input = (
                    ui.input(
                        value="",
                        placeholder="@handle / guest:酒場のマスター",
                    )
                    .props("outlined dense clearable")
                    .classes("w-full")
                )
                suggestion_box = ui.element("div").classes("cs-group-guide-suggestions hidden")

        def _choose_actor(value: str, menu_to_close=None) -> None:
            resolved = _resolve_actor_input(value)
            actor_input.set_value(_actor_display_value(resolved) if resolved is not None else value)
            suggestion_box.classes("hidden")
            if menu_to_close is not None:
                menu_to_close.close()
            actor_menu.close()
            _sync_actor_controls()

        def _open_guest_actor_dialog(menu_to_close=None) -> None:
            with ui.dialog() as guest_dialog, ui.card().classes("w-full max-w-sm"):
                ui.label("ゲストを指定").classes("text-base font-semibold")
                guest_name_input = (
                    ui.input(
                        label="ゲスト名",
                        placeholder="例: 酒場のマスター",
                    )
                    .props("outlined dense clearable")
                    .classes("w-full")
                )

                def _apply_guest() -> None:
                    name = clean_guest_name(str(guest_name_input.value or ""))
                    if not name:
                        ui.notify("ゲスト名を入力してください", type="warning")
                        return
                    guest_dialog.close()
                    _choose_actor(guest_display_name(name), menu_to_close)

                with ui.row().classes("justify-end gap-2 mt-4"):
                    ui.button("キャンセル", on_click=guest_dialog.close).props("flat")
                    ui.button("選択", icon="person_add", on_click=_apply_guest).props("color=primary unelevated")
            guest_dialog.open()
            ui.timer(0.1, lambda: guest_name_input.run_method("focus"), once=True)

        def _render_suggestions() -> None:
            suggestions = _actor_suggestions(str(actor_input.value or ""))
            suggestion_box.clear()
            if not suggestions:
                suggestion_box.classes("hidden")
                return
            suggestion_box.classes(remove="hidden")
            with suggestion_box:
                for index, suggestion in enumerate(suggestions):
                    classes = "cs-group-guide-suggestion"
                    if index == 0:
                        classes += " cs-group-guide-suggestion-active"
                    with (
                        ui.element("button")
                        .props("type=button")
                        .classes(classes)
                        .on(
                            "click",
                            lambda _, value=suggestion["value"]: _choose_actor(value),
                        )
                    ):
                        member = suggestion.get("member")
                        if isinstance(member, GroupMember):
                            _render_group_member_menu_face(controller.ctx, member)
                        else:
                            _render_group_role_icon("guest")
                        ui.label(str(suggestion["label"])).classes("cs-group-guide-suggestion-label")
                        ui.label(str(suggestion["state"])).classes("cs-group-guide-suggestion-state")
            _position_group_actor_suggestions()

        def _render_actor_icon(resolved: dict[str, Any] | None) -> None:
            actor_icon.clear()
            with actor_icon:
                if resolved is None:
                    ui.icon("help_outline").classes("text-sm")
                    return
                member = resolved.get("member")
                if isinstance(member, GroupMember):
                    _render_group_member_menu_face(controller.ctx, member)
                elif resolved.get("kind") == "guest":
                    _render_group_role_icon("guest")
                else:
                    ui.icon("help_outline").classes("text-sm")

        def _sync_actor_controls() -> None:
            if actor_value_syncing["active"]:
                return
            raw_actor_value = str(actor_input.value or "")
            resolved = _resolve_actor_input(raw_actor_value)
            if resolved is not None:
                display_value = _actor_display_value(resolved)
                is_typing_guest_prefix = (
                    resolved.get("kind") == "guest"
                    and re.match(r"^\s*guest\s*[:：]", raw_actor_value, flags=re.IGNORECASE) is not None
                )
                if not is_typing_guest_prefix and raw_actor_value.strip() != display_value:
                    actor_value_syncing["active"] = True
                    actor_input.set_value(display_value)
                    actor_value_syncing["active"] = False
            _render_actor_icon(resolved)
            _render_suggestions()

        actor_input.on_value_change(lambda _: _sync_actor_controls())
        actor_input.on(
            "keydown",
            js_handler="""
event => {
  const root = event.target.closest('.cs-group-guide-actor-wrap');
  const box = root ? root.querySelector('.cs-group-guide-suggestions:not(.hidden)') : null;
  const options = box ? Array.from(box.querySelectorAll('.cs-group-guide-suggestion')) : [];
  if (!options.length) return;
  const activeIndex = () => Math.max(0, options.findIndex(option => option.classList.contains('cs-group-guide-suggestion-active')));
  const setActive = index => {
options.forEach((option, current) => {
  const active = current === index;
  option.classList.toggle('cs-group-guide-suggestion-active', active);
  option.setAttribute('aria-selected', active ? 'true' : 'false');
  if (active) option.scrollIntoView({ block: 'nearest' });
});
  };
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
event.preventDefault();
const delta = event.key === 'ArrowDown' ? 1 : -1;
setActive((activeIndex() + delta + options.length) % options.length);
return;
  }
  if (event.key === 'Enter') {
event.preventDefault();
(options[activeIndex()] || options[0]).click();
return;
  }
  if (event.key === 'Escape') {
box.classList.add('hidden');
  }
}
""",
        )

        async def _apply() -> None:
            resolved = _resolve_actor_input(str(actor_input.value or ""))
            if resolved is None:
                ui.notify("発言者を指定してください", type="warning")
                return
            if resolved["kind"] == "guest":
                controller.set_guest_input_mode(str(resolved.get("guest_name") or ""))
            else:
                member = resolved.get("member")
                if not isinstance(member, GroupMember):
                    ui.notify("発言者を指定してください", type="warning")
                    return
                if controller.settings is not None and member.id not in group_participant_ids(controller.settings):
                    controller.settings = settings_with_participant(controller.settings, member.id)
                    controller.messages.append(group_system_event_message(f"{member.character.name}が入場しました"))
                    controller.refresh_messages(scroll_to_bottom=True)
                    await controller.save_current_session(refresh_history=False)
                    controller.refresh_mention_palette()
                    controller.refresh_chat_header()
                controller.set_character_input_member(member)
            controller.set_input_value(left_text.rstrip())
            controller.focus_chat_input_at_end()
            dlg.close()
            ui.notify("入力モードにしました", type="info")

        _sync_actor_controls()
        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("選択", icon="theater_comedy", on_click=_apply).props("color=primary unelevated")
    dlg.open()
    ui.timer(0.1, lambda: actor_input.run_method("focus"), once=True)


def open_new_chat_dialog(controller: "GroupChatPageController") -> None:
    profile_options = _profile_options(controller.ctx, controller.ctx.api_config.get_llm_profiles())
    default_profile = (
        controller.group.completion_profile_id
        if controller.group.completion_profile_id in profile_options
        else _default_profile_id(controller.ctx, profile_options)
    )
    member_checks: dict[str, Any] = {}

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-2xl"):
        ui.label("新しいチャット").classes("text-lg font-semibold")
        if not profile_options:
            ui.label("LLMプロファイルが登録されていません。設定画面で追加してください。").classes(
                "text-sm text-negative"
            )
        profile_select = (
            ui.select(
                options=profile_options,
                value=default_profile,
                label="LLMプロファイル",
            )
            .props("outlined dense")
            .classes("w-full")
        )
        title_input = (
            ui.input(
                label="タイトル（任意）",
                placeholder="未入力なら自動タイトル",
            )
            .props("outlined clearable")
            .classes("w-full")
        )

        ui.label("参加キャラクター").classes("text-sm font-semibold")
        with ui.element("div").classes("cs-group-selected-list"):
            if not controller.group.members:
                ui.label("参加できるキャラクターがいません").classes("text-sm text-grey-6")
            for member in controller.group.members:
                with ui.row().classes("items-center gap-2 w-full"):
                    _render_face(controller.ctx, member.character.media, "character")
                    with ui.column().classes("gap-0 min-w-0 flex-1"):
                        ui.label(member.character.name).classes("text-sm font-semibold")
                        ui.label(f"@{member.handle}").classes("text-xs text-grey-6")
                    member_checks[member.id] = ui.checkbox(value=True)

        with ui.element("div").classes("cs-group-world-field"):
            situation_input = ui.textarea(label="シチュエーション").props("outlined rows=4").classes("w-full")

            async def _enhance_situation_click() -> None:
                participant_ids = [member_id for member_id, checkbox in member_checks.items() if bool(checkbox.value)]
                enhanced = await controller.enhance_situation(
                    str(profile_select.value or ""),
                    participant_ids,
                    str(situation_input.value or ""),
                )
                if enhanced is not None:
                    situation_input.set_value(enhanced)

            ui.button(
                icon="auto_awesome",
                on_click=_enhance_situation_click,
            ).props("flat round dense size=sm").classes("cs-group-world-enhance").tooltip("シチュエーションを補完")

        async def _start() -> None:
            profile_id = str(profile_select.value or "")
            if not profile_id:
                ui.notify("LLMプロファイルを選択してください", type="warning")
                return
            participant_ids = [member_id for member_id, checkbox in member_checks.items() if bool(checkbox.value)]
            if not participant_ids:
                ui.notify("参加キャラクターを1人以上選択してください", type="warning")
                return
            title = str(title_input.value or "").strip()
            await controller.start_chat_session(
                {
                    "profile_id": profile_id,
                    "participant_ids": participant_ids,
                    "situation": str(situation_input.value or "").strip(),
                },
                title=title,
            )
            dlg.close()

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("開始", icon="chat", on_click=_start).props("color=primary unelevated")
    dlg.open()


def open_rename_current_chat_dialog(controller: "GroupChatPageController") -> None:
    if controller.active_session_id is None:
        ui.notify("先にチャットを開始してください", type="warning")
        return
    controller.open_rename_chat_dialog(controller.active_session_id)


def open_rename_chat_dialog(controller: "GroupChatPageController", session_id: str) -> None:
    session = controller.sessions_by_id.get(session_id)
    if session is None:
        ui.notify("チャットが見つかりません", type="warning")
        return
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-md"):
        ui.label("タイトル変更").classes("text-base font-semibold")
        title_input = (
            ui.input(
                label="タイトル",
                value=session.title or DEFAULT_GROUP_CHAT_TITLE,
            )
            .props("outlined clearable")
            .classes("w-full")
        )

        async def _save_title() -> None:
            title = str(title_input.value or "").strip()
            if not title:
                ui.notify("タイトルを入力してください", type="warning")
                return
            saved = await controller.ctx.group_chats.rename_session(session_id, title)
            if saved is None:
                dlg.close()
                ui.notify("チャットが見つかりません", type="warning")
                await controller.reload_sessions()
                controller.refresh_history()
                return
            controller.sessions_by_id[saved.id] = saved
            if saved.id == controller.active_session_id:
                controller.title = saved.title
                controller.active_title_is_auto = False
                controller.refresh_chat_header()
            await controller.reload_sessions()
            controller.refresh_history()
            dlg.close()

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", icon="save", on_click=_save_title).props("color=primary unelevated")
    dlg.open()


def confirm_delete_current_chat(controller: "GroupChatPageController") -> None:
    if controller.active_session_id is None:
        ui.notify("削除するチャットがありません", type="warning")
        return
    controller.confirm_delete_chat_session(controller.active_session_id)


def confirm_delete_chat_session(controller: "GroupChatPageController", session_id: str) -> None:
    if controller.sending:
        ui.notify("生成中は削除できません", type="warning")
        return
    session = controller.sessions_by_id.get(session_id)
    if session is None:
        ui.notify("チャットが見つかりません", type="warning")
        return
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm"):
        ui.label("チャットを削除しますか？").classes("text-base font-semibold")
        ui.label("この操作は元に戻せません。").classes("text-sm text-grey-6")
        ui.label(session.title or DEFAULT_GROUP_CHAT_TITLE).classes("text-sm font-semibold")

        async def _delete() -> None:
            dlg.close()
            was_active = session_id == controller.active_session_id
            await controller.ctx.group_chats.delete_session(session_id)
            await controller.reload_sessions()
            if was_active:
                if controller.sessions_by_id:
                    await controller.apply_session(next(iter(controller.sessions_by_id.values())))
                else:
                    controller.clear_active_session()
                controller.refresh_input_mode_indicator()
                controller.refresh_chat_header()
                controller.refresh_messages(scroll_to_bottom=True)
            controller.refresh_history()

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("削除", icon="delete", on_click=_delete).props("color=negative unelevated")
    dlg.open()


def open_system_prompt_dialog(controller: "GroupChatPageController") -> None:
    if controller.settings is None:
        ui.notify("先にチャットを開始してください", type="warning")
        return
    active = controller.active_members()
    if not active:
        ui.notify("参加キャラがいません", type="warning")
        return
    prompt = build_group_system_prompt(controller.group, controller.settings, active, active[0])
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-3xl"):
        ui.label("システムプロンプト").classes("text-base font-semibold")
        ui.code(prompt, language="markdown").classes("w-full text-xs")
        with ui.row().classes("justify-end mt-3"):
            ui.button("閉じる", on_click=dlg.close).props("flat")
    dlg.open()
