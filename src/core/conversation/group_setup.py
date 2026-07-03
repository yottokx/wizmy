"""グループ作成補助の LLM 応答整形とハンドル生成ヘルパー。"""

from __future__ import annotations

import json
import re
from typing import Any

from ..character.markdown import remove_markdown_section
from ..character.schemas import CharacterSheet
from .json_utils import longest_json_string, try_parse_json
from .llm_io import sanitize_chat_title
from .sanitize import clean_character_markdown_response


def sanitize_group_generated_markdown(markdown: str) -> str:
    cleaned = clean_character_markdown_response(markdown)
    cleaned = remove_markdown_section(cleaned, "世界観・舞台")
    cleaned = remove_markdown_section(cleaned, "人間関係")
    cleaned = remove_markdown_section(cleaned, "この世界に来た理由")
    return cleaned.strip()


def clean_generated_group_name(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:\w+)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    parsed = try_parse_json(text)
    if parsed is not None:
        text = longest_json_string(parsed) or text
    text = strip_possible_label_prefix(text.strip())
    return sanitize_chat_title(text, max_chars=24)


def clean_world_enhancement(
    raw: str,
    *,
    current_world: str,
    group_name: str,
    characters: list[CharacterSheet],
    persona: Any,
) -> str:
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
        line = strip_possible_label_prefix(line)
        if not line:
            continue
        if looks_like_non_world_line(line):
            continue
        lines.append(line)

    cleaned = "\n".join(lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip(" \t\r\n\"'「」『』")

    if contains_known_non_world_content(
        cleaned,
        current_world=current_world,
        group_name=group_name,
        characters=characters,
        persona=persona,
    ):
        return ""
    return cleaned


def parse_handle_response(raw: str) -> dict[str, str]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    result: dict[str, str] = {}
    if isinstance(data, dict):
        for item in data.get("characters", []):
            if isinstance(item, dict):
                key = str(item.get("id") or item.get("name") or "")
                value = str(item.get("handle") or "")
                if key and value:
                    result[key] = value
        user = data.get("user")
        if isinstance(user, str):
            result["user"] = user
        elif isinstance(user, dict):
            result["user"] = str(user.get("handle") or "")
        for key, value in data.items():
            if isinstance(value, str):
                result.setdefault(str(key), value)
    return result


def sanitize_handle(value: str, fallback: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_]", "", value or "")
    if len(candidate) < 3:
        candidate = fallback
    candidate = re.sub(r"[^A-Za-z0-9_]", "", candidate)
    if len(candidate) < 3:
        candidate = "User"
    return candidate[:12]


def unique_handle(candidate: str, used: set[str]) -> str:
    base = candidate[:12] or "User"
    if len(base) < 3:
        base = (base + "___")[:3]
    if base.lower() not in used:
        return base
    for index in range(2, 100):
        suffix = str(index)
        prefix = base[: 12 - len(suffix)]
        handle = f"{prefix}{suffix}"
        if len(handle) >= 3 and handle.lower() not in used:
            return handle
    return uuid_like_handle(used)


def uuid_like_handle(used: set[str]) -> str:
    index = len(used) + 1
    while True:
        handle = f"User{index}"
        if handle.lower() not in used:
            return handle
        index += 1


def fallback_handle(sheet: CharacterSheet, index: int) -> str:
    return f"Char{index}"


def fallback_persona_handle(persona: Any) -> str:
    for value in (
        getattr(persona, "persona_name", ""),
        getattr(persona, "name", ""),
        getattr(persona, "display_name", ""),
    ):
        candidate = ascii_outside_parentheses(str(value or ""))
        if len(candidate) >= 3:
            return candidate[:12]
    return "Persona"


def ascii_outside_parentheses(value: str) -> str:
    text = re.sub(r"（[^）]*）", "", value)
    text = re.sub(r"\([^)]*\)", "", text)
    return re.sub(r"[^A-Za-z0-9_]", "", text)


def looks_like_non_world_line(line: str) -> bool:
    normalized = line.strip()
    if not normalized:
        return False
    if re.match(r"^[-*・]\s+", normalized):
        return True
    if len(normalized) <= 40 and re.match(r"^[^。.!?！？]{1,40}[：:]\s*.*$", normalized):
        return True
    if re.match(r"^[#>\[\]{}]+", normalized):
        return True
    return False


def strip_possible_label_prefix(line: str) -> str:
    match = re.match(r"^([^。.!?！？\n]{1,24})[：:]\s*(.+)$", line)
    if not match:
        return line
    prefix, body = match.groups()
    if re.search(r"\s", prefix) and not re.search(r"[A-Za-z0-9_]", prefix):
        return line
    return body.strip()


def contains_known_non_world_content(
    text: str,
    *,
    current_world: str,
    group_name: str,
    characters: list[CharacterSheet],
    persona: Any,
) -> bool:
    if not text:
        return False
    allowed = current_world or ""
    fragments = [group_name.strip()]
    fragments.extend(sheet.name.strip() for sheet in characters)
    if persona is not None:
        fragments.extend(
            [
                str(getattr(persona, "name", "") or "").strip(),
                str(getattr(persona, "persona_name", "") or "").strip(),
                str(getattr(persona, "display_name", "") or "").strip(),
            ]
        )
    for fragment in fragments:
        if len(fragment) < 3:
            continue
        if fragment in text and fragment not in allowed:
            return True
    return False
