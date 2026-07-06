"""
キャラクターシートページ(/v2/characters/{id})の純ロジック。

raw_markdown を「章」(## 見出し)単位に分解し、表示種別
(表 / 箇条書き / 台詞 / 本文)へ分類する。章の編集は
`core.character.markdown.replace_markdown_section` で raw_markdown 側へ
書き戻す(シート項目とは常に双方向同期。プレビューは置かない — 確定仕様)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_KANJI_DIGITS = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九"]


def kanji_number(value: int) -> str:
    """1〜99 を漢数字にする(章番号表示用)。範囲外は算用数字のまま。"""
    if not 1 <= value <= 99:
        return str(value)
    tens, ones = divmod(value, 10)
    text = ""
    if tens >= 2:
        text += _KANJI_DIGITS[tens]
    if tens >= 1:
        text += "十"
    text += _KANJI_DIGITS[ones]
    return text


@dataclass(frozen=True)
class SheetSection:
    """シートの章 1 つ分(見出し+生 Markdown 本文)。"""

    header: str
    body: str


def parse_sections(markdown: str) -> list[SheetSection]:
    """raw_markdown を ## 見出し単位の章リストへ分解する(# タイトル行は除外)。"""
    sections: list[SheetSection] = []
    for match in re.finditer(
        r"^##\s*(.+?)\s*\n(.*?)(?=\n##\s|\Z)",
        (markdown or "").strip(),
        re.MULTILINE | re.DOTALL,
    ):
        sections.append(SheetSection(header=match.group(1).strip(), body=match.group(2).strip()))
    return sections


def classify_body(body: str) -> str:
    """章本文の表示種別: "table" / "list" / "quote" / "text"。"""
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if not lines:
        return "text"
    if all(line.startswith("|") for line in lines):
        return "table"
    if all(re.match(r"[-*]\s+", line) for line in lines):
        return "list"
    if len(lines) == 1 and lines[0].startswith("「") and lines[0].endswith("」"):
        return "quote"
    return "text"


def table_rows(body: str) -> list[tuple[str, str]]:
    """Markdown 表を (項目, 内容) の行リストへ(ヘッダ行・罫線行は除外)。"""
    rows: list[tuple[str, str]] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        key, value = cells[0], cells[1]
        if not key or set(key) <= {"-", ":", " "}:
            continue
        if (key, value) == ("項目", "内容"):
            continue
        rows.append((key, value))
    return rows


def list_items(body: str) -> list[str]:
    """箇条書きを表示用テキストへ(`**名前**: 説明` は「名前 — 説明」に整形)。"""
    items: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        match = re.match(r"[-*]\s+(.*)", line)
        if not match:
            continue
        text = match.group(1).strip()
        bold = re.match(r"\*\*(.+?)\*\*\s*[:：]\s*(.+)", text)
        if bold:
            text = f"{bold.group(1).strip()} — {bold.group(2).strip()}"
        items.append(text)
    return items


def strip_outer_quotes(text: str) -> str:
    """外側のカギ括弧を剥がす(吹き出し・台詞表示側で付け直すため)。"""
    value = " ".join((text or "").split())
    while value.startswith("「") and value.endswith("」"):
        value = value[1:-1].strip()
    return value
