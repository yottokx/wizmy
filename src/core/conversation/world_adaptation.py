"""グループ参加者のワールド適応用変換。"""

from __future__ import annotations

from typing import Any

from ..character.markdown import (
    base_character_markdown,
    remove_markdown_section,
    replace_markdown_section,
    sheet_from_markdown_preserving,
)
from ..character.schemas import CharacterSheet


def prepare_group_character_for_world(
    sheet: CharacterSheet,
    *,
    world: str,
    source_character_id: str,
    entry_type: str,
    arrival_reason: str,
    adaptation_note: str,
) -> tuple[CharacterSheet, dict[str, str]]:
    if sheet.id == source_character_id:
        markdown = remove_markdown_section(base_character_markdown(sheet), "世界観・舞台")
        markdown = remove_markdown_section(markdown, "この世界に来た理由")
        return sheet_from_markdown_preserving(sheet, markdown), {
            "world_entry_type": "world_source",
            "arrival_reason": "",
            "world_adaptation_note": adaptation_note.strip(),
        }

    resolved_type = entry_type if entry_type in {"native", "visitor"} else "native"
    markdown = base_character_markdown(sheet)
    if resolved_type == "native":
        markdown = remove_markdown_section(markdown, "世界観・舞台")
        markdown = remove_markdown_section(markdown, "この世界に来た理由")
        note = adaptation_note.strip() or "確定ワールドの住人として設定"
        updated = sheet_from_markdown_preserving(sheet, markdown)
        return updated, {
            "world_entry_type": "native",
            "arrival_reason": "",
            "world_adaptation_note": note,
        }

    reason = arrival_reason.strip()
    markdown = replace_markdown_section(markdown, "この世界に来た理由", reason)
    updated = sheet_from_markdown_preserving(sheet, markdown)
    return updated, {
        "world_entry_type": "visitor",
        "arrival_reason": reason,
        "world_adaptation_note": adaptation_note.strip(),
    }


def prepare_group_user_world_settings(
    persona: Any,
    *,
    world: str,
    entry_type: str,
    arrival_reason: str,
    adaptation_note: str,
    description_override: str = "",
) -> dict[str, str]:
    resolved_type = entry_type if entry_type in {"native", "visitor"} else "native"
    description = (description_override or str(getattr(persona, "description", "") or "")).strip()
    return {
        "description": description,
        "world_entry_type": resolved_type,
        "arrival_reason": arrival_reason.strip() if resolved_type == "visitor" else "",
        "world_adaptation_note": adaptation_note.strip(),
    }


def format_optional_instruction(instruction: str) -> str:
    text = (instruction or "").strip()
    if not text:
        return ""
    return f"追加指示:\n{text}\n\n"
