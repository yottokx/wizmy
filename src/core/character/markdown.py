"""Helpers for reading character-sheet Markdown."""

from __future__ import annotations

import re


UNSET_CHARACTER_NAME = "名称未設定"


def _clean_name_candidate(value: str) -> str:
    name = value.strip()
    if len(name) >= 2 and name[0] == "[" and name[-1] == "]":
        name = name[1:-1].strip()

    if not name or name in {"名前", "キャラクター名", UNSET_CHARACTER_NAME}:
        return ""
    if "上記" in name and "選択結果" in name:
        return ""
    return name


def extract_character_name_from_markdown(
    sheet_md: str,
    default: str = UNSET_CHARACTER_NAME,
) -> str:
    """Extract a character name from a generated character-sheet Markdown."""
    for line in sheet_md.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            break

        match = re.match(r"^#(?!#)\s*(.+?)\s*$", stripped)
        if not match:
            continue

        heading = match.group(1).strip()
        prefixed = re.match(r"^キャラクターシート(?:\s*[:：]|\s+)\s*(.+)$", heading)
        if prefixed:
            candidate = prefixed.group(1)
        elif re.fullmatch(r"キャラクターシート\s*[:：]?", heading):
            candidate = ""
        else:
            candidate = heading

        name = _clean_name_candidate(candidate)
        if name:
            return name

    table_match = re.search(r"^\|\s*名前\s*\|\s*([^|\n]+?)\s*\|", sheet_md, re.MULTILINE)
    if table_match:
        name = _clean_name_candidate(table_match.group(1))
        if name:
            return name

    return default
