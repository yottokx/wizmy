"""NiceGUI components for the character chat page."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from nicegui import ui

from ...core.chat.schemas import ChatMode, UserPersona
from ...core.chat.templates import TemplateError
from ...core.character.schemas import CharacterImageAsset, CharacterSheet, FaceRect
from .commands import (
    command_suggestions,
    input_mode_icon,
    input_mode_label,
    parse_command_input,
)
from .media import cropped_background_style
from .models import (
    ChatDebugInfo,
    ChatMessagePreview,
    ChatRefs,
    ChatSessionSettings,
    ChatState,
    ChatThreadPreview,
)


USER_PERSONA_SOURCE_PERSONA = "persona"
USER_PERSONA_SOURCE_CHARACTER = "character"
_PERSONA_SELECT_PREFIX = "persona:"
_CHARACTER_SELECT_PREFIX = "character:"

VOICE_INPUT_CLICK_JS = r"""
event => {
  event.preventDefault();
  event.stopPropagation();
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const input = document.querySelector('.cs-chat-composer-input textarea');
  const button = event.currentTarget;
  const notify = (message, type = 'warning') => {
    if (window.Quasar && window.Quasar.Notify) {
      window.Quasar.Notify.create({ message, type });
    }
  };
  const focusInput = () => {
    input && input.focus({ preventScroll: true });
  };
  const speechErrorMessage = error => {
    switch (error) {
      case 'no-speech':
        return '音声を検出できませんでした';
      case 'audio-capture':
        return 'マイクを取得できません。端末またはブラウザのマイク権限を確認してください';
      case 'not-allowed':
        return 'マイクが許可されていません。ブラウザのサイト設定と端末のマイク権限を確認してください';
      case 'service-not-allowed':
        return '音声認識サービスが許可されていません。HTTPS接続とマイク権限を確認してください';
      case 'network':
        return '音声認識サービスへ接続できません。ネットワーク接続を確認してください';
      case 'language-not-supported':
        return 'この環境では日本語の音声認識に対応していません';
      case 'aborted':
        return '音声入力を中止しました';
      default:
        return `音声入力に失敗しました: ${error || 'unknown'}`;
    }
  };
  if (!input) return;
  if ((input.value || '').length) return;
  if (!SpeechRecognition) {
    notify('このブラウザは音声入力に対応していません');
    focusInput();
    return;
  }
  const localHosts = new Set(['localhost', '127.0.0.1', '::1']);
  const isSecureOrigin = window.isSecureContext
    || window.location.protocol === 'https:'
    || localHosts.has(window.location.hostname);
  if (!isSecureOrigin) {
    notify('音声入力にはHTTPSまたはlocalhostが必要です。安全なURLで開いてください', 'negative');
    focusInput();
    return;
  }
  if (window.__csSpeechRecognition) {
    window.__csSpeechRecognition.onerror = null;
    window.__csSpeechRecognition.onend = null;
    window.__csSpeechRecognition.abort();
    window.__csSpeechRecognition = null;
  }
  const recognition = new SpeechRecognition();
  window.__csSpeechRecognition = recognition;
  recognition.lang = 'ja-JP';
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;
  button && button.classList.add('cs-chat-voice-input-recording');
  recognition.onresult = resultEvent => {
    const transcript = Array.from(resultEvent.results || [])
      .map(result => result && result[0] ? result[0].transcript : '')
      .join('')
      .trim();
    if (!transcript) return;
    input.value = transcript;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.focus();
  };
  recognition.onerror = errorEvent => {
    const error = errorEvent && errorEvent.error ? errorEvent.error : 'unknown';
    const messageType = error === 'no-speech' || error === 'aborted' ? 'warning' : 'negative';
    console.warn('Speech recognition error:', error, errorEvent && errorEvent.message);
    notify(speechErrorMessage(error), messageType);
    focusInput();
  };
  recognition.onend = () => {
    button && button.classList.remove('cs-chat-voice-input-recording');
    if (window.__csSpeechRecognition === recognition) {
      window.__csSpeechRecognition = null;
    }
  };
  try {
    recognition.start();
  } catch (error) {
    button && button.classList.remove('cs-chat-voice-input-recording');
    if (window.__csSpeechRecognition === recognition) {
      window.__csSpeechRecognition = null;
    }
    console.warn('Speech recognition start failed:', error);
    notify('音声入力を開始できませんでした。ブラウザと端末のマイク権限を確認してください', 'negative');
    focusInput();
  }
}
"""


def render_profile(
    sheet: CharacterSheet,
    image: CharacterImageAsset | None,
    image_path: Path | None,
    *,
    compact: bool = False,
) -> None:
    with ui.element("div").classes("cs-chat-profile-content"):
        render_bust_image(image, image_path)
        ui.label(sheet.name).classes("cs-chat-name")

        if compact:
            with ui.expansion("プロフィール", icon="person").props("dense").classes("w-full"):
                render_profile_fields(sheet)
        else:
            ui.label("プロフィール").classes("cs-chat-profile-title")
            render_profile_fields(sheet)


def render_profile_fields(sheet: CharacterSheet) -> None:
    items = profile_items(sheet)
    if not items:
        ui.label("プロフィールは未入力です").classes("text-sm text-grey-6")
        return

    with ui.element("div").classes("cs-chat-profile-list"):
        for label, value in items:
            with ui.element("div").classes("cs-chat-profile-row"):
                ui.label(label).classes("cs-chat-profile-label")
                ui.label(value).classes("cs-chat-profile-value")


def render_history(
    threads: list[ChatThreadPreview],
    *,
    select_thread=None,
    rename_thread=None,
    delete_thread=None,
) -> None:
    def _select_handler(thread_id: str):
        async def _handler(_) -> None:
            if select_thread is not None:
                await select_thread(thread_id)

        return _handler

    with ui.element("div").classes("cs-chat-history-head"):
        ui.icon("history").style("color: var(--cs-accent);")
        ui.label("チャット履歴").classes("cs-chat-history-title")
    with ui.element("div").classes("cs-chat-scroll"):
        with ui.element("div").classes("cs-chat-thread-list"):
            if not threads:
                ui.label("保存済みチャットはまだありません").classes("cs-chat-history-empty")
                return
            for thread in threads:
                classes = "cs-chat-thread"
                if thread.active:
                    classes += " cs-chat-thread-active"
                with ui.element("div").classes(classes):
                    with ui.element("button").props("type=button").classes(
                        "cs-chat-thread-open"
                    ).on("click", _select_handler(thread.id)):
                        with ui.element("div").classes("cs-chat-thread-title-row"):
                            ui.label(thread.title).classes("cs-chat-thread-title")
                            ui.label(thread.time_label).classes("cs-chat-thread-time")
                        ui.label(thread.preview).classes("cs-chat-thread-preview")
                    with ui.element("div").classes("cs-chat-thread-actions"):
                        if rename_thread is not None:
                            ui.button(
                                icon="edit",
                                on_click=lambda thread_id=thread.id: rename_thread(thread_id),
                            ).props("flat round dense size=sm").classes(
                                "cs-chat-thread-action"
                            ).tooltip("タイトル変更")
                        if delete_thread is not None:
                            ui.button(
                                icon="delete",
                                on_click=lambda thread_id=thread.id: delete_thread(thread_id),
                            ).props("flat round dense size=sm color=negative").classes(
                                "cs-chat-thread-action"
                            ).tooltip("チャット削除")


def render_chat(
    sheet: CharacterSheet,
    image: CharacterImageAsset | None,
    image_path: Path | None,
    user_image: CharacterImageAsset | None,
    user_image_path: Path | None,
    state: ChatState,
    refs: ChatRefs,
    *,
    title: str,
    subtitle: str,
    open_new_chat_dialog,
    open_system_prompt,
    open_rename_current_chat,
    confirm_delete_current_chat,
    send_message,
    rewind_message,
    rewrite_message,
    regenerate_message,
    play_tts_message,
    open_debug,
    set_input_mode,
    set_mobile_sidebar,
    tts_playable_speakers: set[str] | None = None,
) -> None:
    with ui.element("div").classes("cs-chat-main-head"):
        ui.button(icon="menu", on_click=lambda: set_mobile_sidebar(True)).props(
            "flat round dense"
        ).classes("cs-chat-mobile-toggle")
        with ui.column().classes("gap-0 cs-chat-main-title"):
            refs.title = ui.label(title).classes("text-base font-bold")
            refs.subtitle = ui.label(subtitle).classes("text-xs text-grey-6")
        with ui.row().classes("items-center gap-1"):
            ui.button(icon="article", on_click=open_system_prompt).props("flat round dense").tooltip(
                "システムプロンプト"
            )
            ui.button(icon="edit", on_click=open_rename_current_chat).props("flat round dense").tooltip(
                "タイトル変更"
            )
            ui.button(icon="delete", on_click=confirm_delete_current_chat).props(
                "flat round dense color=negative"
            ).tooltip("チャット削除")
            ui.button(icon="add", on_click=open_new_chat_dialog).props("flat round dense").tooltip(
                "新しいチャット"
            )

    with ui.element("div").classes("cs-chat-messages") as messages_container:
        refs.messages = messages_container
        for index, message in enumerate(state.messages):
            render_message(
                message,
                image,
                image_path,
                user_image,
                user_image_path,
                index=index,
                rewind_message=rewind_message,
                rewrite_message=rewrite_message,
                regenerate_message=regenerate_message,
                play_tts_message=play_tts_message,
                tts_playable_speakers=tts_playable_speakers or set(),
                tts_generating=state.tts_generating_index == index,
                open_debug=open_debug,
            )

    with ui.element("div").classes("cs-chat-composer-shell"):
        command_palette = ui.element("div").classes(
            "cs-chat-command-palette cs-chat-command-palette-hidden"
        )
        swipe_action_menu = ui.element("div").classes(
            "cs-chat-swipe-action-menu cs-chat-swipe-action-menu-hidden"
        )

        async def _apply_command_suggestion(command: str) -> None:
            input_box = refs.input
            if input_box is None:
                return
            parsed = parse_command_input(str(input_box.value or ""))
            left_text = parsed[0] if parsed is not None else ""
            command_palette.clear()
            command_palette.classes("cs-chat-command-palette-hidden")
            swipe_action_menu.classes("cs-chat-swipe-action-menu-hidden")
            await send_message(False, f"{left_text}/{command}")

        def _command_click_handler(command: str):
            async def _handler(_) -> None:
                await _apply_command_suggestion(command)

            return _handler

        async def _apply_swipe_action(command: str) -> None:
            input_box = refs.input
            if input_box is None:
                return
            current_text = str(input_box.value or "")
            parsed = parse_command_input(current_text)
            left_text = parsed[0] if parsed is not None else current_text
            command_palette.clear()
            command_palette.classes("cs-chat-command-palette-hidden")
            swipe_action_menu.classes("cs-chat-swipe-action-menu-hidden")
            await send_message(False, f"{left_text.rstrip()}/{command}")

        def _swipe_action_click_handler(command: str):
            async def _handler(_) -> None:
                await _apply_swipe_action(command)

            return _handler

        def _refresh_command_palette(value: str) -> None:
            command_palette.clear()
            parsed = parse_command_input(value)
            if parsed is None:
                command_palette.classes("cs-chat-command-palette-hidden")
                return
            _, query = parsed
            suggestions = command_suggestions(query)
            command_palette.classes(remove="cs-chat-command-palette-hidden")
            if not suggestions:
                with command_palette:
                    ui.label("該当するコマンドがありません").classes("text-xs text-grey-6")
                return
            with command_palette:
                for index, command in enumerate(suggestions):
                    classes = "cs-chat-command-option"
                    if index == 0:
                        classes += " cs-chat-command-option-active"
                    with ui.element("button").props(
                        f"type=button data-command={command.name} aria-selected={'true' if index == 0 else 'false'}"
                    ).classes(classes).on(
                        "click", _command_click_handler(command.name)
                    ):
                        ui.label(f"/{command.name}").classes("cs-chat-command-name")
                        ui.label(command.description).classes("cs-chat-command-desc")

        with swipe_action_menu:
            for command, label, icon in (
                ("choices", "選択肢を生成", "format_list_bulleted"),
                ("fill", "続きを補完", "auto_fix_high"),
                ("tailor", "書き直す", "edit_note"),
            ):
                with ui.element("button").props(
                    f"type=button data-swipe-command={command}"
                ).classes("cs-chat-swipe-action-option").on(
                    "click", _swipe_action_click_handler(command)
                ):
                    ui.icon(icon).classes("cs-chat-swipe-action-icon")
                    ui.label(f"/{command}").classes("cs-chat-swipe-action-command")
                    ui.label(label).classes("cs-chat-swipe-action-label")

        with ui.element("div").classes("cs-chat-composer"):
            render_input_mode_selector(
                state.input_mode,
                refs,
                image,
                image_path,
                user_image,
                user_image_path,
                set_input_mode=set_input_mode,
            )
            with ui.element("div").classes("cs-chat-composer-input-wrap"):
                refs.input = ui.textarea(
                    placeholder="メッセージを入力",
                ).props("outlined dense rows=1 autogrow").classes("cs-chat-composer-input")
                voice_input_btn = ui.button(icon="mic").props(
                    "round flat dense aria-label=音声入力"
                ).classes("cs-chat-voice-input").tooltip("音声入力")
                voice_input_btn.on(
                    "click",
                    js_handler=VOICE_INPUT_CLICK_JS,
                )

            async def _send_from_enter(e) -> None:
                if isinstance(e.args, list):
                    value = str(e.args[0] or "") if e.args else ""
                else:
                    value = str(e.args or "")
                await send_message(False, value)

            refs.input.on_value_change(
                lambda e: _refresh_command_palette(str(e.value or ""))
            )
            refs.input.on(
                "input",
                js_handler="""
