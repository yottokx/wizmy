"""LLM 出力の後処理とグループチャット用の名前整形。"""

from __future__ import annotations

import re

from ..group_chat.schemas import GroupMember
from .json_utils import longest_json_string, try_parse_json, try_parse_json_fragment


def clean_short_llm_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:\w+)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = re.sub(
        r"^(?:候補|返答|回答|ユーザー|キャラクター|キャラ|地の文|ナラティブ|コメント)\s*[:：]\s*", "", text.strip()
    )
    return text.strip()


def sanitize_character_reply(text: str, character_name: str = "") -> str:
    text = text.strip()
    text = re.sub(r"^```(?:\w+)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    lines: list[str] = []
    speaker_pattern = (
        rf"^(?:{re.escape(character_name)}|キャラクター|キャラ|assistant|AI)\s*[:：]\s*"
        if character_name
        else r"^(?:キャラクター|キャラ|assistant|AI)\s*[:：]\s*"
    )
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(speaker_pattern, "", line, flags=re.IGNORECASE).strip()
        line = re.sub(r"^[（(][^）)]*[）)]\s*", "", line).strip()
        line = line.strip("*＊")
        if not line or re.fullmatch(r"[（(【\[].*[）)】\]]", line):
            continue
        lines.append(line)

    cleaned = "\n".join(lines[:3]).strip()
    return cleaned.strip("「」『』\"'")


def clean_guest_name(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"^guest\s*[:：]\s*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s*【ゲスト】\s*$", "", text).strip()
    return text


def guest_name_from_actor_text(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if re.match(r"^guest\s*[:：]", text, flags=re.IGNORECASE):
        return clean_guest_name(text)
    if text.endswith("【ゲスト】"):
        return clean_guest_name(text)
    return ""


def guest_display_name(name: str) -> str:
    clean = clean_guest_name(name)
    return f"{clean}【ゲスト】" if clean else "ゲスト【ゲスト】"


def sanitize_group_character_reply(raw: str, speaker: GroupMember) -> str:
    text = sanitize_character_reply(raw, speaker.character.name)
    text = re.sub(rf"^\s*@?{re.escape(speaker.handle)}\s*[：:\-]\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(rf"^\s*{re.escape(speaker.character.name)}\s*[：:\-]\s*", "", text)
    text = text.strip(" \t\r\n\"'「」『』")
    return text


def sanitize_group_guest_reply(raw: str, guest_name: str) -> str:
    name = clean_guest_name(guest_name)
    text = sanitize_character_reply(raw, name)
    text = re.sub(rf"^\s*{re.escape(guest_display_name(name))}\s*[：:\-]\s*", "", text)
    text = re.sub(rf"^\s*{re.escape(name)}\s*[：:\-]\s*", "", text)
    text = text.strip(" \t\r\n\"'「」『』")
    return text


def sanitize_group_narration(raw: str) -> str:
    text = clean_short_llm_text(raw)
    text = re.sub(r"^(?:地の文|ナラティブ|描写)\s*[:：]\s*", "", text.strip())
    return text.strip(" \t\r\n\"'「」『』")


def clean_character_markdown_response(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:markdown|md)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    parsed = try_parse_json_fragment(text)
    if parsed is not None:
        text = longest_json_string(parsed) or text
    return text.strip()


def clean_persona_description_response(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:markdown|md)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    parsed = try_parse_json_fragment(text)
    if parsed is not None:
        text = longest_json_string(parsed) or text
    text = re.sub(r"^(?:説明|ユーザーペルソナ|更新後の説明)\s*[:：]\s*", "", text.strip())
    return text.strip(" \t\r\n\"'「」『』")


def clean_arrival_reason_response(raw: str) -> str:
    text = clean_short_llm_text(raw)
    text = re.sub(r"^(?:来訪理由|理由|補完結果)\s*[:：]\s*", "", text.strip())
    return text.strip(" \t\r\n\"'「」『』")


def clean_relationship_enhancement(raw: str) -> str:
    text = clean_group_situation_enhancement(raw)
    text = re.sub(r"^(?:関係性|関係|補完結果)\s*[:：]\s*", "", text.strip())
    return text.strip(" \t\r\n\"'「」『』")


def clean_group_situation_enhancement(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:\w+)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()

    parsed = try_parse_json(text)
    if parsed is not None:
        text = longest_json_string(parsed) or text

    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            lines.append("")
            continue
        line = _strip_possible_label_prefix(line)
        if not line:
            continue
        if re.match(r"^[#>\[\]{}]+", line):
            continue
        line = re.sub(r"^[-*・]\s+", "", line).strip()
        if line:
            lines.append(line)

    cleaned = "\n".join(lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip(" \t\r\n\"'「」『』")


def _strip_possible_label_prefix(line: str) -> str:
    match = re.match(r"^([^。.!?！？\n]{1,24})[：:]\s*(.+)$", line)
    if not match:
        return line
    prefix, body = match.groups()
    if re.search(r"\s", prefix) and not re.search(r"[A-Za-z0-9_]", prefix):
        return line
    return body.strip()
