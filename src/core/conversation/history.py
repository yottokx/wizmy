"""会話履歴の整形とグループチャットメッセージ変換。"""

from __future__ import annotations

import re
from typing import Any

from ..group_chat.schemas import GroupMember, GroupUserPersona
from .schemas import ChatDebugInfo, time_label


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


def _clean_guest_name(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"^guest\s*[:：]\s*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s*【ゲスト】\s*$", "", text).strip()
    return text


def _guest_display_name(name: str) -> str:
    clean = _clean_guest_name(name)
    return f"{clean}【ゲスト】" if clean else "ゲスト【ゲスト】"


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
        clean_guest_name = _clean_guest_name(guest_name)
        message.update(
            {
                "speaker_id": f"guest:{clean_guest_name}",
                "speaker_name": _guest_display_name(clean_guest_name),
                "guest_name": clean_guest_name,
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
    try:
        return int(value)
    except (TypeError, ValueError):
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
