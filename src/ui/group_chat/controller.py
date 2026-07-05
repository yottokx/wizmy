"""グループチャット詳細画面のコントローラ。"""

from __future__ import annotations

import json
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
    group_input_mode_for_role,
)
from ...core.conversation.sanitize import (
    clean_guest_name,
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
from ..chat.commands import (
    parse_command_input,
    resolve_chat_command,
)
from ..chat.models import ChatDebugInfo, ChatThreadPreview
from ..state import get_vault_password
from .common import (
    group_member_tts_id as _group_member_tts_id,
    group_user_persona_tts_id as _group_user_persona_tts_id,
    notify_group_chat_llm_runtime_error as _notify_group_chat_llm_runtime_error,
)
from .dialogs_controller import (
    confirm_delete_chat_session,
    confirm_delete_current_chat,
    confirm_or_regenerate_character_message,
    confirm_rewind_to_message,
    open_guest_input_mode_dialog,
    open_guide_next_turn_dialog,
    open_imitate_character_dialog,
    open_new_chat_dialog,
    open_rename_chat_dialog,
    open_rename_current_chat_dialog,
    open_rewrite_message_dialog,
    open_system_prompt_dialog,
)
from .rendering import (
    group_message_target_label as _group_message_target_label,
    group_participants as _group_participants,
    refresh_chat_header,
    refresh_command_palette,
    refresh_history,
    refresh_input_mode_indicator,
    refresh_mention_palette,
    refresh_messages,
    refresh_profiles,
    render_chat_main,
    render_history,
    render_history_section,
    render_input_role_selector,
    render_mention_options,
    render_messages,
    render_shell,
    time_label as _time_label,
)


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
        return render_shell(self)

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
        return refresh_profiles(self)

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
        return render_mention_options(self)

    def refresh_mention_palette(self) -> None:
        return refresh_mention_palette(self)

    def refresh_command_palette(self, value: str) -> None:
        return refresh_command_palette(self, value)

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
        return render_history_section(self)

    def render_history(self) -> None:
        return render_history(self)

    def _select_thread_handler(self, session_id: str):
        async def _handler(_) -> None:
            await self.select_chat_session(session_id)

        return _handler

    def refresh_history(self) -> None:
        return refresh_history(self)

    def render_chat_main(self) -> None:
        return render_chat_main(self)

    def render_input_role_selector(self) -> None:
        return render_input_role_selector(self)

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
        return open_guest_input_mode_dialog(self, left_text)

    def refresh_input_mode_indicator(self) -> None:
        return refresh_input_mode_indicator(self)

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
        return refresh_chat_header(self)

    def render_messages(self) -> None:
        return render_messages(self)

    def refresh_messages(self, *, scroll_to_bottom: bool = False) -> None:
        return refresh_messages(self, scroll_to_bottom=scroll_to_bottom)

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
        return confirm_rewind_to_message(self, index)

    def open_rewrite_message_dialog(self, index: int) -> None:
        return open_rewrite_message_dialog(self, index)

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
        return await confirm_or_regenerate_character_message(self, index)

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
        voice_path = self.ctx.user_personas.media_path(voice.path) if voice else None
        return bool(
            voice and voice_path and self.ctx.tts.has_voice_playback_api(settings.api_type, settings.endpoint_id)
        )

    def _narrator_tts_configured(self, tts_settings=None) -> bool:
        config = self.ctx.user_personas.get_tts_config()
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
        voice_path = self.ctx.user_personas.media_path(voice.path) if voice else None
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
            config = self.ctx.user_personas.get_tts_config()
            settings = config.narrator
            if not self._narrator_tts_configured(settings):
                ui.notify("ナレーターTTS設定を確認してください", type="warning")
                return None
            voice = config.narrator_voice
            voice_path = self.ctx.user_personas.media_path(voice.path) if voice else None
            return {
                "target_id": "narrator",
                "settings": settings,
                "voice": voice,
                "voice_path": voice_path,
                "playback_save": self.ctx.user_personas.save_narrator_tts_playback,
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
            voice_path = self.ctx.user_personas.media_path(voice.path) if voice else None
            if voice_path is None and not self._voice_design_ready(settings):
                ui.notify("ユーザーペルソナのTTS設定を確認してください", type="warning")
                return None
            persona_id = persona.id
            return {
                "target_id": _group_user_persona_tts_id(persona_id),
                "settings": settings,
                "voice": voice,
                "voice_path": voice_path,
                "playback_save": lambda audio, target_id=persona_id: (
                    self.ctx.user_personas.save_user_persona_tts_playback(
                        target_id,
                        audio,
                    )
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
        return await open_guide_next_turn_dialog(self, left_text)

    def open_imitate_character_dialog(self, left_text: str = "") -> None:
        return open_imitate_character_dialog(self, left_text)

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
        return open_new_chat_dialog(self)

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
        return open_rename_current_chat_dialog(self)

    def open_rename_chat_dialog(self, session_id: str) -> None:
        return open_rename_chat_dialog(self, session_id)

    def confirm_delete_current_chat(self) -> None:
        return confirm_delete_current_chat(self)

    def confirm_delete_chat_session(self, session_id: str) -> None:
        return confirm_delete_chat_session(self, session_id)

    def open_system_prompt_dialog(self) -> None:
        return open_system_prompt_dialog(self)


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