event => {
  const target = event.target;
  const value = target && typeof target.value === 'string' ? target.value : '';
  const wrapper = target && typeof target.closest === 'function'
    ? target.closest('.cs-chat-composer-input-wrap')
    : null;
  if (!wrapper) return;
  wrapper.classList.toggle('cs-chat-composer-input-has-text', value.length > 0);
}
""",
            )
            refs.input.on(
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
            refs.input.on(
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
  const palette = document.querySelector('.cs-chat-command-palette');
  if (!menu) return;
  event.preventDefault();
  if (palette) palette.classList.add('cs-chat-command-palette-hidden');
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
            refs.input.on(
                "keydown",
                _send_from_enter,
                js_handler="""
event => {
  const target = event.target;
  const value = target && typeof target.value === 'string' ? target.value : '';
  const commandMatch = value.match(/^([\\s\\S]*)\\/([A-Za-z]*)$/);
  const palette = document.querySelector('.cs-chat-command-palette');
  const options = palette ? Array.from(palette.querySelectorAll('.cs-chat-command-option')) : [];
  const activeIndex = () => Math.max(0, options.findIndex(option => option.classList.contains('cs-chat-command-option-active')));
  const setActive = index => {
    options.forEach((option, optionIndex) => {
      const active = optionIndex === index;
      option.classList.toggle('cs-chat-command-option-active', active);
      option.setAttribute('aria-selected', active ? 'true' : 'false');
      if (active && typeof option.scrollIntoView === 'function') {
        option.scrollIntoView({ block: 'nearest' });
      }
    });
  };
  if (commandMatch && options.length && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
    event.preventDefault();
    const delta = event.key === 'ArrowDown' ? 1 : -1;
    const next = (activeIndex() + delta + options.length) % options.length;
    setActive(next);
    return;
  }
  if (event.key !== 'Enter' || event.isComposing) return;
  if (event.altKey) {
    event.preventDefault();
    if (target && typeof target.value === 'string') {
      const start = target.selectionStart ?? target.value.length;
      const end = target.selectionEnd ?? target.value.length;
      target.value = target.value.slice(0, start) + '\\n' + target.value.slice(end);
      target.selectionStart = target.selectionEnd = start + 1;
      target.dispatchEvent(new Event('input', { bubbles: true }));
    }
    return;
  }
  if (event.shiftKey) return;
  event.preventDefault();
  if (commandMatch && options.length) {
    const active = options[activeIndex()] || options[0];
    const command = active && active.dataset ? active.dataset.command : '';
    if (command) {
      target.value = commandMatch[1] + '/' + command;
      target.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }
  if (palette) {
    palette.classList.add('cs-chat-command-palette-hidden');
  }
  emit(target && typeof target.value === 'string' ? target.value : '');
}
""",
            )

            async def _send_from_button(_) -> None:
                await send_message(True)

            async def _guide_from_long_tap(e) -> None:
                if isinstance(e.args, list):
                    value = str(e.args[0] or "") if e.args else ""
                else:
                    value = str(e.args or "")
                parsed = parse_command_input(value)
                left_text = parsed[0] if parsed is not None else value
                await send_message(False, f"{left_text.rstrip()}/guide")

            refs.send_btn = ui.button(icon="send").props("round color=primary unelevated")
            refs.send_btn.on(
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
            refs.send_btn.on(
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
            refs.send_btn.on(
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
            refs.send_btn.on(
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
            refs.send_btn.on(
                "touchcancel",
                js_handler="""
event => {
  clearTimeout(window.__csSendLongTapTimer);
  window.__csSendLongTapStart = null;
  window.__csSendLongTapTriggered = false;
}
""",
            )


def open_new_chat_dialog_for_sheet(
    *,
    sheet: CharacterSheet,
    profile_options: dict[str, str],
    default_profile_id: str,
    mode_options: dict[str, str],
    default_mode_id: str,
    persona_options: dict[str, str],
    default_persona_id: str,
    get_mode: Callable[[str], ChatMode | None],
    get_persona: Callable[[str], UserPersona | None],
    pick_character_persona: Callable[[Callable[[CharacterSheet], Awaitable[None]]], Awaitable[None]] | None = None,
    render_mode: Callable[[ChatMode, UserPersona], tuple[str, str]],
    validate_profile: Callable[[str], bool],
    enhance_situation: Callable[[str, ChatMode, UserPersona, str, str], Awaitable[str | None]],
    start_chat: Callable[[ChatSessionSettings, str], Awaitable[None]],
) -> None:
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-2xl"):
        ui.label("新しいチャット").classes("text-base font-semibold")

        if not profile_options:
            ui.label("LLMプロファイルが登録されていません。設定画面で追加してください。").classes(
                "text-sm text-negative mt-3"
            )
        if not mode_options:
            ui.label("チャットモードが登録されていません。設定画面で追加してください。").classes(
                "text-sm text-negative mt-3"
            )
        if not persona_options:
            ui.label("ユーザーペルソナが登録されていません。キャラクターシートもユーザー役として選択できます。").classes(
                "text-sm text-negative mt-3"
            )

        profile_select = ui.select(
            options=profile_options,
            value=default_profile_id,
            label="LLMプロファイル",
        ).props("outlined").classes("w-full mt-3")

        title_input = ui.input(
            label="タイトル（任意）",
            placeholder="未入力なら「新しいチャット」",
        ).props("outlined clearable").classes("w-full")

        mode_select = ui.select(
            options=mode_options,
            value=default_mode_id,
            label="チャットモード",
        ).props("outlined").classes("w-full")

        persona_select_options = {
            f"{_PERSONA_SELECT_PREFIX}{persona_id}": label
            for persona_id, label in persona_options.items()
        }
        selected_character_persona: dict[str, CharacterSheet | None] = {"value": None}
        default_persona_value = (
            f"{_PERSONA_SELECT_PREFIX}{default_persona_id}"
            if default_persona_id
            else None
        )

        async def _pick_character_persona() -> None:
            if pick_character_persona is None:
                return

            async def _on_select(character: CharacterSheet) -> None:
                selected_character_persona["value"] = character
                value = f"{_CHARACTER_SELECT_PREFIX}{character.id}"
                persona_select.set_options(
                    {
                        **persona_select_options,
                        value: f"{character.name}（キャラクターシート）",
                    },
                    value=value,
                )
                _sync_situation_default(force=True)
                _refresh_preview()

            await pick_character_persona(_on_select)

        with ui.row().classes("w-full items-end gap-2"):
            persona_select = ui.select(
                options=persona_select_options,
                value=default_persona_value,
                label="ユーザーペルソナ",
            ).props("outlined").classes("flex-1 min-w-0")
            ui.button(
                icon="person_search",
                on_click=_pick_character_persona,
            ).props("outline color=secondary").classes("mb-1").tooltip(
                "キャラクターシートをユーザー役にする"
            )

        def _selected_mode() -> ChatMode | None:
            mode_id = mode_select.value or ""
            return get_mode(mode_id) if mode_id else None

        def _selected_persona_source_and_id() -> tuple[str, str]:
            selected = str(persona_select.value or "")
            if selected.startswith(_CHARACTER_SELECT_PREFIX):
                return USER_PERSONA_SOURCE_CHARACTER, selected[len(_CHARACTER_SELECT_PREFIX):]
            if selected.startswith(_PERSONA_SELECT_PREFIX):
                return USER_PERSONA_SOURCE_PERSONA, selected[len(_PERSONA_SELECT_PREFIX):]
            if selected in persona_options:
                return USER_PERSONA_SOURCE_PERSONA, selected
            return "", ""

        def _selected_persona() -> UserPersona | None:
            source, persona_id = _selected_persona_source_and_id()
            if not persona_id:
                return None
            if source == USER_PERSONA_SOURCE_CHARACTER:
                character = selected_character_persona["value"]
                if character is None or character.id != persona_id:
                    return None
                return user_persona_from_character_sheet(character)
            return get_persona(persona_id)

        def _render_selected_mode() -> tuple[str, str]:
            mode = _selected_mode()
            persona = _selected_persona()
            if mode is None or persona is None:
                return "", ""
            return render_mode(mode, persona)

        def _initial_situation() -> str:
            try:
                return _render_selected_mode()[1]
            except TemplateError:
                return ""

        situation_default = {"value": _initial_situation()}
        with ui.element("div").classes("cs-chat-situation-field"):
            situation_input = ui.textarea(
                label="シチュエーション",
                value=situation_default["value"],
                placeholder="チャットで話したい状況や、特筆したいことを記入",
            ).props("outlined rows=3").classes("w-full")
            enhance_button = ui.button(
                icon="auto_awesome",
            ).props("flat round dense size=sm").classes("cs-chat-situation-enhance").tooltip(
                "シチュエーションを補完"
            )

        preview_container = ui.column().classes("w-full gap-1")

        def _sync_situation_default(*, force: bool = False) -> None:
            try:
                next_default = _render_selected_mode()[1]
            except TemplateError:
                return
            current = (situation_input.value or "").strip()
            previous = situation_default["value"].strip()
            if force or not current or current == previous:
                situation_input.set_value(next_default)
            situation_default["value"] = next_default

        def _refresh_preview() -> None:
            preview_container.clear()
            mode = _selected_mode()
            persona = _selected_persona()
            with preview_container:
                if mode is None or persona is None:
                    return
                try:
                    premise, _ = render_mode(mode, persona)
                except TemplateError as err:
                    ui.label(f"テンプレートエラー: {err}").classes("text-sm text-negative")
                    return
                with ui.expansion("前提 / ユーザー設定", icon="tune").props("dense").classes("w-full"):
                    ui.label("前提").classes("text-xs font-semibold text-grey-6")
                    ui.label(premise or "（未設定）").classes("text-sm").style(
                        "white-space: pre-wrap; overflow-wrap: anywhere;"
                    )
                    ui.label("ユーザー設定").classes("text-xs font-semibold text-grey-6 mt-2")
                    ui.label(persona.description or "（未設定）").classes("text-sm").style(
                        "white-space: pre-wrap; overflow-wrap: anywhere;"
                    )

        def _on_mode_change() -> None:
            _sync_situation_default(force=True)
            _refresh_preview()

        def _on_persona_change() -> None:
            _sync_situation_default()
            _refresh_preview()

        mode_select.on_value_change(lambda _: _on_mode_change())
        persona_select.on_value_change(lambda _: _on_persona_change())
        _refresh_preview()

        async def _enhance_situation() -> None:
            profile_id = profile_select.value or ""
            if not profile_id:
                ui.notify("LLMプロファイルを選択してください", type="warning")
                return
            mode = _selected_mode()
            persona = _selected_persona()
            if mode is None:
                ui.notify("チャットモードを選択してください", type="warning")
                return
            if persona is None:
                ui.notify("ユーザー役を選択してください", type="warning")
                return
            if not persona.description.strip():
                ui.notify("ユーザー役の設定を入力してください", type="warning")
                return
            try:
                premise, rendered_situation = render_mode(mode, persona)
            except TemplateError as err:
                ui.notify(f"チャットモードのテンプレートを確認してください: {err}", type="negative", timeout=8000)
                return

            current_situation = (situation_input.value or "").strip() or rendered_situation
            enhance_button.disable()
            situation_input.disable()
            try:
                enhanced = await enhance_situation(profile_id, mode, persona, premise, current_situation)
                if enhanced is not None:
                    situation_input.set_value(enhanced)
            finally:
                situation_input.enable()
                enhance_button.enable()

        enhance_button.on("click", _enhance_situation)

        async def _start_chat() -> None:
            profile_id = profile_select.value or ""
            if not profile_id:
                ui.notify("LLMプロファイルを選択してください", type="warning")
                return
            if not validate_profile(profile_id):
                return

            mode = _selected_mode()
            if mode is None:
                ui.notify("チャットモードを選択してください", type="warning")
                return
            persona = _selected_persona()
            if persona is None:
                ui.notify("ユーザー役を選択してください", type="warning")
                return
            if not persona.description.strip():
                ui.notify("ユーザー役の設定を入力してください", type="warning")
                return
            try:
                premise, rendered_situation = render_mode(mode, persona)
            except TemplateError as err:
                ui.notify(f"チャットモードのテンプレートを確認してください: {err}", type="negative", timeout=8000)
                return
            situation = (situation_input.value or rendered_situation).strip()
            if not situation:
                ui.notify("シチュエーションを入力してください", type="warning")
                return

            settings = ChatSessionSettings(
                profile_id=profile_id,
                chat_mode_id=mode.id,
                chat_mode_name=mode.name,
                chat_premise=premise,
                situation=situation,
                user_persona_id=persona.id,
                user_persona_name=persona.name,
                user_persona_description=persona.description.strip(),
                user_persona_source=_selected_persona_source_and_id()[0] or USER_PERSONA_SOURCE_PERSONA,
            )
            dlg.close()
            await start_chat(settings, (title_input.value or "").strip())

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("開始", icon="chat", on_click=_start_chat).props("color=primary unelevated")

    dlg.open()


def open_llm_debug_dialog(debug: ChatDebugInfo) -> None:
    token_lines = [
        f"入力: {token_label(debug.input_tokens)}",
        f"出力: {token_label(debug.output_tokens)}",
        f"合計: {token_label(debug.total_tokens)}",
    ]
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-4xl"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("LLMデバッグ").classes("text-lg font-semibold")
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")
        ui.label(" / ".join(token_lines)).classes("text-sm text-grey-6")

        ui.label("入力").classes("text-sm font-semibold mt-2")
        with ui.scroll_area().style("height: 32vh; width: 100%;"):
            ui.code(debug.llm_input, language="text").classes("w-full text-xs")

        if debug.reasoning_output:
            ui.label("推論 / Thinking").classes("text-sm font-semibold mt-2")
            with ui.scroll_area().style("height: 22vh; width: 100%;"):
                ui.code(debug.reasoning_output, language="text").classes("w-full text-xs")

        ui.label("出力").classes("text-sm font-semibold mt-2")
        with ui.scroll_area().style("height: 22vh; width: 100%;"):
            ui.code(debug.raw_output, language="text").classes("w-full text-xs")
    dlg.open()


def open_system_prompt_dialog(prompt: str) -> None:
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-4xl"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("システムプロンプト").classes("text-lg font-semibold")
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")
        with ui.scroll_area().style("height: 62vh; width: 100%;"):
            ui.code(prompt, language="text").classes("w-full text-xs")
    dlg.open()


def token_label(value: int | None) -> str:
    return str(value) if value is not None else "不明"


def render_input_mode_indicator(
    mode: str,
    image: CharacterImageAsset | None,
    image_path: Path | None,
    user_image: CharacterImageAsset | None = None,
    user_image_path: Path | None = None,
) -> None:
    label = input_mode_label(mode)
    face_image = image if mode == "character" else user_image if mode == "user" else None
    face_image_path = image_path if mode == "character" else user_image_path if mode == "user" else None
    if face_image is not None and face_image_path is not None and mode in {"character", "user"}:
        style = cropped_background_style(
            face_image,
            face_image_path,
            face_image.face_rect,
            1.0,
        )
        with ui.element("div") as face:
            face.classes("cs-chat-mode-face").style(style).tooltip(label)
            if not style:
                ui.icon(input_mode_icon(mode))
        return
    ui.icon(input_mode_icon(mode)).tooltip(label)


def render_input_mode_selector(
    mode: str,
    refs: ChatRefs,
    image: CharacterImageAsset | None,
    image_path: Path | None,
    user_image: CharacterImageAsset | None,
    user_image_path: Path | None,
    *,
    set_input_mode: Callable[[str], None],
) -> None:
    with ui.button().props("flat dense unelevated aria-label=入力ロールを変更").classes(
        "cs-chat-mode-icon"
    ):
        with ui.element("div").classes("cs-chat-mode-icon-display") as mode_icon:
            refs.input_mode_icon = mode_icon
            render_input_mode_indicator(mode, image, image_path, user_image, user_image_path)
        with ui.menu().classes("cs-chat-mode-menu"):
            for next_mode in ("user", "character", "narration", "memo"):
                ui.menu_item(
                    role_menu_label(next_mode),
                    on_click=lambda selected=next_mode: set_input_mode(selected),
                )


def user_persona_from_character_sheet(sheet: CharacterSheet) -> UserPersona:
    return UserPersona(
        id=sheet.id,
        name=sheet.name or "ユーザー",
        description=character_persona_description(sheet),
        media=sheet.media,
    )


def character_persona_description(sheet: CharacterSheet) -> str:
    if sheet.raw_markdown.strip():
        return sheet.raw_markdown.strip()
    fields = [
        ("名前", sheet.name),
        ("年齢", sheet.age),
        ("性別", sheet.gender),
        ("職業・役割", sheet.occupation),
        ("出身・所属", sheet.origin),
        ("世界観", sheet.world),
        ("外見", sheet.appearance),
        ("性格", sheet.personality),
        ("動機", sheet.motivation),
        ("弱点", sheet.weakness),
        ("背景", sheet.background),
        ("スキル", sheet.skills),
        ("個性・クセ", sheet.quirks),
        ("物語のフック", sheet.story_hooks),
        ("自己紹介", sheet.self_intro),
        ("声のイメージ", sheet.voice_image),
    ]
    return "\n".join(f"{label}: {value}" for label, value in fields if value)


def role_menu_label(mode: str) -> str:
    labels = {
        "user": "ユーザー",
        "character": "キャラクター",
        "narration": "ナラティブ",
        "memo": "コメント",
    }
    return labels.get(mode, input_mode_label(mode))


def render_message(
    message: ChatMessagePreview,
    image: CharacterImageAsset | None,
    image_path: Path | None,
    user_image: CharacterImageAsset | None = None,
    user_image_path: Path | None = None,
    *,
    index: int = -1,
    rewind_message=None,
    rewrite_message=None,
    regenerate_message=None,
    play_tts_message=None,
    tts_playable_speakers: set[str] | None = None,
    tts_generating: bool = False,
    open_debug=None,
) -> None:
    is_character = message.speaker == "character"
    is_user = message.speaker == "user"
    is_narration = message.speaker == "narration"
    is_memo = message.speaker == "memo"
    tts_playable_speakers = tts_playable_speakers or set()
    if is_character:
        row_class = "cs-chat-message-row-character"
    elif is_narration:
        row_class = "cs-chat-message-row-narration"
    elif is_memo:
        row_class = "cs-chat-message-row-memo"
    else:
        row_class = "cs-chat-message-row-user"
    with ui.element("div").classes(f"cs-chat-message-row {row_class}"):
        if is_character:
            render_face_avatar(image, image_path)
        with ui.element("div").classes("cs-chat-bubble"):
            if is_memo:
                ui.label("コメント").classes("cs-chat-message-kind")
            ui.label(message.text).classes("cs-chat-message-text")
            with ui.element("div").classes("cs-chat-message-meta"):
                with ui.element("div").classes("cs-chat-message-actions"):
                    if message.speaker in tts_playable_speakers and play_tts_message is not None and message.text.strip():
                        if is_character:
                            play_tip = "この台詞を読み上げ"
                        elif is_narration:
                            play_tip = "この地の文を読み上げ"
                        else:
                            play_tip = "この発言を読み上げ"
                        play_btn = ui.button(
                            icon="play_arrow",
                            on_click=lambda i=index: play_tts_message(i),
                        ).props("flat round dense size=sm").classes("cs-chat-message-action").tooltip(
                            play_tip
                        )
                        if tts_generating:
                            play_btn.props("loading")
                            play_btn.disable()
                    if is_character and regenerate_message is not None:
                        ui.button(
                            icon="refresh",
                            on_click=lambda i=index: regenerate_message(i),
                        ).props("flat round dense size=sm").classes("cs-chat-message-action").tooltip(
                            "この台詞を再生成"
                        )
                    if is_character and message.debug is not None and open_debug is not None:
                        ui.button(
                            icon="bug_report",
                            on_click=lambda d=message.debug: open_debug(d),
                        ).props("flat round dense size=sm").classes("cs-chat-message-action").tooltip(
                            "LLM入出力"
                        )
                    if rewrite_message is not None:
                        ui.button(
                            icon="edit",
                            on_click=lambda i=index: rewrite_message(i),
                        ).props("flat round dense size=sm").classes("cs-chat-message-action").tooltip(
                            "この内容を書き換え"
                        )
                    if message.speaker in {"character", "user", "narration", "memo"} and rewind_message is not None:
                        rewind_tip = {
                            "character": "この台詞まで戻る",
                            "narration": "この地の文まで戻る",
                            "memo": "このコメントまで戻る",
                        }.get(message.speaker, "この発言まで戻る")
                        ui.button(
                            icon="undo",
                            on_click=lambda i=index: rewind_message(i),
                        ).props("flat round dense size=sm").classes("cs-chat-message-action").tooltip(rewind_tip)
                ui.label(message.time_label).classes("cs-chat-message-time")
        if is_user and user_image is not None and user_image_path is not None:
            render_face_avatar(user_image, user_image_path)


def render_bust_image(image: CharacterImageAsset | None, image_path: Path | None) -> None:
    style = cropped_background_style(image, image_path, image.bust_rect if image else FaceRect(), 3 / 4)
    with ui.element("div").classes("cs-chat-bust").style(style):
        if not style:
            with ui.element("div").classes("cs-chat-bust-placeholder"):
                ui.icon("person").classes("text-5xl")


def render_face_avatar(image: CharacterImageAsset | None, image_path: Path | None) -> None:
    style = cropped_background_style(image, image_path, image.face_rect if image else FaceRect(), 1.0)
    with ui.element("div").classes("cs-chat-face").style(style):
        if not style:
            with ui.element("div").classes("cs-chat-face-placeholder"):
                ui.icon("person").classes("text-lg")


def profile_items(sheet: CharacterSheet) -> list[tuple[str, str]]:
    candidates = [
        ("年齢", sheet.age),
        ("性別", sheet.gender),
        ("職業・役割", sheet.occupation),
        ("出身・所属", sheet.origin),
        ("世界観", sheet.world),
        ("外見", sheet.appearance),
        ("性格", sheet.personality),
        ("動機", sheet.motivation),
        ("弱点", sheet.weakness),
    ]
    return [(label, value) for label, value in candidates if value]
