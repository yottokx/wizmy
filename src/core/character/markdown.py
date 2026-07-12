"""キャラクターシート Markdown の読み書き補助。"""

from __future__ import annotations

import re
from datetime import datetime

from .schemas import CharacterSheet, Relationship

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
    """生成されたキャラクターシート Markdown から名前を取り出す。"""
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


def parse_markdown_to_sheet(sheet_md: str, sheet_id: str) -> CharacterSheet:
    """Markdown テキストから構造化 CharacterSheet を生成する。"""
    return _parse_sheet_to_structured(sheet_md, sheet_id)


def _parse_sheet_to_structured(sheet_md: str, sheet_id: str) -> CharacterSheet:
    """
    Markdown シートから構造化された CharacterSheet を生成する。
    フィールドが取れない場合は空文字を設定する（パースエラーで失敗しない）。
    """

    def extract_section(md: str, header: str) -> str:
        pattern = rf"##\s*{re.escape(header)}\s*\n(.*?)(?=\n##|\Z)"
        m = re.search(pattern, md, re.DOTALL)
        return m.group(1).strip() if m else ""

    def extract_table_field(md: str, field_name: str) -> str:
        pattern = rf"\|\s*{re.escape(field_name)}\s*\|\s*(.+?)\s*\|"
        m = re.search(pattern, md)
        return m.group(1).strip() if m else ""

    def parse_relationships(section_text: str) -> list[Relationship]:
        rels: list[Relationship] = []
        for line in section_text.splitlines():
            m = re.match(r"[-*]\s*\*{0,2}([^*\n:：]+?)\*{0,2}\s*[:：]\s*(.+)", line.strip())
            if m:
                rels.append(Relationship(name=m.group(1).strip(), description=m.group(2).strip()))
        return rels

    name = extract_character_name_from_markdown(sheet_md)

    return CharacterSheet(
        id=sheet_id,
        name=name,
        age=extract_table_field(sheet_md, "年齢"),
        gender=extract_table_field(sheet_md, "性別"),
        occupation=extract_table_field(sheet_md, "職業・役割"),
        origin=extract_table_field(sheet_md, "出身・所属"),
        world=extract_section(sheet_md, "世界観・舞台"),
        appearance=extract_section(sheet_md, "外見"),
        personality=extract_section(sheet_md, "性格・内面"),
        motivation=extract_section(sheet_md, "動機・目標"),
        weakness=extract_section(sheet_md, "弱点・コンプレックス"),
        background=extract_section(sheet_md, "過去・背景"),
        skills=extract_section(sheet_md, "スキル・能力"),
        relationships=parse_relationships(extract_section(sheet_md, "人間関係")),
        quirks=extract_section(sheet_md, "個性・クセ・口癖"),
        story_hooks=extract_section(sheet_md, "物語のフック"),
        self_intro=extract_section(sheet_md, "自己紹介台詞"),
        sample_dialogues=extract_section(sheet_md, "サンプル台詞"),
        voice_image=extract_section(sheet_md, "声のイメージ"),
        raw_markdown=sheet_md,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def base_character_markdown(sheet: CharacterSheet) -> str:
    markdown = (sheet.raw_markdown or "").strip()
    if markdown:
        return markdown
    return f"# {sheet.name or '名称未設定'}"


def replace_markdown_section(markdown: str, header: str, body: str) -> str:
    text = (markdown or "").strip()
    section = f"## {header}\n{body.strip()}".rstrip()
    pattern = re.compile(
        rf"(^##\s*{re.escape(header)}\s*\n)(.*?)(?=\n##\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    if pattern.search(text):
        # 本文の \ や \1 が正規表現の置換記法として解釈されないよう callable で渡す
        return pattern.sub(lambda _match: section, text, count=1).strip()
    return f"{text}\n\n{section}".strip()


def remove_markdown_section(markdown: str, header: str) -> str:
    pattern = re.compile(
        rf"\n*##\s*{re.escape(header)}\s*\n.*?(?=\n##\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    return pattern.sub("", markdown or "", count=1).strip()


def sheet_from_markdown_preserving(original: CharacterSheet, markdown: str) -> CharacterSheet:
    updated = parse_markdown_to_sheet(markdown.strip(), original.id)
    updated.media = original.media.model_copy(deep=True)
    updated.tags = list(original.tags)
    updated.is_favorite = original.is_favorite
    updated.generation_meta = original.generation_meta.model_copy(deep=True)
    updated.created_at = original.created_at
    return updated
