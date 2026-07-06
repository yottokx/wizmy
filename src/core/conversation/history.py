"""会話履歴の整形とチャットメッセージ変換。"""

from __future__ import annotations

import re
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from ..group_chat.schemas import GroupMember, GroupUserPersona
from .sanitize import clean_guest_name, guest_display_name
from .schemas import ChatDebugInfo, ChatMessagePreview, ChatSessionSettings, time_label
from .solo import chat_user_persona_source


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
            input_tokens=_chat_optional_int(debug_data.get("input_tokens")),
            output_tokens=_chat_optional_int(debug_data.get("output_tokens")),
            total_tokens=_chat_optional_int(debug_data.get("total_tokens")),
        )
    return ChatMessagePreview(
        speaker=str(data.get("speaker", "user")),
        text=str(data.get("text", "")),
        time_label=str(data.get("time_label", "")) or time_label(),
        debug=debug,
    )


def _chat_optional_int(value: Any) -> int | None:
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


def group_participant_ids(settings: dict[str, Any]) -> list[str]:
    return [str(member_id) for member_id in settings.get("participant_ids", [])]


def settings_with_participant(settings: dict[str, Any], member_id: str) -> dict[str, Any]:
    next_settings = dict(settings)
    ids = group_participant_ids(next_settings)
    if member_id not in ids:
        ids.append(member_id)
    next_settings["participant_ids"] = ids
    return next_settings


def settings_without_participant(settings: dict[str, Any], member_id: str) -> dict[str, Any]:
    next_settings = dict(settings)
    next_settings["participant_ids"] = [
        current_id for current_id in group_participant_ids(next_settings) if current_id != member_id
    ]
    return next_settings


def group_system_event_message(text: str) -> dict[str, Any]:
    return group_message("system", text)


def group_message(
    role: str,
    text: str,
    *,
    member: GroupMember | None = None,
    user: GroupUserPersona | None = None,
    guest_name: str = "",
    debug: ChatDebugInfo | None = None,
    speaker_debug: ChatDebugInfo | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": role,
        "text": text,
        "time_label": time_label(),
    }
    if member is not None:
        message.update(
            {
                "speaker_id": member.id,
                "speaker_name": member.character.name,
                "handle": member.handle,
            }
        )
    elif user is not None:
        message.update(
            {
                "speaker_id": user.id,
                "speaker_name": user.display_name or user.name or "ユーザー",
                "handle": user.handle,
            }
        )
    elif role == "guest":
        cleaned_guest_name = clean_guest_name(guest_name)
        message.update(
            {
                "speaker_id": f"guest:{cleaned_guest_name}",
                "speaker_name": guest_display_name(cleaned_guest_name),
                "guest_name": cleaned_guest_name,
                "handle": "",
            }
        )
    if debug is not None:
        message["debug"] = {
            "llm_input": debug.llm_input,
            "raw_output": debug.raw_output,
            "reasoning_output": debug.reasoning_output,
            "input_tokens": debug.input_tokens,
            "output_tokens": debug.output_tokens,
            "total_tokens": debug.total_tokens,
        }
    if speaker_debug is not None:
        message["speaker_debug"] = {
            "llm_input": speaker_debug.llm_input,
            "raw_output": speaker_debug.raw_output,
            "reasoning_output": speaker_debug.reasoning_output,
            "input_tokens": speaker_debug.input_tokens,
            "output_tokens": speaker_debug.output_tokens,
            "total_tokens": speaker_debug.total_tokens,
        }
    return message


def debug_from_dict(value: Any) -> ChatDebugInfo | None:
    if not isinstance(value, dict):
        return None
    return ChatDebugInfo(
        llm_input=str(value.get("llm_input", "")),
        raw_output=str(value.get("raw_output", "")),
        reasoning_output=str(value.get("reasoning_output", "")),
        input_tokens=optional_int(value.get("input_tokens")),
        output_tokens=optional_int(value.get("output_tokens")),
        total_tokens=optional_int(value.get("total_tokens")),
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


def latest_group_message_preview(messages: list[dict[str, Any]], *, limit: int = 56) -> str:
    if not messages:
        return "まだ発言がありません"
    latest = messages[-1]
    text = str(latest.get("text", "")) if isinstance(latest, dict) else ""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return "まだ発言がありません"
    name = str(latest.get("speaker_name", "") or "")
    prefix = f"{name}: " if name else ""
    preview = f"{prefix}{text}"
    return preview if len(preview) <= limit else f"{preview[: limit - 1]}…"


def last_dialog_message(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if message.get("role") in {"user", "character", "guest"}:
            return message
    return None


def format_group_history(messages: list[dict[str, Any]], *, limit: int | None = None) -> str:
    visible = [
        message for message in messages if message.get("role") in {"user", "character", "guest", "narration", "system"}
    ]
    if not visible:
        return "（まだ会話はありません）"
    lines: list[str] = []
    target_messages = visible if limit is None else visible[-limit:]
    for message in target_messages:
        role = message.get("role")
        if role == "narration":
            label = "地の文"
        elif role == "system":
            label = "システム"
        else:
            label = str(message.get("speaker_name") or "")
            handle = str(message.get("handle") or "")
            if handle:
                label = f"{label}(@{handle})" if label else f"@{handle}"
            if not label:
                if role == "user":
                    label = "ユーザー"
                elif role == "guest":
                    label = "ゲスト"
                else:
                    label = "キャラクター"
        lines.append(f"{label}: {message.get('text', '')}")
    return "\n".join(lines)
