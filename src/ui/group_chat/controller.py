# ruff: noqa: F841
"""グループチャット詳細画面のコントローラ。"""

from __future__ import annotations

import json
import re
from typing import Any

from nicegui import app, ui

from ...core.character.schemas import (
    CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3,
    CHARACTER_TTS_API_GEN_SERVER,
    CHARACTER_TTS_API_TTS,
)
from ...core.conversation.history import (
    group_message,
    group_participant_ids,
    group_system_event_message,
    latest_group_message_preview,
    settings_with_participant,
    settings_without_participant,
)
from ...core.conversation.prompts.group import (
    build_group_system_prompt,
    group_input_mode_for_role,
)
from ...core.conversation.sanitize import (
    clean_guest_name,
    guest_display_name,
    guest_name_from_actor_text,
)
from ...core.group_chat.schemas import GroupChatRecord, GroupMember, GroupUserPersona
from ...core.group_chat.sessions import DEFAULT_GROUP_CHAT_TITLE, GroupChatSessionRecord
from ...core.tts.schemas import TTS_PROVIDER_IRODORI_SERVER
from ...services.ai_jobs import AIJobKind, AIJobStatus
from ...services.llm_runtime import (
    API_KEY_LOCKED,
    ENDPOINT_NOT_FOUND,
    LLMRuntimeError,
    MODEL_ID_MISSING,
    PROFILE_NOT_FOUND,
    build_configured_llm,
)
from ...services.tts import TTSServiceError
from ..chat import components as chat_components
from ..chat.commands import (
    command_suggestions,
    parse_command_input,
    resolve_chat_command,
)
from ..chat.models import ChatDebugInfo, ChatThreadPreview
from ..state import get_vault_password
from .common import (
    HANDLE_RE as _HANDLE_RE,
    default_profile_id as _default_profile_id,
    group_member_tts_id as _group_member_tts_id,
    group_user_persona_tts_id as _group_user_persona_tts_id,
    notify_group_chat_llm_runtime_error as _notify_group_chat_llm_runtime_error,
    profile_options as _profile_options,
)
from .rendering import (
    group_input_mode_icon as _group_input_mode_icon,
    group_message_target_label as _group_message_target_label,
    group_participants as _group_participants,
    render_face as _render_face,
    render_group_chat_message as _render_group_chat_message,
    render_group_member_menu_face as _render_group_member_menu_face,
    render_group_profile_panel as _render_group_profile_panel,
    render_group_role_icon as _render_group_role_icon,
    render_group_user_menu_face as _render_group_user_menu_face,
    render_participant_face as _render_participant_face,
    time_label as _time_label,
)


_GROUP_MENTION_REFRESH_JS = r"""
event => {
  const input = event.target;
  const palette = document.querySelector('.cs-group-mention-palette');
  const wrapper = input && typeof input.closest === 'function'
    ? input.closest('.cs-chat-composer-input-wrap')
    : null;
  const value = input && typeof input.value === 'string' ? input.value : '';
  if (wrapper) {
    wrapper.classList.toggle('cs-chat-composer-input-has-text', value.length > 0);
  }
  if (!input || !palette) return;
  const mentionState = target => {
    const cursor = target.selectionStart ?? target.value.length;
    const before = target.value.slice(0, cursor);
    const at = before.lastIndexOf('@');
    if (at < 0) return null;
    const query = before.slice(at + 1);
    if (!/^[A-Za-z0-9_]*$/.test(query)) return null;
    const previous = at > 0 ? before[at - 1] : '';
    if (/[A-Za-z0-9_@]/.test(previous)) return null;
    return { start: at, end: cursor, query: query.toLowerCase() };
  };
  const state = mentionState(input);
  const options = Array.from(palette.querySelectorAll('.cs-group-mention-option'));
  const visible = [];
  for (const option of options) {
    const handle = (option.dataset.handle || '').toLowerCase();
    const matched = !!state && (state.query === '' || handle.startsWith(state.query));
    option.classList.toggle('cs-group-mention-option-hidden', !matched);
    if (matched) visible.push(option);
  }
  if (!state || !visible.length) {
    palette.classList.add('cs-group-mention-palette-hidden');
    return;
  }
  palette.classList.remove('cs-group-mention-palette-hidden');
  let active = visible.find(option => option.classList.contains('cs-group-mention-option-active'));
  if (!active) active = visible[0];
  for (const option of options) {
    const isActive = option === active;
    option.classList.toggle('cs-group-mention-option-active', isActive);
    option.setAttribute('aria-selected', isActive ? 'true' : 'false');
  }
}
"""

_GROUP_MENTION_INSERT_JS = r"""
event => {
  event.preventDefault();
  const option = event.currentTarget;
  const input = document.querySelector('.cs-chat-composer-input textarea');
  const palette = document.querySelector('.cs-group-mention-palette');
  if (!option || !input) return;
  const mentionState = target => {
    const cursor = target.selectionStart ?? target.value.length;
    const before = target.value.slice(0, cursor);
    const at = before.lastIndexOf('@');
    if (at < 0) return null;
    const query = before.slice(at + 1);
    if (!/^[A-Za-z0-9_]*$/.test(query)) return null;
    const previous = at > 0 ? before[at - 1] : '';
    if (/[A-Za-z0-9_@]/.test(previous)) return null;
    return { start: at, end: cursor };
  };
  const state = mentionState(input);
  const handle = option.dataset.handle || '';
  if (!state || !handle) return;
  const replacement = `@${handle} `;
  input.value = input.value.slice(0, state.start) + replacement + input.value.slice(state.end);
  const cursor = state.start + replacement.length;
  input.selectionStart = input.selectionEnd = cursor;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  if (palette) palette.classList.add('cs-group-mention-palette-hidden');
  input.focus();
}
"""

_GROUP_CHAT_INPUT_KEYDOWN_JS = r"""
event => {
  const target = event.target;
  const mentionPalette = document.querySelector('.cs-group-mention-palette');
  const commandPalette = document.querySelector('.cs-chat-command-palette');
  const value = target && typeof target.value === 'string' ? target.value : '';
  const mentionState = input => {
    if (!input || typeof input.value !== 'string') return null;
    const cursor = input.selectionStart ?? input.value.length;
    const before = input.value.slice(0, cursor);
    const at = before.lastIndexOf('@');
    if (at < 0) return null;
    const query = before.slice(at + 1);
    if (!/^[A-Za-z0-9_]*$/.test(query)) return null;
    const previous = at > 0 ? before[at - 1] : '';
    if (/[A-Za-z0-9_@]/.test(previous)) return null;
    return { start: at, end: cursor };
  };
  const mentionOptions = () => mentionPalette
    ? Array.from(mentionPalette.querySelectorAll(
        '.cs-group-mention-option:not(.cs-group-mention-option-hidden)'
      ))
    : [];
  const commandMatch = value.match(/^([\s\S]*)\/([A-Za-z]*)$/);
  const commandOptions = commandPalette
    ? Array.from(commandPalette.querySelectorAll('.cs-chat-command-option'))
    : [];
  const activeIndex = options => Math.max(
    0,
    options.findIndex(option =>
      option.classList.contains('cs-group-mention-option-active')
      || option.classList.contains('cs-chat-command-option-active')
    ),
  );
  const setActive = (options, index, activeClass) => {
    options.forEach((option, optionIndex) => {
      const active = optionIndex === index;
      option.classList.toggle(activeClass, active);
      option.setAttribute('aria-selected', active ? 'true' : 'false');
      if (active && typeof option.scrollIntoView === 'function') {
        option.scrollIntoView({ block: 'nearest' });
      }
    });
  };
  const insertOption = option => {
    const state = mentionState(target);
    const handle = option && option.dataset ? option.dataset.handle : '';
    if (!state || !handle || !target || typeof target.value !== 'string') return false;
    const replacement = `@${handle} `;
    target.value = target.value.slice(0, state.start) + replacement + target.value.slice(state.end);
    const cursor = state.start + replacement.length;
    target.selectionStart = target.selectionEnd = cursor;
    target.dispatchEvent(new Event('input', { bubbles: true }));
    if (mentionPalette) mentionPalette.classList.add('cs-group-mention-palette-hidden');
    return true;
  };

  if (mentionPalette && !mentionPalette.classList.contains('cs-group-mention-palette-hidden')) {
    const options = mentionOptions();
    if (options.length && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
      event.preventDefault();
      const delta = event.key === 'ArrowDown' ? 1 : -1;
      setActive(options, (activeIndex(options) + delta + options.length) % options.length, 'cs-group-mention-option-active');
      return;
    }
    if (options.length && (event.key === 'Enter' || event.key === 'Tab') && !event.isComposing) {
      event.preventDefault();
      insertOption(options[activeIndex(options)] || options[0]);
      return;
    }
    if (event.key === 'Escape') {
      mentionPalette.classList.add('cs-group-mention-palette-hidden');
      return;
    }
  }

  if (
    commandMatch
    && commandPalette
    && !commandPalette.classList.contains('cs-chat-command-palette-hidden')
    && commandOptions.length
  ) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const delta = event.key === 'ArrowDown' ? 1 : -1;
      setActive(
        commandOptions,
        (activeIndex(commandOptions) + delta + commandOptions.length) % commandOptions.length,
        'cs-chat-command-option-active',
      );
      return;
    }
    if (event.key === 'Enter' && !event.isComposing && !event.shiftKey && !event.altKey) {
      event.preventDefault();
      const active = commandOptions[activeIndex(commandOptions)] || commandOptions[0];
      const command = active && active.dataset ? active.dataset.command : '';
      if (command) {
        target.value = commandMatch[1] + '/' + command;
        target.dispatchEvent(new Event('input', { bubbles: true }));
      }
      commandPalette.classList.add('cs-chat-command-palette-hidden');
      emit(target && typeof target.value === 'string' ? target.value : '');
      return;
    }
    if (event.key === 'Escape') {
      commandPalette.classList.add('cs-chat-command-palette-hidden');
      return;
    }
  }

  if (event.key !== 'Enter' || event.isComposing || event.shiftKey || event.altKey) return;
  event.preventDefault();
  emit(target && typeof target.value === 'string' ? target.value : '');
}
"""


