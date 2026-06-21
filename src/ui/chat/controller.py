"""Controller for character chat page interactions."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from nicegui import app, ui

from ...core.chat.schemas import ChatMode, UserPersona
from ...core.chat.sessions import ChatSessionRecord, DEFAULT_CHAT_TITLE
from ...core.chat.templates import TemplateError, render_chat_mode
from ...core.character.schemas import (
    CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3,
    CHARACTER_TTS_API_GEN_SERVER,
    CHARACTER_TTS_API_TTS,
    CharacterSheet,
)
from ...core.tts.schemas import TTS_PROVIDER_IRODORI_SERVER
from ...core.llm.factory import create_llm
from ...services.tts import TTSServiceError
from ..components.character_picker import open_character_picker
from ..state import get_vault_password
from . import components
from .commands import (
    clean_short_llm_text,
    merge_completion,
    parse_command_input,
    parse_response_choices,
    resolve_chat_command,
)
from .models import (
    ChatDebugInfo,
    ChatMessagePreview,
    ChatRefs,
    ChatSessionSettings,
    ChatState,
    ChatThreadPreview,
    time_label,
)
from .prompts import (
    build_chat_title_messages,
    build_debug_info,
    build_llm_messages,
    build_narration_llm_messages,
    build_response_choice_messages,
    build_system_prompt,
    build_tailored_input_messages,
    build_user_completion_messages,
    character_summary,
    format_llm_input,
    is_first_character_turn,
    message_content_to_text,
    sanitize_chat_title,
    sanitize_character_reply,
    sanitize_narration,
)


class ChatPageController:
    def __init__(self, ctx, sheet: CharacterSheet, page_client) -> None:
        self.ctx = ctx
        self.sheet = sheet
        self.page_client = page_client
        self.image = sheet.media.primary_image()
        self.image_path = ctx.characters.media_path(self.image.path) if self.image else None
        self.voice = sheet.media.primary_voice()
        self.voice_path = ctx.characters.media_path(self.voice.path) if self.voice else None
        self.tts_configured = bool(
            self.voice
            and self.voice_path
            and ctx.tts.has_voice_playback_api(sheet.media.tts.api_type, sheet.media.tts.endpoint_id)
        )
        self.user_persona: UserPersona | None = None
        self.user_persona_character: CharacterSheet | None = None
        self.user_image = None
        self.user_image_path = None
        self.user_voice = None
        self.user_voice_path = None
        self.user_tts_configured = False
        self.active_session_id: str | None = None
        self.active_title_is_auto = False
        self.title_generation_attempted = False
        self.sessions_by_id: dict[str, ChatSessionRecord] = {}
        self.threads: list[ChatThreadPreview] = []
        self.state = ChatState()
        self.refs = ChatRefs()

    async def initialize(self) -> None:
        await self.reload_sessions()
        if self.sessions_by_id:
            latest = next(iter(self.sessions_by_id.values()))
            await self.apply_session(latest)

    async def reload_sessions(self) -> None:
        sessions = await self.ctx.chats.list_for_character(self.sheet.id)
        self.sessions_by_id = {session.id: session for session in sessions}
        self.threads = [self.thread_preview(session) for session in sessions]

    def render_shell(self) -> None:
        with ui.element("div").classes("cs-chat-shell"):
            ui.element("div").classes("cs-chat-mobile-backdrop").on(
                "click", lambda: self.set_mobile_sidebar(False)
            )

            with ui.element("aside").classes("cs-chat-mobile-sidebar cs-chat-panel"):
                with ui.row().classes("items-center justify-between px-3 py-2").style(
                    "border-bottom: 1px solid var(--cs-border);"
                ):
                    ui.label("チャット").classes("text-sm font-semibold")
                    ui.button(icon="close", on_click=lambda: self.set_mobile_sidebar(False)).props("flat round dense")
                with ui.element("div").classes("cs-chat-scroll"):
                    components.render_profile(self.sheet, self.image, self.image_path, compact=True)
                    self.render_history_section()

            with ui.element("aside").classes("cs-chat-profile-pane cs-chat-panel"):
                components.render_profile(self.sheet, self.image, self.image_path, compact=False)

            with ui.element("aside").classes("cs-chat-side-pane cs-chat-panel"):
                with ui.element("div").classes("cs-chat-scroll"):
                    components.render_profile(self.sheet, self.image, self.image_path, compact=True)
                    self.render_history_section()

            with ui.element("aside").classes("cs-chat-history-pane cs-chat-panel"):
                self.render_history_section()

            with ui.element("section").classes("cs-chat-main cs-chat-panel"):
                components.render_chat(
                    self.sheet,
                    self.image,
                    self.image_path,
                    self.user_image,
                    self.user_image_path,
                    self.state,
                    self.refs,
                    title=self.chat_title(),
                    subtitle=self.chat_subtitle(),
                    open_new_chat_dialog=self.open_new_chat_dialog,
                    open_system_prompt=self.open_system_prompt_dialog,
                    open_rename_current_chat=self.open_rename_current_chat_dialog,
                    confirm_delete_current_chat=self.confirm_delete_current_chat,
                    send_message=self.send_message,
                    rewind_message=self.confirm_rewind_to_message,
                    rewrite_message=self.open_rewrite_message_dialog,
                    regenerate_message=self.confirm_or_regenerate_character_message,
                    play_tts_message=self.play_tts_message if self.tts_playable_speakers() else None,
                    tts_playable_speakers=self.tts_playable_speakers(),
                    open_debug=components.open_llm_debug_dialog,
                    set_input_mode=self.set_input_mode,
                    set_mobile_sidebar=self.set_mobile_sidebar,
                )
        self.scroll_messages_to_bottom()

    def render_history_section(self) -> None:
        with ui.element("div").classes("cs-chat-history-section") as section:
            self.refs.history_sections.append(section)
            components.render_history(
                self.threads,
                select_thread=self.select_chat_session,
                rename_thread=self.open_rename_chat_dialog,
                delete_thread=self.confirm_delete_chat_session,
            )

    def refresh_history(self) -> None:
        for section in list(self.refs.history_sections):
            section.clear()
            with section:
                components.render_history(
                    self.threads,
                    select_thread=self.select_chat_session,
                    rename_thread=self.open_rename_chat_dialog,
                    delete_thread=self.confirm_delete_chat_session,
                )

    def thread_preview(self, session: ChatSessionRecord) -> ChatThreadPreview:
        return ChatThreadPreview(
            id=session.id,
            title=session.title or DEFAULT_CHAT_TITLE,
            preview=latest_message_preview(session.messages),
            time_label=session_time_label(session.updated_at),
            active=session.id == self.active_session_id,
        )

    async def apply_session(self, session: ChatSessionRecord) -> None:
        self.active_session_id = session.id
        self.active_title_is_auto = session.title_is_auto
        self.title_generation_attempted = False
        self.state.title = session.title or DEFAULT_CHAT_TITLE
        self.state.settings = chat_settings_from_dict(session.settings)
        self.state.messages = [chat_message_from_dict(message) for message in session.messages]
        await self.refresh_user_persona_media()
        self.state.input_mode = "user"
        self.state.sending = False
        self.state.tts_generating_index = None
        self.threads = [self.thread_preview(current) for current in self.sessions_by_id.values()]

    def clear_active_session(self) -> None:
        self.active_session_id = None
        self.active_title_is_auto = False
        self.title_generation_attempted = False
        self.state.title = "チャットを開始"
        self.state.settings = None
        self.state.messages = []
        self.clear_user_persona_media()
        self.state.input_mode = "user"
        self.state.sending = False
        self.state.tts_generating_index = None
        self.threads = [self.thread_preview(current) for current in self.sessions_by_id.values()]

    def clear_user_persona_media(self) -> None:
        self.user_persona = None
        self.user_persona_character = None
        self.user_image = None
        self.user_image_path = None
        self.user_voice = None
        self.user_voice_path = None
        self.user_tts_configured = False

    async def refresh_user_persona_media(self) -> None:
        settings = self.state.settings
        if settings is None or not settings.user_persona_id:
            self.clear_user_persona_media()
            return
        if settings.user_persona_source == components.USER_PERSONA_SOURCE_CHARACTER:
            character = await self.ctx.characters.get(settings.user_persona_id)
            if character is None:
                self.clear_user_persona_media()
                return
            self.user_persona = None
            self.user_persona_character = character
            self.user_image = character.media.primary_image()
            self.user_image_path = (
                self.ctx.characters.media_path(self.user_image.path)
                if self.user_image
                else None
            )
            self.user_voice = character.media.primary_voice()
            self.user_voice_path = (
                self.ctx.characters.media_path(self.user_voice.path)
                if self.user_voice
                else None
            )
            self.user_tts_configured = self._user_media_tts_configured(character.media.tts)
            return
        persona = self.ctx.api_config.get_user_persona(settings.user_persona_id)
        if persona is None:
            self.clear_user_persona_media()
            return

        self.user_persona = persona
        self.user_persona_character = None
        self.user_image = persona.media.primary_image()
        self.user_image_path = (
            self.ctx.api_config.media_path(self.user_image.path)
            if self.user_image
            else None
        )
        self.user_voice = persona.media.primary_voice()
        self.user_voice_path = (
            self.ctx.api_config.media_path(self.user_voice.path)
            if self.user_voice
            else None
        )
        self.user_tts_configured = self._user_media_tts_configured(persona.media.tts)

    def _user_media_tts_configured(self, tts_settings) -> bool:
        voice_design_ready = (
            tts_settings.api_type == CHARACTER_TTS_API_GEN_SERVER
            and tts_settings.gen_server_tts_mode == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3
            and bool(tts_settings.voice_caption.strip())
        )
        voice_registry_ready = (
            tts_settings.api_type == CHARACTER_TTS_API_TTS
            and bool(tts_settings.voice_id.strip())
            and self.ctx.tts.supports_voice_registry(tts_settings.endpoint_id)
        )
        return bool(
            self.ctx.tts.has_voice_playback_api(tts_settings.api_type, tts_settings.endpoint_id)
            and (self.user_voice_path is not None or voice_design_ready or voice_registry_ready)
        )

    def _narrator_tts_configured(self, tts_settings=None) -> bool:
        config = self.ctx.api_config.get_tts_config()
        settings = tts_settings or config.narrator
        narrator_voice_path = (
            self.ctx.api_config.media_path(config.narrator_voice.path)
            if config.narrator_voice is not None
            else None
        )
        if settings.api_type == CHARACTER_TTS_API_GEN_SERVER:
            if settings.gen_server_tts_mode == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3:
                return bool(
                    settings.voice_caption.strip()
                    and self.ctx.tts.resolve_gen_server_voice_design_endpoint(raise_on_missing=False) is not None
                )
            return bool(
                narrator_voice_path is not None
                and self.ctx.tts.resolve_gen_server_voice_clone_endpoint(raise_on_missing=False) is not None
            )
        if settings.api_type != CHARACTER_TTS_API_TTS:
            return False
        endpoint = self.ctx.api_config.get_tts_endpoint(settings.endpoint_id)
        if endpoint is None:
            return False
        if endpoint.provider == TTS_PROVIDER_IRODORI_SERVER:
            return bool(settings.voice_id.strip())
        return narrator_voice_path is not None

    def tts_playable_speakers(self) -> set[str]:
        speakers: set[str] = set()
        if self.tts_configured:
            speakers.add("character")
        if self.user_tts_configured:
            speakers.add("user")
        if self._narrator_tts_configured():
            speakers.add("narration")
        return speakers

    def run_page_javascript(self, code: str) -> None:
        self.page_client.run_javascript(code)

    def focus_chat_input_at_end(self) -> None:
        self.run_page_javascript(
            "setTimeout(() => {"
            "const el = document.querySelector('.cs-chat-composer-input textarea');"
            "if (!el) return;"
            "el.focus();"
            "const end = el.value.length;"
            "if (typeof el.setSelectionRange === 'function') el.setSelectionRange(end, end);"
            "}, 0);"
        )

    def set_mobile_sidebar(self, open_: bool) -> None:
        action = "add" if open_ else "remove"
        self.run_page_javascript(
            "document.querySelector('.cs-chat-shell')"
            f"?.classList.{action}('cs-mobile-sidebar-open');"
        )

    def chat_title(self) -> str:
        return self.state.title or "チャットを開始"

    def chat_subtitle(self) -> str:
        if self.state.settings is None:
            return "新しいチャットを開始してください"
        profile = self.ctx.api_config.get_llm_profile(self.state.settings.profile_id)
        profile_name = profile.name if profile else "不明なプロファイル"
        return f"{self.sheet.name} / {self.state.settings.chat_mode_name} / {profile_name}"

    def refresh_chat_header(self) -> None:
        if self.refs.title is not None:
            self.refs.title.set_text(self.chat_title())
        if self.refs.subtitle is None:
            return
        self.refs.subtitle.set_text(self.chat_subtitle())

    def refresh_messages(self, *, scroll_to_bottom: bool = False) -> None:
        if self.refs.messages is None:
            return
        if not scroll_to_bottom:
            self.run_page_javascript(
                "(() => {"
                "const el = document.querySelector('.cs-chat-messages');"
                "window.__csChatScrollTop = el ? el.scrollTop : null;"
                "})();"
            )
        self.refs.messages.clear()
        with self.refs.messages:
            for index, message in enumerate(self.state.messages):
                components.render_message(
                    message,
                    self.image,
                    self.image_path,
                    self.user_image,
                    self.user_image_path,
                    index=index,
                    rewind_message=self.confirm_rewind_to_message,
                    rewrite_message=self.open_rewrite_message_dialog,
                    regenerate_message=self.confirm_or_regenerate_character_message,
                    play_tts_message=self.play_tts_message if self.tts_playable_speakers() else None,
                    tts_playable_speakers=self.tts_playable_speakers(),
                    tts_generating=self.state.tts_generating_index == index,
                    open_debug=components.open_llm_debug_dialog,
                )
        if scroll_to_bottom:
            self.scroll_messages_to_bottom()
        else:
            self.run_page_javascript(
                "setTimeout(() => {"
                "const el = document.querySelector('.cs-chat-messages');"
                "const top = window.__csChatScrollTop;"
                "if (el && typeof top === 'number') el.scrollTop = top;"
                "window.__csChatScrollTop = null;"
                "}, 0);"
            )

    def scroll_messages_to_bottom(self) -> None:
        self.run_page_javascript(
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
        self.state.sending = sending
        if self.refs.send_btn is not None:
            self.refs.send_btn.disable() if sending else self.refs.send_btn.enable()
        if self.refs.input is not None:
            self.refs.input.disable() if sending else self.refs.input.enable()

    async def save_current_session(self, *, refresh_history: bool = True) -> None:
        if self.active_session_id is None or self.state.settings is None:
            return
        saved = await self.ctx.chats.update_session(
            session_id=self.active_session_id,
            character_id=self.sheet.id,
            title=self.state.title or DEFAULT_CHAT_TITLE,
            title_is_auto=self.active_title_is_auto,
            settings=chat_settings_to_dict(self.state.settings),
            messages=[chat_message_to_dict(message) for message in self.state.messages],
        )
        self.sessions_by_id[saved.id] = saved
        if refresh_history:
            await self.reload_sessions()
            self.refresh_history()

    async def select_chat_session(self, session_id: str) -> None:
        if self.state.sending:
            ui.notify("生成中はチャットを切り替えられません", type="warning")
            return
        session = await self.ctx.chats.get(session_id)
        if session is None or session.character_id != self.sheet.id:
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
        self.set_mobile_sidebar(False)

    async def rewind_to_message(self, index: int) -> None:
        if self.state.sending:
            ui.notify("生成中は戻れません", type="warning")
            return
        if index < 0 or index >= len(self.state.messages):
            return
        message = self.state.messages[index]
        if message.speaker not in {"character", "user", "narration", "memo"}:
            return
        self.state.messages = self.state.messages[:index]
        if self.refs.input is not None:
            self.refs.input.set_value(message.text)
            self.refs.input.enable()
        self.set_input_mode(input_mode_for_speaker(message.speaker))
        self.set_sending(False)
        self.refresh_messages()
        await self.save_current_session()

    def confirm_rewind_to_message(self, index: int) -> None:
        if self.state.sending:
            ui.notify("生成中は戻れません", type="warning")
            return
        if index < 0 or index >= len(self.state.messages):
            return
        message = self.state.messages[index]
        if message.speaker not in {"character", "user", "narration", "memo"}:
            return

        target_label = message_target_label(message.speaker)
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm"):
            ui.label(f"この{target_label}まで戻りますか？").classes("text-base font-semibold")
            ui.label(f"この{target_label}以降の会話を削除し、本文を入力欄に戻します。").classes(
                "text-sm text-grey-6"
            )
            ui.label(message.text).classes("text-sm").style(
                "white-space: pre-wrap; overflow-wrap: anywhere;"
            )

            async def _do_rewind() -> None:
                dlg.close()
                await self.rewind_to_message(index)

            with ui.row().classes("justify-end gap-2 mt-4"):
                ui.button("キャンセル", on_click=dlg.close).props("flat")
                ui.button("OK", icon="undo", on_click=_do_rewind).props(
                    "color=primary unelevated"
                )
        dlg.open()

    def open_rewrite_message_dialog(self, index: int) -> None:
        if self.state.sending:
            ui.notify("生成中は書き換えできません", type="warning")
            return
        if index < 0 or index >= len(self.state.messages):
            return
        message = self.state.messages[index]
        speaker_label = {
            "character": "キャラクターの台詞",
            "user": "ユーザーの発言",
            "narration": "地の文",
            "memo": "コメント",
        }.get(message.speaker, "メッセージ")

        with ui.dialog() as dlg, ui.card().classes("w-full max-w-xl"):
            ui.label(f"{speaker_label}を書き換え").classes("text-base font-semibold")
            ui.label("保存しても、この後の会話は削除されません。").classes("text-sm text-grey-6")
            rewrite_input = ui.textarea(
                value=message.text,
                placeholder="書き換え後の本文",
            ).props("outlined rows=5 autogrow").classes("w-full")

            async def _save_rewrite() -> None:
                next_text = (rewrite_input.value or "").strip()
                if not next_text:
                    ui.notify("本文を入力してください", type="warning")
                    return
                if index >= len(self.state.messages):
                    dlg.close()
                    return
                current = self.state.messages[index]
                self.state.messages[index] = ChatMessagePreview(
                    current.speaker,
                    next_text,
                    current.time_label,
                    current.debug,
                )
                dlg.close()
                self.refresh_messages()
                await self.save_current_session()

            with ui.row().classes("justify-end gap-2 mt-4"):
                ui.button("キャンセル", on_click=dlg.close).props("flat")
                ui.button("保存", icon="save", on_click=_save_rewrite).props(
                    "color=primary unelevated"
                )
        dlg.open()

    def configured_llm(self, settings: ChatSessionSettings):
        return configured_llm_for_profile(self.ctx, settings.profile_id)

    async def build_character_message(
        self,
        llm,
        settings: ChatSessionSettings,
        prior_messages: list[ChatMessagePreview],
        *,
        first_turn: bool = False,
        turn_instruction: str = "",
        empty_reply: str = "……ごめん、うまく言葉にできなかった。",
    ) -> ChatMessagePreview:
        llm_messages = build_llm_messages(
            self.sheet,
            settings,
            prior_messages,
            first_turn=first_turn,
            turn_instruction=turn_instruction,
        )
        debug_input = format_llm_input(llm_messages, settings)
        response = await llm.ainvoke(llm_messages)
        raw_output = message_content_to_text(getattr(response, "content", response))
        reply = sanitize_character_reply(raw_output, self.sheet.name)
        if not reply:
            reply = empty_reply
        return ChatMessagePreview(
            "character",
            reply,
            time_label(),
            build_debug_info(debug_input, raw_output, response),
        )

    async def build_narration_message(
        self,
        llm,
        settings: ChatSessionSettings,
        prior_messages: list[ChatMessagePreview],
        *,
        instruction: str = "",
        empty_reply: str = "場面は静かに次の言葉を待っている。",
    ) -> ChatMessagePreview:
        llm_messages = build_narration_llm_messages(
            self.sheet,
            settings,
            prior_messages,
            instruction=instruction,
        )
        debug_input = format_llm_input(llm_messages, settings)
        response = await llm.ainvoke(llm_messages)
        raw_output = message_content_to_text(getattr(response, "content", response))
        narration = sanitize_narration(raw_output)
        if not narration:
            narration = empty_reply
        return ChatMessagePreview(
            "narration",
            narration,
            time_label(),
            build_debug_info(debug_input, raw_output, response),
        )

    async def maybe_generate_auto_title(self, llm, settings: ChatSessionSettings) -> None:
        if self.active_session_id is None or not self.active_title_is_auto:
            return
        if self.title_generation_attempted:
            return
        character_turns = sum(1 for message in self.state.messages if message.speaker == "character")
        if character_turns < 3:
            return

        self.title_generation_attempted = True
        try:
            response = await llm.ainvoke(
                build_chat_title_messages(self.sheet, settings, self.state.messages)
            )
            title = sanitize_chat_title(
                message_content_to_text(getattr(response, "content", response))
            )
        except Exception:
            return

        if not title:
            return
        self.state.title = title
        self.active_title_is_auto = False
        self.refresh_chat_header()
        await self.save_current_session()

    async def play_tts_message(self, index: int) -> None:
        if self.state.tts_generating_index is not None:
            ui.notify("音声生成中です", type="info")
            return
        if index < 0 or index >= len(self.state.messages):
            return
        message = self.state.messages[index]
        if message.speaker not in {"character", "user", "narration"}:
            return
        text = message.text.strip()
        if not text or text in {"…", "..."}:
            ui.notify("読み上げる本文がありません", type="warning")
            return

        if message.speaker == "narration":
            config = self.ctx.api_config.get_tts_config()
            settings = config.narrator
            if not self._narrator_tts_configured(settings):
                ui.notify("ナレーターTTS設定を確認してください", type="warning")
                return
            target_id = "narrator"
            voice = config.narrator_voice
            voice_path = self.ctx.api_config.media_path(voice.path) if voice else None
            playback_save = self.ctx.api_config.save_narrator_tts_playback
        elif message.speaker == "character":
            if not self.tts_configured or self.voice is None or self.voice_path is None:
                ui.notify("TTS設定を確認してください", type="warning")
                return
            target_id = self.sheet.id
            settings = self.sheet.media.tts
            voice = self.voice
            voice_path = self.voice_path
            playback_save = lambda audio: self.ctx.characters.save_tts_playback(self.sheet.id, audio)
        else:
            if (
                self.state.settings is not None
                and self.state.settings.user_persona_source == components.USER_PERSONA_SOURCE_CHARACTER
            ):
                if (
                    not self.user_tts_configured
                    or self.user_persona_character is None
                    or (self.user_voice_path is None and not self._user_voice_design_ready())
                ):
                    ui.notify("ユーザー役のTTS設定を確認してください", type="warning")
                    return
                user_character_id = self.user_persona_character.id
                target_id = user_character_id
                settings = self.user_persona_character.media.tts
                voice = self.user_voice
                voice_path = self.user_voice_path
                playback_save = lambda audio, character_id=user_character_id: self.ctx.characters.save_tts_playback(
                    character_id,
                    audio,
                )
            else:
                if (
                    not self.user_tts_configured
                    or self.user_persona is None
                    or (self.user_voice_path is None and not self._user_voice_design_ready())
                ):
                    ui.notify("ユーザーペルソナのTTS設定を確認してください", type="warning")
                    return
                user_persona_id = self.user_persona.id
                target_id = user_persona_tts_id(user_persona_id)
                settings = self.user_persona.media.tts
                voice = self.user_voice
                voice_path = self.user_voice_path
                playback_save = lambda audio, persona_id=user_persona_id: self.ctx.api_config.save_user_persona_tts_playback(
                    persona_id,
                    audio,
                )

        if (
            settings.api_type == CHARACTER_TTS_API_GEN_SERVER
            and settings.gen_server_tts_mode == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3
            and not settings.voice_caption.strip()
        ):
            ui.notify("VoiceDesign v3モードのキャプションを設定してください", type="warning")
            return
        self.state.tts_generating_index = index
        self.refresh_messages()
        try:
            audio = await self.ctx.tts.synthesize(
                target_id,
                voice_path,
                text,
                endpoint_id=settings.endpoint_id,
                voice_id=settings.voice_id,
                filename=voice.original_name if voice else "",
                content_type=voice.content_type if voice else "",
                api_type=settings.api_type,
                gen_server_tts_mode=settings.gen_server_tts_mode,
                voice_caption=settings.voice_caption,
                gen_server_params=settings.gen_server_params,
            )
            playback_path = playback_save(audio)
            audio_url = app.add_static_file(local_file=playback_path, max_cache_age=0)
            self.run_page_javascript(
                "(() => {"
                f"const audio = new Audio({json.dumps(audio_url)});"
                "audio.play().catch(() => {});"
                "})();"
            )
        except TTSServiceError as err:
            ui.notify(f"読み上げに失敗しました: {err}", type="negative", timeout=10000)
        except Exception as err:
            ui.notify(f"読み上げに失敗しました: {err}", type="negative", timeout=10000)
        finally:
            self.state.tts_generating_index = None
            self.refresh_messages()

    def _user_voice_design_ready(self) -> bool:
        if self.user_persona_character is not None:
            settings = self.user_persona_character.media.tts
        elif self.user_persona is not None:
            settings = self.user_persona.media.tts
        else:
            return False
        return (
            settings.api_type == CHARACTER_TTS_API_GEN_SERVER
            and settings.gen_server_tts_mode == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3
            and bool(settings.voice_caption.strip())
        )

    def set_input_value(self, value: str) -> None:
        if self.refs.input is not None:
            self.refs.input.set_value(value)

    def clear_input(self) -> None:
        self.set_input_value("")
        self.run_page_javascript(
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

    def refresh_input_mode_indicator(self) -> None:
        if self.refs.input_mode_icon is None:
            return
        self.refs.input_mode_icon.clear()
        with self.refs.input_mode_icon:
            components.render_input_mode_indicator(
                self.state.input_mode,
                self.image,
                self.image_path,
                self.user_image,
                self.user_image_path,
            )

    def set_input_mode(self, mode: str) -> None:
        self.state.input_mode = mode if mode in {"character", "narration", "memo"} else "user"
        self.refresh_input_mode_indicator()

    async def post_narration(self, text: str) -> None:
        self.state.messages.append(ChatMessagePreview("narration", text, time_label()))
        self.refresh_messages(scroll_to_bottom=True)
        await self.save_current_session()

    async def post_memo(self, text: str) -> None:
        self.state.messages.append(ChatMessagePreview("memo", text, time_label()))
        self.refresh_messages(scroll_to_bottom=True)
        await self.save_current_session()

    async def post_character_input(self, text: str) -> None:
        self.state.messages.append(ChatMessagePreview("character", text, time_label()))
        self.refresh_messages(scroll_to_bottom=True)
        await self.save_current_session()

    async def post_hold_user_text(self, left_text: str) -> None:
        self.clear_input()
        self.state.messages.append(ChatMessagePreview("user", left_text.strip(), time_label()))
        self.refresh_messages(scroll_to_bottom=True)
        self.set_input_mode("user")
        await self.save_current_session()

    async def append_character_turn(
        self,
        settings: ChatSessionSettings,
        *,
        llm=None,
        turn_instruction: str = "",
        empty_reply: str = "……少し考え込んでしまった。",
    ) -> None:
        llm = llm or self.configured_llm(settings)
        if llm is None:
            return

        prior_messages = list(self.state.messages)
        self.state.messages.append(ChatMessagePreview("character", "…", time_label()))
        self.refresh_messages(scroll_to_bottom=True)
        self.set_sending(True)
        generated_successfully = False
        try:
            generated = await self.build_character_message(
                llm,
                settings,
                prior_messages,
                first_turn=is_first_character_turn(prior_messages),
                turn_instruction=turn_instruction,
                empty_reply=empty_reply,
            )
            self.state.messages[-1] = generated
            self.refresh_messages(scroll_to_bottom=True)
            generated_successfully = True
        except Exception as err:
            self.state.messages.pop()
            self.refresh_messages(scroll_to_bottom=True)
            ui.notify(f"チャット送信に失敗しました: {err}", type="negative", timeout=10000)
        finally:
            self.set_sending(False)
            await self.save_current_session()
        if generated_successfully:
            await self.maybe_generate_auto_title(llm, settings)

    async def send_user_turn(self, text: str) -> None:
        settings = self.state.settings
        if settings is None:
            ui.notify("先に「新しいチャット」を作成してください", type="warning")
            self.open_new_chat_dialog()
            return
        llm = self.configured_llm(settings)
        if llm is None:
            return

        self.clear_input()
        self.state.messages.append(ChatMessagePreview("user", text, time_label()))
        await self.append_character_turn(settings, llm=llm)

    async def generate_scene(self, settings: ChatSessionSettings, *, instruction: str = "") -> None:
        llm = self.configured_llm(settings)
        if llm is None:
            return

        self.state.messages.append(ChatMessagePreview("narration", "…", time_label()))
        self.refresh_messages(scroll_to_bottom=True)
        self.set_sending(True)
        try:
            generated = await self.build_narration_message(
                llm,
                settings,
                self.state.messages[:-1],
                instruction=instruction,
            )
            self.state.messages[-1] = generated
            self.refresh_messages(scroll_to_bottom=True)
        except Exception as err:
            self.state.messages.pop()
            self.refresh_messages(scroll_to_bottom=True)
            ui.notify(f"地の文生成に失敗しました: {err}", type="negative", timeout=10000)
        finally:
            self.set_sending(False)
            await self.save_current_session()

    async def run_describe_action(
        self,
        settings: ChatSessionSettings,
        left_text: str,
        *,
        instruction: str = "",
    ) -> None:
        if left_text.strip():
            await self.post_command_left_text(left_text)
        else:
            self.clear_input()
        self.set_input_mode("user")
        self.clear_input()
        try:
            await self.generate_scene(settings, instruction=instruction)
        finally:
            self.clear_input()

    async def fill_user_text(self, settings: ChatSessionSettings, left_text: str) -> None:
        if not left_text.strip():
            ui.notify("補完する文を /fill の左側に入力してください", type="warning")
            return
        llm = self.configured_llm(settings)
        if llm is None:
            return

        focus_after_completion = False
        self.set_sending(True)
        try:
            response = await llm.ainvoke(
                build_user_completion_messages(
                    self.sheet,
                    settings,
                    self.state.messages,
                    left_text,
                    input_mode=self.state.input_mode,
                )
            )
            raw_output = message_content_to_text(getattr(response, "content", response))
            completed = merge_completion(left_text, raw_output)
            self.set_input_value(completed)
            focus_after_completion = True
            ui.notify("続きを補完しました", type="positive")
        except Exception as err:
            ui.notify(f"補完に失敗しました: {err}", type="negative", timeout=10000)
        finally:
            self.set_sending(False)
            if focus_after_completion:
                self.focus_chat_input_at_end()

    async def tailor_input_text(self, settings: ChatSessionSettings, left_text: str) -> None:
        if not left_text.strip():
            ui.notify("書き換える文を /tailor の左側に入力してください", type="warning")
            return
        llm = self.configured_llm(settings)
        if llm is None:
            return

        focus_after_tailor = False
        self.set_sending(True)
        try:
            response = await llm.ainvoke(
                build_tailored_input_messages(
                    self.sheet,
                    settings,
                    self.state.messages,
                    left_text,
                    input_mode=self.state.input_mode,
                )
            )
            raw_output = message_content_to_text(getattr(response, "content", response))
            tailored = clean_short_llm_text(raw_output)
            if not tailored:
                ui.notify("書き換え結果が空でした", type="warning")
                return
            self.set_input_value(tailored)
            focus_after_tailor = True
            ui.notify("現在のロール向けに書き換えました", type="positive")
        except Exception as err:
            ui.notify(f"書き換えに失敗しました: {err}", type="negative", timeout=10000)
        finally:
            self.set_sending(False)
            if focus_after_tailor:
                self.focus_chat_input_at_end()

    async def show_response_choices(self, settings: ChatSessionSettings, left_text: str) -> None:
        llm = self.configured_llm(settings)
        if llm is None:
            return

        input_mode = self.state.input_mode
        self.set_sending(True)
        try:
            response = await llm.ainvoke(
                build_response_choice_messages(
                    self.sheet,
                    settings,
                    self.state.messages,
                    left_text,
                    input_mode=input_mode,
                )
            )
            raw_output = message_content_to_text(getattr(response, "content", response))
            choices = parse_response_choices(raw_output)
            if left_text.strip():
                choices = [merge_completion(left_text, choice) for choice in choices]
        except Exception as err:
            ui.notify(f"選択肢生成に失敗しました: {err}", type="negative", timeout=10000)
            return
        finally:
            self.set_sending(False)

        if not choices:
            ui.notify("選択肢を生成できませんでした", type="warning")
            return

        with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg cs-chat-choice-dialog"):
            ui.label("応答を選択").classes("text-base font-semibold")
            target_label = message_target_label(input_mode)
            ui.label(f"選ぶとその{target_label}を投稿します。").classes("text-sm text-grey-6")

            async def _choose(choice: str) -> None:
                dlg.close()
                if input_mode == "narration":
                    self.clear_input()
                    await self.post_narration(choice)
                    self.set_input_mode("user")
                    return
                if input_mode == "character":
                    self.clear_input()
                    await self.post_character_input(choice)
                    self.set_input_mode("user")
                    return
                await self.send_user_turn(choice)

            def _choice_click_handler(choice: str):
                async def _handler() -> None:
                    await _choose(choice)

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
        self.run_page_javascript(
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

    async def post_command_left_text(self, left_text: str) -> None:
        text = left_text.strip()
        if not text:
            return
        self.clear_input()
        if self.state.input_mode == "narration":
            self.state.messages.append(ChatMessagePreview("narration", text, time_label()))
            self.set_input_mode("user")
        elif self.state.input_mode == "character":
            self.state.messages.append(ChatMessagePreview("character", text, time_label()))
            self.set_input_mode("user")
        elif self.state.input_mode == "memo":
            self.state.messages.append(ChatMessagePreview("memo", text, time_label()))
            self.set_input_mode("user")
        else:
            self.state.messages.append(ChatMessagePreview("user", text, time_label()))
        self.refresh_messages(scroll_to_bottom=True)
        await self.save_current_session()

    async def open_guide_next_turn_dialog(self, settings: ChatSessionSettings, left_text: str = "") -> None:
        if left_text.strip():
            self.set_input_value(left_text)
        else:
            self.clear_input()

        target_options = {
            "character": "キャラ",
            "narration": "地の文",
            "user": "ユーザー",
        }
        presets = [
            ("抽象的・曖昧な表現を避け、具体的な表現を用いる", "抽象的・曖昧な表現を避け、具体的な表現を用いる", "auto_awesome", "character"),
            ("シーンを明確に進める描写(or セリフ)", "シーンを明確に進める描写(or セリフ)", "trending_flat", "character"),
            ("場面を転換する(地の文のみ)", "場面を転換する", "alt_route", "narration"),
        ]

        with ui.dialog() as dlg, ui.card().classes("w-full max-w-xl"):
            ui.label("次の行動").classes("text-base font-semibold")
            target_select = ui.select(
                options=target_options,
                value="character",
                label="次の行動",
            ).props("outlined").classes("w-full")
            direction_input = ui.textarea(
                label="指示",
                placeholder="キャラまたは地の文にだけ反映する任意の指示",
            ).props("outlined rows=4 autogrow").classes("w-full")

            def _sync_direction_input() -> None:
                if target_select.value == "user":
                    direction_input.set_value("")
                    direction_input.disable()
                    return
                direction_input.enable()

            target_select.on_value_change(lambda _: _sync_direction_input())

            with ui.row().classes("gap-2 flex-wrap"):
                for preset_label, preset_text, icon, target in presets:
                    def _apply_preset(text=preset_text, target_mode=target) -> None:
                        direction_input.set_value(text)
                        target_select.set_value(target_mode)
                        _sync_direction_input()

                    ui.button(
                        preset_label,
                        icon=icon,
                        on_click=_apply_preset,
                    ).props("outline size=sm color=primary").classes("cs-chat-guide-preset")

            async def _run_directed_turn() -> None:
                direction = (direction_input.value or "").strip()
                target = target_select.value or "character"
                dlg.close()
                if target == "user":
                    if left_text.strip():
                        await self.post_hold_user_text(left_text)
                    else:
                        self.clear_input()
                        self.set_input_mode("user")
                    return
                if target == "narration":
                    await self.run_describe_action(settings, left_text, instruction=direction)
                    return
                if not direction:
                    await self.send_message(True, left_text)
                    return
                if left_text.strip():
                    await self.post_command_left_text(left_text)
                else:
                    self.clear_input()
                await self.append_character_turn(settings, turn_instruction=direction)

            with ui.row().classes("justify-end gap-2 mt-4"):
                ui.button("キャンセル", on_click=dlg.close).props("flat")
                ui.button("実行", icon="play_arrow", on_click=_run_directed_turn).props(
                    "color=primary unelevated"
                )
        dlg.open()

    async def execute_chat_command(self, settings: ChatSessionSettings, left_text: str, query: str) -> None:
        command = resolve_chat_command(query)
        if command is None:
            ui.notify("実行するコマンドを選択してください", type="warning")
            return

        left_text = left_text.rstrip()
        if command == "hold":
            if not left_text.strip():
                ui.notify("/hold の左側に投稿する文を入力してください", type="warning")
                return
            await self.post_hold_user_text(left_text)
            return

        if command == "guide":
            await self.open_guide_next_turn_dialog(settings, left_text)
            return

        if command == "fill":
            self.set_input_value(left_text)
            await self.fill_user_text(settings, left_text)
            return

        if command == "tailor":
            self.set_input_value(left_text)
            await self.tailor_input_text(settings, left_text)
            return

        if command == "choices":
            self.set_input_value(left_text)
            await self.show_response_choices(settings, left_text)
            return

        if command == "skip":
            if left_text.strip():
                ui.notify("/skip は単独で入力してください", type="warning")
                return
            self.clear_input()
            await self.append_character_turn(settings)
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
            self.set_input_value(left_text)
            self.set_input_mode("character")
            ui.notify("キャラクター入力モードにしました", type="info")
            return

        if command == "user":
            self.set_input_value(left_text)
            self.set_input_mode("user")
            ui.notify("ユーザー入力モードに戻しました", type="info")
            return

        if command == "describe":
            await self.run_describe_action(settings, left_text)
            return

    async def send_message(
        self,
        allow_skip: bool = False,
        submitted_text: str | None = None,
    ) -> None:
        if self.state.sending:
            return
        settings = self.state.settings
        if settings is None:
            ui.notify("先に「新しいチャット」を作成してください", type="warning")
            self.open_new_chat_dialog()
            return

        raw_text = submitted_text if submitted_text is not None else (
            self.refs.input.value if self.refs.input is not None else ""
        )
        parsed_command = parse_command_input(raw_text or "")
        if parsed_command is not None:
            left_text, query = parsed_command
            await self.execute_chat_command(settings, left_text, query)
            return

        text = (raw_text or "").strip()
        if not text:
            if not allow_skip:
                ui.notify("メッセージを入力してください", type="warning")
                return
            await self.append_character_turn(settings)
            return

        if self.state.input_mode == "narration":
            self.clear_input()
            await self.post_narration(text)
            self.set_input_mode("user")
            return

        if self.state.input_mode == "memo":
            self.clear_input()
            await self.post_memo(text)
            self.set_input_mode("user")
            return

        if self.state.input_mode == "character":
            self.clear_input()
            await self.post_character_input(text)
            self.set_input_mode("user")
            return

        await self.send_user_turn(text)

    def open_new_chat_dialog(self) -> None:
        profile_options = profile_options_for_context(self.ctx)
        chat_modes = self.ctx.api_config.get_chat_modes()
        mode_options = {mode.id: mode.name for mode in chat_modes}
        user_personas = self.ctx.api_config.get_user_personas()
        persona_options = {persona.id: persona.display_name for persona in user_personas}
        components.open_new_chat_dialog_for_sheet(
            sheet=self.sheet,
            profile_options=profile_options,
            default_profile_id=default_profile_id(self.ctx, profile_options),
            mode_options=mode_options,
            default_mode_id=default_chat_mode_id(mode_options),
            persona_options=persona_options,
            default_persona_id=default_user_persona_id(persona_options),
            get_mode=lambda mode_id: self.ctx.api_config.get_chat_mode(mode_id),
            get_persona=lambda persona_id: self.ctx.api_config.get_user_persona(persona_id),
            pick_character_persona=lambda on_select: open_character_picker(
                self.ctx,
                on_select,
                title="ユーザー役にするキャラクターを選択",
            ),
            render_mode=lambda mode, persona: render_mode_for_sheet(mode, self.sheet, persona),
            validate_profile=lambda profile_id: validate_profile_for_start(self.ctx, profile_id),
            enhance_situation=self.enhance_situation,
            start_chat=self.start_chat_session,
        )

    def open_rename_current_chat_dialog(self) -> None:
        if self.active_session_id is None:
            ui.notify("先にチャットを開始してください", type="warning")
            return
        self.open_rename_chat_dialog(self.active_session_id)

    def confirm_delete_current_chat(self) -> None:
        if self.active_session_id is None:
            ui.notify("削除するチャットがありません", type="warning")
            return
        self.confirm_delete_chat_session(self.active_session_id)

    def open_rename_chat_dialog(self, session_id: str) -> None:
        session = self.sessions_by_id.get(session_id)
        if session is None:
            ui.notify("チャットが見つかりません", type="warning")
            return
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-md"):
            ui.label("タイトル変更").classes("text-base font-semibold")
            title_input = ui.input(
                label="タイトル",
                value=session.title or DEFAULT_CHAT_TITLE,
            ).props("outlined clearable").classes("w-full")

            async def _save_title() -> None:
                title = (title_input.value or "").strip()
                if not title:
                    ui.notify("タイトルを入力してください", type="warning")
                    return
                saved = await self.ctx.chats.rename_session(session_id, title)
                if saved is None:
                    dlg.close()
                    ui.notify("チャットが見つかりません", type="warning")
                    await self.reload_sessions()
                    self.refresh_history()
                    return
                self.sessions_by_id[saved.id] = saved
                if saved.id == self.active_session_id:
                    self.state.title = saved.title
                    self.active_title_is_auto = False
                    self.refresh_chat_header()
                await self.reload_sessions()
                self.refresh_history()
                dlg.close()

            with ui.row().classes("justify-end gap-2 mt-4"):
                ui.button("キャンセル", on_click=dlg.close).props("flat")
                ui.button("保存", icon="save", on_click=_save_title).props(
                    "color=primary unelevated"
                )
        dlg.open()

    def confirm_delete_chat_session(self, session_id: str) -> None:
        if self.state.sending:
            ui.notify("生成中は削除できません", type="warning")
            return
        session = self.sessions_by_id.get(session_id)
        if session is None:
            ui.notify("チャットが見つかりません", type="warning")
            return
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm"):
            ui.label("チャットを削除しますか？").classes("text-base font-semibold")
            ui.label("この操作は元に戻せません。").classes("text-sm text-grey-6")
            ui.label(session.title or DEFAULT_CHAT_TITLE).classes("text-sm font-semibold")

            async def _delete() -> None:
                dlg.close()
                was_active = session_id == self.active_session_id
                await self.ctx.chats.delete_session(session_id)
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
                ui.button("削除", icon="delete", on_click=_delete).props(
                    "color=negative unelevated"
                )
        dlg.open()

    async def enhance_situation(
        self,
        profile_id: str,
        mode: ChatMode,
        persona: UserPersona,
        premise: str,
        current_situation: str,
    ) -> str | None:
        llm = configured_llm_for_profile(self.ctx, profile_id)
        if llm is None:
            return None
        try:
            response = await llm.ainvoke([
                SystemMessage(content="あなたはキャラクターチャット開始時のシチュエーションを整える編集者です。"),
                HumanMessage(content=(
                    "次のチャット開始シチュエーションを、矛盾を増やさず具体性だけ補ってください。\n"
                    "出力は補強後のシチュエーション本文だけにしてください。箇条書き、解説、前置きは禁止です。\n\n"
                    f"キャラクター名: {self.sheet.name or 'キャラクター'}\n"
                    f"チャットモード: {mode.name}\n"
                    f"前提: {premise}\n"
                    f"ユーザーペルソナ名: {persona.name}\n"
                    f"ユーザーペルソナ設定:\n{persona.description.strip()}\n\n"
                    f"現在のシチュエーション:\n{current_situation}\n\n"
                    f"キャラクター概要:\n{character_summary(self.sheet)}"
                )),
            ])
            enhanced = message_content_to_text(getattr(response, "content", response)).strip()
            enhanced = re.sub(r"^```(?:\w+)?\s*", "", enhanced)
            enhanced = re.sub(r"\s*```$", "", enhanced).strip()
            if not enhanced:
                ui.notify("シチュエーションを補完できませんでした", type="warning")
                return None
            ui.notify("シチュエーションを補完しました", type="positive")
            return enhanced
        except Exception as err:
            ui.notify(f"シチュエーション補完に失敗しました: {err}", type="negative", timeout=10000)
            return None

    def open_system_prompt_dialog(self) -> None:
        settings = self.state.settings
        if settings is None:
            ui.notify("先に「新しいチャット」を作成してください", type="warning")
            return
        components.open_system_prompt_dialog(build_system_prompt(self.sheet, settings))

    async def start_chat_session(self, settings: ChatSessionSettings, title: str = "") -> None:
        title = title.strip()
        title_is_auto = not title
        self.state.settings = settings
        self.state.title = title or DEFAULT_CHAT_TITLE
        self.state.messages = []
        self.state.input_mode = "user"
        await self.refresh_user_persona_media()
        self.active_title_is_auto = title_is_auto
        self.title_generation_attempted = False
        if self.refs.input is not None:
            self.refs.input.set_value("")
        if settings.situation.strip():
            self.state.messages.append(
                ChatMessagePreview("narration", settings.situation.strip(), time_label())
            )
        saved = await self.ctx.chats.create_session(
            character_id=self.sheet.id,
            title=self.state.title,
            title_is_auto=title_is_auto,
            settings=chat_settings_to_dict(settings),
            messages=[chat_message_to_dict(message) for message in self.state.messages],
        )
        self.active_session_id = saved.id
        self.sessions_by_id[saved.id] = saved
        await self.reload_sessions()
        self.refresh_input_mode_indicator()
        self.refresh_chat_header()
        self.refresh_messages(scroll_to_bottom=True)
        self.refresh_history()

    async def regenerate_character_message(self, index: int) -> None:
        if self.state.sending:
            ui.notify("生成中は再生成できません", type="warning")
            return
        settings = self.state.settings
        if settings is None:
            ui.notify("先に「新しいチャット」を作成してください", type="warning")
            self.open_new_chat_dialog()
            return
        if index < 0 or index >= len(self.state.messages):
            return
        if self.state.messages[index].speaker != "character":
            return

        llm = self.configured_llm(settings)
        if llm is None:
            return

        original_messages = list(self.state.messages)
        prior_messages = self.state.messages[:index]
        first_turn = is_first_character_turn(prior_messages)
        was_latest = index == len(original_messages) - 1
        self.state.messages = prior_messages + [
            ChatMessagePreview("character", "…", time_label())
        ]
        self.refresh_messages()
        self.set_sending(True)
        generated_successfully = False
        try:
            generated = await self.build_character_message(
                llm,
                settings,
                prior_messages,
                first_turn=first_turn,
                empty_reply="こんにちは。少し話そう。" if first_turn else "……ごめん、うまく言葉にできなかった。",
            )
            self.state.messages[-1] = generated
            self.refresh_messages()
            generated_successfully = True
        except Exception as err:
            if was_latest:
                self.state.messages = original_messages
            else:
                self.state.messages.pop()
            self.refresh_messages()
            ui.notify(f"再生成に失敗しました: {err}", type="negative", timeout=10000)
        finally:
            self.set_sending(False)
            await self.save_current_session()
        if generated_successfully:
            await self.maybe_generate_auto_title(llm, settings)

    async def confirm_or_regenerate_character_message(self, index: int) -> None:
        if self.state.sending:
            ui.notify("生成中は再生成できません", type="warning")
            return
        if index < 0 or index >= len(self.state.messages):
            return
        if self.state.messages[index].speaker != "character":
            return
        if index == len(self.state.messages) - 1:
            await self.regenerate_character_message(index)
            return

        with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm"):
            ui.label("この台詞から再生成しますか？").classes("text-base font-semibold")
            ui.label("この台詞以降の会話を削除してから、新しい台詞を生成します。").classes(
                "text-sm text-grey-6"
            )
            ui.label(self.state.messages[index].text).classes("text-sm").style(
                "white-space: pre-wrap; overflow-wrap: anywhere;"
            )

            async def _do_regenerate() -> None:
                dlg.close()
                await self.regenerate_character_message(index)

            with ui.row().classes("justify-end gap-2 mt-4"):
                ui.button("キャンセル", on_click=dlg.close).props("flat")
                ui.button("再生成", icon="refresh", on_click=_do_regenerate).props(
                    "color=primary unelevated"
                )
        dlg.open()


def chat_settings_to_dict(settings: ChatSessionSettings) -> dict[str, Any]:
    return asdict(settings)


def chat_settings_from_dict(data: dict[str, Any]) -> ChatSessionSettings:
    if not isinstance(data, dict):
        data = {}
    return ChatSessionSettings(
        profile_id=str(data.get("profile_id", "")),
        chat_mode_id=str(data.get("chat_mode_id", "")),
        chat_mode_name=str(data.get("chat_mode_name", "")),
        chat_premise=str(data.get("chat_premise", "")),
        situation=str(data.get("situation", "")),
        user_persona_id=str(data.get("user_persona_id", "")),
        user_persona_name=str(data.get("user_persona_name", "ユーザー")),
        user_persona_description=str(data.get("user_persona_description", "")),
        user_persona_source=chat_user_persona_source(str(data.get("user_persona_source", ""))),
    )


def chat_user_persona_source(value: str) -> str:
    if value == components.USER_PERSONA_SOURCE_CHARACTER:
        return components.USER_PERSONA_SOURCE_CHARACTER
    return components.USER_PERSONA_SOURCE_PERSONA


def input_mode_for_speaker(speaker: str) -> str:
    if speaker == "character":
        return "character"
    if speaker == "narration":
        return "narration"
    if speaker == "memo":
        return "memo"
    return "user"


def message_target_label(speaker: str) -> str:
    if speaker == "character":
        return "キャラクターの台詞"
    if speaker == "narration":
        return "地の文"
    if speaker == "memo":
        return "コメント"
    return "発言"


def user_persona_tts_id(persona_id: str) -> str:
    return f"user-persona-{persona_id}"


def chat_message_to_dict(message: ChatMessagePreview) -> dict[str, Any]:
    result: dict[str, Any] = {
        "speaker": message.speaker,
        "text": message.text,
        "time_label": message.time_label,
    }
    if message.debug is not None:
        result["debug"] = asdict(message.debug)
    return result


def chat_message_from_dict(data: dict[str, Any]) -> ChatMessagePreview:
    if not isinstance(data, dict):
        data = {}
    debug_data = data.get("debug")
    debug = None
    if isinstance(debug_data, dict):
        debug = ChatDebugInfo(
            llm_input=str(debug_data.get("llm_input", "")),
            raw_output=str(debug_data.get("raw_output", "")),
            reasoning_output=str(debug_data.get("reasoning_output", "")),
            input_tokens=optional_int(debug_data.get("input_tokens")),
            output_tokens=optional_int(debug_data.get("output_tokens")),
            total_tokens=optional_int(debug_data.get("total_tokens")),
        )
    return ChatMessagePreview(
        speaker=str(data.get("speaker", "user")),
        text=str(data.get("text", "")),
        time_label=str(data.get("time_label", "")) or time_label(),
        debug=debug,
    )


def optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def latest_message_preview(messages: list[dict[str, Any]], *, limit: int = 56) -> str:
    if not messages:
        return "まだ発言がありません"
    latest = messages[-1]
    text = str(latest.get("text", "")) if isinstance(latest, dict) else ""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return "まだ発言がありません"
    if len(text) > limit:
        return f"{text[:limit].rstrip()}..."
    return text


def session_time_label(updated_at: datetime) -> str:
    now = datetime.now()
    if updated_at.date() == now.date():
        return updated_at.strftime("%H:%M")
    if updated_at.date() == (now - timedelta(days=1)).date():
        return "昨日"
    if updated_at.year == now.year:
        return f"{updated_at.month}/{updated_at.day}"
    return updated_at.strftime("%Y/%m/%d")


def profile_options_for_context(ctx) -> dict[str, str]:
    profiles = ctx.api_config.get_llm_profiles()
    endpoints = {ep.id: ep for ep in ctx.api_config.get_endpoints()}
    options: dict[str, str] = {}
    for profile in profiles:
        endpoint = endpoints.get(profile.endpoint_id)
        endpoint_name = endpoint.name if endpoint else "不明"
        model = profile.model_id or "未設定"
        options[profile.id] = f"{profile.name} [{endpoint_name} / {model}]"
    return options


def validate_profile_for_start(ctx, profile_id: str) -> bool:
    profile = ctx.api_config.get_llm_profile(profile_id)
    if profile is None:
        ui.notify("LLMプロファイルが見つかりません", type="negative")
        return False
    if not profile.model_id:
        ui.notify("モデルIDが未設定です。設定画面でLLMプロファイルのモデルを設定してください。", type="negative")
        return False
    if ctx.api_config.get_endpoint(profile.endpoint_id) is None:
        ui.notify("エンドポイントが見つかりません", type="negative")
        return False
    return True


def configured_llm_for_profile(ctx, profile_id: str):
    profile = ctx.api_config.get_llm_profile(profile_id)
    if profile is None:
        ui.notify("LLMプロファイルが見つかりません", type="negative")
        return None
    if not profile.model_id:
        ui.notify("モデルIDが未設定です。設定画面でLLMプロファイルのモデルを設定してください。", type="negative")
        return None
    endpoint = ctx.api_config.get_endpoint(profile.endpoint_id)
    if endpoint is None:
        ui.notify("エンドポイントが見つかりません", type="negative")
        return None

    vault_pw = get_vault_password()
    api_key = ctx.api_config.get_api_key(profile.endpoint_id, vault_pw)
    if ctx.api_config.is_api_key_locked(profile.endpoint_id, api_key):
        ui.notify(
            "このエンドポイントにはAPIキーが設定されています。APIキーボルトをロック解除してください。",
            type="warning",
            timeout=8000,
        )
        return None
    return create_llm(profile, endpoint, api_key)


def default_profile_id(ctx, profile_options: dict[str, str]) -> str:
    if not profile_options:
        return ""
    app_config = ctx.api_config.get_app_llm_config()
    for default_id in (app_config.chat_profile_id, app_config.generation_profile_id):
        if default_id in profile_options:
            return default_id
    return next(iter(profile_options))


def default_chat_mode_id(mode_options: dict[str, str]) -> str:
    if not mode_options:
        return ""
    for preferred in ("smalltalk", "roleplay", "summon"):
        if preferred in mode_options:
            return preferred
    return next(iter(mode_options))


def default_user_persona_id(persona_options: dict[str, str]) -> str:
    if not persona_options:
        return ""
    return next(iter(persona_options))


def render_mode_for_sheet(
    mode: ChatMode,
    sheet: CharacterSheet,
    persona: UserPersona,
) -> tuple[str, str]:
    return render_chat_mode(
        mode,
        character_name=sheet.name or "キャラクター",
        user_persona_name=persona.name or "ユーザー",
    )
