"""シートページ純ロジック(ui2/sheet_logic.py)の単体テスト。"""

from __future__ import annotations

from src.ui2.sheet_logic import (
    classify_body,
    kanji_number,
    list_items,
    parse_sections,
    strip_outer_quotes,
    table_rows,
)

SAMPLE_MD = """# トワ

## 基本情報
| 項目 | 内容 |
|------|------|
| 名前 | トワ |
| 年齢 | 17歳 |

## 世界観・舞台
星を観測する塔のある世界。

## スキル・能力
- 星読み
- **観測術**: 遠くの星をつぶさに見る

## 自己紹介台詞
「トワです。今日の星はよく瞬いていますよ」
"""


def test_parse_sections_extracts_headers_and_bodies() -> None:
    sections = parse_sections(SAMPLE_MD)
    assert [s.header for s in sections] == ["基本情報", "世界観・舞台", "スキル・能力", "自己紹介台詞"]
    assert sections[1].body == "星を観測する塔のある世界。"


def test_parse_sections_handles_empty_markdown() -> None:
    assert parse_sections("") == []
    assert parse_sections("# 名前だけ") == []


def test_parse_sections_ignores_leading_h3_and_keeps_h3_in_body() -> None:
    # 先頭が ### でも「# 見出し」として拾わない。章内部の ### は本文のまま残る。
    md = "### 前書き\n導入文。\n\n## 基本情報\n年齢: 17歳\n### 補足\n塔で育った。"
    sections = parse_sections(md)
    assert [s.header for s in sections] == ["基本情報"]
    assert sections[0].body == "年齢: 17歳\n### 補足\n塔で育った。"


def test_classify_body() -> None:
    sections = {s.header: s.body for s in parse_sections(SAMPLE_MD)}
    assert classify_body(sections["基本情報"]) == "table"
    assert classify_body(sections["世界観・舞台"]) == "text"
    assert classify_body(sections["スキル・能力"]) == "list"
    assert classify_body(sections["自己紹介台詞"]) == "quote"
    assert classify_body("") == "text"


def test_table_rows_skips_header_and_separator() -> None:
    sections = {s.header: s.body for s in parse_sections(SAMPLE_MD)}
    assert table_rows(sections["基本情報"]) == [("名前", "トワ"), ("年齢", "17歳")]


def test_list_items_formats_bold_pairs() -> None:
    sections = {s.header: s.body for s in parse_sections(SAMPLE_MD)}
    assert list_items(sections["スキル・能力"]) == ["星読み", "観測術 — 遠くの星をつぶさに見る"]


def test_kanji_number() -> None:
    assert kanji_number(1) == "一"
    assert kanji_number(10) == "十"
    assert kanji_number(13) == "十三"
    assert kanji_number(21) == "二十一"
    assert kanji_number(0) == "0"


def test_strip_outer_quotes() -> None:
    assert strip_outer_quotes("「こんばんは」") == "こんばんは"
    assert strip_outer_quotes("  そのまま ") == "そのまま"
    assert strip_outer_quotes("") == ""