class GroupChatPageController:
    def __init__(self, ctx, group: GroupChatRecord, page_client) -> None:
        self.ctx = ctx
        self.group = group
        self.page_client = page_client
        self.participants = _group_participants(group)
        self.selected = {
            "key": self.participants[0]["key"] if self.participants else "",
            "tab": "profile",
        }
        self.profile_containers: list[tuple[Any, bool]] = []
        self.history_sections: list[Any] = []
        self.messages_container = None
        self.command_palette = None
        self.mention_palette = None
        self.title_label = None
        self.subtitle_label = None
        self.input_box = None
        self.send_button = None
        self.input_mode_icon = None
        self.sessions_by_id: dict[str, GroupChatSessionRecord] = {}
        self.threads: list[ChatThreadPreview] = []
        self.active_session_id: str | None = None
        self.active_title_is_auto = False
        self.title_generation_attempted = False
        self.title = "チャットを開始"
        self.settings: dict[str, Any] | None = None
        self.messages: list[dict[str, Any]] = []
        self.input_mode = "user"
        self.guest_input_name = ""
        self.sending = False
        self.tts_generating_index: int | None = None
        self.last_speaker_debug: ChatDebugInfo | None = None

    async def initialize(self) -> None:
        await self.reload_sessions()
        if self.sessions_by_id:
            await self.apply_session(next(iter(self.sessions_by_id.values())))

    async def reload_sessions(self) -> None:
        sessions = await self.ctx.group_chats.list_sessions_for_group(self.group.id)
        self.sessions_by_id = {session.id: session for session in sessions}
        self.threads = [self.thread_preview(session) for session in sessions]

    def render_shell(self) -> None:
        with ui.element("div").classes("cs-chat-shell cs-group-chat-shell"):
            ui.element("div").classes("cs-chat-mobile-backdrop").on("click", lambda: self.set_mobile_sidebar(False))

            with ui.element("aside").classes("cs-chat-mobile-sidebar cs-chat-panel"):
                with (
                    ui.row()
                    .classes("items-center justify-between px-3 py-2")
                    .style("border-bottom: 1px solid var(--cs-border);")
                ):
                    ui.label("グループ").classes("text-sm font-semibold")
                    ui.button(icon="close", on_click=lambda: self.set_mobile_sidebar(False)).props("flat round dense")
                with ui.element("div").classes("cs-chat-scroll"):
                    mobile_profile = ui.element("div")
                    self.profile_containers.append((mobile_profile, True))
                    self.render_history_section()

            with ui.element("aside").classes("cs-chat-profile-pane cs-chat-panel"):
                profile = ui.element("div")
                self.profile_containers.append((profile, False))

            with ui.element("aside").classes("cs-chat-side-pane cs-chat-panel"):
                with ui.element("div").classes("cs-chat-scroll"):
                    side_profile = ui.element("div")
                    self.profile_containers.append((side_profile, True))
                    self.render_history_section()

            with ui.element("aside").classes("cs-chat-history-pane cs-chat-panel"):
                self.render_history_section()

            with ui.element("section").classes("cs-chat-main cs-chat-panel"):
                self.render_chat_main()

        self.refresh_profiles()
        self.scroll_messages_to_bottom()
        ui.timer(0.1, self.restore_active_ai_job, once=True)

    async def restore_active_ai_job(self) -> None:
        if self.active_session_id is None:
            return
        job = self.ctx.ai_jobs.latest_active_job(scope=self._active_group_chat_scope())
        if job is None:
            return
        await self._wait_for_active_group_job(job.id, failure_message="生成に失敗しました")

    def current_participant(self) -> dict[str, Any] | None:
        for participant in self.participants:
            if participant["key"] == self.selected["key"]:
                return participant
        return self.participants[0] if self.participants else None

    def refresh_profiles(self) -> None:
        current = self.current_participant()
        for container, compact in self.profile_containers:
            container.clear()
            with container:
                _render_group_profile_panel(
                    self.ctx,
                    self.group,
                    self.participants,
                    current,
                    selected_key=self.selected["key"],
                    active_tab=self.selected["tab"],
                    select_profile=self.select_profile,
                    select_tab=self.select_tab,
                    on_group_updated=self.apply_group_update,
                    compact=compact,
                )

    def apply_group_update(self, group: GroupChatRecord) -> None:
        self.group = group
        self.participants = _group_participants(group)
        if self.participants and not any(
            participant["key"] == self.selected["key"] for participant in self.participants
        ):
            self.selected["key"] = self.participants[0]["key"]
        self.refresh_profiles()
        self.refresh_mention_palette()

    def mention_participants(self) -> list[dict[str, Any]]:
        active_ids: set[str] | None = None
        if self.settings is not None:
            active_ids = {str(member_id) for member_id in self.settings.get("participant_ids", [])}
        participants: list[dict[str, Any]] = []
        for participant in self.participants:
            if participant.get("kind") == "character" and active_ids is not None:
                member = participant.get("member")
                if not isinstance(member, GroupMember) or member.id not in active_ids:
                    continue
            participants.append(participant)
        return participants

    def render_mention_options(self) -> None:
        for index, participant in enumerate(self.mention_participants()):
            handle = str(participant.get("handle") or "").strip()
            if not _HANDLE_RE.match(handle):
                continue
            name = str(participant.get("name") or "メンバー")
            selected = "true" if index == 0 else "false"
            with (
                ui.element("button")
                .props(f"type=button data-handle={handle} aria-selected={selected}")
                .classes("cs-group-mention-option")
                .on(
                    "mousedown",
                    js_handler=_GROUP_MENTION_INSERT_JS,
                )
            ):
                _render_participant_face(self.ctx, participant)
                with ui.element("div").classes("cs-group-mention-info"):
                    ui.label(name).classes("cs-group-mention-name")
                    ui.label(f"@{handle}").classes("cs-group-mention-handle")
                kind = "User" if participant.get("kind") == "user" else "Char"
                ui.label(kind).classes("cs-group-mention-kind")

    def refresh_mention_palette(self) -> None:
        if self.mention_palette is None:
            return
        self.mention_palette.clear()
        with self.mention_palette:
            self.render_mention_options()
        self.page_client.run_javascript(
            "document.querySelector('.cs-group-mention-palette')?.classList.add('cs-group-mention-palette-hidden');"
        )

    def refresh_command_palette(self, value: str) -> None:
        if self.command_palette is None:
            return
        self.command_palette.clear()
        parsed = parse_command_input(value)
        if parsed is None:
            self.command_palette.classes("cs-chat-command-palette-hidden")
            return
        _, query = parsed
        suggestions = command_suggestions(query)
        self.command_palette.classes(remove="cs-chat-command-palette-hidden")
        if not suggestions:
            with self.command_palette:
                ui.label("該当するコマンドがありません").classes("text-xs text-grey-6")
            return
        with self.command_palette:
            for index, command in enumerate(suggestions):
                classes = "cs-chat-command-option"
                if index == 0:
                    classes += " cs-chat-command-option-active"
                with (
                    ui.element("button")
                    .props(f"type=button data-command={command.name} aria-selected={'true' if index == 0 else 'false'}")
                    .classes(classes)
                    .on(
                        "click",
                        self._command_click_handler(command.name),
                    )
                ):
                    ui.label(f"/{command.name}").classes("cs-chat-command-name")
                    ui.label(command.description).classes("cs-chat-command-desc")

    def _command_click_handler(self, command: str):
        async def _handler(_) -> None:
            current_text = str(self.input_box.value or "") if self.input_box is not None else ""
            parsed = parse_command_input(current_text)
            left_text = parsed[0] if parsed is not None else ""
            if self.command_palette is not None:
                self.command_palette.clear()
                self.command_palette.classes("cs-chat-command-palette-hidden")
            await self.send_message(False, f"{left_text}/{command}")

        return _handler

    def select_profile(self, key: str) -> None:
        self.selected["key"] = key
        self.refresh_profiles()

    def select_tab(self, tab: str) -> None:
        self.selected["tab"] = tab if tab == "world" else "profile"
        self.refresh_profiles()

    def set_mobile_sidebar(self, open_: bool) -> None:
        action = "add" if open_ else "remove"
        self.page_client.run_javascript(
            f"document.querySelector('.cs-chat-shell')?.classList.{action}('cs-mobile-sidebar-open');"
        )

    def render_history_section(self) -> None:
        with ui.element("div").classes("cs-chat-history-section") as section:
            self.history_sections.append(section)
            self.render_history()

    def render_history(self) -> None:
        with ui.element("div").classes("cs-chat-history-head"):
            ui.icon("history").style("color: var(--cs-accent);")
            ui.label("チャット履歴").classes("cs-chat-history-title")
            ui.space()
            ui.button(icon="add", on_click=self.open_new_chat_dialog).props("flat round dense").tooltip(
                "新しいチャット"
            )
        with ui.element("div").classes("cs-chat-scroll"):
            with ui.element("div").classes("cs-chat-thread-list"):
                if not self.threads:
                    ui.label("保存済みチャットはまだありません").classes("cs-chat-history-empty")
                    return
                for thread in self.threads:
                    classes = "cs-chat-thread"
                    if thread.active:
                        classes += " cs-chat-thread-active"
                    with ui.element("div").classes(classes):
                        with (
                            ui.element("button")
                            .props("type=button")
                            .classes("cs-chat-thread-open")
                            .on("click", self._select_thread_handler(thread.id))
                        ):
                            with ui.element("div").classes("cs-chat-thread-title-row"):
                                ui.label(thread.title).classes("cs-chat-thread-title")
                                ui.label(thread.time_label).classes("cs-chat-thread-time")
                            ui.label(thread.preview).classes("cs-chat-thread-preview")
                        with ui.element("div").classes("cs-chat-thread-actions"):
                            ui.button(
                                icon="edit",
                                on_click=lambda thread_id=thread.id: self.open_rename_chat_dialog(thread_id),
                            ).props("flat round dense size=sm").classes("cs-chat-thread-action").tooltip("タイトル変更")
                            ui.button(
                                icon="delete",
                                on_click=lambda thread_id=thread.id: self.confirm_delete_chat_session(thread_id),
                            ).props("flat round dense size=sm color=negative").classes("cs-chat-thread-action").tooltip(
                                "チャット削除"
                            )

    def _select_thread_handler(self, session_id: str):
        async def _handler(_) -> None:
            await self.select_chat_session(session_id)

        return _handler

    def refresh_history(self) -> None:
        for section in list(self.history_sections):
            section.clear()
            with section:
                self.render_history()

    def render_chat_main(self) -> None:
        with ui.element("div").classes("cs-chat-main-head"):
            ui.button(icon="menu", on_click=lambda: self.set_mobile_sidebar(True)).props("flat round dense").classes(
                "cs-chat-mobile-toggle"
            )
            with ui.column().classes("gap-0 cs-chat-main-title"):
                self.title_label = ui.label(self.chat_title()).classes("text-base font-bold")
                self.subtitle_label = ui.label(self.chat_subtitle()).classes("text-xs text-grey-6")
            chat_components.render_chat_header_menu(
                open_new_chat_dialog=self.open_new_chat_dialog,
                open_system_prompt=self.open_system_prompt_dialog,
                open_rename_current_chat=self.open_rename_current_chat_dialog,
                confirm_delete_current_chat=self.confirm_delete_current_chat,
            )

        with ui.element("div").classes("cs-chat-messages") as messages_container:
            self.messages_container = messages_container
            self.render_messages()

        with ui.element("div").classes("cs-chat-composer-shell"):
            with ui.element("div").classes("cs-chat-command-palette cs-chat-command-palette-hidden") as command_palette:
                self.command_palette = command_palette

            with (
                ui.element("div")
                .classes("cs-group-mention-palette cs-group-mention-palette-hidden")
                .props("role=listbox") as mention_palette
            ):
                self.mention_palette = mention_palette
                self.render_mention_options()

            swipe_action_menu = ui.element("div").classes("cs-chat-swipe-action-menu cs-chat-swipe-action-menu-hidden")

            async def _apply_swipe_action(command: str) -> None:
                current_text = str(self.input_box.value or "") if self.input_box is not None else ""
                parsed = parse_command_input(current_text)
                left_text = parsed[0] if parsed is not None else current_text
                if self.command_palette is not None:
                    self.command_palette.clear()
                    self.command_palette.classes("cs-chat-command-palette-hidden")
                if self.mention_palette is not None:
                    self.mention_palette.classes("cs-group-mention-palette-hidden")
                swipe_action_menu.classes("cs-chat-swipe-action-menu-hidden")
                await self.send_message(False, f"{left_text.rstrip()}/{command}")

            def _swipe_action_click_handler(command: str):
                async def _handler(_) -> None:
                    await _apply_swipe_action(command)

                return _handler

            with swipe_action_menu:
                for command, label, icon in (
                    ("choices", "選択肢を生成", "format_list_bulleted"),
                    ("fill", "続きを補完", "auto_fix_high"),
                    ("tailor", "書き直す", "edit_note"),
                ):
                    with (
                        ui.element("button")
                        .props(f"type=button data-swipe-command={command}")
                        .classes("cs-chat-swipe-action-option")
                        .on("click", _swipe_action_click_handler(command))
                    ):
                        ui.icon(icon).classes("cs-chat-swipe-action-icon")
                        ui.label(f"/{command}").classes("cs-chat-swipe-action-command")
                        ui.label(label).classes("cs-chat-swipe-action-label")

            with ui.element("div").classes("cs-chat-composer"):
                self.render_input_role_selector()
                with ui.element("div").classes("cs-chat-composer-input-wrap"):
                    self.input_box = (
                        ui.textarea(placeholder="メッセージを入力")
                        .props("outlined dense rows=1 autogrow")
                        .classes("cs-chat-composer-input")
                    )
                    voice_input_btn = (
                        ui.button(icon="mic")
                        .props("round flat dense aria-label=音声入力")
                        .classes("cs-chat-voice-input")
                        .tooltip("音声入力")
                    )
                    voice_input_btn.on(
                        "click",
                        js_handler=chat_components.VOICE_INPUT_CLICK_JS,
                    )

                    async def _send_from_enter(e) -> None:
                        if isinstance(e.args, list):
                            value = str(e.args[0] or "") if e.args else ""
                        else:
                            value = str(e.args or "")
                        await self.send_message(False, value)

                    self.input_box.on_value_change(lambda e: self.refresh_command_palette(str(e.value or "")))
                    self.input_box.on("input", js_handler=_GROUP_MENTION_REFRESH_JS)
                    self.input_box.on("keyup", js_handler=_GROUP_MENTION_REFRESH_JS)
                    self.input_box.on("click", js_handler=_GROUP_MENTION_REFRESH_JS)
                    self.input_box.on("focus", js_handler=_GROUP_MENTION_REFRESH_JS)
                    self.input_box.on(
                        "touchstart",
                        js_handler="""
event => {
  const touch = event.touches && event.touches[0];
  if (!touch) return;
  window.__csComposerSwipeStart = {
    x: touch.clientX,
    y: touch.clientY,
    time: Date.now(),
  };
}
""",
                    )
                    self.input_box.on(
                        "touchend",
                        js_handler="""
event => {
  const start = window.__csComposerSwipeStart;
  const touch = event.changedTouches && event.changedTouches[0];
  window.__csComposerSwipeStart = null;
  if (!start || !touch) return;
  const dx = touch.clientX - start.x;
  const dy = touch.clientY - start.y;
  const elapsed = Date.now() - start.time;
  const isSwipeUp = dy < -42 && Math.abs(dy) > Math.abs(dx) * 1.15 && elapsed < 900;
  if (!isSwipeUp) return;
  const menu = document.querySelector('.cs-chat-swipe-action-menu');
  const commandPalette = document.querySelector('.cs-chat-command-palette');
  const mentionPalette = document.querySelector('.cs-group-mention-palette');
  if (!menu) return;
  event.preventDefault();
  if (commandPalette) commandPalette.classList.add('cs-chat-command-palette-hidden');
  if (mentionPalette) mentionPalette.classList.add('cs-group-mention-palette-hidden');
  menu.classList.remove('cs-chat-swipe-action-menu-hidden');
  if (!window.__csSwipeActionDismiss) {
    window.__csSwipeActionDismiss = dismissEvent => {
      const currentMenu = document.querySelector('.cs-chat-swipe-action-menu');
      if (!currentMenu || currentMenu.classList.contains('cs-chat-swipe-action-menu-hidden')) return;
      const target = dismissEvent.target;
      if (target && typeof target.closest === 'function' && target.closest('.cs-chat-swipe-action-menu')) return;
      currentMenu.classList.add('cs-chat-swipe-action-menu-hidden');
    };
    document.addEventListener('click', window.__csSwipeActionDismiss, true);
    document.addEventListener('touchstart', window.__csSwipeActionDismiss, true);
  }
}
""",
                    )
                    self.input_box.on(
                        "blur",
                        js_handler="""
event => {
  setTimeout(() => {
    document.querySelector('.cs-group-mention-palette')
      ?.classList.add('cs-group-mention-palette-hidden');
  }, 120);
}
""",
                    )
                    self.input_box.on(
                        "keydown",
                        _send_from_enter,
                        js_handler=_GROUP_CHAT_INPUT_KEYDOWN_JS,
                    )

                async def _send_from_button(_) -> None:
                    await self.send_message(True)

                async def _guide_from_long_tap(e) -> None:
                    if isinstance(e.args, list):
                        value = str(e.args[0] or "") if e.args else ""
                    else:
                        value = str(e.args or "")
                    parsed = parse_command_input(value)
                    left_text = parsed[0] if parsed is not None else value
                    await self.send_message(False, f"{left_text.rstrip()}/guide")

                self.send_button = ui.button(icon="send").props("round color=primary unelevated")
                self.send_button.on(
                    "click",
                    _send_from_button,
                    js_handler="""
event => {
  if (window.__csSendLongTapSuppressClick) {
    window.__csSendLongTapSuppressClick = false;
    event.preventDefault();
    event.stopPropagation();
    return;
  }
  emit();
}
""",
                )
                self.send_button.on(
                    "touchstart",
                    _guide_from_long_tap,
                    js_handler="""
event => {
  const touch = event.touches && event.touches[0];
  if (!touch) return;
  clearTimeout(window.__csSendLongTapTimer);
  window.__csSendLongTapStart = {
    x: touch.clientX,
    y: touch.clientY,
  };
  window.__csSendLongTapTriggered = false;
  window.__csSendLongTapTimer = setTimeout(() => {
    window.__csSendLongTapTriggered = true;
    window.__csSendLongTapSuppressClick = true;
    setTimeout(() => {
      window.__csSendLongTapSuppressClick = false;
    }, 1200);
    const input = document.querySelector('.cs-chat-composer-input textarea');
    emit(input && typeof input.value === 'string' ? input.value : '');
  }, 650);
}
""",
                )
                self.send_button.on(
                    "touchmove",
                    js_handler="""
event => {
  const start = window.__csSendLongTapStart;
  const touch = event.touches && event.touches[0];
  if (!start || !touch) return;
  const dx = touch.clientX - start.x;
  const dy = touch.clientY - start.y;
  if (Math.hypot(dx, dy) > 14) {
    clearTimeout(window.__csSendLongTapTimer);
  }
}
""",
                )
                self.send_button.on(
                    "touchend",
                    js_handler="""
event => {
  clearTimeout(window.__csSendLongTapTimer);
  window.__csSendLongTapStart = null;
  if (window.__csSendLongTapTriggered) {
    event.preventDefault();
  }
}
""",
                )
                self.send_button.on(
                    "touchcancel",
                    js_handler="""
event => {
  clearTimeout(window.__csSendLongTapTimer);
  window.__csSendLongTapStart = null;
  window.__csSendLongTapTriggered = false;
}
""",
                )
        self.refresh_input_mode_indicator()

    def render_input_role_selector(self) -> None:
        with ui.button().props("flat dense unelevated aria-label=入力ロールを変更").classes("cs-chat-mode-icon"):
            self.input_mode_icon = ui.element("div").classes("cs-chat-mode-icon-display")
            with self.input_mode_icon:
                ui.icon(_group_input_mode_icon(self.input_mode))
            with ui.menu().classes("cs-chat-mode-menu"):
                with (
                    ui.element("button")
                    .props("type=button")
                    .classes("cs-group-menu-option")
                    .on(
                        "click",
                        lambda _: self.set_input_mode("user"),
                    )
                ):
                    _render_group_user_menu_face(self.ctx, self.group.user_persona)
                    ui.label("ユーザー").classes("cs-group-menu-option-label")
                    ui.element("span")
                with ui.element("button").props("type=button").classes("cs-group-menu-parent"):
                    _render_group_role_icon("character")
                    ui.label("キャラクター").classes("cs-group-menu-option-label")
                    ui.icon("chevron_right").classes("text-grey-6")
                    with (
                        ui.menu()
                        .props('anchor="top end" self="top start"')
                        .classes("cs-chat-mode-menu cs-group-character-submenu")
                    ):
                        active = self.active_members()
                        if not active:
                            ui.label("参加キャラがいません").classes("text-xs text-grey-6 px-3 py-2")
                        for member in active:
                            with (
                                ui.element("button")
                                .props("type=button")
                                .classes("cs-group-menu-option")
                                .on(
                                    "click",
                                    lambda _, member=member: self.set_character_input_member(member),
                                )
                            ):
                                _render_group_member_menu_face(self.ctx, member)
                                ui.label(f"{member.character.name} / @{member.handle}").classes(
                                    "cs-group-menu-option-label"
                                )
                                ui.element("span")
                        with (
                            ui.element("button")
                            .props("type=button")
                            .classes("cs-group-menu-option")
                            .on(
                                "click",
                                lambda _: self.open_guest_input_mode_dialog(),
                            )
                        ):
                            _render_group_role_icon("guest")
                            ui.label("ゲスト").classes("cs-group-menu-option-label")
                            ui.element("span")
                with (
                    ui.element("button")
                    .props("type=button")
                    .classes("cs-group-menu-option")
                    .on(
                        "click",
                        lambda _: self.set_input_mode("narration"),
                    )
                ):
                    _render_group_role_icon("narration")
                    ui.label("ナラティブ").classes("cs-group-menu-option-label")
                    ui.element("span")
                with (
                    ui.element("button")
                    .props("type=button")
                    .classes("cs-group-menu-option")
                    .on(
                        "click",
                        lambda _: self.set_input_mode("memo"),
                    )
                ):
                    _render_group_role_icon("memo")
                    ui.label("コメント").classes("cs-group-menu-option-label")
                    ui.element("span")

    def set_input_mode(self, mode: str) -> None:
        self.input_mode = mode if mode in {"user", "character", "guest", "narration", "memo"} else "user"
        if self.input_mode != "guest":
            self.guest_input_name = ""
        self.refresh_input_mode_indicator()

    def set_character_input_member(self, member: GroupMember) -> None:
        self.selected["key"] = f"member:{member.id}"
        self.set_input_mode("character")
        self.refresh_profiles()

    def set_guest_input_mode(self, guest_name: str) -> None:
        name = clean_guest_name(guest_name)
        if not name:
            ui.notify("ゲスト名を入力してください", type="warning")
            return
        self.guest_input_name = name
        self.input_mode = "guest"
        self.refresh_input_mode_indicator()

    def open_guest_input_mode_dialog(self, left_text: str = "") -> None:
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm"):
            ui.label("ゲスト入力").classes("text-base font-semibold")
            name_input = (
                ui.input(
                    label="ゲスト名",
                    value=self.guest_input_name,
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
                self.set_guest_input_mode(name)
                if left_text:
                    self.set_input_value(left_text.rstrip())
                self.focus_chat_input_at_end()
                dlg.close()
                ui.notify(f"{guest_display_name(name)}入力モードにしました", type="info")

            with ui.row().classes("justify-end gap-2 mt-4"):
                ui.button("キャンセル", on_click=dlg.close).props("flat")
                ui.button("選択", icon="person_add", on_click=_apply).props("color=primary unelevated")
        dlg.open()
        ui.timer(0.1, lambda: name_input.run_method("focus"), once=True)

    def refresh_input_mode_indicator(self) -> None:
        if self.input_mode_icon is None:
            return
        self.input_mode_icon.clear()
        with self.input_mode_icon:
            ui.icon(_group_input_mode_icon(self.input_mode))

    def chat_title(self) -> str:
        return self.title or "チャットを開始"

    def chat_subtitle(self) -> str:
        if self.settings is None:
            return "新しいチャットを開始してください"
        profile = self.ctx.api_config.get_llm_profile(str(self.settings.get("profile_id", "")))
        profile_name = profile.name if profile else "不明なプロファイル"
        active_names = [member.character.name for member in self.active_members()]
        members = "、".join(active_names) if active_names else "参加キャラなし"
        return f"{self.group.name} / {members} / {profile_name}"

    def refresh_chat_header(self) -> None:
        if self.title_label is not None:
            self.title_label.set_text(self.chat_title())
        if self.subtitle_label is not None:
            self.subtitle_label.set_text(self.chat_subtitle())

    def render_messages(self) -> None:
        if not self.messages:
            with ui.element("div").classes("cs-group-chat-empty"):
                ui.label("チャットはまだありません")
            return
        for index, message in enumerate(self.messages):
            _render_group_chat_message(
                self.ctx,
                message,
                self.participants,
                index=index,
                rewind_message=self.confirm_rewind_to_message,
                rewrite_message=self.open_rewrite_message_dialog,
                regenerate_message=self.confirm_or_regenerate_character_message,
                play_tts_message=self.play_tts_message,
                tts_playable=self.message_tts_playable(message),
                tts_generating=self.tts_generating_index == index,
            )

    def refresh_messages(self, *, scroll_to_bottom: bool = False) -> None:
        if self.messages_container is None:
            return
        self.messages_container.clear()
        with self.messages_container:
            self.render_messages()
        if scroll_to_bottom:
            self.scroll_messages_to_bottom()

    def scroll_messages_to_bottom(self) -> None:
        self.page_client.run_javascript(
            "(() => {"
            "const scroll = () => {"
            "const el = document.querySelector('.cs-chat-messages');"
            "if (el) el.scrollTop = el.scrollHeight;"
            "};"
            "setTimeout(scroll, 0);"
            "setTimeout(scroll, 50);"
            "})();"
        )

    def set_sending(self, sending: bool) -> None:
        self.sending = sending
        if self.send_button is not None:
            self.send_button.disable() if sending else self.send_button.enable()
        if self.input_box is not None:
            self.input_box.disable() if sending else self.input_box.enable()

    def set_input_value(self, value: str) -> None:
        if self.input_box is not None:
            self.input_box.set_value(value)

    def focus_chat_input_at_end(self) -> None:
        self.page_client.run_javascript(
            "setTimeout(() => {"
            "const el = document.querySelector('.cs-chat-composer-input textarea');"
            "if (!el) return;"
            "el.focus();"
            "const end = el.value.length;"
            "if (typeof el.setSelectionRange === 'function') el.setSelectionRange(end, end);"
            "}, 0);"
        )

    def clear_input(self) -> None:
        if self.input_box is not None:
            self.input_box.set_value("")
        self.page_client.run_javascript(
            "(() => {"
            "const clear = () => {"
            "const el = document.querySelector('.cs-chat-composer-input textarea');"
            "if (!el) return;"
            "el.value = '';"
            "el.dispatchEvent(new Event('input', { bubbles: true }));"
            "};"
            "clear();"
            "setTimeout(clear, 0);"
            "setTimeout(clear, 50);"
            "setTimeout(clear, 150);"
            "})();"
        )

    def thread_preview(self, session: GroupChatSessionRecord) -> ChatThreadPreview:
        return ChatThreadPreview(
            id=session.id,
            title=session.title or DEFAULT_GROUP_CHAT_TITLE,
            preview=latest_group_message_preview(session.messages),
            time_label=_time_label(session.updated_at),
            active=session.id == self.active_session_id,
        )

    async def apply_session(self, session: GroupChatSessionRecord) -> None:
        self.active_session_id = session.id
        self.active_title_is_auto = session.title_is_auto
        self.title_generation_attempted = False
        self.title = session.title or DEFAULT_GROUP_CHAT_TITLE
        self.settings = dict(session.settings or {})
        self.messages = [dict(message) for message in session.messages if isinstance(message, dict)]
        self.input_mode = "user"
        self.guest_input_name = ""
        self.sending = False
        self.tts_generating_index = None
        self.threads = [self.thread_preview(current) for current in self.sessions_by_id.values()]
        self.refresh_mention_palette()

    def clear_active_session(self) -> None:
        self.active_session_id = None
        self.active_title_is_auto = False
        self.title_generation_attempted = False
        self.title = "チャットを開始"
        self.settings = None
        self.messages = []
        self.input_mode = "user"
        self.guest_input_name = ""
        self.sending = False
        self.tts_generating_index = None
        self.threads = [self.thread_preview(current) for current in self.sessions_by_id.values()]
        self.refresh_mention_palette()

    async def save_current_session(self, *, refresh_history: bool = True) -> None:
        if self.active_session_id is None or self.settings is None:
            return
        saved = await self.ctx.group_chats.update_session(
            session_id=self.active_session_id,
            group_id=self.group.id,
            title=self.title or DEFAULT_GROUP_CHAT_TITLE,
            title_is_auto=self.active_title_is_auto,
            settings=self.settings,
            messages=self.messages,
        )
        self.sessions_by_id[saved.id] = saved
        if refresh_history:
            await self.reload_sessions()
            self.refresh_history()

    async def _save_session_messages_snapshot(
        self,
        *,
        session_id: str,
        title: str,
        title_is_auto: bool,
        settings: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> None:
        saved = await self.ctx.group_chats.update_session(
            session_id=session_id,
            group_id=self.group.id,
            title=title or DEFAULT_GROUP_CHAT_TITLE,
            title_is_auto=title_is_auto,
            settings=settings,
            messages=messages,
        )
        self.sessions_by_id[saved.id] = saved

    async def _sync_active_session_from_storage(self) -> None:
        if self.active_session_id is None:
            return
        session = await self.ctx.group_chats.get_session(self.active_session_id)
        if session is None:
            return
        self.sessions_by_id[session.id] = session
        await self.apply_session(session)
        self.refresh_input_mode_indicator()
        self.refresh_chat_header()
        self.refresh_messages(scroll_to_bottom=True)
        await self.reload_sessions()
        self.refresh_history()

    def _active_group_chat_scope(self) -> str:
        return f"group_chat:{self.active_session_id or 'none'}"

    async def _wait_for_active_group_job(self, job_id: str, *, failure_message: str) -> bool:
        self.set_sending(True)
        try:
            job = await self.ctx.ai_jobs.wait(job_id)
            if job.status == AIJobStatus.SUCCEEDED:
                await self._sync_active_session_from_storage()
                return True
            if job.status == AIJobStatus.CANCELLED:
                ui.notify("生成を停止しました", type="info")
                await self._sync_active_session_from_storage()
                return False
            ui.notify(f"{failure_message}: {job.error_message}", type="negative", timeout=10000)
            await self._sync_active_session_from_storage()
            return False
        finally:
            self.set_sending(False)

    def _group_assist_scope(self) -> str:
        return f"group_assist:{self.active_session_id or self.group.id}"

    def _group_assist_metadata(self) -> dict[str, str]:
        return {"group_id": self.group.id, "session_id": self.active_session_id or ""}

    def _group_assist_result_url(self) -> str:
        return f"/groups/{self.group.id}" if self.active_session_id else ""

    async def _await_group_llm_assist_result(self, result_awaitable, *, failure_message: str):
        self.set_sending(True)
        try:
            result = await result_awaitable
            if result.status == AIJobStatus.SUCCEEDED:
                return result.value
            if result.status == AIJobStatus.CANCELLED:
                ui.notify("生成を停止しました", type="info")
                return None
            ui.notify(f"{failure_message}: {result.error_message}", type="negative", timeout=10000)
            return None
        except LLMRuntimeError as err:
            _notify_group_chat_llm_runtime_error(err)
            return None
        finally:
            self.set_sending(False)

    async def rewind_to_message(self, index: int) -> None:
        if index < 0 or index >= len(self.messages):
            return
        message = self.messages[index]
        role = str(message.get("role", ""))
        if role not in {"character", "guest", "user", "narration", "memo"}:
            return
        self.messages = self.messages[:index]
        if self.input_box is not None:
            self.input_box.set_value(str(message.get("text", "")))
            self.input_box.enable()
        if role == "guest":
            self.guest_input_name = clean_guest_name(
                str(message.get("guest_name") or message.get("speaker_name") or "")
            )
        self.set_input_mode(group_input_mode_for_role(role))
        self.set_sending(False)
        self.tts_generating_index = None
        self.refresh_messages()
        await self.save_current_session()

    def confirm_rewind_to_message(self, index: int) -> None:
        if self.sending:
            ui.notify("生成中は戻れません", type="warning")
            return
        if index < 0 or index >= len(self.messages):
            return
        message = self.messages[index]
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
                await self.rewind_to_message(index)

            with ui.row().classes("justify-end gap-2 mt-4"):
                ui.button("キャンセル", on_click=dlg.close).props("flat")
                ui.button("OK", icon="undo", on_click=_do_rewind).props("color=primary unelevated")
        dlg.open()

    def open_rewrite_message_dialog(self, index: int) -> None:
        if self.sending:
            ui.notify("生成中は書き換えできません", type="warning")
            return
        if index < 0 or index >= len(self.messages):
            return
        message = self.messages[index]
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
                if index >= len(self.messages):
                    dlg.close()
                    return
                self.messages[index]["text"] = next_text
                dlg.close()
                self.refresh_messages()
                await self.save_current_session()

            with ui.row().classes("justify-end gap-2 mt-4"):
                ui.button("キャンセル", on_click=dlg.close).props("flat")
                ui.button("保存", icon="save", on_click=_save_rewrite).props("color=primary unelevated")
        dlg.open()

    async def regenerate_character_message(self, index: int) -> None:
        if self.sending:
            ui.notify("生成中は再生成できません", type="warning")
            return
        if self.settings is None:
            ui.notify("先に「新しいチャット」を作成してください", type="warning")
            self.open_new_chat_dialog()
            return
        if index < 0 or index >= len(self.messages):
            return
        message = self.messages[index]
        if message.get("role") != "character":
            return
        active = self.active_members()
        if not active:
            ui.notify("参加キャラがいません", type="warning")
            return
        llm = _configured_group_chat_llm(self.ctx, str(self.settings.get("profile_id", "")))
        if llm is None:
            return
        if self.active_session_id is None:
            return

        original_messages = [dict(item) for item in self.messages]
        prior_messages = [dict(item) for item in self.messages[:index]]
        rollback_messages = original_messages if index == len(original_messages) - 1 else prior_messages
        self.last_speaker_debug = None

        display_speaker = self._member_by_id(str(message.get("speaker_id", ""))) or active[0]
        self.messages = prior_messages + [group_message("character", "…", member=display_speaker)]
        self.refresh_messages()
        session_id = self.active_session_id
        title = self.title
        title_is_auto = self.active_title_is_auto
        settings_snapshot = dict(self.settings)
        await self.save_current_session(refresh_history=False)

        async def _runner(job) -> list[dict[str, Any]]:
            try:
                self.last_speaker_debug = None
                result = await self.ctx.group_chat_turns.run_character_turn(
                    group=self.group,
                    settings=settings_snapshot,
                    messages=prior_messages,
                    llm=llm,
                    active_members=active,
                )
                self.last_speaker_debug = result.speaker_debug
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=settings_snapshot,
                    messages=result.messages,
                )
                return result.messages
            except Exception:
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=settings_snapshot,
                    messages=rollback_messages,
                )
                raise

        job = self.ctx.ai_jobs.start_job(
            kind=AIJobKind.LLM_GROUP_CHAT,
            label=f"{self.group.name or 'グループ'}の再生成",
            scope=self._active_group_chat_scope(),
            metadata={"session_id": session_id, "group_id": self.group.id},
            runner=_runner,
        )
        self.ctx.ai_jobs.set_result_meta(job.id, {"result_url": f"/groups/{self.group.id}"})
        generated_successfully = await self._wait_for_active_group_job(
            job.id,
            failure_message="再生成に失敗しました",
        )
        if generated_successfully:
            await self.maybe_generate_auto_title(llm)

    async def confirm_or_regenerate_character_message(self, index: int) -> None:
        if self.sending:
            ui.notify("生成中は再生成できません", type="warning")
            return
        if index < 0 or index >= len(self.messages):
            return
        if self.messages[index].get("role") != "character":
            return
        if index == len(self.messages) - 1:
            await self.regenerate_character_message(index)
            return

        with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm"):
            ui.label("この台詞から再生成しますか？").classes("text-base font-semibold")
            ui.label("この台詞以降の会話を削除してから、新しい台詞を生成します。").classes("text-sm text-grey-6")
            ui.label(str(self.messages[index].get("text", ""))).classes("text-sm").style(
                "white-space: pre-wrap; overflow-wrap: anywhere;"
            )

            async def _do_regenerate() -> None:
                dlg.close()
                await self.regenerate_character_message(index)

            with ui.row().classes("justify-end gap-2 mt-4"):
                ui.button("キャンセル", on_click=dlg.close).props("flat")
                ui.button("再生成", icon="refresh", on_click=_do_regenerate).props("color=primary unelevated")
        dlg.open()

    def message_tts_playable(self, message: dict[str, Any]) -> bool:
        role = str(message.get("role", ""))
        if not str(message.get("text", "")).strip():
            return False
        if role == "narration":
            return self._narrator_tts_configured()
        if role == "character":
            member = self._member_by_id(str(message.get("speaker_id", "")))
            return member is not None and self._character_tts_configured(member)
        if role == "user":
            persona = self.group.user_persona
            return persona is not None and self._user_persona_tts_configured(persona)
        return False

    async def play_tts_message(self, index: int) -> None:
        if self.tts_generating_index is not None:
            ui.notify("音声生成中です", type="info")
            return
        if index < 0 or index >= len(self.messages):
            return
        message = self.messages[index]
        role = str(message.get("role", ""))
        if role not in {"character", "user", "narration"}:
            return
        text = str(message.get("text", "")).strip()
        if not text or text in {"…", "..."}:
            ui.notify("読み上げる本文がありません", type="warning")
            return

        target = self._tts_target_for_message(message)
        if target is None:
            return
        settings = target["settings"]
        if (
            settings.api_type == CHARACTER_TTS_API_GEN_SERVER
            and settings.gen_server_tts_mode == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3
            and not settings.voice_caption.strip()
        ):
            ui.notify("VoiceDesign v3モードのキャプションを設定してください", type="warning")
            return

        self.tts_generating_index = index
        self.refresh_messages()
        try:
            voice = target["voice"]

            def _save_playback(audio: bytes, job) -> dict[str, str]:
                playback_path = target["playback_save"](audio)
                return {
                    "playback_path": str(playback_path),
                    "result_url": f"/groups/{self.group.id}",
                }

            job = self.ctx.tts.start_synthesize_job(
                target["target_id"],
                target["voice_path"],
                text,
                endpoint_id=settings.endpoint_id,
                voice_id=settings.voice_id,
                filename=voice.original_name if voice else "",
                content_type=voice.content_type if voice else "",
                api_type=settings.api_type,
                gen_server_tts_mode=settings.gen_server_tts_mode,
                voice_caption=settings.voice_caption,
                gen_server_params=settings.gen_server_params,
                label="グループチャット読み上げ",
                scope=f"group_tts:{self.active_session_id or self.group.id}",
                metadata={"message_index": index, "group_id": self.group.id},
                result_handler=_save_playback,
            )
            finished = await self.ctx.ai_jobs.wait(job.id)
            if finished.status == AIJobStatus.CANCELLED:
                ui.notify("読み上げを停止しました", type="info")
                return
            if finished.status != AIJobStatus.SUCCEEDED:
                ui.notify(f"読み上げに失敗しました: {finished.error_message}", type="negative", timeout=10000)
                return
            playback_path = finished.result_meta.get("playback_path")
            if not playback_path:
                ui.notify("読み上げ音声を取得できませんでした", type="negative")
                return
            audio_url = app.add_static_file(local_file=playback_path, max_cache_age=0)
            self.page_client.run_javascript(
                f"(() => {{const audio = new Audio({json.dumps(audio_url)});audio.play().catch(() => {{}});}})();"
            )
        except TTSServiceError as err:
            ui.notify(f"読み上げに失敗しました: {err}", type="negative", timeout=10000)
        except Exception as err:
            ui.notify(f"読み上げに失敗しました: {err}", type="negative", timeout=10000)
        finally:
            self.tts_generating_index = None
            self.refresh_messages()

    def _member_by_id(self, member_id: str) -> GroupMember | None:
        return next((member for member in self.group.members if member.id == member_id), None)

    def _character_tts_configured(self, member: GroupMember) -> bool:
        voice = member.character.media.primary_voice()
        voice_path = self.ctx.group_chats.media_path(voice.path) if voice else None
        return bool(
            voice
            and voice_path
            and self.ctx.tts.has_voice_playback_api(
                member.character.media.tts.api_type,
                member.character.media.tts.endpoint_id,
            )
        )

    def _user_persona_tts_configured(self, persona: GroupUserPersona) -> bool:
        settings = persona.media.tts
        if (
            settings.api_type == CHARACTER_TTS_API_GEN_SERVER
            and settings.gen_server_tts_mode == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3
        ):
            return (
                bool(settings.voice_caption.strip())
                and self.ctx.tts.resolve_gen_server_voice_design_endpoint(raise_on_missing=False) is not None
            )
        if (
            settings.api_type == CHARACTER_TTS_API_TTS
            and bool(settings.voice_id.strip())
            and self.ctx.tts.supports_voice_registry(settings.endpoint_id)
        ):
            return self.ctx.tts.has_voice_playback_api(settings.api_type, settings.endpoint_id)
        voice = persona.media.primary_voice()
        voice_path = self.ctx.api_config.media_path(voice.path) if voice else None
        return bool(
            voice and voice_path and self.ctx.tts.has_voice_playback_api(settings.api_type, settings.endpoint_id)
        )

    def _narrator_tts_configured(self, tts_settings=None) -> bool:
        config = self.ctx.api_config.get_tts_config()
        settings = tts_settings or config.narrator
        if settings.api_type == CHARACTER_TTS_API_GEN_SERVER:
            if settings.gen_server_tts_mode == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3:
                return (
                    bool(settings.voice_caption.strip())
                    and self.ctx.tts.resolve_gen_server_voice_design_endpoint(raise_on_missing=False) is not None
                )
            return self.ctx.tts.resolve_gen_server_voice_clone_endpoint(raise_on_missing=False) is not None
        if settings.api_type != CHARACTER_TTS_API_TTS:
            return False
        endpoint = self.ctx.api_config.get_tts_endpoint(settings.endpoint_id)
        if endpoint is None:
            return False
        if endpoint.provider == TTS_PROVIDER_IRODORI_SERVER:
            return bool(settings.voice_id.strip()) and self.ctx.tts.supports_voice_registry(settings.endpoint_id)
        voice = config.narrator_voice
        voice_path = self.ctx.api_config.media_path(voice.path) if voice else None
        return voice is not None and voice_path is not None

    def _voice_design_ready(self, settings) -> bool:
        return (
            settings.api_type == CHARACTER_TTS_API_GEN_SERVER
            and settings.gen_server_tts_mode == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3
            and bool(settings.voice_caption.strip())
        )

    def _tts_target_for_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        role = str(message.get("role", ""))
        if role == "narration":
            config = self.ctx.api_config.get_tts_config()
            settings = config.narrator
            if not self._narrator_tts_configured(settings):
                ui.notify("ナレーターTTS設定を確認してください", type="warning")
                return None
            voice = config.narrator_voice
            voice_path = self.ctx.api_config.media_path(voice.path) if voice else None
            return {
                "target_id": "narrator",
                "settings": settings,
                "voice": voice,
                "voice_path": voice_path,
                "playback_save": self.ctx.api_config.save_narrator_tts_playback,
            }
        if role == "character":
            member = self._member_by_id(str(message.get("speaker_id", "")))
            if member is None or not self._character_tts_configured(member):
                ui.notify("TTS設定を確認してください", type="warning")
                return None
            voice = member.character.media.primary_voice()
            voice_path = self.ctx.group_chats.media_path(voice.path) if voice else None
            target_id = _group_member_tts_id(self.group.id, member.id)
            return {
                "target_id": target_id,
                "settings": member.character.media.tts,
                "voice": voice,
                "voice_path": voice_path,
                "playback_save": lambda audio, member_id=member.id: self.ctx.group_chats.save_member_tts_playback(
                    self.group.id,
                    member_id,
                    audio,
                ),
            }
        if role == "user":
            persona = self.group.user_persona
            if persona is None or not self._user_persona_tts_configured(persona):
                ui.notify("ユーザーペルソナのTTS設定を確認してください", type="warning")
                return None
            settings = persona.media.tts
            voice = persona.media.primary_voice()
            voice_path = self.ctx.api_config.media_path(voice.path) if voice else None
            if voice_path is None and not self._voice_design_ready(settings):
                ui.notify("ユーザーペルソナのTTS設定を確認してください", type="warning")
                return None
            persona_id = persona.id
            return {
                "target_id": _group_user_persona_tts_id(persona_id),
                "settings": settings,
                "voice": voice,
                "voice_path": voice_path,
                "playback_save": lambda audio, target_id=persona_id: self.ctx.api_config.save_user_persona_tts_playback(
                    target_id,
                    audio,
                ),
            }
        return None

    async def select_chat_session(self, session_id: str) -> None:
        if self.sending:
            ui.notify("生成中はチャットを切り替えられません", type="warning")
            return
        session = await self.ctx.group_chats.get_session(session_id)
        if session is None or session.group_id != self.group.id:
            ui.notify("チャットが見つかりません", type="warning")
            await self.reload_sessions()
            self.refresh_history()
            return
        self.sessions_by_id[session.id] = session
        await self.apply_session(session)
        self.refresh_input_mode_indicator()
        self.refresh_chat_header()
        self.refresh_messages(scroll_to_bottom=True)
        self.refresh_history()
        self.refresh_mention_palette()
        self.set_mobile_sidebar(False)

    def active_members(self) -> list[GroupMember]:
        if self.settings is None:
            return []
        ids = {str(member_id) for member_id in self.settings.get("participant_ids", [])}
        return [member for member in self.group.members if member.id in ids]

    async def post_narration(self, text: str) -> None:
        self.messages.append(group_message("narration", text))
        self.refresh_messages(scroll_to_bottom=True)
        await self.save_current_session()

    async def post_memo(self, text: str) -> None:
        self.messages.append(group_message("memo", text))
        self.refresh_messages(scroll_to_bottom=True)
        await self.save_current_session()

    async def post_character_input(self, text: str, member: GroupMember | None = None) -> None:
        member = member or self._manual_character_speaker()
        if member is None:
            ui.notify("参加キャラがいません", type="warning")
            self.set_input_mode("user")
            return
        self.messages.append(group_message("character", text, member=member))
        self.refresh_messages(scroll_to_bottom=True)
        await self.save_current_session()

    async def post_guest_input(self, text: str, guest_name: str | None = None) -> None:
        name = clean_guest_name(guest_name or self.guest_input_name)
        if not name:
            ui.notify("ゲスト名を入力してください", type="warning")
            self.open_guest_input_mode_dialog(text)
            return
        self.messages.append(group_message("guest", text, guest_name=name))
        self.refresh_messages(scroll_to_bottom=True)
        await self.save_current_session()

    async def post_hold_user_text(self, text: str) -> None:
        self.messages.append(group_message("user", text, user=self.group.user_persona))
        self.refresh_messages(scroll_to_bottom=True)
        await self.save_current_session()

    async def post_command_left_text(self, left_text: str) -> None:
        text = left_text.strip()
        if not text:
            return
        self.clear_input()
        if self.input_mode == "narration":
            await self.post_narration(text)
            self.set_input_mode("user")
            return
        if self.input_mode == "memo":
            await self.post_memo(text)
            self.set_input_mode("user")
            return
        if self.input_mode == "character":
            await self.post_character_input(text)
            self.set_input_mode("user")
            return
        if self.input_mode == "guest":
            await self.post_guest_input(text)
            self.set_input_mode("user")
            return
        await self.post_hold_user_text(text)

    async def send_user_turn(self, text: str) -> None:
        self.clear_input()
        self.messages.append(group_message("user", text.strip(), user=self.group.user_persona))
        self.set_input_mode("user")
        self.refresh_messages(scroll_to_bottom=True)
        await self.save_current_session(refresh_history=False)
        await self.append_character_turn()

    async def generate_scene(self, *, instruction: str = "") -> None:
        if self.settings is None:
            return
        try:
            llm = self.ctx.group_chat_assist.build_llm(
                str(self.settings.get("profile_id", "")),
                get_vault_password(),
            )
        except LLMRuntimeError as err:
            _notify_group_chat_llm_runtime_error(err)
            return
        if self.active_session_id is None:
            return

        prior_messages = [dict(message) for message in self.messages]
        self.messages.append(group_message("narration", "…"))
        self.refresh_messages(scroll_to_bottom=True)
        session_id = self.active_session_id
        title = self.title
        title_is_auto = self.active_title_is_auto
        settings_snapshot = dict(self.settings)
        await self.save_current_session(refresh_history=False)

        async def _runner(job) -> list[dict[str, Any]]:
            generated = await self.ctx.group_chat_assist.generate_scene_message(
                llm=llm,
                group=self.group,
                settings=settings_snapshot,
                messages=prior_messages,
                instruction=instruction,
            )
            messages = prior_messages + [generated]
            await self._save_session_messages_snapshot(
                session_id=session_id,
                title=title,
                title_is_auto=title_is_auto,
                settings=settings_snapshot,
                messages=messages,
            )
            return messages

        async def _safe_runner(job) -> list[dict[str, Any]]:
            try:
                return await _runner(job)
            except Exception:
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=settings_snapshot,
                    messages=prior_messages,
                )
                raise

        job = self.ctx.ai_jobs.start_job(
            kind=AIJobKind.LLM_NARRATION,
            label="グループ地の文生成",
            scope=self._active_group_chat_scope(),
            metadata={"session_id": session_id, "group_id": self.group.id},
            runner=_safe_runner,
        )
        self.ctx.ai_jobs.set_result_meta(job.id, {"result_url": f"/groups/{self.group.id}"})
        await self._wait_for_active_group_job(
            job.id,
            failure_message="地の文生成に失敗しました",
        )

    async def run_describe_action(self, left_text: str, *, instruction: str = "") -> None:
        if left_text.strip():
            await self.post_command_left_text(left_text)
        else:
            self.clear_input()
        self.set_input_mode("user")
        self.clear_input()
        try:
            await self.generate_scene(instruction=instruction)
        finally:
            self.clear_input()

    async def fill_input_text(self, left_text: str) -> None:
        if self.settings is None:
            return
        if not left_text.strip():
            ui.notify("補完する文を /fill の左側に入力してください", type="warning")
            return
        completed = await self._await_group_llm_assist_result(
            self.ctx.group_chat_assist.complete_input_text(
                profile_id=str(self.settings.get("profile_id", "")),
                vault_password=get_vault_password(),
                group=self.group,
                settings=self.settings,
                messages=self.messages,
                left_text=left_text,
                input_mode=self.input_mode,
                speaker=self._manual_character_speaker(),
                guest_name=self.guest_input_name,
                scope=self._group_assist_scope(),
                metadata=self._group_assist_metadata(),
                result_url=self._group_assist_result_url(),
            ),
            failure_message="補完に失敗しました",
        )
        if completed is None:
            return
        self.set_input_value(str(completed))
        ui.notify("続きを補完しました", type="positive")
        self.focus_chat_input_at_end()

    async def tailor_input_text(self, left_text: str) -> None:
        if self.settings is None:
            return
        if not left_text.strip():
            ui.notify("書き換える文を /tailor の左側に入力してください", type="warning")
            return
        tailored = await self._await_group_llm_assist_result(
            self.ctx.group_chat_assist.tailor_input_text(
                profile_id=str(self.settings.get("profile_id", "")),
                vault_password=get_vault_password(),
                group=self.group,
                settings=self.settings,
                messages=self.messages,
                left_text=left_text,
                input_mode=self.input_mode,
                speaker=self._manual_character_speaker(),
                guest_name=self.guest_input_name,
                scope=self._group_assist_scope(),
                metadata=self._group_assist_metadata(),
                result_url=self._group_assist_result_url(),
            ),
            failure_message="書き換えに失敗しました",
        )
        if tailored is None:
            return
        if not tailored:
            ui.notify("書き換え結果が空でした", type="warning")
            return
        self.set_input_value(str(tailored))
        ui.notify("現在のロール向けに書き換えました", type="positive")
        self.focus_chat_input_at_end()

    async def show_response_choices(self, left_text: str) -> None:
        if self.settings is None:
            return
        input_mode = self.input_mode
        speaker = self._manual_character_speaker()
        guest_name = self.guest_input_name

        choices = await self._await_group_llm_assist_result(
            self.ctx.group_chat_assist.generate_response_choices(
                profile_id=str(self.settings.get("profile_id", "")),
                vault_password=get_vault_password(),
                group=self.group,
                settings=self.settings,
                messages=self.messages,
                left_text=left_text,
                input_mode=input_mode,
                speaker=speaker,
                guest_name=guest_name,
                scope=self._group_assist_scope(),
                metadata=self._group_assist_metadata(),
                result_url=self._group_assist_result_url(),
            ),
            failure_message="選択肢生成に失敗しました",
        )
        if choices is None:
            return
        choices = list(choices or [])

        if not choices:
            ui.notify("選択肢を生成できませんでした", type="warning")
            return

        with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg cs-chat-choice-dialog"):
            ui.label("応答を選択").classes("text-base font-semibold")
            target_label = _group_message_target_label(input_mode)
            ui.label(f"選ぶとその{target_label}を入力欄に入れます。").classes("text-sm text-grey-6")

            def _choose(choice: str) -> None:
                dlg.close()
                self.set_input_value(choice)
                self.focus_chat_input_at_end()

            def _choice_click_handler(choice: str):
                def _handler() -> None:
                    _choose(choice)

                return _handler

            with ui.column().classes("w-full gap-2 mt-2"):
                for index, choice in enumerate(choices[:3]):
                    classes = "w-full cs-chat-choice-option"
                    if index == 0:
                        classes += " cs-chat-choice-option-active"
                    ui.button(choice, on_click=_choice_click_handler(choice)).props(
                        f"outline color=primary align=left data-choice-index={index} aria-selected={'true' if index == 0 else 'false'}"
                    ).classes(classes)
            with ui.row().classes("justify-end mt-2"):
                ui.button("閉じる", on_click=dlg.close).props(
                    "flat data-choice-index=close aria-selected=false"
                ).classes("cs-chat-choice-close")
        dlg.open()
        self.install_choice_keyboard_handler()

    def install_choice_keyboard_handler(self) -> None:
        self.page_client.run_javascript(
            """
setTimeout(() => {
  const root = document.querySelector('.cs-chat-choice-dialog');
  if (!root) return;
  const options = Array.from(root.querySelectorAll('.cs-chat-choice-option, .cs-chat-choice-close'));
  if (!options.length) return;
  const activeIndex = () => Math.max(0, options.findIndex(option => option.classList.contains('cs-chat-choice-option-active')));
  const setActive = index => {
    options.forEach((option, optionIndex) => {
      const active = optionIndex === index;
      option.classList.toggle('cs-chat-choice-option-active', active);
      option.setAttribute('aria-selected', active ? 'true' : 'false');
      if (active && typeof option.scrollIntoView === 'function') {
        option.scrollIntoView({ block: 'nearest' });
      }
    });
  };
  setActive(0);
  if (window.__csChoiceKeydown) {
    document.removeEventListener('keydown', window.__csChoiceKeydown, true);
  }
  window.__csChoiceKeydown = event => {
    if (!document.body.contains(root)) {
      document.removeEventListener('keydown', window.__csChoiceKeydown, true);
      window.__csChoiceKeydown = null;
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const delta = event.key === 'ArrowDown' ? 1 : -1;
      setActive((activeIndex() + delta + options.length) % options.length);
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      (options[activeIndex()] || options[0]).click();
    }
  };
  document.addEventListener('keydown', window.__csChoiceKeydown, true);
}, 0);
"""
        )

    async def open_guide_next_turn_dialog(self, left_text: str = "") -> None:
        if left_text.strip():
            self.set_input_value(left_text)
        else:
            self.clear_input()

        active = self.active_members()
        active_ids = {member.id for member in active}
        inactive = [member for member in self.group.members if member.id not in active_ids]
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
            for member in self.group.members:
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
                for member in self.group.members:
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
                    ui.button()
                    .props("flat dense unelevated aria-label=行動者を選択")
                    .classes("cs-group-guide-actor-icon")
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
                                        _render_group_member_menu_face(self.ctx, member)
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
                                        _render_group_member_menu_face(self.ctx, member)
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
                            _render_group_user_menu_face(self.ctx, self.group.user_persona)
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
                                _render_group_member_menu_face(self.ctx, member)
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
                        _render_group_member_menu_face(self.ctx, member)
                        return
                    kind = str(resolved.get("kind") or "")
                    if kind == "auto":
                        _render_group_role_icon("character")
                    elif kind == "guest":
                        _render_group_role_icon("guest")
                    elif kind == "narration":
                        _render_group_role_icon("narration")
                    elif kind == "user":
                        _render_group_user_menu_face(self.ctx, self.group.user_persona)
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
                        self.clear_input()
                        await self.post_hold_user_text(left_text.strip())
                    else:
                        self.clear_input()
                        self.set_input_mode("user")
                    return
                if resolved["kind"] == "narration":
                    await self.run_describe_action(left_text, instruction=direction)
                    return
                if left_text.strip():
                    await self.post_command_left_text(left_text)
                else:
                    self.clear_input()
                if resolved["kind"] == "auto":
                    await self.append_character_turn(turn_instruction=direction)
                    return
                if resolved["kind"] == "guest":
                    await self.append_guest_turn(
                        str(resolved.get("guest_name") or ""),
                        turn_instruction=direction,
                    )
                    return
                member = resolved.get("member")
                if not isinstance(member, GroupMember):
                    ui.notify("行動者を指定してください", type="warning")
                    return
                if not resolved["active"]:
                    await self.append_guided_member_turn(
                        member,
                        turn_instruction=direction,
                        membership_action="join",
                    )
                    return
                if departure_state["value"]:
                    await self.append_guided_member_turn(
                        member,
                        turn_instruction=direction,
                        membership_action="leave",
                    )
                    return
                await self.append_character_turn(
                    speaker=member,
                    turn_instruction=direction,
                )

            _sync_actor_controls()
            with ui.row().classes("justify-end gap-2 mt-4"):
                ui.button("キャンセル", on_click=dlg.close).props("flat")
                ui.button("実行", icon="play_arrow", on_click=_run_directed_turn).props("color=primary unelevated")
        dlg.open()
        ui.timer(0.1, lambda: actor_input.run_method("focus"), once=True)

    def open_imitate_character_dialog(self, left_text: str = "") -> None:
        active = self.active_members()
        active_ids = {member.id for member in active}
        inactive = [member for member in self.group.members if member.id not in active_ids]
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
            for member in self.group.members:
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
                for member in self.group.members:
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
                    ui.button()
                    .props("flat dense unelevated aria-label=発言者を選択")
                    .classes("cs-group-guide-actor-icon")
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
                                        _render_group_member_menu_face(self.ctx, member)
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
                                            _render_group_member_menu_face(self.ctx, member)
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
                                _render_group_member_menu_face(self.ctx, member)
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
                        _render_group_member_menu_face(self.ctx, member)
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
                    self.set_guest_input_mode(str(resolved.get("guest_name") or ""))
                else:
                    member = resolved.get("member")
                    if not isinstance(member, GroupMember):
                        ui.notify("発言者を指定してください", type="warning")
                        return
                    if self.settings is not None and member.id not in group_participant_ids(self.settings):
                        self.settings = settings_with_participant(self.settings, member.id)
                        self.messages.append(group_system_event_message(f"{member.character.name}が入場しました"))
                        self.refresh_messages(scroll_to_bottom=True)
                        await self.save_current_session(refresh_history=False)
                        self.refresh_mention_palette()
                        self.refresh_chat_header()
                    self.set_character_input_member(member)
                self.set_input_value(left_text.rstrip())
                self.focus_chat_input_at_end()
                dlg.close()
                ui.notify("入力モードにしました", type="info")

            _sync_actor_controls()
            with ui.row().classes("justify-end gap-2 mt-4"):
                ui.button("キャンセル", on_click=dlg.close).props("flat")
                ui.button("選択", icon="theater_comedy", on_click=_apply).props("color=primary unelevated")
        dlg.open()
        ui.timer(0.1, lambda: actor_input.run_method("focus"), once=True)

    async def execute_chat_command(self, left_text: str, query: str) -> None:
        command = resolve_chat_command(query)
        if command is None:
            ui.notify("実行するコマンドを選択してください", type="warning")
            return

        left_text = left_text.rstrip()
        if command == "hold":
            if not left_text.strip():
                ui.notify("/hold の左側に投稿する文を入力してください", type="warning")
                return
            self.clear_input()
            await self.post_command_left_text(left_text)
            return
        if command == "guide":
            await self.open_guide_next_turn_dialog(left_text)
            return
        if command == "fill":
            self.set_input_value(left_text)
            await self.fill_input_text(left_text)
            return
        if command == "tailor":
            self.set_input_value(left_text)
            await self.tailor_input_text(left_text)
            return
        if command == "choices":
            self.set_input_value(left_text)
            await self.show_response_choices(left_text)
            return
        if command == "skip":
            if left_text.strip():
                ui.notify("/skip は単独で入力してください", type="warning")
                return
            self.clear_input()
            await self.append_character_turn()
            return
        if command == "narrate":
            self.set_input_value(left_text)
            self.set_input_mode("narration")
            ui.notify("ナラティブ入力モードにしました", type="info")
            return
        if command == "memo":
            self.set_input_value(left_text)
            self.set_input_mode("memo")
            ui.notify("コメント入力モードにしました", type="info")
            return
        if command == "imitate":
            self.open_imitate_character_dialog(left_text)
            return
        if command == "user":
            self.set_input_value(left_text)
            self.set_input_mode("user")
            ui.notify("ユーザー入力モードに戻しました", type="info")
            return
        if command == "describe":
            await self.run_describe_action(left_text)
            return

    async def send_message(self, allow_skip: bool = False, submitted_text: str | None = None) -> None:
        if self.sending:
            return
        if self.settings is None:
            ui.notify("先に「新しいチャット」を作成してください", type="warning")
            self.open_new_chat_dialog()
            return

        raw_text = (
            submitted_text
            if submitted_text is not None
            else (self.input_box.value if self.input_box is not None else "")
        )
        parsed_command = parse_command_input(raw_text or "")
        if parsed_command is not None:
            left_text, query = parsed_command
            await self.execute_chat_command(left_text, query)
            return

        text = (raw_text or "").strip()
        if text == "/skip":
            self.clear_input()
            await self.append_character_turn()
            return
        if not text:
            if not allow_skip:
                ui.notify("メッセージを入力してください", type="warning")
                return
            await self.append_character_turn()
            return

        self.clear_input()
        if self.input_mode == "narration":
            self.messages.append(group_message("narration", text))
            self.set_input_mode("user")
            self.refresh_messages(scroll_to_bottom=True)
            await self.save_current_session()
            return
        if self.input_mode == "memo":
            self.messages.append(group_message("memo", text))
            self.set_input_mode("user")
            self.refresh_messages(scroll_to_bottom=True)
            await self.save_current_session()
            return
        if self.input_mode == "character":
            member = self._manual_character_speaker()
            if member is None:
                ui.notify("参加キャラがいません", type="warning")
                self.set_input_mode("user")
                return
            self.messages.append(group_message("character", text, member=member))
            self.set_input_mode("user")
            self.refresh_messages(scroll_to_bottom=True)
            await self.save_current_session()
            return
        if self.input_mode == "guest":
            name = clean_guest_name(self.guest_input_name)
            if not name:
                ui.notify("ゲスト名を入力してください", type="warning")
                self.open_guest_input_mode_dialog(text)
                return
            self.messages.append(group_message("guest", text, guest_name=name))
            self.set_input_mode("user")
            self.refresh_messages(scroll_to_bottom=True)
            await self.save_current_session()
            return

        self.messages.append(group_message("user", text, user=self.group.user_persona))
        self.set_input_mode("user")
        self.refresh_messages(scroll_to_bottom=True)
        await self.save_current_session(refresh_history=False)
        await self.append_character_turn()

    def _manual_character_speaker(self) -> GroupMember | None:
        current = self.current_participant()
        if current is not None and current.get("kind") == "character":
            member = current.get("member")
            if isinstance(member, GroupMember) and member in self.active_members():
                return member
        active = self.active_members()
        return active[0] if active else None

    async def append_character_turn(
        self,
        *,
        speaker: GroupMember | None = None,
        turn_instruction: str = "",
    ) -> None:
        if self.settings is None:
            ui.notify("先に「新しいチャット」を作成してください", type="warning")
            self.open_new_chat_dialog()
            return
        active = self.active_members()
        if not active:
            ui.notify("参加キャラがいません", type="warning")
            return

        llm = _configured_group_chat_llm(self.ctx, str(self.settings.get("profile_id", "")))
        if llm is None:
            return
        if self.active_session_id is None:
            return

        prior_messages = [dict(message) for message in self.messages]
        placeholder_index = len(self.messages)
        self.last_speaker_debug = None
        display_speaker = speaker or active[0]
        self.messages.append(group_message("character", "…", member=display_speaker))
        self.refresh_messages(scroll_to_bottom=True)
        session_id = self.active_session_id
        title = self.title
        title_is_auto = self.active_title_is_auto
        settings_snapshot = dict(self.settings)
        await self.save_current_session(refresh_history=False)

        async def _runner(job) -> list[dict[str, Any]]:
            self.last_speaker_debug = None
            try:
                result = await self.ctx.group_chat_turns.run_character_turn(
                    group=self.group,
                    settings=settings_snapshot,
                    messages=prior_messages,
                    llm=llm,
                    active_members=active,
                    speaker=speaker,
                    turn_instruction=turn_instruction,
                )
                self.last_speaker_debug = result.speaker_debug
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=settings_snapshot,
                    messages=result.messages,
                )
                return result.messages
            except Exception:
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=settings_snapshot,
                    messages=prior_messages,
                )
                raise

        job = self.ctx.ai_jobs.start_job(
            kind=AIJobKind.LLM_GROUP_CHAT,
            label=f"{self.group.name or 'グループ'}の発言生成",
            scope=self._active_group_chat_scope(),
            metadata={"session_id": session_id, "group_id": self.group.id},
            runner=_runner,
        )
        self.ctx.ai_jobs.set_result_meta(job.id, {"result_url": f"/groups/{self.group.id}"})
        generated_successfully = await self._wait_for_active_group_job(
            job.id,
            failure_message="グループチャット生成に失敗しました",
        )
        self.set_input_mode("user")
        if generated_successfully:
            await self.maybe_generate_auto_title(llm)

    async def append_guided_member_turn(
        self,
        speaker: GroupMember,
        *,
        turn_instruction: str = "",
        membership_action: str = "",
    ) -> None:
        if self.settings is None:
            ui.notify("先に「新しいチャット」を作成してください", type="warning")
            self.open_new_chat_dialog()
            return
        if self.active_session_id is None:
            return

        current_settings = dict(self.settings)
        current_ids = group_participant_ids(current_settings)
        if membership_action == "join":
            if speaker.id in current_ids:
                await self.append_character_turn(
                    speaker=speaker,
                    turn_instruction=turn_instruction,
                )
                return
            generation_settings = settings_with_participant(current_settings, speaker.id)
            final_settings = dict(generation_settings)
            pre_events = [group_system_event_message(f"{speaker.character.name}が入場しました")]
            post_events: list[dict[str, Any]] = []
        elif membership_action == "leave":
            if speaker.id not in current_ids:
                ui.notify("退場させるキャラクターが現在のチャットに参加していません", type="warning")
                return
            if len(current_ids) <= 1:
                ui.notify("参加キャラクターがいなくなるため退場できません", type="warning")
                return
            generation_settings = dict(current_settings)
            final_settings = settings_without_participant(current_settings, speaker.id)
            pre_events = []
            post_events = [group_system_event_message(f"{speaker.character.name}が退場しました")]
        else:
            await self.append_character_turn(
                speaker=speaker,
                turn_instruction=turn_instruction,
            )
            return

        llm = _configured_group_chat_llm(self.ctx, str(current_settings.get("profile_id", "")))
        if llm is None:
            return

        original_messages = [dict(message) for message in self.messages]
        original_settings = dict(current_settings)
        prior_messages = [dict(message) for message in self.messages] + [dict(message) for message in pre_events]
        self.messages = prior_messages + [group_message("character", "…", member=speaker)]
        self.settings = dict(generation_settings)
        self.refresh_messages(scroll_to_bottom=True)
        self.refresh_mention_palette()

        session_id = self.active_session_id
        title = self.title
        title_is_auto = self.active_title_is_auto
        await self.save_current_session(refresh_history=False)

        async def _runner(job) -> list[dict[str, Any]]:
            base_messages = [dict(message) for message in prior_messages]
            try:
                result = await self.ctx.group_chat_turns.run_character_turn(
                    group=self.group,
                    settings=generation_settings,
                    messages=base_messages,
                    llm=llm,
                    active_members=[speaker],
                    speaker=speaker,
                    turn_instruction=turn_instruction,
                )
                messages = result.messages + [dict(message) for message in post_events]
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=final_settings,
                    messages=messages,
                )
                return messages
            except Exception:
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=original_settings,
                    messages=original_messages,
                )
                raise

        job = self.ctx.ai_jobs.start_job(
            kind=AIJobKind.LLM_GROUP_CHAT,
            label=f"{self.group.name or 'グループ'}の発言生成",
            scope=self._active_group_chat_scope(),
            metadata={"session_id": session_id, "group_id": self.group.id},
            runner=_runner,
        )
        self.ctx.ai_jobs.set_result_meta(job.id, {"result_url": f"/groups/{self.group.id}"})
        generated_successfully = await self._wait_for_active_group_job(
            job.id,
            failure_message="グループチャット生成に失敗しました",
        )
        self.set_input_mode("user")
        if generated_successfully:
            await self.maybe_generate_auto_title(llm)

    async def append_guest_turn(
        self,
        guest_name: str,
        *,
        turn_instruction: str = "",
    ) -> None:
        name = clean_guest_name(guest_name)
        if not name:
            ui.notify("ゲスト名を入力してください", type="warning")
            return
        if self.settings is None:
            ui.notify("先に「新しいチャット」を作成してください", type="warning")
            self.open_new_chat_dialog()
            return
        llm = _configured_group_chat_llm(self.ctx, str(self.settings.get("profile_id", "")))
        if llm is None:
            return
        if self.active_session_id is None:
            return

        prior_messages = [dict(message) for message in self.messages]
        self.messages.append(group_message("guest", "…", guest_name=name))
        self.refresh_messages(scroll_to_bottom=True)
        session_id = self.active_session_id
        title = self.title
        title_is_auto = self.active_title_is_auto
        settings_snapshot = dict(self.settings)
        await self.save_current_session(refresh_history=False)

        async def _runner(job) -> list[dict[str, Any]]:
            try:
                result = await self.ctx.group_chat_turns.run_guest_turn(
                    group=self.group,
                    settings=settings_snapshot,
                    messages=prior_messages,
                    llm=llm,
                    guest_name=name,
                    turn_instruction=turn_instruction,
                )
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=settings_snapshot,
                    messages=result.messages,
                )
                return result.messages
            except Exception:
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=settings_snapshot,
                    messages=prior_messages,
                )
                raise

        job = self.ctx.ai_jobs.start_job(
            kind=AIJobKind.LLM_GROUP_CHAT,
            label=f"{self.group.name or 'グループ'}のゲスト発言生成",
            scope=self._active_group_chat_scope(),
            metadata={"session_id": session_id, "group_id": self.group.id},
            runner=_runner,
        )
        self.ctx.ai_jobs.set_result_meta(job.id, {"result_url": f"/groups/{self.group.id}"})
        generated_successfully = await self._wait_for_active_group_job(
            job.id,
            failure_message="ゲスト発言生成に失敗しました",
        )
        self.set_input_mode("user")
        if generated_successfully:
            await self.maybe_generate_auto_title(llm)

    async def choose_next_speaker(self, llm, active: list[GroupMember]) -> GroupMember:
        result = await self.ctx.group_chat_turns.choose_next_speaker(
            group=self.group,
            settings=self.settings or {},
            messages=self.messages,
            llm=llm,
            active_members=active,
        )
        self.last_speaker_debug = result.debug
        return result.speaker

    async def choose_speaker_with_llm(self, llm, candidates: list[GroupMember]) -> GroupMember:
        result = await self.ctx.group_chat_turns.choose_speaker_with_llm(
            group=self.group,
            settings=self.settings or {},
            messages=self.messages,
            llm=llm,
            candidates=candidates,
        )
        self.last_speaker_debug = result.debug
        return result.speaker

    async def build_character_message(
        self,
        llm,
        speaker: GroupMember,
        *,
        speaker_debug: ChatDebugInfo | None = None,
        prior_messages: list[dict[str, Any]] | None = None,
        turn_instruction: str = "",
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self.ctx.group_chat_turns.build_character_message(
            group=self.group,
            settings=settings or self.settings or {},
            messages=self.messages if prior_messages is None else prior_messages,
            llm=llm,
            speaker=speaker,
            speaker_debug=speaker_debug,
            turn_instruction=turn_instruction,
        )

    async def maybe_generate_auto_title(self, llm) -> None:
        if self.active_session_id is None or not self.active_title_is_auto:
            return
        if self.title_generation_attempted:
            return
        dialog_turns = [message for message in self.messages if message.get("role") in {"user", "character"}]
        if len(dialog_turns) < 4:
            return
        self.title_generation_attempted = True
        try:
            title = await self.ctx.group_chat_turns.generate_auto_title(
                group=self.group,
                messages=self.messages,
                llm=llm,
            )
        except Exception:
            return
        if not title:
            return
        self.title = title
        self.active_title_is_auto = False
        self.refresh_chat_header()
        await self.save_current_session()

    def open_new_chat_dialog(self) -> None:
        profile_options = _profile_options(self.ctx, self.ctx.api_config.get_llm_profiles())
        default_profile = (
            self.group.completion_profile_id
            if self.group.completion_profile_id in profile_options
            else _default_profile_id(self.ctx, profile_options)
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
                if not self.group.members:
                    ui.label("参加できるキャラクターがいません").classes("text-sm text-grey-6")
                for member in self.group.members:
                    with ui.row().classes("items-center gap-2 w-full"):
                        _render_face(self.ctx, member.character.media, "character")
                        with ui.column().classes("gap-0 min-w-0 flex-1"):
                            ui.label(member.character.name).classes("text-sm font-semibold")
                            ui.label(f"@{member.handle}").classes("text-xs text-grey-6")
                        member_checks[member.id] = ui.checkbox(value=True)

            with ui.element("div").classes("cs-group-world-field"):
                situation_input = ui.textarea(label="シチュエーション").props("outlined rows=4").classes("w-full")

                async def _enhance_situation_click() -> None:
                    participant_ids = [
                        member_id for member_id, checkbox in member_checks.items() if bool(checkbox.value)
                    ]
                    enhanced = await self.enhance_situation(
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
                await self.start_chat_session(
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

    async def enhance_situation(
        self,
        profile_id: str,
        participant_ids: list[str],
        current_situation: str,
    ) -> str | None:
        current = current_situation.strip()
        if not current:
            ui.notify("先にシチュエーションを入力してください", type="warning")
            return None
        enhanced = await self._await_group_llm_assist_result(
            self.ctx.group_chat_assist.enhance_situation(
                profile_id=profile_id,
                vault_password=get_vault_password(),
                group=self.group,
                participant_ids=participant_ids,
                current_situation=current,
                scope=self._group_assist_scope(),
                metadata=self._group_assist_metadata(),
                result_url=self._group_assist_result_url(),
            ),
            failure_message="シチュエーション補完に失敗しました",
        )
        if enhanced is None:
            return None
        if not enhanced:
            ui.notify("シチュエーションを補完できませんでした", type="warning")
            return None
        ui.notify("シチュエーションを補完しました", type="positive")
        return str(enhanced)

    async def start_chat_session(self, settings: dict[str, Any], *, title: str = "") -> None:
        title = title.strip()
        self.settings = settings
        self.title = title or DEFAULT_GROUP_CHAT_TITLE
        self.active_title_is_auto = not title
        self.title_generation_attempted = False
        self.messages = []
        self.input_mode = "user"
        if self.input_box is not None:
            self.input_box.set_value("")
        situation = str(settings.get("situation", "") or "").strip()
        if situation:
            self.messages.append(group_message("narration", situation))
        saved = await self.ctx.group_chats.create_session(
            group_id=self.group.id,
            title=self.title,
            title_is_auto=self.active_title_is_auto,
            settings=settings,
            messages=self.messages,
        )
        self.active_session_id = saved.id
        self.sessions_by_id[saved.id] = saved
        await self.reload_sessions()
        self.refresh_input_mode_indicator()
        self.refresh_chat_header()
        self.refresh_messages(scroll_to_bottom=True)
        self.refresh_history()

    def open_rename_current_chat_dialog(self) -> None:
        if self.active_session_id is None:
            ui.notify("先にチャットを開始してください", type="warning")
            return
        self.open_rename_chat_dialog(self.active_session_id)

    def open_rename_chat_dialog(self, session_id: str) -> None:
        session = self.sessions_by_id.get(session_id)
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
                saved = await self.ctx.group_chats.rename_session(session_id, title)
                if saved is None:
                    dlg.close()
                    ui.notify("チャットが見つかりません", type="warning")
                    await self.reload_sessions()
                    self.refresh_history()
                    return
                self.sessions_by_id[saved.id] = saved
                if saved.id == self.active_session_id:
                    self.title = saved.title
                    self.active_title_is_auto = False
                    self.refresh_chat_header()
                await self.reload_sessions()
                self.refresh_history()
                dlg.close()

            with ui.row().classes("justify-end gap-2 mt-4"):
                ui.button("キャンセル", on_click=dlg.close).props("flat")
                ui.button("保存", icon="save", on_click=_save_title).props("color=primary unelevated")
        dlg.open()

    def confirm_delete_current_chat(self) -> None:
        if self.active_session_id is None:
            ui.notify("削除するチャットがありません", type="warning")
            return
        self.confirm_delete_chat_session(self.active_session_id)

    def confirm_delete_chat_session(self, session_id: str) -> None:
        if self.sending:
            ui.notify("生成中は削除できません", type="warning")
            return
        session = self.sessions_by_id.get(session_id)
        if session is None:
            ui.notify("チャットが見つかりません", type="warning")
            return
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm"):
            ui.label("チャットを削除しますか？").classes("text-base font-semibold")
            ui.label("この操作は元に戻せません。").classes("text-sm text-grey-6")
            ui.label(session.title or DEFAULT_GROUP_CHAT_TITLE).classes("text-sm font-semibold")

            async def _delete() -> None:
                dlg.close()
                was_active = session_id == self.active_session_id
                await self.ctx.group_chats.delete_session(session_id)
                await self.reload_sessions()
                if was_active:
                    if self.sessions_by_id:
                        await self.apply_session(next(iter(self.sessions_by_id.values())))
                    else:
                        self.clear_active_session()
                    self.refresh_input_mode_indicator()
                    self.refresh_chat_header()
                    self.refresh_messages(scroll_to_bottom=True)
                self.refresh_history()

            with ui.row().classes("justify-end gap-2 mt-4"):
                ui.button("キャンセル", on_click=dlg.close).props("flat")
                ui.button("削除", icon="delete", on_click=_delete).props("color=negative unelevated")
        dlg.open()

    def open_system_prompt_dialog(self) -> None:
        if self.settings is None:
            ui.notify("先にチャットを開始してください", type="warning")
            return
        active = self.active_members()
        if not active:
            ui.notify("参加キャラがいません", type="warning")
            return
        prompt = build_group_system_prompt(self.group, self.settings, active, active[0])
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-3xl"):
            ui.label("システムプロンプト").classes("text-base font-semibold")
            ui.code(prompt, language="markdown").classes("w-full text-xs")
            with ui.row().classes("justify-end mt-3"):
                ui.button("閉じる", on_click=dlg.close).props("flat")
        dlg.open()


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


def _configured_group_chat_llm(ctx, profile_id: str):
    try:
        return build_configured_llm(ctx.api_config, profile_id, get_vault_password())
    except LLMRuntimeError as err:
        if err.kind == PROFILE_NOT_FOUND:
            ui.notify("LLMプロファイルを選択してください", type="warning")
        elif err.kind == MODEL_ID_MISSING:
            ui.notify("LLMプロファイルのモデルIDが未設定です", type="negative")
        elif err.kind == ENDPOINT_NOT_FOUND:
            ui.notify("LLMプロファイルのエンドポイントが見つかりません", type="negative")
        elif err.kind == API_KEY_LOCKED:
            ui.notify("APIキーがロックされています。設定画面で解除してください。", type="warning")
        return None
